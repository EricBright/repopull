"""Remember which filesystem the watched root pointed at last time."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT_STATE_FILE = "root-state.json"


@dataclass(frozen=True, slots=True)
class RootState:
    """The watched path and device seen on the last successful discovery."""

    root: str
    device: int
    repo_count: int


def _state_path(log_dir: Path) -> Path:
    return log_dir / ROOT_STATE_FILE


def load_root_state(log_dir: Path) -> RootState | None:
    """Read the saved root state, or None when absent or malformed."""
    path = _state_path(log_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        root = str(data["root"])
        device = int(data["device"])
        repo_count = int(data["repo_count"])
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if device < 0 or repo_count < 0:
        return None
    return RootState(root=root, device=device, repo_count=repo_count)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def save_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> None:
    """Record the current root/device after a successful discovery."""
    state = RootState(
        root=str(root),
        device=os.stat(root).st_dev,
        repo_count=repo_count,
    )
    _atomic_write(
        _state_path(log_dir),
        json.dumps(
            {
                "root": state.root,
                "device": state.device,
                "repo_count": state.repo_count,
            },
            indent=2,
        )
        + "\n",
    )


def root_state_problem(
    previous: RootState | None,
    *,
    root: Path,
    device: int,
    repo_count: int,
) -> str | None:
    """Return a refusal message when the root changed unexpectedly."""
    if previous is None or previous.root != str(root):
        return None
    if previous.device != device:
        return (
            "watched root is on a different device than last time "
            f"({previous.device} -> {device})"
        )
    if previous.repo_count > 0 and repo_count == 0:
        return (
            "watched root is empty but contained "
            f"{previous.repo_count} repositories last time; is it mounted?"
        )
    return None


def verify_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> str | None:
    """Check the saved identity and record a successful discovery.

    Returns a refusal message when the same path now points at a different
    device or an unexpectedly empty root. A first discovery, or a deliberately
    changed root path, simply records the new state.
    """
    previous = load_root_state(log_dir)
    try:
        device = os.stat(root).st_dev
    except OSError:
        return None
    problem = root_state_problem(
        previous,
        root=root,
        device=device,
        repo_count=repo_count,
    )
    if problem is not None:
        return problem
    if repo_count > 0:
        try:
            save_root_state(log_dir, root, repo_count)
        except OSError:
            pass
    return None
