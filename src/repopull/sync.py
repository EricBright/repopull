"""Inspection, classification, and application of sync decisions."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

from repopull import git
from repopull.config import Config
from repopull.models import Outcome, RepoRef, RepoState, Report, Row
from repopull.report import write_log

ProgressFn = Callable[[int, int, str], None]
"""Called as `(index, total, label)` immediately before each fetch."""

RowCallback = Callable[[Row], None]
"""Called with each row as soon as that repository has been decided."""

_CANCELLED = "cancelled"
_NETWORK_FAILURE_LIMIT = 2


@dataclass(frozen=True, slots=True)
class Verdict:
    """What should happen to one repository, and why."""

    outcome: Outcome
    detail: str = ""
    commits: int = 0


def _broken(ref: RepoRef, message: str) -> RepoState:
    """A repository whose state could not be read."""
    return RepoState(
        ref=ref,
        branch=None,
        upstream=None,
        dirty=False,
        ahead=0,
        behind=0,
        shallow=False,
        uses_lfs=False,
        has_submodules=False,
        lfs_enabled=False,
        error=message,
    )


def inspect_repo(ref: RepoRef, *, timeout: float) -> RepoState:
    """Read a repository's state without touching the network."""
    try:
        branch = git.current_branch(ref.path, timeout=timeout)
    except git.GitError as exc:
        if git.head_sha(ref.path, timeout=timeout) is None:
            return _broken(
                ref, "empty repository: no commits (incomplete clone?)"
            )
        return _broken(ref, str(exc))

    try:
        upstream = (
            git.upstream_ref(ref.path, branch=branch, timeout=timeout)
            if branch is not None
            else None
        )
        dirty = git.is_dirty(ref.path, timeout=timeout)
        shallow = git.is_shallow(ref.path, timeout=timeout)
        ahead, behind = (
            git.ahead_behind(ref.path, upstream, timeout=timeout)
            if upstream is not None
            else (0, 0)
        )
        uses_lfs = git.uses_lfs(ref.path, timeout=timeout)
        if behind > 0 and upstream is not None:
            # Catch LFS tracking introduced by the very commit we would pull.
            uses_lfs = uses_lfs or git.uses_lfs(
                ref.path, timeout=timeout, rev=upstream
            )
        has_submodules = git.has_submodules(ref.path)
        lfs_enabled = (
            git.git_lfs_enabled(ref.path, timeout=timeout)
            if uses_lfs
            else False
        )
    except git.GitError as exc:
        return _broken(ref, str(exc))
    return RepoState(
        ref=ref,
        branch=branch,
        upstream=upstream,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
        shallow=shallow,
        uses_lfs=uses_lfs,
        has_submodules=has_submodules,
        lfs_enabled=lfs_enabled,
    )


def classify(
    state: RepoState,
    *,
    force: bool,
    lfs_ok: bool,
    require_lfs: bool,
    preview: bool,
) -> Verdict:
    """Decide a repository's fate from its state.

    `preview` turns a would-be update into `BEHIND` for the status table; the
    sync pipeline passes `preview=False` and then applies the update.
    """
    if state.error == _CANCELLED:
        return Verdict(Outcome.SKIPPED, "cancelled")
    if state.error is not None:
        return Verdict(Outcome.ERROR, state.error)
    if state.is_detached:
        return Verdict(Outcome.SKIPPED, "detached HEAD")
    if state.upstream is None:
        return Verdict(Outcome.SKIPPED, "no upstream branch")
    if state.uses_lfs and require_lfs and not lfs_ok:
        return Verdict(Outcome.SKIPPED, "uses Git LFS but git-lfs is not installed")
    if state.uses_lfs and require_lfs and not state.lfs_enabled:
        return Verdict(
            Outcome.SKIPPED,
            "uses Git LFS but git-lfs is not enabled; run `git lfs install`",
        )

    if force:
        if state.ahead == 0 and state.behind == 0 and not state.dirty:
            return Verdict(Outcome.UP_TO_DATE)
        return Verdict(Outcome.UPDATED, "hard reset to upstream", state.behind)

    if state.dirty:
        return Verdict(Outcome.SKIPPED, "dirty working tree")
    if state.behind == 0:
        detail = f"local commits: {state.ahead}" if state.ahead else ""
        return Verdict(Outcome.UP_TO_DATE, detail)
    if state.ahead > 0:
        return Verdict(Outcome.SKIPPED, "diverged from upstream")
    return Verdict(
        Outcome.BEHIND if preview else Outcome.UPDATED,
        commits=state.behind,
    )


def _row(state: RepoState, verdict: Verdict) -> Row:
    return Row(
        label=state.ref.label,
        branch=state.branch or "-",
        outcome=verdict.outcome,
        commits=verdict.commits,
        detail=verdict.detail,
    )


def _within_root(path: Path, root: Path) -> bool:
    """True when `path` resolves inside `root`, following symlinks."""
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
    except OSError:
        return False
    return resolved == root_resolved or root_resolved in resolved.parents


