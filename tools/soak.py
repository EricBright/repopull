"""Resource soak harness for repopull.

Runs repeated discovery/status (or sync) cycles against throwaway local
repositories, or repeated Qt window create/close cycles, and reports growth in
resident memory, open file descriptors, threads, and Python allocations. It is
deliberately outside `make check`: a soak is slower than the unit suite and its
thresholds depend on the machine.

Usage:

    make soak
    make soak-qt
    python tools/soak.py --cycles 200 --repos 6
    python tools/soak.py --qt --cycles 100
    python tools/soak.py --cycles 20 --warmup 5 --repos 2 --plant-leak

`--plant-leak` adds a 64 KiB object per cycle to a module-level list. A healthy
harness must fail that run; if it passes, the harness is not measuring anything.
`--plant-window` keeps one Qt window alive per cycle and must trip the
window-survival check.
"""

from __future__ import annotations

import argparse
import gc
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from repopull.config import Config  # noqa: E402
from repopull.discovery import discover_repos  # noqa: E402
from repopull.models import Outcome  # noqa: E402
from repopull.sync import status_report, sync_report  # noqa: E402

PLANT_BYTES = 64 * 1024
_LEAKED: list[bytes] = []
_HELD_WINDOWS: list[object] = []


@dataclass(frozen=True, slots=True)
class Sample:
    """One post-cycle measurement."""

    cycle: int
    rss_kb: int
    fds: int
    threads: int
    traced_kb: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class Finding:
    """One metric's verdict over the measured cycles."""

    metric: str
    start: float
    end: float
    delta: float
    slope: float
    limit: float
    unit: str
    digits: int
    ok: bool

    def line(self) -> str:
        """Human-readable summary row."""
        start = format(self.start, f".{self.digits}f")
        end = format(self.end, f".{self.digits}f")
        delta = format(self.delta, f"+.{self.digits}f")
        slope = format(self.slope, f"+.{self.digits}f")
        limit = format(self.limit, f".{self.digits}f")
        verdict = "OK" if self.ok else "FAIL"
        return (
            f"  {self.metric:<18} {start:>8}{self.unit} -> {end:>8}{self.unit}"
            f"  delta {delta:>8}{self.unit}"
            f"  slope {slope:>8}{self.unit}/1000"
            f"  limit {limit}{self.unit}  {verdict}"
        )


def _read_kb(key: str) -> int:
    """Read a kilobyte field such as VmRSS from /proc/self/status."""
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    raise RuntimeError(f"{key} is missing from /proc/self/status")


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _thread_count() -> int:
    return len(os.listdir("/proc/self/task"))


def _traced_kb() -> int:
    return tracemalloc.get_traced_memory()[0] // 1024


def _sample(cycle: int, elapsed_ms: float) -> Sample:
    gc.collect()
    return Sample(
        cycle=cycle,
        rss_kb=_read_kb("VmRSS"),
        fds=_fd_count(),
        threads=_thread_count(),
        traced_kb=_traced_kb(),
        elapsed_ms=elapsed_ms,
    )


def _window_stats(
    first: list[float], last: list[float], count: int
) -> tuple[float, float, float, float]:
    """Return first median, last median, their delta, and a per-1000 slope."""
    start = statistics.median(first)
    end = statistics.median(last)
    delta = end - start
    slope = delta / max(1, count - 1) * 1000
    return start, end, delta, slope


class Series:
    """Bounded collector for the measured cycles.

    Keeping every Sample would grow the harness's own memory and show up as a
    false tracemalloc leak. Ten samples at each end are enough for the medians;
    descriptor and thread spans are tracked incrementally.
    """

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.first: list[Sample] = []
        self.last: deque[Sample] = deque(maxlen=window)
        self.count = 0
        self.fd_min = 0
        self.fd_max = 0
        self.thread_min = 0
        self.thread_max = 0

    def add(self, sample: Sample) -> None:
        self.count += 1
        if len(self.first) < self.window:
            self.first.append(sample)
        self.last.append(sample)
        if self.count == 1:
            self.fd_min = self.fd_max = sample.fds
            self.thread_min = self.thread_max = sample.threads
        else:
            self.fd_min = min(self.fd_min, sample.fds)
            self.fd_max = max(self.fd_max, sample.fds)
            self.thread_min = min(self.thread_min, sample.threads)
            self.thread_max = max(self.thread_max, sample.threads)

    def findings(
        self,
        *,
        rss_limit_mb: float = 5.0,
        fd_limit: int = 3,
        thread_limit: int = 1,
        trace_limit_kb: int = 512,
    ) -> list[Finding]:
        """Compare the collected cycles against the configured limits."""
        if self.count < 5:
            raise ValueError("need at least 5 measured cycles")

        last = list(self.last)
        rss_start, rss_end, rss_delta, rss_slope = _window_stats(
            [sample.rss_kb / 1024 for sample in self.first],
            [sample.rss_kb / 1024 for sample in last],
            self.count,
        )
        trace_start, trace_end, trace_delta, trace_slope = _window_stats(
            [float(sample.traced_kb) for sample in self.first],
            [float(sample.traced_kb) for sample in last],
            self.count,
        )
        fd_start, fd_end, _, fd_slope = _window_stats(
            [float(sample.fds) for sample in self.first],
            [float(sample.fds) for sample in last],
            self.count,
        )
        thread_start, thread_end, _, thread_slope = _window_stats(
            [float(sample.threads) for sample in self.first],
            [float(sample.threads) for sample in last],
            self.count,
        )
        fd_growth = self.fd_max - self.fd_min
        thread_growth = self.thread_max - self.thread_min

        return [
            Finding(
                "resident memory",
                rss_start,
                rss_end,
                rss_delta,
                rss_slope,
                rss_limit_mb,
                "MB",
                2,
                rss_delta <= rss_limit_mb,
            ),
            Finding(
                "file descriptors",
                fd_start,
                fd_end,
                float(fd_growth),
                fd_slope,
                float(fd_limit),
                "",
                0,
                fd_growth <= fd_limit,
            ),
            Finding(
                "threads",
                thread_start,
                thread_end,
                float(thread_growth),
                thread_slope,
                float(thread_limit),
                "",
                0,
                thread_growth <= thread_limit,
            ),
            Finding(
                "tracemalloc",
                trace_start,
                trace_end,
                trace_delta,
                trace_slope,
                float(trace_limit_kb),
                "KB",
                0,
                trace_delta <= trace_limit_kb,
            ),
        ]


