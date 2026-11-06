"""Tests for the run lock."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repopull import runtime


class RunLockTests(unittest.TestCase):
    def test_lock_creates_dot_lock_and_rejects_a_second_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"

            with runtime.run_lock(log_dir):
                self.assertTrue((log_dir / ".lock").is_file())

                with self.assertRaises(runtime.LockError):
                    with runtime.run_lock(log_dir):
                        pass

    def test_leftover_lock_file_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / ".lock").write_text("stale content", encoding="utf-8")

            with runtime.run_lock(log_dir):
                self.assertTrue((log_dir / ".lock").is_file())
