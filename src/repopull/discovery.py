"""Repository discovery under the watched root."""

from __future__ import annotations

import fnmatch
import os
import shutil
import time
from collections.abc import Sequence
from pathlib import Path

from repopull.models import RepoRef

MIN_FREE_BYTES = 64 * 1024 * 1024

CLONE_TEMP_PREFIX = ".repopull-clone-"
"""A clone in progress lives under this prefix and is never discovered."""

CLONE_TEMP_MAX_AGE_S = 24 * 60 * 60.0
"""A clone cannot run this long, so an older temp folder was abandoned."""


class DiscoveryError(RuntimeError):
    """Raised when the watched root cannot be scanned."""


def _ignored(label: str, name: str, patterns: Sequence[str]) -> bool:
    """True when `label` or `name` matches any ignore glob."""
    return any(
        fnmatch.fnmatch(label, pattern) or fnmatch.fnmatch(name, pattern)
        for pattern in patterns
    )


def discover_repos(
    root: Path,
    *,
    max_depth: int = 2,
    ignore: Sequence[str] = (),
) -> list[RepoRef]:
    """Find every git repository at depth 1..`max_depth` under `root`.

    A directory counts as a repository when it contains `.git`, either as a
    directory (normal clone) or as a file (linked worktree). Discovery never
    descends into a repository, never follows symlinked directories, and
    ignores the temporary folders used while `repopull clone` is running.
    """
    if not root.exists():
        raise DiscoveryError(f"watched root does not exist: {root}")
    if not root.is_dir():
        raise DiscoveryError(f"watched root is not a directory: {root}")
    if not os.access(root, os.W_OK | os.X_OK):
        raise DiscoveryError(
            f"watched root is not writable: {root} (permissions, or a "
            "filesystem left read-only by an unclean shutdown)"
        )
    try:
        free = shutil.disk_usage(root).free
    except OSError as exc:
        raise DiscoveryError(f"cannot read watched root usage: {exc}") from exc
    if free < MIN_FREE_BYTES:
        raise DiscoveryError(
            f"watched root has less than {MIN_FREE_BYTES // (1024 * 1024)} MiB free"
        )

    root = root.resolve()
    found: list[RepoRef] = []

    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        relative = current.relative_to(root)
        depth = len(relative.parts)

        if depth == 0:
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name != ".git"
                and not name.startswith(CLONE_TEMP_PREFIX)
                and not _ignored(name, name, ignore)
            )
            continue

        if depth > max_depth:
            dirnames[:] = []
            continue

        if current.name.startswith(CLONE_TEMP_PREFIX):
            dirnames[:] = []
            continue

        if _ignored(relative.as_posix(), current.name, ignore):
            dirnames[:] = []
            continue

        if (current / ".git").exists():
            found.append(RepoRef(path=current, label=relative.as_posix()))
            dirnames[:] = []
            continue

        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        if depth >= max_depth:
            dirnames[:] = []

    return sorted(found, key=lambda ref: ref.label)


def sweep_stale_clones(
    root: Path,
    *,
    max_age_s: float = CLONE_TEMP_MAX_AGE_S,
    now: float | None = None,
) -> list[Path]:
    """Remove clone temp folders left behind by a crash or a power cut.

    `clone` removes its own temporary folder on every path it can control, so
    one that survives can only have outlived a process that never returned.
    Discovery skips these folders, which means nothing would ever delete them
    and a killed clone of a large repository could sit in the watched root for
    good. Only names this tool creates are touched, and only ones older than a
    clone can possibly run.

    Returns the folders that were removed. Failures are ignored: a folder that
    cannot be read is left alone rather than failing the scan.
    """
    current = time.time() if now is None else now
    removed: list[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return removed
    for entry in entries:
        if not entry.name.startswith(CLONE_TEMP_PREFIX):
            continue
        try:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if current - entry.stat().st_mtime < max_age_s:
                continue
        except OSError:
            continue
        try:
            shutil.rmtree(entry)
        except OSError:
            continue
        removed.append(entry)
    return removed
