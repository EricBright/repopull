"""Tests for persisted watched-root identity."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repopull.rootstate import (
    ROOT_STATE_FILE,
    RootState,
    load_root_state,
    root_state_problem,
    save_root_state,
    verify_root_state,
)


class RootStateTests(unittest.TestCase):
    def test_round_trip_and_first_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            self.assertIsNone(verify_root_state(logs, root, 3))
            state = load_root_state(logs)

            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.root, str(root))
            self.assertEqual(state.repo_count, 3)
            self.assertEqual(state.device, root.stat().st_dev)
            self.assertTrue((logs / ROOT_STATE_FILE).is_file())

    def test_different_device_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous, root=Path("/repos"), device=2, repo_count=3
        )

        self.assertIsNotNone(problem)
        self.assertIn("different device", problem or "")

    def test_empty_after_nonempty_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous, root=Path("/repos"), device=1, repo_count=0
        )

        self.assertIsNotNone(problem)
        self.assertIn("empty", problem or "")

    def test_changed_root_path_starts_a_new_identity(self) -> None:
        previous = RootState(root="/old", device=1, repo_count=3)

        self.assertIsNone(
            root_state_problem(
                previous, root=Path("/new"), device=2, repo_count=4
            )
        )

    def test_malformed_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            (logs / ROOT_STATE_FILE).write_text("{not json", encoding="utf-8")

            self.assertIsNone(load_root_state(logs))

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            save_root_state(logs, root, 7)

            state = load_root_state(logs)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.repo_count, 7)
            self.assertEqual(state.device, root.stat().st_dev)
