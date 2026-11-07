"""Probe the mounted filesystem identity of a watched path."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RootIdentity:
    """What the watched path resolves to right now."""

    device: int
    filesystem_uuid: str | None
    mount_source: str | None


_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape_mountinfo(value: str) -> str:
    """Decode the octal escapes used by /proc/self/mountinfo."""
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _mount_source(path: Path, mountinfo: Path | None = None) -> str | None:
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
