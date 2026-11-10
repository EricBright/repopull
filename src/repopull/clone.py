"""Clone one remote into the watched folder.

`repopull` is pull-only for the repositories it already watches. A clone is the
one operation that creates a new repository, so it gets its own validation:

* only ordinary web, SSH, git, file or local-path addresses are accepted;
* the destination is one folder name, never a path;
* the clone happens in a hidden temporary folder and is renamed into place, so
  an interrupted clone is never discovered as a repository;
* an existing folder is never overwritten.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from repopull import git
from repopull.discovery import CLONE_TEMP_PREFIX

_ALLOWED_SCHEMES = frozenset({"http", "https", "ssh", "git", "file"})
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_SCP_LIKE = re.compile(r"^(?:[A-Za-z0-9._~-]+@)?[A-Za-z0-9._-]+:.+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_NAME = 120


class CloneError(RuntimeError):
    """A clone cannot be started or did not finish."""


class CloneCancelled(CloneError):
    """The user cancelled the clone; no destination was created."""


@dataclass(frozen=True, slots=True)
class CloneResult:
    """A repository that was cloned successfully."""

    destination: Path
    url: str
    empty: bool = False


def validate_url(raw: str) -> str:
    """Return a safe clone address or explain why it is rejected."""
    url = raw.strip()
    if not url:
        raise CloneError("Enter a repository URL.")
    if url.startswith("-"):
        raise CloneError("A repository URL cannot start with '-'.")
    if _CONTROL.search(url):
        raise CloneError("The repository URL contains a control character.")

    scheme = _SCHEME.match(url)
    if scheme is not None:
        name = scheme.group(1).casefold()
        if name not in _ALLOWED_SCHEMES:
            raise CloneError(
                f"{name} addresses are not supported; use https, ssh, git, "
                "file, or a local path."
            )
        return url

    # Git's "ext::" (and similar) transports run a helper command. They are
    # not repository addresses, and repopull never needs them.
    if "::" in url:
        raise CloneError("That git transport is not supported.")

    if _SCP_LIKE.match(url):
        return url

    path = Path(url).expanduser()
    if not path.exists():
        raise CloneError("Not a recognised URL or an existing local path.")
    return url


def derive_name(url: str) -> str:
    """Guess a folder name from a URL, without validating the result."""
    text = url.strip().rstrip("/")
    if "://" in text:
        candidate = urlsplit(text).path.rstrip("/").rsplit("/", 1)[-1]
    elif _SCP_LIKE.match(text):
        candidate = (
            text.rsplit(":", 1)[-1].rstrip("/").rsplit("/", 1)[-1]
        )
    else:
        candidate = Path(text).name
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    return candidate


def validate_name(raw: str) -> str:
    """Return a single, safe folder name or raise CloneError."""
    name = raw.strip()
    if not name:
        raise CloneError("Enter a folder name.")
    if name in {".", ".."}:
        raise CloneError("'.' and '..' are not folder names.")
    if name.startswith((".", "-")):
        raise CloneError("The folder name cannot start with '.' or '-'.")
    if len(name) > _MAX_NAME:
        raise CloneError(f"The folder name must be at most {_MAX_NAME} characters.")
    if "/" in name or "\\" in name or "\x00" in name:
        raise CloneError("The folder name must not contain a path separator.")
    if _CONTROL.search(name):
        raise CloneError("The folder name contains a control character.")
    return name


def destination_for(root: Path, name: str) -> Path:
    """Absolute destination inside `root`; the name is validated first."""
    root = root.expanduser()
    if not root.is_dir():
        raise CloneError(f"The watched folder does not exist: {root}")
    return root.resolve() / validate_name(name)


def clone_repository(
    url: str,
    name: str,
    root: Path,
    *,
    timeout: float,
    cancel: Event | None = None,
) -> CloneResult:
    """Clone `url` into `root/name`, cleaning up on failure or cancellation."""
    url = validate_url(url)
    name = validate_name(name)
    root = root.expanduser()
    if not root.is_dir():
        raise CloneError(f"The watched folder does not exist: {root}")
    root = root.resolve()
    destination = root / name
    if os.path.lexists(destination):
        raise CloneError(f"A folder named '{name}' already exists in {root}.")

    try:
        temporary = Path(tempfile.mkdtemp(prefix=CLONE_TEMP_PREFIX, dir=root))
    except OSError as exc:
        raise CloneError(f"Cannot write to {root}: {exc}") from exc

    try:
        checkout = temporary / "repo"
        result = git.run_git(
            root,
            "clone",
            "--progress",
            "--",
            url,
            str(checkout),
            timeout=timeout,
            cancel=cancel,
        )
        if result.cancelled:
            raise CloneCancelled("Clone cancelled.")
        if result.timed_out:
            raise CloneError(f"Clone timed out after {timeout:g}s.")
        if not result.ok:
            raise CloneError(result.summary())
        if not (checkout / ".git").exists():
            raise CloneError("git did not create a repository.")

        empty = git.head_sha(checkout, timeout=min(30.0, timeout)) is None
        try:
            os.rename(checkout, destination)
        except OSError as exc:
            raise CloneError(f"Cannot create {destination}: {exc}") from exc
        return CloneResult(destination=destination, url=url, empty=empty)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
