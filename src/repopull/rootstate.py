"""Remember which filesystem the watched root pointed at last time."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT_STATE_FILE = "root-state.json"
ROOT_STATE_VERSION = 2


@dataclass(frozen=True, slots=True)
class RootState:
    """The watched path and filesystem seen on the last successful discovery."""

    root: str
    device: int
    repo_count: int
    filesystem_uuid: str | None = None
    mount_source: str | None = None


@dataclass(frozen=True, slots=True)
class RootIdentity:
    """What the watched path resolves to right now."""

    device: int
    filesystem_uuid: str | None
    mount_source: str | None


@dataclass(frozen=True, slots=True)
class RootStateCheck:
    """The result of comparing the saved identity with the current one."""

    problem: str | None
    previous: RootState | None
    current: RootIdentity | None
    repo_count: int
    repairable: bool = False


def _state_path(log_dir: Path) -> Path:
    return log_dir / ROOT_STATE_FILE


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return value or None


def load_root_state(log_dir: Path) -> RootState | None:
    """Read the saved root state, or None when absent or malformed."""
    path = _state_path(log_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        version = data.get("version", 1)
        if isinstance(version, bool) or version not in (1, ROOT_STATE_VERSION):
            return None
        root = str(data["root"])
        device = int(data["device"])
        repo_count = int(data["repo_count"])
        filesystem_uuid = _optional_text(data.get("filesystem_uuid"))
        mount_source = _optional_text(data.get("mount_source"))
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if device < 0 or repo_count < 0:
        return None
    return RootState(
        root=root,
        device=device,
        repo_count=repo_count,
        filesystem_uuid=filesystem_uuid,
        mount_source=mount_source,
    )


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


_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape_mountinfo(value: str) -> str:
    """Decode the octal escapes used by /proc/self/mountinfo."""
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _mount_source(
    path: Path, mountinfo: Path | None = None
) -> str | None:
    """Return the filesystem source shown in mountinfo for *path*.

    This is only used to find a filesystem UUID. The source itself is not an
    identity: /dev/sdb1 can become /dev/sdc1 after re-enumeration.
    """
    info = mountinfo if mountinfo is not None else Path("/proc/self/mountinfo")
    try:
        text = info.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    target = os.path.realpath(path)
    best_mount = ""
    best_source: str | None = None
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        if len(fields) < 5:
            continue
        mount_point = _unescape_mountinfo(fields[4])
        matches = target == mount_point or target.startswith(
            mount_point.rstrip("/") + "/"
        )
        if not matches or len(mount_point) < len(best_mount):
            continue
        after_fields = after.split()
        if len(after_fields) < 2:
            continue
        best_mount = mount_point
        best_source = _unescape_mountinfo(after_fields[1])
    return best_source


def _filesystem_uuid(
    source: str | None, by_uuid: Path | None = None
) -> str | None:
    """Resolve a mount source to its filesystem UUID without running blkid."""
    if source is None:
        return None
    if source.startswith("UUID="):
        return source[len("UUID=") :] or None
    if not source.startswith("/dev/"):
        return None
    source_real = os.path.realpath(source)
    directory = by_uuid if by_uuid is not None else Path("/dev/disk/by-uuid")
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            if os.path.realpath(entry) == source_real:
                return entry.name
        except OSError:
            continue
    return None


def root_identity(root: Path) -> RootIdentity:
    """Read the current device, filesystem UUID, and mount source."""
    source = _mount_source(root)
    return RootIdentity(
        device=os.stat(root).st_dev,
        filesystem_uuid=_filesystem_uuid(source),
        mount_source=source,
    )


def _device_label(device: int) -> str:
    return f"{device} ({os.major(device)}:{os.minor(device)})"


def describe_state(state: RootState | None) -> str:
    """One-line description of a saved identity for a repair dialog."""
    if state is None:
        return "no saved identity"
    parts = [f"device {_device_label(state.device)}"]
    if state.filesystem_uuid is not None:
        parts.append(f"filesystem UUID {state.filesystem_uuid}")
    if state.mount_source is not None:
        parts.append(f"source {state.mount_source}")
    parts.append(f"{state.repo_count} repositories")
    return ", ".join(parts)


def describe_identity(identity: RootIdentity | None) -> str:
    """One-line description of the current identity for a repair dialog."""
    if identity is None:
        return "unavailable"
    parts = [f"device {_device_label(identity.device)}"]
    if identity.filesystem_uuid is not None:
        parts.append(f"filesystem UUID {identity.filesystem_uuid}")
    if identity.mount_source is not None:
        parts.append(f"source {identity.mount_source}")
    return ", ".join(parts)


def save_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> None:
    """Record the current path and filesystem after a successful discovery."""
    identity = root_identity(root)
    payload: dict[str, object] = {
        "version": ROOT_STATE_VERSION,
        "root": str(root),
        "device": identity.device,
        "filesystem_uuid": identity.filesystem_uuid,
        "mount_source": identity.mount_source,
        "repo_count": repo_count,
    }
    _atomic_write(
        _state_path(log_dir),
        json.dumps(payload, indent=2) + "\n",
    )


def _problem_and_repair(
    previous: RootState | None,
    *,
    root: Path,
    device: int,
    repo_count: int,
    filesystem_uuid: str | None = None,
) -> tuple[str, bool] | None:
    """Return (message, repairable) when the saved identity no longer fits."""
    if previous is None or previous.root != str(root):
        return None
    if (
        previous.filesystem_uuid is not None
        and filesystem_uuid is not None
        and previous.filesystem_uuid != filesystem_uuid
    ):
        return (
            "watched root is on a different filesystem than last time "
            f"(UUID {previous.filesystem_uuid} -> {filesystem_uuid})",
            True,
        )
    same_uuid = (
        previous.filesystem_uuid is not None
        and filesystem_uuid is not None
        and previous.filesystem_uuid == filesystem_uuid
    )
    if not same_uuid and previous.device != device:
        detail = (
            f"watched root is on a different device than last time "
            f"({_device_label(previous.device)} -> {_device_label(device)})"
        )
        if previous.filesystem_uuid is None:
            detail += (
                "; the saved identity predates filesystem UUIDs, so "
                "repopull cannot confirm the disk"
            )
        return detail, True
    if previous.repo_count > 0 and repo_count == 0:
        return (
            "watched root is empty but contained "
            f"{previous.repo_count} repositories last time; is it mounted?",
            False,
        )
    return None


def root_state_problem(
    previous: RootState | None,
    *,
    root: Path,
    device: int,
    repo_count: int,
    filesystem_uuid: str | None = None,
) -> str | None:
    """Return a refusal message when the root changed unexpectedly."""
    result = _problem_and_repair(
        previous,
        root=root,
        device=device,
        repo_count=repo_count,
        filesystem_uuid=filesystem_uuid,
    )
    return result[0] if result is not None else None


def check_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> RootStateCheck:
    """Compare the saved identity and record a successful discovery."""
    previous = load_root_state(log_dir)
    try:
        current = root_identity(root)
    except OSError:
        return RootStateCheck(None, previous, None, repo_count)

    result = _problem_and_repair(
        previous,
        root=root,
        device=current.device,
        repo_count=repo_count,
        filesystem_uuid=current.filesystem_uuid,
    )
    if result is not None:
        message, repairable = result
        return RootStateCheck(
            message, previous, current, repo_count, repairable
        )
    if repo_count > 0:
        try:
            save_root_state(log_dir, root, repo_count)
        except OSError:
            pass
    return RootStateCheck(None, previous, current, repo_count)


def verify_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> str | None:
    """Check the saved identity and record a successful discovery.

    Returns a refusal message when the same path now points at a different
    filesystem or an unexpectedly empty root. A first discovery, or a
    deliberately changed root path, simply records the new state.
    """
    return check_root_state(log_dir, root, repo_count).problem
