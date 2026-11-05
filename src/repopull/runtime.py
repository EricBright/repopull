"""Process-level runtime helpers: the run lock."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockError(RuntimeError):
    """Raised when another repopull run already holds the lock."""


@contextmanager
def run_lock(log_dir: Path) -> Iterator[None]:
    """Hold an exclusive, non-blocking lock for the duration of the block."""
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_path = log_dir / ".lock"
    handle = lock_path.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockError(
                f"another repopull run is in progress ({lock_path})"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
