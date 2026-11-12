"""Ask GitHub for the latest repopull release.

The check only reads. repopull never downloads or replaces its own image, so a
failed or hostile answer can cost a stale notification and nothing else.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from repopull import __version__

API_URL = "https://api.github.com/repos/EricBright/repopull/releases/latest"
RELEASE_PAGE = "https://github.com/EricBright/repopull/releases/tag/{tag}"
TIMEOUT_S = 10.0

Fetcher = Callable[[str], bytes]
"""Reads a URL and returns the body; tests and the GUI inject their own."""

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-?rc(\d+))?$")


class UpdateError(RuntimeError):
    """The check could not be completed; the message is for the user."""


@dataclass(frozen=True, slots=True)
class Version:
    """The parts of a release tag that decide which number is newer."""

    major: int
    minor: int
    patch: int
    candidate: int = 0

    @property
    def key(self) -> tuple[int, int, int, int, int]:
        """Sort key where 0.8.0rc1 < 0.8.0 but 0.8.0rc1 < 0.8.0rc2."""
        final = 1 if self.candidate == 0 else 0
        return (self.major, self.minor, self.patch, final, self.candidate)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.candidate == 0 else f"{base}rc{self.candidate}"


def parse_version(text: str) -> Version | None:
    """Read `0.8.0`, `v0.8.0` or `v0.8.0-rc1`; None for anything else."""
    match = _VERSION.match(text.strip())
    if match is None:
        return None
    major, minor, patch, candidate = match.groups()
    return Version(
        int(major), int(minor), int(patch), int(candidate or 0)
    )


@dataclass(frozen=True, slots=True)
class Release:
    """One published release, as far as a check needs to know it."""

    version: Version
    tag: str
    page: str
    notes: str
    published: str
    asset: str | None
    download: str | None


def is_newer(release: Release, current: str = __version__) -> bool:
    """True when `release` is a later version than the running one."""
    running = parse_version(current)
    if running is None:
        return False
    return release.version.key > running.key


def _text(data: dict[object, object], key: str) -> str | None:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else None


def _appimage_asset(data: dict[object, object]) -> tuple[str | None, str | None]:
    assets = data.get("assets")
    if not isinstance(assets, list):
        return (None, None)
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = _text(asset, "name")
        url = _text(asset, "browser_download_url")
        if name is not None and url is not None and name.endswith(".AppImage"):
            return (name, url)
    return (None, None)


def _parse_release(payload: bytes) -> Release:
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise UpdateError("GitHub returned something that is not JSON") from exc
    if not isinstance(data, dict):
        raise UpdateError("GitHub returned an unexpected document")

    tag = _text(data, "tag_name")
    if tag is None:
        raise UpdateError("the release has no tag name")
    version = parse_version(tag)
    if version is None:
        raise UpdateError(
            f"the release tag {tag!r} is not a version repopull understands"
        )
    asset, download = _appimage_asset(data)
    return Release(
        version=version,
        tag=tag,
        page=_text(data, "html_url") or RELEASE_PAGE.format(tag=tag),
        notes=_text(data, "body") or "",
        published=_text(data, "published_at") or "",
        asset=asset,
        download=download,
    )


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"repopull/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError(
                "GitHub is limiting how often this can run; try again later"
            ) from exc
        if exc.code == 404:
            raise UpdateError("no published release was found") from exc
        raise UpdateError(f"GitHub answered HTTP {exc.code}") from exc
    except OSError as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc


def latest_release(fetch: Fetcher | None = None) -> Release:
    """Read the newest published release, or raise UpdateError."""
    read = _http_get if fetch is None else fetch
    try:
        payload = read(API_URL)
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    return _parse_release(payload)