def analyse(
    samples: list[Sample],
    *,
    rss_limit_mb: float = 5.0,
    fd_limit: int = 3,
    thread_limit: int = 1,
    trace_limit_kb: int = 512,
) -> list[Finding]:
    """Compare a full sample list against the configured limits."""
    series = Series()
    for sample in samples:
        series.add(sample)
    return series.findings(
        rss_limit_mb=rss_limit_mb,
        fd_limit=fd_limit,
        thread_limit=thread_limit,
        trace_limit_kb=trace_limit_kb,
    )


def _git(*args: str, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(
        ("git", *args),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"fixture git {' '.join(args)} failed:\n{completed.stderr}"
        )


def _build_fixture(base: Path, root: Path, count: int) -> None:
    """Create local bare remotes and watched clones; no network is used."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Soak",
            "GIT_AUTHOR_EMAIL": "soak@example.invalid",
            "GIT_COMMITTER_NAME": "Soak",
            "GIT_COMMITTER_EMAIL": "soak@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    for index in range(count):
        name = f"repo-{index:02d}"
        remote = base / "remotes" / f"{name}.git"
        seed = base / "seed" / name
        parent = root / ("nested" if index % 3 == 0 else "")
        watched = parent / name
        parent.mkdir(parents=True, exist_ok=True)

        _git("init", "--bare", "--initial-branch=main", str(remote), cwd=base, env=env)
        _git("clone", str(remote), str(seed), cwd=base, env=env)
        (seed / "file.txt").write_text(f"one {index}\n", encoding="utf-8")
        _git("add", "file.txt", cwd=seed, env=env)
        _git("commit", "-m", f"one {index}", cwd=seed, env=env)
        _git("push", "origin", "main", cwd=seed, env=env)
        _git("clone", str(remote), str(watched), cwd=base, env=env)


def _run_cycle(config: Config, mode: str) -> None:
    root = config.root
    if root is None:
        raise SystemExit("soak config has no root")
    refs = discover_repos(root, max_depth=config.max_depth, ignore=config.ignore)
    if not refs:
        raise SystemExit("discovery found no repositories")
    if mode == "sync":
        report = sync_report(refs, config)
    else:
        report = status_report(refs, config)
    failed = [row for row in report.rows if row.outcome is Outcome.ERROR]
    if failed:
        details = "; ".join(f"{row.label}: {row.detail}" for row in failed)
        raise SystemExit(f"soak cycle failed: {details}")


def _print_header() -> None:
    print(f"{'cycle':>5}  {'rss MB':>8}  {'fds':>4}  {'thr':>4}  {'traced KB':>9}  {'ms':>7}")
    print("-" * 52)


def _print_sample(sample: Sample) -> None:
    print(
        f"{sample.cycle:>5}  {sample.rss_kb / 1024:>8.2f}  {sample.fds:>4}"
        f"  {sample.threads:>4}  {sample.traced_kb:>9}  {sample.elapsed_ms:>7.0f}"
    )


def _measure(
    args: argparse.Namespace, step: Callable[[], float]
) -> tuple[Series, tracemalloc.Snapshot | None]:
    """Run warm-up and measured cycles, returning the series and baseline."""
    tracemalloc.start(1)
    series = Series()
    baseline: tracemalloc.Snapshot | None = None
    total = args.warmup + args.cycles
    for index in range(total):
        elapsed_ms = step()
        if args.plant_leak:
            _LEAKED.append(b"x" * PLANT_BYTES)
        if index < args.warmup:
            continue
        if baseline is None:
            baseline = tracemalloc.take_snapshot()
        sample = _sample(index - args.warmup + 1, elapsed_ms)
        series.add(sample)
        if args.verbose or series.count == 1 or series.count % 10 == 0:
            if series.count == 1:
                _print_header()
            _print_sample(sample)
    return series, baseline


def _finish(
    series: Series, baseline: "tracemalloc.Snapshot | None", args: argparse.Namespace
) -> int:
    findings = series.findings(
        rss_limit_mb=args.rss_limit_mb,
        fd_limit=args.fd_limit,
        thread_limit=args.thread_limit,
        trace_limit_kb=args.trace_limit_kb,
    )

    print()
    for finding in findings:
        print(finding.line())

    failures = [finding for finding in findings if not finding.ok]
    if failures:
        assert baseline is not None
        print("\ntop Python allocations since the last warm-up cycle:")
        final = tracemalloc.take_snapshot()
        for stat in final.compare_to(baseline, "lineno")[:8]:
            print(f"  {stat}")
        print(f"\nresult: FAIL ({len(failures)} metric(s) over limit)")
        return 1

    print("\nresult: PASS")
    return 0


def _soak_cli(config: Config, args: argparse.Namespace) -> int:
    def step() -> float:
        clock = time.perf_counter()
        _run_cycle(config, args.mode)
        return (time.perf_counter() - clock) * 1000

    series, baseline = _measure(args, step)
    return _finish(series, baseline, args)


def _soak_qt(config: Config, args: argparse.Namespace) -> int:
    import weakref

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit(f"--qt needs PySide6: {exc}") from exc

    from repopull.gui.theme import stylesheet
    from repopull.gui.window import MainWindow

    app = QApplication.instance() or QApplication(["repopull-soak-qt"])
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    app.setQuitOnLastWindowClosed(False)
    app.processEvents()
    baseline_widgets = len(app.allWidgets())
    cycle = 0

    def step() -> float:
        nonlocal cycle
        cycle += 1
        clock = time.perf_counter()
        window = MainWindow(config)
        window.show()
        app.processEvents()
        if args.plant_window:
            _HELD_WINDOWS.append(window)
        reference = weakref.ref(window)
        window.hide()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        del window
        gc.collect()
        app.processEvents()

        survivor = reference()
        if survivor is not None:
            valid = shiboken6.isValid(survivor)
            raise SystemExit(
                f"Qt window wrapper survived cycle {cycle} (C++ valid={valid})"
            )
        widgets = len(app.allWidgets())
        if widgets > baseline_widgets:
            raise SystemExit(
                f"Qt widget count grew at cycle {cycle}: "
                f"{baseline_widgets} -> {widgets}"
            )
        return (time.perf_counter() - clock) * 1000

    series, baseline = _measure(args, step)
    return _finish(series, baseline, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=100, help="measured cycles")
    parser.add_argument("--warmup", type=int, default=10, help="warm-up cycles")
    parser.add_argument("--repos", type=int, default=4, help="fixture repositories")
    parser.add_argument("--mode", choices=("status", "sync"), default="status")
    parser.add_argument("--qt", action="store_true", help="soak window create/close")
    parser.add_argument("--plant-leak", action="store_true", help="add a known leak")
    parser.add_argument(
        "--plant-window", action="store_true", help="hold one Qt window per cycle"
    )
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    parser.add_argument("--verbose", action="store_true", help="print every cycle")
    parser.add_argument("--rss-limit-mb", type=float, default=5.0)
    parser.add_argument("--fd-limit", type=int, default=3)
    parser.add_argument("--thread-limit", type=int, default=1)
    parser.add_argument("--trace-limit-kb", type=int, default=512)
    args = parser.parse_args(argv)

    if args.cycles < 10:
        parser.error("--cycles must be at least 10")
    if args.warmup < 0:
        parser.error("--warmup must not be negative")
    if args.repos < 1:
        parser.error("--repos must be at least 1")
    if shutil.which("git") is None:
        parser.error("git is required")
    if not Path("/proc/self/status").is_file():
        parser.error("this harness needs Linux /proc")
    if args.qt:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    elif args.plant_window:
        parser.error("--plant-window requires --qt")

    workdir = Path(tempfile.mkdtemp(prefix="repopull-soak-"))
    try:
        base = workdir / "fixture"
        root = base / "repos"
        logs = workdir / "logs"
        base.mkdir(parents=True)
        root.mkdir(parents=True)
        _build_fixture(base, root, args.repos)

        config = Config(
            root=root,
            max_depth=2,
            delay_between_repos_s=0.0,
            fetch_timeout_s=30.0,
            command_timeout_s=30.0,
            log_dir=logs,
            log_retention_days=0,
        )

        label = "Qt windows" if args.qt else f"{args.mode} cycles"
        print(
            f"repopull soak: {args.repos} repos, {label}, "
            f"{args.warmup} warm-up + {args.cycles} measured cycles"
        )
        if args.plant_leak:
            print("planted leak: 64 KiB per cycle")
        if args.plant_window:
            print("planted window leak: one held window per cycle")

        if args.qt:
            return _soak_qt(config, args)
        return _soak_cli(config, args)
    finally:
        tracemalloc.stop()
        if args.keep:
            print(f"work directory kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
