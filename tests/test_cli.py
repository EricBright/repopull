"""CLI-only paths that do not need the network."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from repopull.cli import main
from repopull.models import Outcome, Report, Row
from repopull.report import write_log


class SyncBehindTests(unittest.TestCase):
    def _config(self, base: Path) -> Path:
        root = base / "repos"
        for name in ("alpha", "beta"):
            (root / name / ".git").mkdir(parents=True)
        path = base / "config.toml"
        path.write_text(
            f'root = "{root}"\nlog_dir = "{base / "logs"}"\n',
            encoding="utf-8",
        )
        return path

    def test_behind_without_a_report_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            errors = io.StringIO()

            with contextlib.redirect_stderr(errors):
                code = main(
                    ["--config", str(config_path), "sync", "--behind"]
                )

            self.assertEqual(code, 2)
            self.assertIn("no previous report", errors.getvalue())

    def test_behind_with_no_behind_rows_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            write_log(
                Report(
                    mode="status",
                    started_at=datetime(2026, 11, 5, 16, 0, 0),
                    elapsed_s=1.0,
                    rows=(
                        Row("alpha", "main", Outcome.UP_TO_DATE, 0, ""),
                        Row("beta", "main", Outcome.SKIPPED, 0, "dirty"),
                    ),
                ),
                base / "logs",
            )
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                code = main(
                    ["--config", str(config_path), "sync", "--behind"]
                )

            self.assertEqual(code, 0)
            self.assertIn("No repositories are behind", output.getvalue())
