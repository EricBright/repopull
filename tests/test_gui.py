"""Offscreen tests for the optional GUI; skipped when PySide6 is absent."""

from __future__ import annotations

import contextlib
import dataclasses
import gc
import json
import os
import shutil
import tempfile
import time
import unittest
import weakref
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover - exercised only without the dependency
    HAVE_PYSIDE = False
else:
    HAVE_PYSIDE = True

if HAVE_PYSIDE:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThreadPool
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from repopull import __version__, autostart
    from repopull.config import Config, load_config, save_config
    from repopull.diagnostics import LfsStatus
    from repopull.gui.jobs import RunTask
    from repopull.gui.rows import row_view, unchecked_view
    from repopull.gui.settings import SETTINGS_SECTIONS
    from repopull.gui.switch import Switch
    from repopull.gui.theme import STATUS_COLORS
    from repopull.gui.app import _repair_autostart
    from repopull.gui.instance import ask_to_show
    from repopull.gui.window import DiscoveryTask, MainWindow
    from repopull.rootstate import RootStateCheck
    from repopull.updates import Release, Version
    from repopull.models import Outcome, Report, Row
    from repopull.refresh import SuspendDetector
    from repopull.report import write_log


if HAVE_PYSIDE:

    class GuiTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls) -> None:
            cls.app = QApplication.instance() or QApplication(
                ["repopull-gui-test"]
            )

        def _config(self, base: Path, root: Path) -> Config:
            return Config(
                root=root,
                log_dir=base / "logs",
                delay_between_repos_s=0,
                update_submodules=False,
            )

        def _tree(self, base: Path) -> Path:
            root = base / "repos"
            for name in ("alpha", "beta", "gamma"):
                (root / name / ".git").mkdir(parents=True)
            return root

        def _many(self, base: Path, count: int = 40) -> Path:
            root = base / "repos"
            for index in range(count):
                (root / f"repo-{index:02d}" / ".git").mkdir(parents=True)
            return root

        def test_unconfigured_root_shows_setup_message(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(
                    Config(
                        root=None,
                        log_dir=base / "logs",
                        delay_between_repos_s=0,
                        update_submodules=False,
                    )
                )

                self.assertEqual(window.visible_row_count(), 0)
                self.assertIn("No watched folder", window.empty_label.text())
                window.close()

        def test_empty_root_mismatch_shows_removal_guidance(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / "repos"
                root.mkdir()
                logs = base / "logs"
                logs.mkdir()
                (logs / "root-state.json").write_text(
                    json.dumps(
                        {
                            "version": 2,
                            "root": str(root),
                            "device": root.stat().st_dev,
                            "repo_count": 3,
                            "filesystem_uuid": "stable-uuid",
                        }
                    ),
                    encoding="utf-8",
                )
                window = MainWindow(self._config(base, root))

                self.assertIn("empty", window.empty_label.text())
                self.assertIn("Remove", window.empty_label.text())
                self.assertTrue(window.repair_button.isHidden())
                window.close()

        def test_root_state_mismatch_offers_and_performs_repair(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                logs = base / "logs"
                logs.mkdir()
                (logs / "root-state.json").write_text(
                    json.dumps(
                        {
                            "root": str(root),
                            "device": root.stat().st_dev + 1,
                            "repo_count": 3,
                        }
                    ),
                    encoding="utf-8",
                )
                window = MainWindow(self._config(base, root))

                self.assertEqual(window.visible_row_count(), 0)
                self.assertIn("different device", window.empty_label.text())
                self.assertFalse(window.repair_button.isHidden())

                with patch(
                    "repopull.gui.window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    window._repair_root_state()

                self.assertIsNone(window.discovery_error)
                self.assertEqual(window.visible_row_count(), 3)
                self.assertTrue(window.repair_button.isHidden())
                saved = json.loads((logs / "root-state.json").read_text())
                self.assertEqual(saved["device"], root.stat().st_dev)
                self.assertEqual(saved["version"], 2)
                window.close()

        def test_repair_refuses_when_the_state_file_moved(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                logs = base / "logs"
                logs.mkdir()
                state_path = logs / "root-state.json"
                state_path.write_text(
                    json.dumps(
                        {
                            "root": str(root),
                            "device": root.stat().st_dev + 1,
                            "repo_count": 3,
                        }
                    ),
                    encoding="utf-8",
                )
                window = MainWindow(self._config(base, root))
                self.assertTrue(window.root_state_check is not None)
                self.assertTrue(window.root_state_check.repairable)

                replacement = {
                    "version": 2,
                    "root": str(root),
                    "device": root.stat().st_dev + 2,
                    "repo_count": 5,
                }
                state_path.write_text(json.dumps(replacement), encoding="utf-8")

                with (
                    patch(
                        "repopull.gui.window.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes,
                    ),
                    patch(
                        "repopull.gui.window.QMessageBox.warning"
                    ) as warning,
                ):
                    window._repair_root_state()

                warning.assert_called_once()
                self.assertIn("changed", warning.call_args.args[2])
                saved = json.loads(state_path.read_text())
                self.assertEqual(saved["device"], root.stat().st_dev + 2)
                self.assertEqual(saved["repo_count"], 5)
                window.close()

        def test_behind_refs_selects_only_behind(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                write_log(
                    Report(
                        mode="status",
                        started_at=datetime(2026, 11, 5, 16, 0, 0),
                        elapsed_s=1.0,
                        rows=(
                            Row("alpha", "main", Outcome.BEHIND, 3, ""),
                            Row("beta", "main", Outcome.UP_TO_DATE, 0, ""),
                            Row("gamma", "main", Outcome.SKIPPED, 0, "dirty"),
                        ),
                    ),
                    base / "logs",
                )
                window = MainWindow(self._config(base, root))

                self.assertEqual(
                    [ref.label for ref in window._behind_refs()], ["alpha"]
                )
                window.close()

        def test_watched_folder_link_opens_settings(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))

                self.assertEqual(window.watched_link.text(), "Watched folder")
                self.assertEqual(window.watched_link.toolTip(), str(root))
                window._open_watched_settings()
                self.assertIs(
                    window.stack.currentWidget(), window.settings_page
                )
                window.close()

        def test_open_folder_uses_the_default_handler(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))
                window.current_label = "alpha"

                with patch(
                    "repopull.gui.window.QDesktopServices.openUrl",
                    return_value=True,
                ) as open_url:
                    window._open_folder_current()

                url = open_url.call_args.args[0]
                self.assertEqual(url.toLocalFile(), str(root / "alpha"))
                window.close()

        def test_open_folder_reports_a_missing_directory(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))
                window.current_label = "alpha"
                shutil.rmtree(root / "alpha")

                with patch(
                    "repopull.gui.window.QDesktopServices.openUrl"
                ) as open_url:
                    window._open_folder_current()

                open_url.assert_not_called()
                self.assertIn("Folder not found", window.status_message.text())
                window.close()

        def test_next_check_line_and_settings_link(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                )
                window = MainWindow(config)

                self.assertTrue(
                    window.next_label.text().startswith("Next check ")
                )
                self.assertNotIn("— off", window.next_label.text())
                window.next_label.click()
                self.assertIs(
                    window.stack.currentWidget(), window.settings_page
                )
                self.assertEqual(window.settings_stack.currentIndex(), 1)

                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=0
                )
                window._schedule_auto_refresh()
                window._update_status_block()
                self.assertEqual(window.next_label.text(), "Next check — off")
                window.close()

        def test_bulk_refs_honor_exclusions(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    exclude_from_refresh=("alpha",),
                    exclude_from_sync=("beta",),
                )
                window = MainWindow(config)

                self.assertEqual(
                    [ref.label for ref in window._status_refs()],
                    ["beta", "gamma"],
                )
                self.assertEqual(
                    [ref.label for ref in window._sync_refs()],
                    ["alpha", "gamma"],
                )
                window.close()

        def test_hold_rows_filters_and_banner(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = dataclasses.replace(
                    self._config(base, root),
                    exclude_from_refresh=("gamma",),
                    exclude_from_sync=("beta",),
                )
                write_log(
                    Report(
                        mode="status",
                        started_at=datetime(2026, 11, 5, 16, 0, 0),
                        elapsed_s=1.0,
                        rows=(
                            Row("alpha", "main", Outcome.BEHIND, 3, ""),
                            Row("beta", "main", Outcome.BEHIND, 4, ""),
                            Row("gamma", "main", Outcome.BEHIND, 5, ""),
                        ),
                    ),
                    base / "logs",
                )
                window = MainWindow(config)
                window._set_filter("behind")

                self.assertEqual(
                    [view.label for view in window._visible_rows()],
                    ["alpha", "beta"],
                )
                self.assertEqual(window.nav_buttons["behind"].text(), "Behind  2")
                self.assertIn(
                    "1 repository can be updated · 1 held",
                    window.banner_label.text(),
                )
                self.assertFalse(window.banner_button.isHidden())
                self.assertEqual(
                    [ref.label for ref in window._behind_refs()], ["alpha"]
                )
                self.assertEqual(
                    window.row_widgets["alpha"].chip.text(), "Behind"
                )
                self.assertEqual(
                    window.row_widgets["beta"].chip.text(), "No sync"
                )
                self.assertEqual(
                    window.row_widgets["beta"].sub_label.text(),
                    'main · <span style="color:'
                    f'{STATUS_COLORS["warn"]}; font-weight:600;">'
                    "4 commits behind</span>",
                )

                window._set_filter("all")
                self.assertEqual(
                    window.row_widgets["gamma"].chip.text(), "No checks"
                )
                window.close()

        def test_banner_with_only_held_rows_hides_the_action(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = dataclasses.replace(
                    self._config(base, root),
                    exclude_from_sync=("beta",),
                )
                write_log(
                    Report(
                        mode="status",
                        started_at=datetime(2026, 11, 5, 16, 0, 0),
                        elapsed_s=1.0,
                        rows=(
                            Row("alpha", "main", Outcome.UP_TO_DATE, 0, ""),
                            Row("beta", "main", Outcome.BEHIND, 4, ""),
                        ),
                    ),
                    base / "logs",
                )
                window = MainWindow(config)

                self.assertIn(
                    "1 repository is held from Sync all",
                    window.banner_label.text(),
                )
                self.assertTrue(window.banner_button.isHidden())
                self.assertEqual(window._behind_refs(), [])
                self.assertEqual(window.nav_buttons["behind"].text(), "Behind  1")
                window.close()

        def test_detail_hold_switches_persist(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                path = base / "config.toml"
                config = dataclasses.replace(
                    self._config(base, root),
                    config_path=path,
                    root_source="test",
                )
                save_config(config, path)
                window = MainWindow(config)
                window.current_label = "alpha"

                window._populate_detail_holds("alpha")
                window.detail_exclude_refresh.setChecked(True)
                self.assertIn(
                    "alpha", load_config(config_path=path).exclude_from_refresh
                )

                window.detail_exclude_sync.setChecked(True)
                loaded = load_config(config_path=path)
                self.assertIn("alpha", loaded.exclude_from_refresh)
                self.assertIn("alpha", loaded.exclude_from_sync)

                window.detail_exclude_refresh.setChecked(False)
                self.assertNotIn(
                    "alpha", load_config(config_path=path).exclude_from_refresh
                )
                window.close()

        def test_settings_is_grouped_into_sections(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                self.assertEqual(
                    tuple(button.text() for button in window.settings_nav_buttons),
                    SETTINGS_SECTIONS,
                )
                self.assertEqual(
                    window.settings_stack.count(), len(SETTINGS_SECTIONS)
                )
                self.assertEqual(window.settings_stack.currentIndex(), 0)
                self.assertTrue(window.settings_nav_buttons[0].isChecked())
                self.assertFalse(window.save_button.isEnabled())
                self.assertEqual(window.save_button.text(), "Saved")
                self.assertEqual(
                    window.save_button.property("saveState"), "clean"
                )
                window.close()

        def test_lfs_status_refreshes_when_settings_is_active(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                missing = LfsStatus(
                    installed=False,
                    enabled=False,
                    version="",
                    install_hint="install git-lfs",
                )
                ready = LfsStatus(
                    installed=True,
                    enabled=True,
                    version="git-lfs/3.7.0 (GitHub; linux amd64)",
                    install_hint="install git-lfs",
                )
                with patch(
                    "repopull.gui.window.lfs_status", return_value=missing
                ):
                    window = MainWindow(self._config(base, self._tree(base)))
                    window._show_settings()
                self.assertEqual(
                    window.settings_lfs_status.text(), "not installed"
                )

                window._lfs_last_check = 0.0
                with patch(
                    "repopull.gui.window.lfs_status", return_value=ready
                ) as check:
                    window._maybe_refresh_lfs_status()

                check.assert_called_once()
                self.assertEqual(
                    window.settings_lfs_status.text(),
                    "installed · git-lfs/3.7.0 · enabled",
                )
                window.close()

        def test_lfs_check_again_button_refreshes_status(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                missing = LfsStatus(
                    installed=False,
                    enabled=False,
                    version="",
                    install_hint="install git-lfs",
                )
                ready = LfsStatus(
                    installed=True,
                    enabled=False,
                    version="git-lfs/3.7.0 (GitHub; linux amd64)",
                    install_hint="install git-lfs",
                )
                with patch(
                    "repopull.gui.window.lfs_status", return_value=missing
                ):
                    window = MainWindow(self._config(base, self._tree(base)))
                    window._show_settings()
                self.assertEqual(
                    window.settings_lfs_status.text(), "not installed"
                )

                with patch(
                    "repopull.gui.window.lfs_status", return_value=ready
                ) as check:
                    window.settings_lfs_check.click()

                check.assert_called_once()
                self.assertEqual(
                    window.settings_lfs_status.text(),
                    "installed · git-lfs/3.7.0 · not enabled",
                )
                window.close()

        def test_lfs_status_is_not_rechecked_after_ready(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                ready = LfsStatus(
                    installed=True,
                    enabled=True,
                    version="git-lfs/3.7.0 (GitHub; linux amd64)",
                    install_hint="install git-lfs",
                )
                with patch(
                    "repopull.gui.window.lfs_status", return_value=ready
                ) as check:
                    window = MainWindow(self._config(base, self._tree(base)))
                    window._show_settings()
                    window._populate_settings()
                    window._refresh_lfs_status()
                    window._maybe_refresh_lfs_status()

                check.assert_called_once()
                self.assertEqual(
                    window.settings_lfs_status.text(),
                    "installed · git-lfs/3.7.0 · enabled",
                )
                window.close()

        def test_settings_sections_keep_drafts_until_saved(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config_path = base / "config.toml"
                config = Config(
                    root=self._tree(base),
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                    root_source="test",
                )
                save_config(config, config_path)
                window = MainWindow(config)

                window._show_settings()
                window.settings_max_depth.setValue(3)
                self.assertEqual(
                    window.save_button.text(), "Save unsaved settings"
                )
                self.assertTrue(window.save_button.isEnabled())
                self.assertEqual(
                    window.save_button.property("saveState"), "dirty"
                )

                window._select_settings_section(2)
                window._select_settings_section(0)
                window._set_filter("all")
                window._show_settings()
                self.assertEqual(window.settings_max_depth.value(), 3)

                window._save_settings()
                self.assertEqual(window.save_button.text(), "Saved")
                self.assertFalse(window.save_button.isEnabled())
                self.assertEqual(
                    load_config(config_path=config_path).max_depth, 3
                )
                window.close()

        def test_watched_folder_link_selects_watching_section(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window._show_settings()
                window._select_settings_section(3)

                window._open_watched_settings()

                self.assertEqual(window.settings_stack.currentIndex(), 0)
                self.assertTrue(window.settings_nav_buttons[0].isChecked())
                window.close()

        def test_refresh_changes_do_not_use_the_save_button(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                self.assertIsInstance(window.settings_background, Switch)
                self.assertIsInstance(window.settings_auto, Switch)
                self.assertIsInstance(window.settings_hidden_pause, Switch)
                self.assertEqual(
                    window.settings_interval_hint.text(),
                    "Applies and saves immediately.",
                )
                window.settings_auto.setChecked(True)

                self.assertEqual(window.save_button.text(), "Saved")
                self.assertFalse(window.save_button.isEnabled())
                window.close()

        def test_switch_toggles_with_mouse_and_space(self) -> None:
            switch = Switch()
            switch.setAccessibleName("Test switch")
            switch.show()
            self.app.processEvents()

            self.assertFalse(switch.isChecked())
            QTest.mouseClick(
                switch,
                Qt.MouseButton.LeftButton,
                pos=switch.rect().center(),
            )
            self.assertTrue(switch.isChecked())
            QTest.keyClick(switch, Qt.Key.Key_Space)
            self.assertFalse(switch.isChecked())
            self.assertEqual(switch.accessibleName(), "Test switch")
            self.assertEqual((switch.width(), switch.height()), (48, 28))
            switch.close()

        def test_sidebar_brand_mark_is_loaded(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                self.assertFalse(window.brand_mark.pixmap().isNull())
                window.close()

        def test_builds_with_unchecked_rows(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                self.assertEqual(window.visible_row_count(), 3)
                window.close()

        def test_library_scroll_survives_rebuild_and_back(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._many(base)))
                window.resize(1040, 720)
                window.show()
                self.app.processEvents()
                bar = window.list.verticalScrollBar()
                self.assertGreater(bar.maximum(), 500)

                bar.setValue(500)
                window._render_library()
                self.assertEqual(bar.value(), 500)

                window._open_detail("repo-20")
                window._render_library()
                window._back_to_library()
                self.app.processEvents()
                self.assertEqual(bar.value(), 500)

                window.refs = window.refs[:3]
                window._render_library()
                self.assertLessEqual(bar.value(), bar.maximum())
                window.close()

        def test_filter_and_search_reset_library_scroll(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._many(base)))
                window.resize(1040, 720)
                window.show()
                self.app.processEvents()
                bar = window.list.verticalScrollBar()

                bar.setValue(500)
                window._set_filter("behind")
                self.assertEqual(bar.value(), 0)

                window._set_filter("all")
                bar.setValue(500)
                window._on_search("repo-2")
                self.assertEqual(bar.value(), 0)
                window.close()

        def test_report_is_loaded_and_filtered(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                report = Report(
                    mode="status",
                    started_at=datetime(2026, 11, 5, 16, 0, 0),
                    elapsed_s=1.0,
                    rows=(
                        Row("alpha", "main", Outcome.BEHIND, 3, ""),
                        Row(
                            "beta",
                            "main",
                            Outcome.SKIPPED,
                            0,
                            "dirty working tree",
                        ),
                        Row("gamma", "main", Outcome.ERROR, 0, "empty"),
                    ),
                )
                write_log(report, base / "logs")

                window = MainWindow(self._config(base, root))
                self.assertEqual(window.visible_row_count(), 3)

                for key in ("behind", "skipped", "errors"):
                    window._set_filter(key)
                    self.assertEqual(window.visible_row_count(), 1, key)

                window._set_filter("all")
                window._on_search("alp")
                self.assertEqual(window.visible_row_count(), 1)
                window.close()

        def test_chip_text_and_kind(self) -> None:
            view = row_view(Row("x", "main", Outcome.BEHIND, 12, ""))
            self.assertEqual(view.status, "Behind")
            self.assertEqual(view.kind, "warn")
            self.assertEqual(view.count_text, "12 commits behind")
            self.assertEqual(view.count_color, STATUS_COLORS["warn"])

            updated = row_view(Row("x", "main", Outcome.UPDATED, 1, ""))
            self.assertEqual(updated.status, "Up to date")
            self.assertEqual(updated.kind, "ok")
            self.assertEqual(
                updated.count_text, "1 commit pulled at last sync"
            )
            self.assertEqual(unchecked_view("x").kind, "neutral")
            self.assertEqual(unchecked_view("x").status, "Not checked")

        def test_chip_formats_large_counts(self) -> None:
            behind = row_view(Row("x", "main", Outcome.BEHIND, 1_234, ""))
            updated = row_view(Row("x", "main", Outcome.UPDATED, 12_345, ""))

            self.assertEqual(behind.status, "Behind")
            self.assertEqual(behind.count_text, "1,234 commits behind")
            self.assertEqual(updated.status, "Up to date")
            self.assertEqual(
                updated.count_text, "12,345 commits pulled at last sync"
            )

        def test_hold_labels_suppress_stale_counts(self) -> None:
            behind = Row("x", "main", Outcome.BEHIND, 12, "")

            no_checks = row_view(behind, no_checks=True)
            self.assertEqual(no_checks.status, "No checks")
            self.assertEqual(no_checks.kind, "neutral")
            self.assertEqual(no_checks.count_text, "")
            self.assertEqual(no_checks.detail, "")
            self.assertIn("Sync all can still update", no_checks.hint)

            no_sync = row_view(behind, no_sync=True)
            self.assertEqual(no_sync.status, "No sync")
            self.assertEqual(no_sync.count_text, "12 commits behind")
            self.assertEqual(no_sync.count_color, STATUS_COLORS["warn"])
            self.assertIn("Refresh status still runs", no_sync.hint)

            both = row_view(behind, no_checks=True, no_sync=True)
            self.assertEqual(both.status, "No checks/sync")
            self.assertEqual(both.count_text, "")
            self.assertIn("both bulk actions", both.hint)

            self.assertEqual(
                unchecked_view("x", no_checks=True).status, "No checks"
            )
            self.assertEqual(
                unchecked_view("x", no_sync=True).status, "No sync"
            )
            self.assertEqual(
                unchecked_view("x", no_checks=True, no_sync=True).status,
                "No checks/sync",
            )

        def test_force_sync_uses_detail_not_a_pulled_count(self) -> None:
            view = row_view(
                Row(
                    "x",
                    "main",
                    Outcome.UPDATED,
                    12,
                    "hard reset to upstream",
                )
            )

            self.assertEqual(view.status, "Up to date")
            self.assertEqual(view.detail, "")
            self.assertEqual(
                view.count_text, "hard reset to upstream at last sync"
            )

        def test_row_update_applies_in_place(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                window._on_row(
                    Row("alpha", "main", Outcome.UPDATED, 3, "")
                )

                self.assertIs(
                    window.rows_by_label["alpha"].outcome, Outcome.UPDATED
                )
                widget = window.row_widgets["alpha"]
                self.assertEqual(widget.chip.text(), "Up to date")
                self.assertIn(
                    "3 commits pulled at last sync", widget.sub_label.text()
                )
                widths = {
                    item.chip.minimumWidth()
                    for item in window.row_widgets.values()
                }
                self.assertEqual(widths, {132})
                window.close()

        def test_single_repo_sync_keeps_other_status_rows(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                write_log(
                    Report(
                        mode="status",
                        started_at=datetime(2026, 11, 5, 16, 0, 0),
                        elapsed_s=1.0,
                        rows=(
                            Row("alpha", "main", Outcome.BEHIND, 3, ""),
                            Row("beta", "main", Outcome.UP_TO_DATE, 0, ""),
                            Row("gamma", "main", Outcome.ERROR, 0, "empty"),
                        ),
                    ),
                    base / "logs",
                )
                window = MainWindow(self._config(base, root))

                window._on_finished(
                    Report(
                        mode="sync",
                        started_at=datetime(2026, 11, 5, 16, 5, 0),
                        elapsed_s=1.0,
                        rows=(
                            Row("alpha", "main", Outcome.UPDATED, 3, ""),
                        ),
                    )
                )

                self.assertIs(
                    window.rows_by_label["alpha"].outcome, Outcome.UPDATED
                )
                self.assertIs(
                    window.rows_by_label["beta"].outcome, Outcome.UP_TO_DATE
                )
                self.assertIs(
                    window.rows_by_label["gamma"].outcome, Outcome.ERROR
                )
                window.close()

        def test_settings_save_changes_root(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                old_root = self._tree(base)
                config_path = base / "config.toml"
                config = Config(
                    root=old_root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                    config_found=False,
                    root_source="test",
                )
                save_config(config, config_path)

                window = MainWindow(config)
                new_root = base / "new-repos"
                (new_root / "delta" / ".git").mkdir(parents=True)
                window.settings_root.setText(str(new_root))
                window.settings_max_depth.setValue(3)
                window.settings_ignore.setPlainText("skip-me\n*.old")
                window.settings_fetch_timeout.setValue(600)
                window.settings_command_timeout.setValue(90)
                window.settings_retention.setValue(7)
                window._save_settings()

                reloaded = load_config(config_path=config_path)
                self.assertEqual(window.config.root, new_root)
                self.assertEqual(window.visible_row_count(), 1)
                self.assertEqual(reloaded.max_depth, 3)
                self.assertEqual(reloaded.ignore, ("skip-me", "*.old"))
                self.assertEqual(reloaded.fetch_timeout_s, 600)
                self.assertEqual(reloaded.command_timeout_s, 90)
                self.assertEqual(reloaded.log_retention_days, 7)
                window.close()

        def test_auto_refresh_warning_and_save(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config_path = base / "config.toml"
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                    root_source="test",
                )
                save_config(config, config_path)
                window = MainWindow(config)

                window.settings_auto.setChecked(True)
                window.settings_auto_minutes.setValue(5)
                self.assertFalse(window.settings_auto_warning.isHidden())
                self.assertIn("15 minutes", window.settings_auto_warning.text())

                window.settings_auto_minutes.setValue(15)
                self.assertTrue(window.settings_auto_warning.isHidden())

                window.settings_auto_minutes.setValue(10)
                window._save_settings()

                reloaded = load_config(config_path=config_path)
                self.assertEqual(reloaded.auto_refresh_s, 600)
                self.assertFalse(reloaded.background_mode)
                self.assertTrue(window.auto_timer.isActive())
                window._set_auto_paused(True)
                self.assertFalse(window.auto_timer.isActive())
                window._set_auto_paused(False)
                self.assertTrue(window.auto_timer.isActive())
                window.close()

        def test_tray_menu_is_built(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))
                window._tray_available = True
                window._ensure_tray()

                self.assertIsNotNone(window.tray)
                self.assertIsNotNone(window.tray_menu)
                self.assertTrue(window.tray.icon().isMask())
                window.request_quit()

        def test_editing_interval_enables_auto_refresh(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))
                self.assertFalse(window.settings_auto.isChecked())

                window.settings_auto_minutes.setValue(10)

                self.assertTrue(window.settings_auto.isChecked())
                self.assertFalse(window.settings_auto_warning.isHidden())
                window.request_quit()

        def test_tray_is_visible_without_background_mode(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                window = MainWindow(self._config(base, root))
                window._tray_available = True
                window._apply_background_mode()

                self.assertIsNotNone(window.tray)
                self.assertFalse(window.config.background_mode)
                window.request_quit()

        def test_background_toggle_persists_immediately(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config_path = base / "config.toml"
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                )
                save_config(config, config_path)
                window = MainWindow(config)
                window._tray_available = True
                window.settings_background.setEnabled(True)

                window.settings_background.setChecked(True)

                reloaded = load_config(config_path=config_path)
                self.assertTrue(reloaded.background_mode)
                self.assertTrue(window.config.background_mode)
                window.request_quit()

        def test_hidden_pause_toggle_persists_immediately(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config_path = base / "config.toml"
                config = Config(
                    root=self._tree(base),
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                )
                save_config(config, config_path)
                window = MainWindow(config)

                self.assertFalse(window.settings_hidden_pause.isEnabled())
                window.settings_auto.setChecked(True)
                self.assertTrue(window.settings_hidden_pause.isEnabled())
                window.settings_hidden_pause.setChecked(True)

                reloaded = load_config(config_path=config_path)
                self.assertTrue(reloaded.auto_refresh_pause_when_hidden)
                self.assertTrue(window.config.auto_refresh_pause_when_hidden)
                window.request_quit()

        def test_hidden_pause_stops_and_restarts_scheduler(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                    auto_refresh_pause_when_hidden=True,
                )
                window = MainWindow(config)

                self.assertFalse(window.auto_timer.isActive())
                window.show()
                self.app.processEvents()
                self.assertTrue(window.auto_timer.isActive())

                window.hide()
                self.app.processEvents()
                self.assertFalse(window.auto_timer.isActive())

                window.show()
                self.app.processEvents()
                self.assertTrue(window.auto_timer.isActive())
                window.request_quit()

        def test_manual_fields_have_a_visible_text_inset(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                self.assertEqual(
                    window.settings_root.textMargins().left(), 12
                )
                self.assertEqual(
                    window.settings_max_depth.lineEdit()
                    .textMargins()
                    .left(),
                    4,
                )
                window.request_quit()

        def test_refresh_section_reports_the_next_check(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                )
                window = MainWindow(config)

                with patch.object(
                    window, "_jitter_seconds", return_value=0.0
                ):
                    window._last_network_finished = time.monotonic() - 600
                    window._schedule_auto_refresh()
                    self.assertIn(
                        "Next automatic status check",
                        window.settings_auto_next.text(),
                    )

                    window.settings_auto.setChecked(False)
                    self.assertIn(
                        "off", window.settings_auto_next.text()
                    )
                window.request_quit()

        def test_interval_change_keeps_the_remaining_countdown(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                )
                window = MainWindow(config)

                with patch.object(
                    window, "_jitter_seconds", return_value=0.0
                ):
                    window._last_network_finished = time.monotonic() - 600
                    window._schedule_auto_refresh()
                    self.assertAlmostEqual(
                        window.auto_timer.interval(), 300_000, delta=3_000
                    )

                    # Changing the interval recalculates from the last run
                    # instead of starting a fresh countdown.
                    window.settings_auto_minutes.setValue(30)
                    self.assertAlmostEqual(
                        window.auto_timer.interval(), 1_200_000, delta=3_000
                    )
                window.request_quit()

        def test_hidden_pause_catches_up_after_a_long_hide(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                    auto_refresh_pause_when_hidden=True,
                )
                window = MainWindow(config)
                window.show()
                self.app.processEvents()
                window.hide()
                self.app.processEvents()
                window._last_network_finished = time.monotonic() - 1_000

                with patch.object(window, "_start_run") as start:
                    window.show()
                    self.app.processEvents()

                start.assert_called_once()
                window.request_quit()

        def test_hidden_pause_blocks_a_due_automatic_run(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = dataclasses.replace(
                    self._config(base, self._tree(base)),
                    auto_refresh_s=900,
                    auto_refresh_pause_when_hidden=True,
                )
                window = MainWindow(config)
                window.show()
                self.app.processEvents()
                window.hide()
                self.app.processEvents()

                with patch.object(window, "_start_run") as start:
                    window._auto_refresh_due()

                start.assert_not_called()
                window.request_quit()

        def test_failed_immediate_save_shows_retry(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config_path = base / "config.toml"
                config = Config(
                    root=self._tree(base),
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=config_path,
                )
                save_config(config, config_path)
                window = MainWindow(config)
                window._tray_available = True
                window.settings_background.setEnabled(True)

                with patch(
                    "repopull.gui.window.save_behavior_settings",
                    side_effect=OSError("read-only"),
                ):
                    window.settings_background.setChecked(True)

                self.assertEqual(
                    window.save_button.text(), "Couldn't save — Retry"
                )
                self.assertTrue(window.save_button.isEnabled())
                self.assertEqual(
                    window.save_button.property("saveState"), "error"
                )
                self.assertFalse(window._settings_dirty)

                with patch(
                    "repopull.gui.window.save_behavior_settings"
                ):
                    window.settings_background.setChecked(False)
                self.assertEqual(window.save_button.text(), "Saved")
                self.assertFalse(window.save_button.isEnabled())
                window.request_quit()

        def test_network_retry_bypasses_normal_cooldown(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=900
                )
                window._network_offline = True
                window._last_network_finished = time.monotonic()

                with patch.object(window, "_start_run") as start:
                    window._auto_refresh_due()

                start.assert_called_once()
                window.request_quit()

        def test_remembers_settings_page(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=base / "config.toml",
                )
                window = MainWindow(config)
                window._show_settings()
                window.request_quit()

                restored = MainWindow(config)
                self.assertIs(
                    restored.stack.currentWidget(), restored.settings_page
                )
                restored.request_quit()

        def test_remembers_filter(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=base / "config.toml",
                )
                window = MainWindow(config)
                window._set_filter("behind")
                window.request_quit()

                restored = MainWindow(config)
                self.assertEqual(restored.filter, "behind")
                self.assertTrue(restored.nav_buttons["behind"].isChecked())
                restored.request_quit()

        def test_remembers_detail_selection(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    config_path=base / "config.toml",
                )
                window = MainWindow(config)
                window._open_detail("alpha")
                window.request_quit()

                restored = MainWindow(config)
                self.assertIs(
                    restored.stack.currentWidget(), restored.detail_page
                )
                self.assertEqual(restored.current_label, "alpha")
                restored.request_quit()

        def test_settings_folder_check_is_backgrounded(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                window._check_root()
                self.assertEqual(window.check_result.text(), "Checking…")

                QThreadPool.globalInstance().waitForDone(2_000)
                self.app.processEvents()

                self.assertIn("Found 3 repositories", window.check_result.text())
                window.request_quit()

        def test_background_discovery_fills_the_library(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(
                    self._config(base, self._tree(base)),
                    discover_async=True,
                )
                self.assertEqual(window.visible_row_count(), 0)

                QThreadPool.globalInstance().waitForDone(2_000)
                self.app.processEvents()

                self.assertEqual(window.visible_row_count(), 3)
                window.request_quit()

        def test_discovery_task_checks_the_root_state(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                task = DiscoveryTask(
                    root,
                    2,
                    (),
                    log_dir=base / "logs",
                )
                seen: list[tuple[list[object], object]] = []
                task.signals.checked.connect(
                    lambda refs, check: seen.append((refs, check))
                )

                task.run()

                self.assertEqual(len(seen), 1)
                refs, check = seen[0]
                self.assertEqual(len(refs), 3)
                self.assertIsInstance(check, RootStateCheck)
                self.assertIsNone(check.problem)  # type: ignore[union-attr]
                self.assertEqual(check.repo_count, 3)  # type: ignore[union-attr]

        def test_network_failure_schedules_short_retry(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=900
                )
                window._auto_run = True

                with patch.object(window, "_jitter_seconds", return_value=0.0):
                    window._on_finished(
                        Report(
                            mode="status",
                            started_at=datetime(2026, 11, 6, 12, 0, 0),
                            elapsed_s=1.0,
                            rows=(
                                Row(
                                    "alpha",
                                    "main",
                                    Outcome.ERROR,
                                    0,
                                    "fetch failed: Could not resolve host",
                                ),
                            ),
                            network_error=True,
                        )
                    )

                self.assertTrue(window._network_offline)
                self.assertAlmostEqual(
                    window.auto_timer.interval(), 120_000, delta=1_000
                )
                window.request_quit()

        def test_resume_defers_auto_refresh_by_grace(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=900
                )
                window.auto_timer.start(900_000)

                window._on_resume(3_600.0)

                self.assertTrue(window._resume_pending)
                self.assertTrue(window._resume_timer.isActive())
                self.assertEqual(window._resume_timer.interval(), 60_000)
                self.assertFalse(window.auto_timer.isActive())
                window.request_quit()

        def test_check_suspend_triggers_grace(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=900
                )
                window._suspend_detector = SuspendDetector(0.0)

                with (
                    patch(
                        "repopull.gui.window._boottime", return_value=700.0
                    ),
                    patch(
                        "repopull.gui.window.time.monotonic",
                        return_value=100.0,
                    ),
                ):
                    window._check_suspend()

                self.assertTrue(window._resume_pending)
                self.assertTrue(window._resume_timer.isActive())
                window.request_quit()

        def test_resume_check_starts_one_status_run(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window.config = dataclasses.replace(
                    window.config, auto_refresh_s=900
                )
                window._resume_pending = True

                with patch.object(window, "_start_run") as start:
                    window._resume_check_due()

                self.assertFalse(window._resume_pending)
                start.assert_called_once()
                refs = start.call_args.args[0]
                self.assertEqual(len(refs), 3)
                self.assertEqual(
                    start.call_args.kwargs,
                    {"force": False, "mode": "status", "auto": True},
                )
                window.request_quit()

        @contextlib.contextmanager
        def _autostart(
            self, entry: Path, program: str = "/opt/repopull/repopull-gui"
        ) -> object:
            target = autostart.Target((program,), "test")
            with (
                patch(
                    "repopull.autostart.entry_path", return_value=entry
                ),
                patch(
                    "repopull.autostart.resolve_target", return_value=target
                ),
            ):
                yield entry

        def test_startup_section_starts_switched_off(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with self._autostart(entry):
                    window = MainWindow(self._config(base, self._tree(base)))

                    self.assertTrue(window.settings_login.isEnabled())
                    self.assertFalse(window.settings_login.isChecked())
                    self.assertFalse(
                        window.settings_login_hidden.isEnabled()
                    )
                    self.assertIn("Not in", window.settings_login_note.text())
                    window.close()

        def test_launch_at_login_writes_and_removes_the_entry(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with self._autostart(entry) as path:
                    window = MainWindow(self._config(base, self._tree(base)))

                    window.settings_login.setChecked(True)

                    self.assertTrue(path.is_file())
                    state = autostart.read(path)
                    self.assertTrue(state.installed)
                    self.assertFalse(state.hidden)
                    self.assertEqual(state.argv, ("/opt/repopull/repopull-gui",))
                    self.assertTrue(
                        window.settings_login_hidden.isEnabled()
                    )

                    window.settings_login.setChecked(False)

                    self.assertFalse(path.exists())
                    window.close()

        def test_hidden_switch_rewrites_the_entry(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with self._autostart(entry) as path:
                    window = MainWindow(self._config(base, self._tree(base)))
                    window.settings_login.setChecked(True)

                    window.settings_login_hidden.setChecked(True)

                    self.assertTrue(autostart.read(path).hidden)
                    self.assertIn(
                        "opens hidden", window.settings_login_note.text()
                    )
                    window.close()

        def test_startup_switches_paint_what_the_entry_says(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with self._autostart(entry):
                    autostart.install(
                        entry,
                        autostart.Target(("/opt/app",), "test"),
                        hidden=True,
                    )

                    window = MainWindow(self._config(base, self._tree(base)))

                    self.assertTrue(window.settings_login.isChecked())
                    # The knob is animated from `toggled`, so a blocked signal
                    # would leave it painted as off.
                    self.assertEqual(window.settings_login._position, 1.0)
                    self.assertEqual(
                        window.settings_login_hidden._position, 1.0
                    )
                    window.close()

        def _release(self, tag: str = "v0.8.0") -> Release:
            version = Version(
                *[int(part) for part in tag.lstrip("v").split(".")]
            )
            return Release(
                version=version,
                tag=tag,
                page=f"https://example.invalid/tag/{tag}",
                notes="",
                published="2026-11-20T12:00:00Z",
                asset=None,
                download=None,
            )

        def test_update_check_reports_a_newer_release(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                window._on_update_finished(self._release("v0.8.0"))

                self.assertIn(
                    "0.8.0 is available", window.settings_update_note.text()
                )
                self.assertFalse(window.settings_update_open.isHidden())
                window.close()

        def test_update_check_reports_the_running_version_as_current(
            self,
        ) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                window._on_update_finished(self._release(f"v{__version__}"))

                self.assertIn(
                    "is the latest release",
                    window.settings_update_note.text(),
                )
                self.assertTrue(window.settings_update_open.isHidden())
                window.close()

        def test_update_check_failure_is_reported_and_recoverable(
            self,
        ) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))

                window._on_update_failed("could not reach GitHub: offline")

                self.assertIn(
                    "Could not check", window.settings_update_note.text()
                )
                self.assertTrue(window.settings_update.isEnabled())
                self.assertTrue(window.settings_update_open.isHidden())
                window.close()

        def test_update_check_runs_in_the_background(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                asked: list[int] = []

                def fake() -> Release:
                    asked.append(1)
                    return self._release("v9.9.9")

                with patch(
                    "repopull.gui.window.latest_release", side_effect=fake
                ):
                    window._check_for_updates()
                    for _ in range(200):
                        self.app.processEvents()
                        if "9.9.9" in window.settings_update_note.text():
                            break
                        QTest.qWait(10)

                self.assertTrue(asked)
                self.assertIn(
                    "9.9.9 is available",
                    window.settings_update_note.text(),
                )
                self.assertTrue(window.settings_update.isEnabled())
                window.close()

        def test_tray_menu_offers_an_update_check(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                window._tray_available = True
                window._ensure_tray()

                labels = [
                    action.text() for action in window.tray_menu.actions()
                ]

                self.assertIn("Check for updates…", labels)
                window.request_quit()

        def test_a_moved_executable_is_not_offered(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with patch(
                    "repopull.autostart.entry_path", return_value=entry
                ), patch(
                    "repopull.autostart.resolve_target", return_value=None
                ):
                    window = MainWindow(self._config(base, self._tree(base)))

                    self.assertFalse(window.settings_login.isEnabled())
                    self.assertFalse(
                        window.settings_login_hidden.isEnabled()
                    )
                    self.assertIn(
                        "stable command",
                        window.settings_login_note.text(),
                    )
                    window.close()

        def test_failed_entry_write_reverts_the_switch(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                with self._autostart(entry):
                    window = MainWindow(self._config(base, self._tree(base)))
                    with patch(
                        "repopull.autostart.install",
                        side_effect=OSError("read-only home"),
                    ):
                        window.settings_login.setChecked(True)

                    self.assertFalse(window.settings_login.isChecked())
                    self.assertIn(
                        "Could not update", window.status_message.text()
                    )
                    window.close()

        def test_hidden_start_needs_a_tray(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(
                    self._config(base, self._tree(base)), hidden=True
                )

                self.assertFalse(window.starts_hidden)

                window._tray_available = True
                self.assertTrue(window.starts_hidden)
                window.close()

        def test_a_second_launch_raises_the_window(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                config = self._config(base, self._tree(base))
                window = MainWindow(config, hidden=True)
                window._tray_available = True
                window.start_instance_channel()
                self.assertFalse(window.isVisible())

                self.assertTrue(ask_to_show(config.log_dir))
                for _ in range(100):
                    self.app.processEvents()
                    if window.isVisible():
                        break
                    QTest.qWait(10)

                self.assertTrue(window.isVisible())
                window.request_quit()

        def test_startup_repairs_an_entry_left_at_an_old_path(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                entry = base / "autostart" / "repopull.desktop"
                autostart.install(
                    entry, autostart.Target(("/old/app",), "test"), hidden=True
                )

                with self._autostart(entry, "/new/app"):
                    _repair_autostart()

                self.assertEqual(
                    autostart.read(entry).argv,
                    ("/new/app", autostart.HIDDEN_FLAG),
                )

        def test_close_to_tray_hides_instead_of_quitting(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._tree(base)
                config = Config(
                    root=root,
                    log_dir=base / "logs",
                    delay_between_repos_s=0,
                    update_submodules=False,
                    background_mode=True,
                )
                window = MainWindow(config)
                window._tray_available = True
                window._ensure_tray()
                window.show()

                window.close()

                self.assertFalse(window.isVisible())
                self.assertFalse(window._quit_requested)
                window.request_quit()

        def test_close_while_running_cancels_and_window_is_collectable(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                logs = base / "logs"
                logs.mkdir()
                window = MainWindow(self._config(base, self._tree(base)))
                window.show()
                self.app.processEvents()
                started = Event()

                def operation(
                    cancel: Event, _progress: object, _row: object
                ) -> Report:
                    started.set()
                    while not cancel.is_set():
                        time.sleep(0.01)
                    return Report(
                        mode="status",
                        started_at=datetime.now(),
                        elapsed_s=0.0,
                        rows=(),
                    )

                task = RunTask(operation, logs)
                task.signals.finished.connect(window._on_finished)
                task.signals.cancelled.connect(window._on_cancelled)
                task.signals.failed.connect(window._on_failed)
                window.task = task
                QThreadPool.globalInstance().start(task)
                self.assertTrue(started.wait(2.0))

                with patch.object(MainWindow, "_quit_application", lambda self: None):
                    window.close()
                    self.assertTrue(window._quit_requested)
                    self.assertTrue(task.cancel.is_set())
                    deadline = time.monotonic() + 5
                    while window.task is not None and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.01)

                self.assertIsNone(window.task)
                QThreadPool.globalInstance().waitForDone(2000)
                task_reference = weakref.ref(task)

                reference = weakref.ref(window)
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                del window
                gc.collect()
                self.app.processEvents()
                self.assertIsNone(reference())

                del task
                gc.collect()
                self.assertIsNone(task_reference())

        def test_task_signals_do_not_retain_a_deleted_window(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window = MainWindow(self._config(base, self._tree(base)))
                task = RunTask(
                    lambda _cancel, _progress, _row: Report(
                        mode="status",
                        started_at=datetime.now(),
                        elapsed_s=0.0,
                        rows=(),
                    ),
                    base / "logs",
                )
                task.signals.finished.connect(window._on_finished)
                task.signals.cancelled.connect(window._on_cancelled)
                task.signals.failed.connect(window._on_failed)
                reference = weakref.ref(window)

                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                del window
                gc.collect()
                self.app.processEvents()

                self.assertIsNone(reference())
                self.assertIsNotNone(task)



if __name__ == "__main__":
    unittest.main()
