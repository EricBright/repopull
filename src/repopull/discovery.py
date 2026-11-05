"""Repository discovery under the watched root."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Sequence
from pathlib import Path

from repopull.models import RepoRef


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
    descends into a repository and never follows symlinked directories.
    """
    if not root.exists():
        raise DiscoveryError(f"watched root does not exist: {root}")
    if not root.is_dir():
        raise DiscoveryError(f"watched root is not a directory: {root}")

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
                if name != ".git" and not _ignored(name, name, ignore)
            )
            continue

        if depth > max_depth:
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
