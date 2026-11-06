"""Rendering and persistence of the run brief."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from repopull.models import Outcome, Report, Row

_RESET = "\033[0m"
_COLORS: dict[Outcome, str] = {
    Outcome.UPDATED: "\033[32m",  # green
    Outcome.UP_TO_DATE: "\033[2m",  # dim
    Outcome.BEHIND: "\033[36m",  # cyan
    Outcome.SKIPPED: "\033[33m",  # yellow
    Outcome.ERROR: "\033[31m",  # red
}

_HEADERS: tuple[str, ...] = ("Repository", "Branch", "Status", "Commits", "Detail")
_MAX_LABEL = 48
_MAX_DETAIL = 100
_RUN_LOG_RE = re.compile(r"(?P<stamp>\d{8}-\d{6})-.+\.log")


def _paint(text: str, outcome: Outcome, *, color: bool) -> str:
    if not color:
        return text
    return f"{_COLORS[outcome]}{text}{_RESET}"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(report: Report, *, color: bool) -> str:
    """Render a report as a fixed-width text table plus totals."""
    cells: list[tuple[str, str, str, str, str]] = []
    for row in report.rows:
        cells.append(
            (
                _clip(row.label, _MAX_LABEL),
                row.branch,
                row.outcome.value,
                str(row.commits) if row.commits else "",
                _clip(row.detail, _MAX_DETAIL),
            )
        )

    widths = [len(header) for header in _HEADERS]
    for cell in cells:
        for index, value in enumerate(cell):
            widths[index] = max(widths[index], len(value))

    lines: list[str] = []
    lines.append(f"{report.mode} — {report.started_at:%Y-%m-%d %H:%M:%S}")
    lines.append("-" * min(sum(widths) + 2 * (len(widths) - 1), 120))

    header = "  ".join(
        f"{name:<{widths[index]}}" for index, name in enumerate(_HEADERS)
    )
    lines.append(header)

    for row, cell in zip(report.rows, cells, strict=True):
        label, branch, _status, commits, detail = cell
        status_cell = _paint(f"{_status:<{widths[2]}}", row.outcome, color=color)
        lines.append(
            f"{label:<{widths[0]}}  {branch:<{widths[1]}}  {status_cell}"
            f"  {commits:>{widths[3]}}  {detail}"
        )

    totals = report.totals
    summary = ", ".join(
        f"{totals[outcome]} {outcome.value}"
        for outcome in Outcome
        if totals[outcome]
    )
    lines.append("")
    lines.append(f"Totals: {summary} in {report.elapsed_s:.1f}s")

    attention = [
        row for row in report.rows if row.outcome in (Outcome.SKIPPED, Outcome.ERROR)
    ]
    if attention:
        lines.append("")
        lines.append("Attention:")
        for row in attention:
            lines.append(f"  - {row.label}: {row.detail or row.outcome.value}")

    if report.log_path is not None:
        lines.append("")
        lines.append(f"Log: {report.log_path}")

    return "\n".join(lines)


def _merged_snapshot(report: Report, log_dir: Path) -> Report:
    """Merge this run's rows into the last known status per repository.

    A single-repo sync writes one row. Without this merge it would replace
    `latest.json` and the GUI would forget every other repository's status.
    """
    previous = load_latest_report(log_dir)
    if previous is None:
        return report
    merged = {row.label: row for row in previous.rows}
    for row in report.rows:
        merged[row.label] = row
    return dataclasses.replace(report, rows=tuple(merged.values()))


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text through a same-directory temp file and atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def prune_logs(
    log_dir: Path,
    retention_days: int,
    *,
    reference: datetime | None = None,
) -> int:
    """Delete timestamped run logs older than `retention_days`.

    `0` disables pruning. Only top-level files matching
    `YYYYMMDD-HHMMSS-<mode>.log` are considered; `latest.log`, `latest.json`,
    `.lock`, unrelated files, and symlinks are left alone. Failures are
    best-effort and never raise.
    """
    if retention_days <= 0:
        return 0

    cutoff = (reference or datetime.now()) - timedelta(days=retention_days)
    try:
        entries = list(log_dir.iterdir())
    except OSError:
        return 0

    removed = 0
    for path in entries:
        if path.is_symlink() or not path.is_file():
            continue
        match = _RUN_LOG_RE.fullmatch(path.name)
        if match is None:
            continue
        try:
            stamp = datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if stamp >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def write_log(
    report: Report,
    log_dir: Path,
    *,
    retention_days: int = 0,
) -> Report:
    """Write this run's log plus merged `latest.log` and `latest.json` files.

    The timestamped log is exactly this run. The two `latest` files hold the
    last known status for every repository, so a partial sync does not erase the
    other rows. With `retention_days > 0`, older timestamped run logs are pruned
    after the new files are safely written.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"{stamp}-{report.mode}.log"
    stamped = dataclasses.replace(report, log_path=path)

    run_text = render_report(stamped, color=False) + "\n"
    _atomic_write_text(path, run_text)

    snapshot = _merged_snapshot(stamped, log_dir)
    snapshot_text = render_report(snapshot, color=False) + "\n"
    _atomic_write_text(log_dir / "latest.log", snapshot_text)
    _atomic_write_text(
        log_dir / "latest.json",
        json.dumps(report_to_dict(snapshot), indent=2) + "\n",
    )
    if retention_days > 0:
        prune_logs(log_dir, retention_days, reference=stamped.started_at)
    return stamped


def report_to_dict(report: Report) -> dict[str, Any]:
    """Machine-readable form, used by `--json`, the GUI, and scheduled runs."""
    return {
        "mode": report.mode,
        "started_at": report.started_at.isoformat(),
        "elapsed_s": round(report.elapsed_s, 3),
        "log_path": str(report.log_path) if report.log_path else None,
        "totals": {outcome.value: count for outcome, count in report.totals.items()},
        "rows": [
            {
                "label": row.label,
                "branch": row.branch,
                "outcome": row.outcome.value,
                "commits": row.commits,
                "detail": row.detail,
            }
            for row in report.rows
        ],
    }


def report_from_dict(data: dict[str, Any]) -> Report:
    """Rebuild a report from `report_to_dict` output.

    Raises ValueError when the data is malformed, so callers can treat a corrupt
    cache as "no saved report" rather than crashing.
    """
    try:
        rows = tuple(
            Row(
                label=str(item["label"]),
                branch=str(item["branch"]),
                outcome=Outcome(str(item["outcome"])),
                commits=int(item["commits"]),
                detail=str(item["detail"]),
            )
            for item in data["rows"]
        )
        log_path = data.get("log_path")
        return Report(
            mode=str(data["mode"]),
            started_at=datetime.fromisoformat(str(data["started_at"])),
            elapsed_s=float(data["elapsed_s"]),
            rows=rows,
            log_path=Path(str(log_path)) if log_path else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid report data: {exc}") from exc


def load_latest_report(log_dir: Path) -> Report | None:
    """Read `logs/latest.json`, or None when it is absent or unreadable."""
    path = log_dir / "latest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return report_from_dict(data)
    except ValueError:
        return None
