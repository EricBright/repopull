"""Shrink the staged AppDir to the Qt modules repopull actually imports.

`python-appimage` installs the complete PySide6-Essentials wheel. That wheel is
built for every Qt application, so it also carries QML, Quick, Designer, the
designer command-line tools, type stubs, translations for modules this app does
not use, and a bundled pip. None of it is reachable from repopull.

The trim is deliberately narrow: it deletes a fixed list of known-unused trees,
then follows the ELF NEEDED entries of every retained Python binding and Qt
plugin, keeping exactly the shared libraries those files load. If a retained
file needs a Qt library that is absent, the build stops rather than producing an
image that only starts on the build machine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

KEEP_BINDINGS = frozenset({"QtCore", "QtGui", "QtWidgets", "QtNetwork"})
"""PySide6 Python modules imported by repopull; see tests/test_packaging.py."""

KEEP_PLATFORM_PLUGINS = frozenset(
    {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"}
)
"""The four Qt platform plugins a Linux desktop needs (or a smoke test)."""

KEEP_TRANSLATION_PREFIXES = ("qtbase_", "qt_")
"""Qt's own strings; dialog buttons stay translated."""

IMAGE_SIZE_CEILING = 60 * 1024 * 1024
"""Build fails above this, so a dependency bump cannot silently double the file."""

_DROP_PLUGIN_DIRS = (
    "designer",
    "qmltooling",
    "sqldrivers",
    "printsupport",
    "vectorimageformats",
    "wayland-graphics-integration-server",
    "egldeviceintegrations",
)

_DROP_PYSIDE_TOOLS = (
    "assistant",
    "designer",
    "linguist",
    "lrelease",
    "lupdate",
    "qmlformat",
    "qmllint",
    "qmlls",
    "svgtoqml",
)

_NEEDED = re.compile(r"\(NEEDED\).*\[([^\]]+)\]")


class TrimError(RuntimeError):
    """Raised when the AppDir does not have the expected layout."""


@dataclass(frozen=True, slots=True)
class TrimResult:
    """What the trim changed, for the build log."""

    appdir_bytes: int
    kept_bindings: int
    kept_libraries: int
    removed_entries: int


def keeps_binding(filename: str) -> bool:
    """True for the PySide6 bindings repopull imports."""
    name = Path(filename).name
    if not name.endswith(".abi3.so"):
        return False
    return any(name == f"{module}.abi3.so" for module in KEEP_BINDINGS)


def keeps_platform_plugin(filename: str) -> bool:
    """True for the platform plugins kept in the image."""
    return Path(filename).name in KEEP_PLATFORM_PLUGINS


def keeps_translation(filename: str) -> bool:
    """True for Qt's own translation catalogues, e.g. qtbase_de.qm."""
    return Path(filename).name.startswith(KEEP_TRANSLATION_PREFIXES)


def _python_prefix(appdir: Path) -> Path:
    candidates = sorted(
        path
        for path in (appdir / "opt").glob("python3.*")
        if path.is_dir() and (path / "lib").is_dir()
    )
    if len(candidates) != 1:
        raise TrimError(
            f"expected one opt/python3.* directory in {appdir}, found {len(candidates)}"
        )
    return candidates[0]


