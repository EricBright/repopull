"""The XDG autostart entry that starts the desktop interface at login.

The entry on disk is the only record: the Settings switches read it rather
than a config key, so disabling repopull in the desktop's own autostart panel
cannot drift from what the switches show.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENTRY_NAME = "repopull.desktop"
HIDDEN_FLAG = "--hidden"
SECTION = "[Desktop Entry]"
COMMENT = "Watch Git repositories and pull when they change"

_ESCAPED = {"\\": "\\\\", '"': '\\"', "`": "\\`", "$": "\\$"}
_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "_./+,:@=-"
)
_VALUE_ESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}


@dataclass(frozen=True, slots=True)
class Target:
    """The command an autostart entry should launch."""

    argv: tuple[str, ...]
    origin: str


@dataclass(frozen=True, slots=True)
class State:
    """What the entry on disk currently says."""

    installed: bool
    hidden: bool
    argv: tuple[str, ...] = ()


def entry_path(env: Mapping[str, str] | None = None) -> Path:
    """Where this user's autostart entries live."""
    values = os.environ if env is None else env
    configured = values.get("XDG_CONFIG_HOME", "").strip()
    if configured and Path(configured).is_absolute():
        base = Path(configured)
    else:
        base = Path(values.get("HOME", "") or str(Path.home())) / ".config"
    return base / "autostart" / ENTRY_NAME


def _runnable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve_target(
    *,
    env: Mapping[str, str] | None = None,
    argv0: str | None = None,
    executable: str | None = None,
) -> Target | None:
    """Find a command that will still exist at the next login.

    An AppImage reports its own path in `APPIMAGE`; `sys.argv[0]` there points
    into a mount that is gone by then, so it is never used. A checkout run has
    `bin/repopull-gui`, which sets up its own environment. Nothing inside a
    mounted AppDir survives either, hence the guards below.
    """
    values = os.environ if env is None else env
    program = executable or sys.executable

    appimage = values.get("APPIMAGE", "").strip()
    if appimage:
        path = Path(appimage)
        return Target((str(path),), "AppImage") if _runnable(path) else None

    home = values.get("REPOPULL_HOME", "").strip()
    if home:
        launcher = Path(home) / "bin" / "repopull-gui"
        if _runnable(launcher):
            return Target((str(launcher),), "checkout")

    appdir = values.get("APPDIR", "").strip()
    found = shutil.which("repopull-gui", path=values.get("PATH"))
    if found is not None and not (appdir and found.startswith(appdir)):
        return Target((found,), "installed command")

    if appdir:
        # A mounted AppDir's interpreter disappears with the mount.
        return None
    return Target((program, "-m", "repopull.gui"), "Python module")


def _value_escape(text: str) -> str:
    """Apply the string-value escape rule (`\\\\` for one backslash)."""
    escaped = text.replace("\\", "\\\\")
    return (
        escaped.replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def quote_exec_argument(value: str) -> str:
    """One Exec argument, left alone when it is plainly safe, else quoted."""
    if value and all(char in _SAFE for char in value):
        return value
    quoted = "".join(_ESCAPED.get(char, char) for char in value)
    return '"' + _value_escape(quoted) + '"'


def _exec_field(argv: tuple[str, ...]) -> str:
    return " ".join(
        quote_exec_argument(arg.replace("%", "%%")) for arg in argv
    )


def _unescape_value(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            replacement = _VALUE_ESCAPES.get(text[index + 1])
            if replacement is not None:
                result.append(replacement)
                index += 2
                continue
        result.append(char)
        index += 1
    return "".join(result)


def split_exec(value: str) -> tuple[str, ...]:
    """Undo quoting and escaping, returning the arguments as they were built."""
    text = _unescape_value(value)
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    started = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] in _ESCAPED:
            current.append(text[index + 1])
            started = True
            index += 2
            continue
        if char == '"':
            in_quotes = not in_quotes
            started = True
            index += 1
            continue
        if char in " \t" and not in_quotes:
            if started:
                tokens.append("".join(current))
                current = []
                started = False
            index += 1
            continue
        current.append(char)
        started = True
        index += 1
    if started:
        tokens.append("".join(current))
    return tuple(token.replace("%%", "%") for token in tokens)


def parse(text: str) -> dict[str, str]:
    """Read the keys of the `[Desktop Entry]` group."""
    values: dict[str, str] = {}
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line == SECTION
            continue
        if not in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def render(argv: tuple[str, ...]) -> str:
    """The entry text for one command line."""
    return "\n".join(
        (
            SECTION,
            "Type=Application",
            "Name=repopull",
            f"Comment={COMMENT}",
            f"Exec={_exec_field(argv)}",
            "Icon=repopull",
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        )
    )


def read(path: Path) -> State:
    """The current state, treating a missing or broken file as "off"."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return State(installed=False, hidden=False)
    values = parse(text)
    disabled = (
        values.get("Hidden", "").strip().lower() == "true"
        or values.get("X-GNOME-Autostart-enabled", "").strip().lower()
        == "false"
    )
    argv = split_exec(values.get("Exec", ""))
    installed = bool(argv) and not disabled
    return State(
        installed=installed,
        hidden=installed and HIDDEN_FLAG in argv,
        argv=argv,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        # A power cut between the rename and the data reaching the disk would
        # leave an empty entry, which starts nothing at the next login.
        os.fsync(handle.fileno())
    temporary.chmod(0o644)
    temporary.replace(path)


def install(path: Path, target: Target, *, hidden: bool) -> State:
    """Write the entry, replacing whatever was there."""
    argv = target.argv + ((HIDDEN_FLAG,) if hidden else ())
    _write(path, render(argv))
    return read(path)


def uninstall(path: Path) -> State:
    """Remove the entry; a missing file is not an error."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return State(installed=False, hidden=False)


def refresh(path: Path, target: Target) -> State:
    """Repair an entry whose program is gone, keeping its hidden flag.

    Replacing an AppImage with a new version can leave the recorded path
    dangling. Only a missing program is repaired: a running checkout must not
    hijack an entry that still points at a working AppImage.
    """
    state = read(path)
    if not state.installed:
        return state
    expected = target.argv + ((HIDDEN_FLAG,) if state.hidden else ())
    if state.argv == expected:
        return state
    recorded = Path(state.argv[0]) if state.argv else None
    if recorded is None:
        return state
    if not recorded.is_absolute() or _runnable(recorded):
        return state
    return install(path, target, hidden=state.hidden)

