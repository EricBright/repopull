"""Remember which filesystem the watched root pointed at last time."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from repopull.mounts import RootIdentity, root_identity

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
class RootStateCheck:
    """The result of comparing the saved identity with the current one."""

    problem: str | None
    previous: RootState | None
    current: RootIdentity | None
    repo_count: int
    repairable: bool = False


@dataclass(frozen=True, slots=True)
class RootStateRead:
    """A parsed state file, or a reason it could not be used."""

    state: RootState | None
    problem: str | None = None


class RootStateChanged(RuntimeError):
    """The saved or mounted identity changed before a repair could apply."""


def _state_path(log_dir: Path) -> Path:
    return log_dir / ROOT_STATE_FILE


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a string or null")
    return value or None


def _unusable(path: Path, detail: str) -> RootStateRead:
    return RootStateRead(None, f"{path} is not usable: {detail}")


def read_root_state(log_dir: Path) -> RootStateRead:
    """Read the state file, distinguishing absence from an unusable file."""
    path = _state_path(log_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return RootStateRead(None)
    except UnicodeError as exc:
        return _unusable(path, f"not UTF-8 ({exc})")
    except OSError as exc:
        return RootStateRead(None, f"cannot read {path}: {exc}")

    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        return _unusable(path, f"malformed JSON ({exc})")
    if not isinstance(data, dict):
        return _unusable(path, "expected a JSON object")

    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        return _unusable(path, "version must be an integer")
    if version not in (1, ROOT_STATE_VERSION):
        return _unusable(
            path,
            f"unsupported version {version}; this repopull supports "
            f"version {ROOT_STATE_VERSION}",
        )

    try:
        root = data["root"]
        device = data["device"]
        repo_count = data["repo_count"]
        if not isinstance(root, str):
            raise ValueError("root must be a string")
        if isinstance(device, bool) or not isinstance(device, int):
            raise ValueError("device must be an integer")
        if isinstance(repo_count, bool) or not isinstance(repo_count, int):
            raise ValueError("repo_count must be an integer")
        filesystem_uuid = _optional_text(data.get("filesystem_uuid"))
        mount_source = _optional_text(data.get("mount_source"))
    except (KeyError, TypeError, ValueError) as exc:
        return _unusable(path, str(exc))

    if device < 0 or repo_count < 0:
        return _unusable(path, "device and repo_count must be non-negative")
    return RootStateRead(
        RootState(
            root=root,
            device=device,
            repo_count=repo_count,
            filesystem_uuid=filesystem_uuid,
            mount_source=mount_source,
        )
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _device_label(device: int) -> str:
    try:
        return f"{device} ({os.major(device)}:{os.minor(device)})"
    except (OverflowError, ValueError):
        return str(device)


def _identity_parts(
    device: int,
    filesystem_uuid: str | None,
    mount_source: str | None,
) -> list[str]:
    parts = [f"device {_device_label(device)}"]
    if filesystem_uuid is not None:
        parts.append(f"filesystem UUID {filesystem_uuid}")
    if mount_source is not None:
        parts.append(f"source {mount_source}")
    return parts


def describe_state(state: RootState | None) -> str:
    """One-line description of a saved identity for a repair dialog."""
    if state is None:
        return "no saved identity"
    parts = _identity_parts(
        state.device, state.filesystem_uuid, state.mount_source
    )
    parts.append(f"{state.repo_count} repositories")
    return ", ".join(parts)


def describe_identity(identity: RootIdentity | None) -> str:
    """One-line description of the current identity for a repair dialog."""
    if identity is None:
        return "unavailable"
    return ", ".join(
        _identity_parts(
            identity.device,
            identity.filesystem_uuid,
            identity.mount_source,
        )
    )


def save_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
    *,
    identity: RootIdentity | None = None,
    previous: RootState | None = None,
) -> None:
    """Record a path and identity after a successful discovery.

    ``identity`` must be the one that was just checked. When it is omitted,
    the current filesystem is read here; callers that already verified an
    identity should pass it so a remount cannot change what is written.

    Concurrent writers are last-writer-wins: each write is an atomic replace,
    so readers see one complete state or the other, never a partial file.
    """
    current = identity if identity is not None else root_identity(root)
    if (
        current.filesystem_uuid is None
        and previous is not None
        and previous.root == str(root)
        and previous.device == current.device
        and previous.filesystem_uuid is not None
    ):
        # A transient /dev/disk/by-uuid failure must not erase the stable
        # identity and silently return to device-only comparison.
        current = RootIdentity(
            device=current.device,
            filesystem_uuid=previous.filesystem_uuid,
            mount_source=current.mount_source or previous.mount_source,
        )
    payload: dict[str, object] = {
        "version": ROOT_STATE_VERSION,
        "root": str(root),
        "device": current.device,
        "filesystem_uuid": current.filesystem_uuid,
        "mount_source": current.mount_source,
        "repo_count": repo_count,
    }
    _atomic_write(
        _state_path(log_dir),
        json.dumps(payload, indent=2) + "\n",
    )


def _classify_root_change(
    previous: RootState | None,
    *,
    root: Path,
    current: RootIdentity,
    repo_count: int,
) -> tuple[str, bool] | None:
    """Return (message, repairable) when the saved identity no longer fits."""
    if previous is None or previous.root != str(root):
        return None

    device = current.device
    filesystem_uuid = current.filesystem_uuid
    identity_problem: str | None = None
    if (
        previous.filesystem_uuid is not None
        and filesystem_uuid is not None
        and previous.filesystem_uuid != filesystem_uuid
    ):
        identity_problem = (
            "watched root is on a different filesystem than last time "
            f"(UUID {previous.filesystem_uuid} -> {filesystem_uuid})"
        )
    else:
        same_uuid = (
            previous.filesystem_uuid is not None
            and filesystem_uuid is not None
            and previous.filesystem_uuid == filesystem_uuid
        )
        if not same_uuid and previous.device != device:
            identity_problem = (
                "watched root is on a different device than last time "
                f"({_device_label(previous.device)} -> {_device_label(device)})"
            )
            if previous.filesystem_uuid is None:
                identity_problem += (
                    "; the saved identity predates filesystem UUIDs, so "
                    "repopull cannot confirm the disk"
                )

    if identity_problem is not None:
        if previous.repo_count > 0 and repo_count == 0:
            identity_problem += (
                "; it also contains no repositories "
                f"(saved {previous.repo_count})"
            )
        # Repair must never replace a positive saved count with zero: that
        # would disable the empty-root guard permanently.
        return identity_problem, repo_count > 0

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
    current: RootIdentity,
    repo_count: int,
) -> str | None:
    """Pure comparison seam: return a refusal message, if any."""
    result = _classify_root_change(
        previous,
        root=root,
        current=current,
        repo_count=repo_count,
    )
    return result[0] if result is not None else None


def check_root_state(
    log_dir: Path,
    root: Path,
    repo_count: int,
) -> RootStateCheck:
    """Compare the saved identity and record a successful discovery."""
    loaded = read_root_state(log_dir)
    if loaded.problem is not None:
        return RootStateCheck(loaded.problem, None, None, repo_count)
    previous = loaded.state
    try:
        current = root_identity(root)
    except OSError:
        return RootStateCheck(None, previous, None, repo_count)

    result = _classify_root_change(
        previous,
        root=root,
        current=current,
        repo_count=repo_count,
    )
    if result is not None:
        message, repairable = result
        return RootStateCheck(
            message, previous, current, repo_count, repairable
        )
    if repo_count > 0:
        try:
            save_root_state(
                log_dir,
                root,
                repo_count,
                identity=current,
                previous=previous,
            )
        except OSError:
            pass
    return RootStateCheck(None, previous, current, repo_count)


def repair_root_state(
    log_dir: Path, root: Path, check: RootStateCheck
) -> RootIdentity:
    """Accept the checked identity only if nothing changed meanwhile.

    The GUI confirmation can sit on screen while a disk is remounted or
    another writer replaces the state file. Re-read both sides immediately
    before writing; if either moved, refuse instead of overwriting a newer
    observation with a stale one.
    """
    if (
        not check.repairable
        or check.previous is None
        or check.current is None
    ):
        raise ValueError("this root state is not repairable")

    loaded = read_root_state(log_dir)
    if loaded.problem is not None:
        raise RootStateChanged(loaded.problem)
    if loaded.state != check.previous:
        raise RootStateChanged(
            "the saved root state changed while the confirmation was open"
        )

    current = root_identity(root)
    if current != check.current:
        raise RootStateChanged(
            "the watched folder's mounted filesystem changed while the "
            "confirmation was open"
        )

    save_root_state(
        log_dir,
        root,
        check.repo_count,
        identity=current,
        previous=check.previous,
    )
    return current