def _delete(path: Path) -> bool:
    """Remove a file, symlink or tree; report whether anything existed."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _delete_all(paths: Iterable[Path]) -> int:
    removed = 0
    for path in paths:
        if _delete(path):
            removed += 1
    return removed


def _needed_libraries(binary: Path) -> set[str]:
    """ELF NEEDED names, read with binutils rather than guessed from filenames."""
    if shutil.which("readelf") is None:
        raise TrimError("readelf is missing; install binutils to build the AppImage")
    result = subprocess.run(
        ["readelf", "-d", str(binary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TrimError(f"cannot read ELF dependencies of {binary}: {result.stderr}")
    return set(_NEEDED.findall(result.stdout))


def _prune_qt_libraries(appdir: Path, pyside: Path, qt: Path) -> tuple[int, int]:
    """Keep only Qt shared libraries reachable from bindings and plugins."""
    library_dir = qt / "lib"
    libraries = {path.name: path for path in library_dir.iterdir() if path.is_file()}
    plugins = qt / "plugins"

    pending = [*pyside.glob("*.so*"), *plugins.rglob("*.so")]
    visited: set[Path] = set()
    while pending:
        binary = pending.pop()
        if binary in visited:
            continue
        visited.add(binary)
        for name in _needed_libraries(binary):
            library = libraries.get(name)
            if library is not None:
                pending.append(library)
            elif name.startswith("libQt6"):
                relative = binary.relative_to(appdir)
                raise TrimError(f"{relative} needs {name}, which is not in the AppDir")

    removed = 0
    kept = 0
    for path in libraries.values():
        if path in visited:
            kept += 1
        else:
            path.unlink()
            removed += 1
    return kept, removed


def _appdir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def trim_appdir(appdir: Path) -> TrimResult:
    """Remove unused runtime pieces from a staged AppDir in place."""
    appdir = appdir.resolve()
    if not (appdir / "opt").is_dir():
        raise TrimError(f"not a staged AppDir: {appdir}")

    python = _python_prefix(appdir)
    site = next(
        (python / "lib").glob("python3.*/site-packages"),
        None,
    )
    if site is None or not (site / "PySide6").is_dir():
        raise TrimError(f"PySide6 is not installed under {python}")
    pyside = site / "PySide6"
    qt = pyside / "Qt"
    stdlib = python / "lib" / python.name
    removed = 0

    removed += _delete_all(
        [
            site / "pip",
            *site.glob("pip-*.dist-info"),
            stdlib / "ensurepip",
            python / "include",
            pyside / "include",
            pyside / "typesystems",
            pyside / "glue",
            pyside / "doc",
            pyside / "scripts",
            qt / "qml",
            qt / "metatypes",
            qt / "libexec",
        ]
    )

    # Python's Tk, IDLE and SQLite are part of the base image, not repopull.
    removed += _delete_all(
        [
            stdlib / "tkinter",
            stdlib / "idlelib",
            stdlib / "turtledemo",
            stdlib / "sqlite3",
            appdir / "usr/share/tcltk",
        ]
    )
    for name in ("turtle.py",):
        removed += int(_delete(stdlib / name))
    for pattern in ("_tkinter*.so", "_sqlite3*.so"):
        for path in (stdlib / "lib-dynload").glob(pattern):
            removed += int(_delete(path))
    for name in ("libtcl8.6.so", "libtk8.6.so", "libsqlite3.so"):
        removed += int(_delete(appdir / "usr/lib" / name))

    for path in pyside.glob("Qt*.abi3.so"):
        if not keeps_binding(path.name):
            removed += int(_delete(path))
    for path in pyside.glob("*.pyi"):
        removed += int(_delete(path))
    for name in _DROP_PYSIDE_TOOLS:
        removed += int(_delete(pyside / name))
    for path in pyside.glob("libpyside6qml*"):
        removed += int(_delete(path))

    plugins = qt / "plugins"
    removed += _delete_all(plugins / name for name in _DROP_PLUGIN_DIRS)
    for plugin in (plugins / "platforms").glob("*.so"):
        if not keeps_platform_plugin(plugin.name):
            removed += int(_delete(plugin))
    for name in (
        "platforminputcontexts/libqtvirtualkeyboardplugin.so",
        "imageformats/libqpdf.so",
    ):
        removed += int(_delete(plugins / name))

    translations = qt / "translations"
    if translations.is_dir():
        for path in translations.iterdir():
            if not keeps_translation(path.name):
                removed += int(_delete(path))

    kept_libraries, library_removals = _prune_qt_libraries(appdir, pyside, qt)
    removed += library_removals

    return TrimResult(
        appdir_bytes=_appdir_size(appdir),
        kept_bindings=sum(1 for path in pyside.glob("Qt*.abi3.so")),
        kept_libraries=kept_libraries,
        removed_entries=removed,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("usage: trim_appdir.py <AppDir>", file=sys.stderr)
        return 2
    result = trim_appdir(Path(argv[0]))
    print(
        f"Trimmed AppDir: {result.appdir_bytes / 1_000_000:.1f} MB, "
        f"{result.kept_bindings} bindings, {result.kept_libraries} Qt libraries, "
        f"{result.removed_entries} entries removed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
