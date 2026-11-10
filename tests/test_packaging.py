"""Tests for the AppImage trim policy.

The trim runs during a release build, not during normal use, so these tests use
a synthetic AppDir: they check the policy (what is deleted, what is kept) and
the source-import guard without needing a 245 MB PySide6 install.
"""

from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "trim_appdir", ROOT / "packaging" / "trim_appdir.py"
)
assert _SPEC is not None and _SPEC.loader is not None
trim = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(trim)


def _fake_appdir(base: Path) -> tuple[Path, Path, Path]:
    """Create the directories trim expects, with no real Qt payload."""
    appdir = base / "AppDir"
    pyside = (
        appdir
        / "opt/python3.13/lib/python3.13/site-packages/PySide6"
    )
    qt = pyside / "Qt"
    for path in (
        pyside / "QtCore.abi3.so",
        pyside / "QtGui.abi3.so",
        pyside / "QtWidgets.abi3.so",
        pyside / "QtQml.abi3.so",
        pyside / "QtNetwork.abi3.so",
        pyside / "QtCore.abi3.so.types",
        qt / "lib/QtCore.so.6",
        qt / "lib/QtQml.so.6",
        qt / "lib/QtGui.so.6",
        qt / "lib/QtWidgets.so.6",
        qt / "plugins/platforms/libqxcb.so",
        qt / "plugins/platforms/libqeglfs.so",
        qt / "plugins/platforms/libqwayland.so",
        qt / "plugins/platforms/libqoffscreen.so",
        qt / "plugins/platforms/libqminimal.so",
        qt / "plugins/platforms/libqlinuxfb.so",
        qt / "plugins/imageformats/libqpdf.so",
        qt / "plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
        qt / "translations/qtbase_en.qm",
        qt / "translations/qt_de.qm",
        qt / "translations/qtquickcontrols2_de.qm",
        qt / "translations/qtwebengine_de.qm",
        qt / "qml/thing.qml",
        qt / "metatypes/thing.json",
        qt / "libexec/thing",
        pyside / "include/thing.h",        pyside / "scripts/thing.py",
        pyside / "typesystems/thing.json",
        pyside / "doc/thing.html",
        appdir / "opt/python3.13/lib/python3.13/site-packages/pip/thing.py",
        appdir / "opt/python3.13/lib/python3.13/ensurepip/thing.py",
        appdir / "opt/python3.13/include/python3.13/Python.h",
        appdir / "opt/python3.13/lib/python3.13/tkinter/thing.py",
        appdir / "opt/python3.13/lib/python3.13/idlelib/thing.py",
        appdir / "opt/python3.13/lib/python3.13/turtledemo/thing.py",
        appdir / "opt/python3.13/lib/python3.13/sqlite3/thing.py",
        appdir / "opt/python3.13/lib/python3.13/turtle.py",
        appdir / "opt/python3.13/lib/python3.13/lib-dynload/_sqlite3.so",
        appdir / "opt/python3.13/lib/python3.13/lib-dynload/_tkinter.so",
        appdir / "usr/lib/libtcl8.6.so",
        appdir / "usr/lib/libtk8.6.so",
        appdir / "usr/lib/libsqlite3.so",
        appdir / "usr/share/tcltk/thing.tcl",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not a real ELF")
    return appdir, pyside, qt


_IMPORT = re.compile(r"(?:from|import)\s+PySide6\.(Qt[A-Za-z0-9]+)")
imported_qt_modules = {
    match
    for path in (ROOT / "src").rglob("*.py")
    for match in _IMPORT.findall(path.read_text(encoding="utf-8"))
}


class TrimPolicyTests(unittest.TestCase):
    def test_source_imports_match_the_keep_list(self) -> None:
        """A new Qt module in repopull must be added to KEEP_BINDINGS."""
        self.assertEqual(imported_qt_modules, set(trim.KEEP_BINDINGS))

    def test_binding_filter_keeps_only_imported_modules(self) -> None:
        for name in ("QtCore.abi3.so", "QtGui.abi3.so", "QtWidgets.abi3.so"):
            self.assertTrue(trim.keeps_binding(name), name)
        for name in (
            "QtQml.abi3.so",
            "QtNetwork.abi3.so",
            "QtOpenGL.abi3.so",
            "QtCore.so",
            "QtCore.abi3.so.6",
        ):
            self.assertFalse(trim.keeps_binding(name), name)

    def test_platform_plugins_cover_wayland_x11_and_tests(self) -> None:
        for name in (
            "libqxcb.so",
            "libqwayland.so",
            "libqoffscreen.so",
            "libqminimal.so",
        ):
            self.assertTrue(trim.keeps_platform_plugin(name), name)
        for name in ("libqeglfs.so", "libqlinuxfb.so", "libqvnc.so"):
            self.assertFalse(trim.keeps_platform_plugin(name), name)

    def test_translations_keep_qtbase_and_qt_but_not_other_modules(self) -> None:
        for name in ("qtbase_en.qm", "qtbase_de.qm", "qt_help_en.qm"):
            self.assertTrue(trim.keeps_translation(name), name)
        for name in (
            "qtquickcontrols2_de.qm",
            "qtwebengine_de.qm",
            "qtdeclarative_de.qm",
        ):
            self.assertFalse(trim.keeps_translation(name), name)


class TrimAppDirTests(unittest.TestCase):
    def test_unused_trees_and_bindings_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            appdir, pyside, qt = _fake_appdir(Path(temporary))
            with patch.object(trim, "_prune_qt_libraries", return_value=(0, 0)):
                result = trim.trim_appdir(appdir)

            self.assertGreater(result.removed_entries, 20)
            for removed in (
                pyside / "QtQml.abi3.so",
                pyside / "QtNetwork.abi3.so",
                qt / "qml",
                qt / "metatypes",
                qt / "libexec",
                pyside / "include",
                pyside / "scripts",
                pyside / "typesystems",
                qt / "plugins/platforms/libqeglfs.so",
                qt / "plugins/platforms/libqlinuxfb.so",
                qt / "plugins/imageformats/libqpdf.so",
                qt / "plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
                qt / "translations/qtquickcontrols2_de.qm",
                qt / "translations/qtwebengine_de.qm",
            ):
                self.assertFalse(removed.exists(), removed)

            for kept in (
                pyside / "QtCore.abi3.so",
                pyside / "QtGui.abi3.so",
                pyside / "QtWidgets.abi3.so",
                qt / "plugins/platforms/libqxcb.so",
                qt / "plugins/platforms/libqwayland.so",
                qt / "translations/qtbase_en.qm",
                qt / "translations/qt_de.qm",
            ):
                self.assertTrue(kept.exists(), kept)

    def test_pip_and_tk_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            appdir, pyside, _qt = _fake_appdir(Path(temporary))
            with patch.object(trim, "_prune_qt_libraries", return_value=(0, 0)):
                trim.trim_appdir(appdir)
            for removed in (
                pyside.parent / "pip",
                appdir / "opt/python3.13/lib/python3.13/ensurepip",
                appdir / "opt/python3.13/lib/python3.13/tkinter",
                appdir / "opt/python3.13/lib/python3.13/idlelib",
                appdir / "opt/python3.13/lib/python3.13/sqlite3",
                appdir / "opt/python3.13/lib/python3.13/turtle.py",
                appdir / "opt/python3.13/lib/python3.13/lib-dynload/_sqlite3.so",
                appdir / "usr/lib/libsqlite3.so",
                appdir / "usr/share/tcltk",
            ):
                self.assertFalse(removed.exists(), removed)

    def test_non_appdir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(trim.TrimError):
                trim.trim_appdir(Path(temporary))

    def test_missing_readelf_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            appdir, pyside, qt = _fake_appdir(Path(temporary))
            with patch.object(trim.shutil, "which", return_value=None):
                with self.assertRaisesRegex(trim.TrimError, "readelf"):
                    trim._prune_qt_libraries(appdir, pyside, qt)


if __name__ == "__main__":
    unittest.main()