def _apply(
    state: RepoState,
    verdict: Verdict,
    config: Config,
    *,
    force: bool,
    cancel: Event | None = None,
) -> Verdict:
    """Run the update a `UPDATED` verdict calls for, or report why it failed."""
    if config.root is not None and not _within_root(
        state.ref.path, config.root
    ):
        return Verdict(Outcome.ERROR, "refusing path outside watched root")
    upstream = state.upstream
    if upstream is None:  # classify guarantees this cannot happen
        return Verdict(Outcome.ERROR, "no upstream branch")

    if force:
        operation = git.hard_reset(
            state.ref.path,
            upstream,
            timeout=config.command_timeout_s,
            cancel=cancel,
        )
    else:
        operation = git.fast_forward(
            state.ref.path,
            upstream,
            timeout=config.command_timeout_s,
            cancel=cancel,
        )
    if operation.cancelled:
        return Verdict(Outcome.SKIPPED, _CANCELLED)
    if not operation.ok:
        return Verdict(Outcome.ERROR, operation.summary())

    detail = verdict.detail
    if state.has_submodules and config.update_submodules:
        submodules = git.update_submodules(
            state.ref.path,
            timeout=config.command_timeout_s,
            cancel=cancel,
        )
        if submodules.cancelled:
            detail = "submodule update cancelled"
        elif not submodules.ok:
            detail = f"submodule update failed: {submodules.summary()}"
    return Verdict(Outcome.UPDATED, detail, commits=verdict.commits)


def _run(
    refs: list[RepoRef],
    config: Config,
    *,
    force: bool,
    preview: bool,
    progress: ProgressFn | None,
    on_row: RowCallback | None,
    cancel: Event | None,
) -> tuple[list[Row], bool]:
    """Process one repository at a time, emitting each row as it is decided.

    Fetching and classifying per repository (rather than fetching everything
    first) is what lets a caller show progress repository by repository. The
    second consecutive network-level failure stops the sweep: a single bad
    remote is reported but does not starve the rest. Remaining repositories are
    marked not attempted instead of each paying its own timeout.
    """
    states = _collect(refs, config)
    lfs_ok = git.git_lfs_available()
    rows: list[Row] = []
    network_error = False
    network_failures = 0
    total = len(states)

    for index, state in enumerate(states, start=1):
        if cancel is not None and cancel.is_set():
            break
        if progress is not None:
            progress(index, total, state.ref.label)

        current = state
        if state.error is not None:
            network_failures = 0
        if state.error is None:
            fetched = git.fetch(
                state.ref.path,
                timeout=config.fetch_timeout_s,
                cancel=cancel,
            )
            if fetched.cancelled:
                current = dataclasses.replace(state, error=_CANCELLED)
            elif not fetched.ok:
                current = dataclasses.replace(
                    state, error=f"fetch failed: {fetched.summary()}"
                )
                if git.is_network_error(fetched):
                    network_failures += 1
                    if network_failures >= _NETWORK_FAILURE_LIMIT:
                        network_error = True
                        verdict = classify(
                            current,
                            force=force,
                            lfs_ok=lfs_ok,
                            require_lfs=config.require_git_lfs_for_lfs_repos,
                            preview=preview,
                        )
                        row = _row(current, verdict)
                        rows.append(row)
                        if on_row is not None:
                            on_row(row)
                        for remaining in states[index:]:
                            row = _row(
                                remaining,
                                Verdict(
                                    Outcome.SKIPPED,
                                    "not attempted: network unavailable",
                                ),
                            )
                            rows.append(row)
                            if on_row is not None:
                                on_row(row)
                        break
                else:
                    network_failures = 0
            else:
                network_failures = 0
                current = inspect_repo(
                    state.ref, timeout=config.command_timeout_s
                )

        verdict = classify(
            current,
            force=force,
            lfs_ok=lfs_ok,
            require_lfs=config.require_git_lfs_for_lfs_repos,
            preview=preview,
        )
        if not preview and verdict.outcome is Outcome.UPDATED:
            verdict = _apply(
                current, verdict, config, force=force, cancel=cancel
            )

        row = _row(current, verdict)
        rows.append(row)
        if on_row is not None:
            on_row(row)

        if index < total:
            if cancel is not None:
                cancel.wait(config.delay_between_repos_s)
            else:
                time.sleep(config.delay_between_repos_s)

    # Repositories the run never reached because it was cancelled.
    for state in states[len(rows) :]:
        row = _row(state, Verdict(Outcome.SKIPPED, _CANCELLED))
        rows.append(row)
        if on_row is not None:
            on_row(row)

    return rows, network_error


def _collect(refs: list[RepoRef], config: Config) -> list[RepoState]:
    return [
        inspect_repo(ref, timeout=config.command_timeout_s) for ref in refs
    ]


def status_report(
    refs: list[RepoRef],
    config: Config,
    *,
    progress: ProgressFn | None = None,
    on_row: RowCallback | None = None,
    cancel: Event | None = None,
) -> Report:
    """Fetch and report what a sync *would* do, changing no working tree."""
    started_at = datetime.now()
    clock = time.monotonic()
    rows, network_error = _run(
        refs,
        config,
        force=False,
        preview=True,
        progress=progress,
        on_row=on_row,
        cancel=cancel,
    )
    report = Report(
        mode="status",
        started_at=started_at,
        elapsed_s=time.monotonic() - clock,
        rows=tuple(rows),
        network_error=network_error,
    )
    return write_log(
        report, config.log_dir, retention_days=config.log_retention_days
    )


def sync_report(
    refs: list[RepoRef],
    config: Config,
    *,
    force: bool = False,
    progress: ProgressFn | None = None,
    on_row: RowCallback | None = None,
    cancel: Event | None = None,
) -> Report:
    """Fetch and update every repository that can be updated safely."""
    started_at = datetime.now()
    clock = time.monotonic()
    rows, network_error = _run(
        refs,
        config,
        force=force,
        preview=False,
        progress=progress,
        on_row=on_row,
        cancel=cancel,
    )
    report = Report(
        mode="force-sync" if force else "sync",
        started_at=started_at,
        elapsed_s=time.monotonic() - clock,
        rows=tuple(rows),
        network_error=network_error,
    )
    return write_log(
        report, config.log_dir, retention_days=config.log_retention_days
    )
