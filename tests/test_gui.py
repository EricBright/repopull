"""Offscreen tests for the optional GUI; skipped when PySide6 is absent."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover - exercised only without the dependency
    HAVE_PYSIDE = False
else:
    HAVE_PYSIDE = True

if HAVE_PYSIDE:
    from PySide6.QtWidgets import QApplication

    from repopull.config import Config, load_config, save_config
    from repopull.gui.rows import row_view, unchecked_view
    from repopull.gui.window import MainWindow
    from repopull.models import Outcome, Report, Row
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
            self.assertIn("12", view.status)
            self.assertEqual(view.kind, "warn")

            updated = row_view(Row("x", "main", Outcome.UPDATED, 1, ""))
            self.assertEqual(updated.status, "✓ Updated")
            self.assertEqual(updated.kind, "ok")
            self.assertEqual(unchecked_view("x").kind, "neutral")

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
                self.assertIn("Updated", window.row_widgets["alpha"].chip.text())
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


if __name__ == "__main__":
    unittest.main()
