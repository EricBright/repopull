"""Offscreen tests for the Clone dialog and its window wiring."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover - exercised only without the dependency
    HAVE_PYSIDE = False
else:
    HAVE_PYSIDE = True

if HAVE_PYSIDE:
    from PySide6.QtWidgets import QApplication, QMessageBox

    import support

    from repopull.clone import CloneResult
    from repopull.config import Config
    from repopull.gui.clone_dialog import CloneDialog
    from repopull.gui.jobs import CloneTask
    from repopull.gui.window import MainWindow
    from repopull.models import RepoRef


if HAVE_PYSIDE:

    class CloneGuiTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls) -> None:
            cls.app = QApplication.instance() or QApplication(
                ["repopull-clone-test"]
            )

        def _config(self, base: Path, root: Path) -> Config:
            return Config(
                root=root,
                log_dir=base / "logs",
                delay_between_repos_s=0,
                update_submodules=False,
            )

        def _window(self, base: Path) -> tuple[MainWindow, Path]:
            root = base / "repos"
            (root / "alpha" / ".git").mkdir(parents=True)
            return MainWindow(self._config(base, root)), root

        def test_dialog_derives_the_folder_and_enables_clone(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repos"
                root.mkdir()
                dialog = CloneDialog(root)

                dialog.url_edit.setText(
                    "https://github.com/owner/repo.git"
                )

                self.assertEqual(dialog.name_edit.text(), "repo")
                self.assertTrue(dialog.clone_button.isEnabled())
                self.assertEqual(
                    dialog.values(),
                    ("https://github.com/owner/repo.git", "repo"),
                )
                self.assertIn(str(root / "repo"), dialog.preview.text())
                dialog.deleteLater()

        def test_dialog_rejects_a_path_name_and_an_existing_folder(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repos"
                root.mkdir()
                dialog = CloneDialog(root)
                dialog.url_edit.setText(
                    "https://github.com/owner/repo.git"
                )

                dialog.name_edit.setText("bad/escape")

                self.assertFalse(dialog.clone_button.isEnabled())
                self.assertIn("path separator", dialog.error.text())

                (root / "repo").mkdir()
                dialog.name_edit.setText("repo")

                self.assertFalse(dialog.clone_button.isEnabled())
                self.assertIn("already exists", dialog.error.text())
                dialog.deleteLater()

        def test_clone_task_reports_success(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                remote, _seed, _watched = support.make_pair(base)
                root = base / "clone-root"
                root.mkdir()
                task = CloneTask(
                    str(remote),
                    "cloned",
                    root,
                    timeout=60,
                    log_dir=base / "logs",
                )
                finished: list[object] = []
                failed: list[str] = []
                cancelled: list[bool] = []
                task.signals.finished.connect(finished.append)
                task.signals.failed.connect(failed.append)
                task.signals.cancelled.connect(lambda: cancelled.append(True))

                task.run()

                self.assertEqual(failed, [])
                self.assertEqual(cancelled, [])
                self.assertEqual(len(finished), 1)
                self.assertIsInstance(finished[0], CloneResult)
                self.assertTrue((root / "cloned" / "file.txt").is_file())

        def test_clone_task_cancels_without_a_destination(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                remote, _seed, _watched = support.make_pair(base)
                root = base / "clone-root"
                root.mkdir()
                task = CloneTask(
                    str(remote),
                    "cloned",
                    root,
                    timeout=60,
                    log_dir=base / "logs",
                )
                cancelled: list[bool] = []
                task.signals.cancelled.connect(lambda: cancelled.append(True))
                task.cancel.set()

                task.run()

                self.assertEqual(cancelled, [True])
                self.assertEqual(list(root.iterdir()), [])

        def test_clone_button_follows_busy_state(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window, _root = self._window(base)

                window._set_busy(True)
                self.assertFalse(window.clone_button.isEnabled())

                window._set_busy(False)
                self.assertTrue(window.clone_button.isEnabled())
                window.deleteLater()

        def test_finished_clone_rescans_and_clears_busy(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window, root = self._window(base)
                window.clone_task = SimpleNamespace()
                window._set_busy(True)
                callbacks: list[object] = []

                with patch.object(
                    window,
                    "_start_discovery",
                    side_effect=lambda callback=None: callbacks.append(callback),
                ):
                    window._on_clone_finished(
                        CloneResult(
                            destination=root / "new",
                            url="https://example.invalid/new.git",
                        )
                    )

                self.assertIsNone(window.clone_task)
                self.assertTrue(window.clone_button.isEnabled())
                self.assertIn("Cloned new", window.status_message.text())
                self.assertEqual(len(callbacks), 1)
                window.deleteLater()

        def test_open_cloned_opens_the_matching_detail_page(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window, root = self._window(base)
                window.refs = [RepoRef(path=root / "alpha", label="alpha")]

                with patch.object(window, "_open_detail") as open_detail:
                    window._open_cloned(root / "alpha")

                open_detail.assert_called_once_with("alpha")
                window.deleteLater()

        def test_failed_clone_warns_and_clears_busy(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window, _root = self._window(base)
                window.clone_task = SimpleNamespace()
                window._set_busy(True)

                with patch.object(QMessageBox, "warning") as warning:
                    window._on_clone_failed("boom")

                self.assertIsNone(window.clone_task)
                self.assertTrue(window.clone_button.isEnabled())
                self.assertEqual(window.status_message.text(), "Clone failed")
                warning.assert_called_once()
                window.deleteLater()

        def test_close_while_cloning_cancels_the_clone(self) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                window, _root = self._window(base)
                fake = SimpleNamespace(cancel=Event())
                window.clone_task = fake

                with patch.object(
                    MainWindow, "_quit_application", lambda self: None
                ):
                    window.close()

                self.assertTrue(fake.cancel.is_set())
                self.assertTrue(window._quit_requested)
                window.clone_task = None
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
