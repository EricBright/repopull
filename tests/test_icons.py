"""Tests for the icon family and window icon wiring."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from repopull.gui.app import build_app_icon

ASSETS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "repopull"
    / "gui"
    / "assets"
)


class IconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["icon-test"])

    def test_all_sizes_exist(self) -> None:
        for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
            path = ASSETS / f"repopull-{size}.png"
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 0)

    def test_sidebar_mark_exists(self) -> None:
        path = ASSETS / "repopull-mark.png"
        self.assertTrue(path.is_file(), path)
        self.assertGreater(path.stat().st_size, 0)

    def test_symbolic_sizes_exist(self) -> None:
        for size in (16, 22, 24, 32):
            path = ASSETS / f"repopull-symbolic-{size}.png"
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 0)

    def test_window_icon_has_all_sizes(self) -> None:
        icon = build_app_icon()

        self.assertFalse(icon.isNull())
        sizes = {size.width() for size in icon.availableSizes()}
        self.assertEqual(sizes, {16, 22, 24, 32, 48, 64, 128, 256, 512})
