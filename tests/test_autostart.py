"""Tests for the XDG autostart entry written by the GUI."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from repopull.autostart import (
    ENTRY_NAME,
    HIDDEN_FLAG,
    State,
    Target,
    entry_path,
    install,
    parse,
    quote_exec_argument,
    read,
    refresh,
    render,
    resolve_target,
    split_exec,
    uninstall,
)

TRICKY = (
    "/tmp/with space/repopull.AppImage",
    "/tmp/dollar$sign/app",
    "/tmp/back`tick/app",
    '/tmp/quote"inside/app',
    "/tmp/back\\slash/app",
    "/tmp/percent%20/app",
    "",
    "/tmp/new\nline/app",
)


def _script(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class EntryPathTests(unittest.TestCase):
    def test_xdg_config_home_wins_when_absolute(self) -> None:
        path = entry_path({"XDG_CONFIG_HOME": "/tmp/xdg", "HOME": "/home/u"})
        self.assertEqual(path, Path("/tmp/xdg/autostart") / ENTRY_NAME)

    def test_relative_xdg_config_home_is_ignored(self) -> None:
        path = entry_path({"XDG_CONFIG_HOME": "relative", "HOME": "/home/u"})
        self.assertEqual(path, Path("/home/u/.config/autostart") / ENTRY_NAME)

    def test_missing_variables_fall_back_to_home(self) -> None:
        self.assertEqual(entry_path({}), entry_path())


class QuotingTests(unittest.TestCase):
    def test_plain_argument_is_left_alone(self) -> None:
        self.assertEqual(quote_exec_argument("/opt/app"), "/opt/app")
        self.assertEqual(quote_exec_argument("--hidden"), "--hidden")

    def test_space_forces_quoting(self) -> None:
        self.assertEqual(
            quote_exec_argument("/opt/my app"), '"/opt/my app"'
        )

    def test_empty_argument_stays_an_argument(self) -> None:
        self.assertEqual(quote_exec_argument(""), '""')

    def test_backslash_needs_four(self) -> None:
        self.assertEqual(
            quote_exec_argument("/a\\b"), '"/a\\\\\\\\b"'
        )

    def test_specials_are_backslashed_twice(self) -> None:
        self.assertEqual(quote_exec_argument("/a$b"), '"/a\\\\$b"')
        self.assertEqual(quote_exec_argument("/a`b"), '"/a\\\\`b"')
        self.assertEqual(quote_exec_argument('/a"b'), '"/a\\\\"b"')

    def test_every_tricky_argument_survives_a_round_trip(self) -> None:
        for value in TRICKY:
            with self.subTest(value=value):
                quoted = quote_exec_argument(value)
                self.assertEqual(split_exec(quoted), (value,))

    def test_percent_is_escaped_as_a_field_code(self) -> None:
        text = render(("/tmp/100%/app",))
        self.assertIn("100%%", text)
        self.assertEqual(read_from(text).argv, ("/tmp/100%/app",))

    def test_entries_round_trip_through_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autostart" / ENTRY_NAME
            target = Target(TRICKY, "test")

            install(path, target, hidden=True)

            state = read(path)
            self.assertTrue(state.installed)
            self.assertTrue(state.hidden)
            self.assertEqual(state.argv, TRICKY + (HIDDEN_FLAG,))

    def test_parse_ignores_other_groups_and_comments(self) -> None:
        values = parse(
            "# a comment\n[Other]\nName=nope\n[Desktop Entry]\n"
            "Name=repopull\nExec=/bin/app\n"
        )
        self.assertEqual(values["Name"], "repopull")
        self.assertEqual(values["Exec"], "/bin/app")


def read_from(text: str) -> State:
    """Read a state from text by writing it to a temporary file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ENTRY_NAME
        path.write_text(text, encoding="utf-8")
        return read(path)


