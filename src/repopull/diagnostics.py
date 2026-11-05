"""Human-readable explanations of where repopull points and how to fix it.

The one link between this tool and the watched data is the ``root`` setting.
These helpers make that link visible on demand (``repopull where``) and make a
missing or empty root actionable instead of a bare stack-free error.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from repopull import git
from repopull.config import Config
from repopull.discovery import DiscoveryError, discover_repos


def _config_label(config: Config) -> str:
    if config.config_path is None:
        return "(none)"
    state = "found" if config.config_found else "MISSING"
    return f"{config.config_path} ({state})"


def _root_state(config: Config) -> str:
    if config.root is None:
        return "not configured"
    if not config.root.exists():
        return "MISSING"
    if not config.root.is_dir():
        return "not a directory"
    try:
        refs = discover_repos(
            config.root, max_depth=config.max_depth, ignore=config.ignore
        )
    except DiscoveryError as exc:
        return f"unreadable ({exc})"
    noun = "repo" if len(refs) == 1 else "repos"
    return f"found, {len(refs)} {noun}"


def describe_paths(config: Config) -> str:
    """One screen answering: where is the link, and is it working?"""
    root_text = (
        str(config.root) if config.root is not None else "(not configured)"
    )
    if config.root is None:
        hint = (
            'Choose the watched folder in the GUI Settings, or set "root" in '
            "the config file above, or pass --root PATH."
        )
    elif config.root_source == "--root":
        if config.config_found:
            hint = (
                "This run uses --root. To make it permanent, edit the "
                '"root" key in the config file above.'
            )
        else:
            hint = (
                "This run uses --root. To make it permanent, create "
                "config.toml with a root key."
            )
    else:
        hint = 'Edit "root" in the config file above, or pass --root PATH.'

    root_line = (
        f"root:        {root_text}"
        if config.root is None
        else f"root:        {root_text} ({_root_state(config)})"
    )
    lines = [
        f"config file: {_config_label(config)}",
        root_line,
        f"root source: {config.root_source}",
        f"logs:        {config.log_dir}",
    ]
    if config.root is not None and not config.root.exists():
        lines.extend(
            [
                "",
                "The root is missing: mount the disk, fix the path, or pass --root.",
            ]
        )
    lines.extend(
        [
            "",
            'The only link between this tool and the watched repos is the "root" key above.',
            hint,
        ]
    )
    return "\n".join(lines)


def missing_root_advice(config: Config) -> str:
    """Actionable text shown when no watched root is configured or found."""
    if config.config_path is None:
        config_line = "  config file: (none found)"
        edit_line = "    - or create config.toml containing a root key;"
    else:
        state = "" if config.config_found else "  (not found)"
        config_line = f"  config file: {config.config_path}{state}"
        edit_line = f'    - or edit the "root" key in {config.config_path};'

    if config.root is None:
        first_step = (
            "    - open the GUI and choose the watched folder in Settings;"
        )
    else:
        first_step = (
            "    - if the external disk is not mounted, mount it and rerun;"
        )

    lines = [
        f"  root source: {config.root_source}",
        config_line,
        "  Next steps:",
        first_step,
        edit_line,
        "    - or pass --root PATH for this one run.",
        "  Run `repopull where` to inspect the resolved paths at any time.",
    ]
    return "\n".join(lines)


def no_repos_advice(config: Config) -> str:
    """Actionable text shown when the root exists but contains no repositories."""
    where = (
        str(config.config_path)
        if config.config_path is not None
        else "config.toml (not present)"
    )
    return "\n".join(
        [
            f"  root source: {config.root_source}",
            "  Check that the disk is mounted and that max_depth/ignore in",
            f"  {where} still match the folder layout.",
            "  Run `repopull where` to inspect the resolved paths at any time.",
        ]
    )


@dataclass(frozen=True, slots=True)
class LfsStatus:
    """What the machine can tell us about Git LFS."""

    installed: bool
    enabled: bool
    version: str
    install_hint: str
    docs_url: str = "https://git-lfs.com/"


def lfs_install_hint() -> str:
    """A package-manager command for this machine, or a generic sentence."""
    if sys.platform == "darwin":
        return "brew install git-lfs"

    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return "Install git-lfs with your package manager."

    values: list[str] = []
    for line in release.splitlines():
        if line.startswith(("ID=", "ID_LIKE=")):
            value = line.split("=", 1)[1].strip().strip('"')
            values.extend(value.split())
    joined = " ".join(values)

    # Immutable Fedora (Bazzite, Silverblue, Kinoite) has a read-only root;
    # `dnf install` is not the right tool there. Homebrew is user-level and
    # needs no reboot, so prefer it when present.
    if "bazzite" in joined or Path("/run/ostree-booted").exists():
        if shutil.which("brew") is not None:
            return "brew install git-lfs"
        return "rpm-ostree install git-lfs"

    if "debian" in joined or "ubuntu" in joined:
        return "sudo apt install git-lfs"
    if "fedora" in joined or "rhel" in joined or "centos" in joined:
        return "sudo dnf install git-lfs"
    if "arch" in joined:
        return "sudo pacman -S git-lfs"
    if "suse" in joined:
        return "sudo zypper install git-lfs"
    if "alpine" in joined:
        return "sudo apk add git-lfs"
    return "Install git-lfs with your package manager."


def lfs_status(repo: Path | None = None) -> LfsStatus:
    """Read-only Git LFS status; never installs or configures anything."""
    version = git.git_lfs_version() or ""
    installed = bool(version)
    if not installed:
        enabled = False
    elif repo is not None:
        enabled = git.git_lfs_enabled(repo, timeout=10)
    else:
        enabled = git.git_lfs_enabled_global()
    return LfsStatus(
        installed=installed,
        enabled=enabled,
        version=version,
        install_hint=lfs_install_hint(),
    )
