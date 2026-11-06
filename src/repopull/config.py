"""Configuration loading, defaults, and validation."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from repopull.refresh import clamp_auto_refresh_s

DEFAULT_ROOT: Final[Path | None] = None
"""No watched folder is assumed; the user chooses one on first run."""

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "root",
        "max_depth",
        "ignore",
        "fetch_timeout_s",
        "command_timeout_s",
        "delay_between_repos_s",
        "update_submodules",
        "require_git_lfs_for_lfs_repos",
        "background_mode",
        "auto_refresh_s",
        "log_dir",
        "log_retention_days",
    }
)


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or is invalid."""


def project_home() -> Path:
    """Project root: `REPOPULL_HOME`, else two levels above this file."""
    override = os.environ.get("REPOPULL_HOME")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    """The config file shipped with the project."""
    return project_home() / "config.toml"


@dataclass(frozen=True, slots=True)
class Config:
    """Effective settings for one run."""

    root: Path | None = DEFAULT_ROOT
    max_depth: int = 2
    ignore: tuple[str, ...] = ()
    fetch_timeout_s: float = 300.0
    command_timeout_s: float = 120.0
    delay_between_repos_s: float = 0.5
    update_submodules: bool = True
    require_git_lfs_for_lfs_repos: bool = True
    background_mode: bool = False
    auto_refresh_s: int = 0
    log_dir: Path = field(default_factory=lambda: project_home() / "logs")
    log_retention_days: int = 30
    # Provenance, so the tool can explain where it is pointing and why.
    config_path: Path | None = None
    config_found: bool = False
    root_source: str = "not configured"


def _config_path_from_env() -> Path | None:
    value = os.environ.get("REPOPULL_CONFIG")
    return Path(value).expanduser() if value else None


def _as_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} must be true or false")


