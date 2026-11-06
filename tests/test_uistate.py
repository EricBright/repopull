"""Tests for remembered GUI page/filter state."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repopull.uistate import UI_STATE_FILE, UiState, load_ui_state, save_ui_state


class UiStateTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            state = UiState(page="detail", filter="behind", repo="alpha")

            save_ui_state(config, state)

            self.assertEqual(load_ui_state(config), state)
            self.assertTrue((Path(tmp) / UI_STATE_FILE).is_file())

    def test_missing_or_malformed_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            self.assertIsNone(load_ui_state(config))

            (Path(tmp) / UI_STATE_FILE).write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_ui_state(config))

    def test_unknown_page_or_filter_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            path = Path(tmp) / UI_STATE_FILE
            path.write_text('{"page": "nope", "filter": "all"}', encoding="utf-8")
            self.assertIsNone(load_ui_state(config))

            path.write_text('{"page": "library", "filter": "nope"}', encoding="utf-8")
            self.assertIsNone(load_ui_state(config))

    def test_no_config_path_is_a_noop(self) -> None:
        save_ui_state(None, UiState())
        self.assertIsNone(load_ui_state(None))
