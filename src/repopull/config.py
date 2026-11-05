"""Configuration loading, defaults, and validation."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

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
        "log_dir",
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
    log_dir: Path = field(default_factory=lambda: project_home() / "logs")
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
            log_dir=log_dir,
            config_path=path,
            config_found=path.is_file(),
            root_source=root_source,
        )
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration in {path}: {exc}") from exc


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
            f"log_dir = {json.dumps(str(config.log_dir))}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