class StateTests(unittest.TestCase):
    def test_missing_file_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = read(Path(tmp) / ENTRY_NAME)
            self.assertFalse(state.installed)
            self.assertFalse(state.hidden)
            self.assertEqual(state.argv, ())

    def test_hidden_flags_disable_the_entry(self) -> None:
        base = "[Desktop Entry]\nExec=/bin/repopull-gui\n"
        for extra in ("Hidden=true\n", "X-GNOME-Autostart-enabled=false\n"):
            with self.subTest(extra=extra):
                state = read_from(base + extra)
                self.assertFalse(state.installed)

    def test_install_then_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autostart" / ENTRY_NAME
            target = Target(("/bin/app",), "t")
            self.assertTrue(install(path, target, hidden=False).installed)
            self.assertTrue(path.is_file())

            self.assertFalse(uninstall(path).installed)
            self.assertFalse(path.exists())
            self.assertFalse(uninstall(path).installed)

    def test_installed_file_states_its_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ENTRY_NAME
            install(path, Target(("/bin/app",), "t"), hidden=False)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Type=Application", text)
            self.assertIn("Name=repopull", text)
            self.assertIn("X-GNOME-Autostart-enabled=true", text)
            self.assertNotIn(HIDDEN_FLAG, text)


class RefreshTests(unittest.TestCase):
    def test_moved_executable_is_repaired_and_keeps_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ENTRY_NAME
            install(path, Target(("/old/app.AppImage",), "AppImage"), hidden=True)

            state = refresh(path, Target(("/new/app.AppImage",), "AppImage"))

            self.assertEqual(
                state.argv, ("/new/app.AppImage", HIDDEN_FLAG)
            )
            self.assertTrue(state.hidden)

    def test_matching_entry_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ENTRY_NAME
            install(path, Target(("/same/app",), "t"), hidden=False)
            before = path.stat().st_mtime_ns

            refresh(path, Target(("/same/app",), "t"))

            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_a_working_entry_is_not_hijacked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ENTRY_NAME
            installed = _script(Path(tmp) / "bin", "repopull-gui")
            install(path, Target((str(installed),), "t"), hidden=False)

            state = refresh(path, Target(("/somewhere/else",), "t"))

            self.assertEqual(state.argv, (str(installed),))

    def test_absent_entry_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ENTRY_NAME
            self.assertFalse(refresh(path, Target(("/same/app",), "t")).installed)
            self.assertFalse(path.exists())


class TargetTests(unittest.TestCase):
    def test_appimage_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appimage = _script(Path(tmp), "app.AppImage")
            target = resolve_target(
                env={"APPIMAGE": str(appimage), "PATH": ""},
                argv0=str(appimage),
            )
            self.assertIsNotNone(target)
            assert target is not None
            self.assertEqual(target.argv, (str(appimage),))

    def test_missing_appimage_is_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            absent = str(Path(tmp) / "gone.AppImage")
            launcher = _script(Path(tmp), "repopull-gui")
            self.assertIsNone(
                resolve_target(
                    env={"APPIMAGE": absent, "PATH": str(Path(tmp))},
                    executable=str(launcher),
                )
            )

    def test_checkout_launcher_is_preferred_over_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "checkout"
            launcher = _script(home / "bin", "repopull-gui")
            elsewhere = _script(Path(tmp) / "bin", "repopull-gui")
            target = resolve_target(
                env={"REPOPULL_HOME": str(home), "PATH": str(elsewhere.parent)},
            )
            assert target is not None
            self.assertEqual(target.argv, (str(launcher),))

    def test_installed_command_is_used_when_nothing_else_fits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launcher = _script(Path(tmp), "repopull-gui")
            target = resolve_target(env={"PATH": str(Path(tmp))})
            assert target is not None
            self.assertEqual(target.argv, (str(launcher),))

    def test_nothing_inside_a_mounted_appdir_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdir = Path(tmp) / "AppDir"
            launcher = _script(appdir / "bin", "repopull-gui")
            self.assertIsNone(
                resolve_target(
                    env={"APPDIR": str(appdir), "PATH": str(launcher.parent)},
                    executable=str(appdir / "python3"),
                )
            )

    def test_a_plain_python_run_falls_back_to_the_module(self) -> None:
        target = resolve_target(env={"PATH": ""}, executable="/usr/bin/python3")
        assert target is not None
        self.assertEqual(
            target.argv, ("/usr/bin/python3", "-m", "repopull.gui")
        )
        self.assertEqual(target.origin, "Python module")


class EnvironmentTests(unittest.TestCase):
    def test_real_entry_path_is_under_home(self) -> None:
        path = entry_path()
        self.assertEqual(path.name, ENTRY_NAME)
        self.assertTrue(str(path).endswith(".config/autostart/repopull.desktop"))
        self.assertEqual(os.path.basename(str(path.parent)), "autostart")

    def test_python_fallback_uses_this_interpreter(self) -> None:
        target = resolve_target(env={"PATH": ""})
        assert target is not None
        self.assertEqual(target.argv[0], sys.executable)
