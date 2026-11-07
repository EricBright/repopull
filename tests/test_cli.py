"""CLI-only paths that do not need the network."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from repopull.cli import main
from repopull.models import Outcome, Report, Row
from repopull.report import write_log
from repopull.runtime import run_lock


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


class RepairRootTests(unittest.TestCase):
    def _config(self, base: Path) -> Path:
        root = base / "repos"
        for name in ("alpha", "beta"):
            (root / name / ".git").mkdir(parents=True)
        path = base / "config.toml"
        path.write_text(
            f'root = "{root}"\nlog_dir = "{base / "logs"}"\n',
            encoding="utf-8",
        )
        logs = base / "logs"
        logs.mkdir()
        (logs / "root-state.json").write_text(
            json.dumps(
                {
                    "root": str(root),
                    "device": root.stat().st_dev + 1,
                    "repo_count": 2,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_repair_root_without_yes_only_shows_the_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                code = main(["--config", str(config_path), "repair-root"])

            self.assertEqual(code, 0)
            self.assertIn("No changes made", output.getvalue())
            saved = json.loads(
                (base / "logs" / "root-state.json").read_text()
            )
            self.assertNotIn("version", saved)

    def test_repair_root_yes_accepts_the_current_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                code = main(
                    ["--config", str(config_path), "repair-root", "--yes"]
                )

            self.assertEqual(code, 0)
            self.assertIn("Repaired", output.getvalue())
            saved = json.loads(
                (base / "logs" / "root-state.json").read_text()
            )
            self.assertEqual(saved["version"], 2)
            self.assertEqual(
                saved["device"], (base / "repos").stat().st_dev
            )

    def test_repair_root_obeys_the_run_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            errors = io.StringIO()

            with run_lock(base / "logs"):
                with contextlib.redirect_stderr(errors):
                    code = main(
                        ["--config", str(config_path), "repair-root"]
                    )

            self.assertEqual(code, 2)
            self.assertIn("another repopull run", errors.getvalue())

    def test_repair_root_reports_an_unusable_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._config(base)
            path = base / "logs" / "root-state.json"
            path.write_text("{not json", encoding="utf-8")
            errors = io.StringIO()

            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(errors),
            ):
                code = main(["--config", str(config_path), "repair-root"])

            self.assertEqual(code, 0)
            self.assertIn("not usable", errors.getvalue())
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")