def _as_float(value: Any, key: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number < 0:
            raise ConfigError(f"{key} must not be negative")
        return number
    raise ConfigError(f"{key} must be a number")


def _as_int(value: Any, key: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 1:
            raise ConfigError(f"{key} must be at least 1")
        return value
    raise ConfigError(f"{key} must be an integer")


def _as_non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ConfigError(f"{key} must not be negative")
        return value
    raise ConfigError(f"{key} must be an integer")


def load_config(
    *,
    config_path: Path | None = None,
    root_override: Path | None = None,
) -> Config:
    """Load `config.toml` and apply command-line overrides.

    Missing file is fine when no explicit path was given: built-in defaults
    apply. An explicitly requested file that does not exist is an error.
    """
    path = config_path or _config_path_from_env() or default_config_path()

    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {path}: {exc}") from exc
    elif config_path is not None:
        raise ConfigError(f"config file not found: {path}")

    unknown = set(data) - _KNOWN_KEYS
    if unknown:
        print(
            f"repopull: ignoring unknown config keys: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )

    root = root_override
    root_source: str
    if root_override is not None:
        root = root_override
        root_source = "--root"
    else:
        raw_root = data.get("root")
        if raw_root is not None:
            root = Path(str(raw_root))
            root_source = f'{path.name} key "root"'
        else:
            root = None
            root_source = "not configured"
    if root is not None:
        root = root.expanduser()

    raw_log_dir = data.get("log_dir", "logs")
    if not isinstance(raw_log_dir, str):
        raise ConfigError("log_dir must be a string")
    log_dir = Path(raw_log_dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = project_home() / log_dir

    raw_auto_refresh = _as_non_negative_int(
        data.get("auto_refresh_s", 0), "auto_refresh_s"
    )
    auto_refresh_s = clamp_auto_refresh_s(raw_auto_refresh)
    if raw_auto_refresh != auto_refresh_s:
        print(
            "repopull: auto_refresh_s clamped from "
            f"{raw_auto_refresh} to {auto_refresh_s}",
            file=sys.stderr,
        )

    raw_ignore = data.get("ignore", [])
    if not isinstance(raw_ignore, list) or not all(
        isinstance(item, str) for item in raw_ignore
    ):
        raise ConfigError("ignore must be a list of strings")

    try:
        return Config(
            root=root,
            max_depth=_as_int(data.get("max_depth", 2), "max_depth"),
            ignore=tuple(raw_ignore),
            fetch_timeout_s=_as_float(
                data.get("fetch_timeout_s", 300.0), "fetch_timeout_s"
            ),
            command_timeout_s=_as_float(
                data.get("command_timeout_s", 120.0), "command_timeout_s"
            ),
            delay_between_repos_s=_as_float(
                data.get("delay_between_repos_s", 0.5), "delay_between_repos_s"
            ),
            update_submodules=_as_bool(
                data.get("update_submodules", True), "update_submodules"
            ),
            require_git_lfs_for_lfs_repos=_as_bool(
                data.get("require_git_lfs_for_lfs_repos", True),
                "require_git_lfs_for_lfs_repos",
            ),
            background_mode=_as_bool(
                data.get("background_mode", False), "background_mode"
            ),
            auto_refresh_s=auto_refresh_s,
            log_dir=log_dir,
            log_retention_days=_as_non_negative_int(
                data.get("log_retention_days", 30), "log_retention_days"
            ),
            config_path=path,
            config_found=path.is_file(),
            root_source=root_source,
        )
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration in {path}: {exc}") from exc


def _write_config_atomic(path: Path, text: str) -> None:
    """Write a config file through a flushed, fsynced temporary file."""
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
    try:
        directory = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory)
    except OSError:
        pass
    finally:
        os.close(directory)


def save_config(config: Config, path: Path) -> None:
    """Write the known keys to `path` atomically, with a short header.

    The GUI uses this when the user changes the watched folder. Comments from a
    hand-edited file are not preserved; the generated header says so.
    """
    lines = [
        "# repopull configuration (written by the GUI).",
        "# The only link between this tool and the watched repos is the root key.",
    ]
    if config.root is not None:
        lines.append(f"root = {json.dumps(str(config.root))}")
    else:
        lines.append('# root = "/path/to/your/repositories"')
    lines.extend(
        [
            f"max_depth = {config.max_depth}",
            "ignore = ["
            + ", ".join(json.dumps(item) for item in config.ignore)
            + "]",
            f"fetch_timeout_s = {config.fetch_timeout_s:g}",
            f"command_timeout_s = {config.command_timeout_s:g}",
            f"delay_between_repos_s = {config.delay_between_repos_s:g}",
            f"update_submodules = {str(config.update_submodules).lower()}",
            "require_git_lfs_for_lfs_repos = "
            f"{str(config.require_git_lfs_for_lfs_repos).lower()}",
            f"background_mode = {str(config.background_mode).lower()}",
            f"auto_refresh_s = {config.auto_refresh_s}",
            f"log_dir = {json.dumps(str(config.log_dir))}",
            f"log_retention_days = {config.log_retention_days}",
            "",
        ]
    )
    _write_config_atomic(path, "\n".join(lines))


def save_behavior_settings(
    path: Path,
    *,
    background_mode: bool,
    auto_refresh_s: int,
) -> None:
    """Update only the two behavior keys, preserving other lines and comments.

    This is for the checkboxes that must take effect immediately; the full
    `save_config` rewrite remains behind the Save button.
    """
    updates = {
        "background_mode": str(background_mode).lower(),
        "auto_refresh_s": str(auto_refresh_s),
    }
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    found: set[str] = set()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        for key, value in updates.items():
            if stripped == key or stripped.startswith(key + " ") or stripped.startswith(
                key + "="
            ):
                indent = line[: len(line) - len(stripped)]
                lines[index] = f"{indent}{key} = {value}"
                found.add(key)
    for key, value in updates.items():
        if key not in found:
            lines.append(f"{key} = {value}")

    _write_config_atomic(path, "\n".join(lines) + "\n")
