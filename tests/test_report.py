"""Tests for the persisted JSON report."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from repopull.models import Outcome, Report, Row
from repopull.report import (
    load_latest_report,
    render_report,
    report_from_dict,
    report_to_dict,
    write_log,
)


def _report() -> Report:
    return Report(
        mode="status",
        started_at=datetime(2026, 11, 5, 16, 0, 0),
        elapsed_s=1.25,
        rows=(
            Row("alpha", "main", Outcome.BEHIND, 3, ""),
            Row("beta", "develop", Outcome.SKIPPED, 0, "dirty working tree"),
        ),
    )


class ReportRoundTripTests(unittest.TestCase):
    def test_dict_round_trip(self) -> None:
        report = _report()

        restored = report_from_dict(report_to_dict(report))

        self.assertEqual(restored, report)

    def test_write_log_persists_latest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)

            stamped = write_log(_report(), log_dir)
            loaded = load_latest_report(log_dir)

            self.assertEqual(loaded, stamped)
            self.assertTrue((log_dir / "latest.json").is_file())
            self.assertTrue((log_dir / "latest.log").is_file())

    def test_malformed_json_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "latest.json").write_text("{not json", encoding="utf-8")

            self.assertIsNone(load_latest_report(log_dir))

    def test_partial_run_merges_into_latest_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            write_log(
                Report(
                    mode="status",
                    started_at=datetime(2026, 11, 5, 16, 0, 0),
                    elapsed_s=10.0,
                    rows=(
                        Row("alpha", "main", Outcome.BEHIND, 3, ""),
                        Row("beta", "main", Outcome.SKIPPED, 0, "dirty"),
                    ),
                ),
                log_dir,
            )
            write_log(
                Report(
                    mode="sync",
                    started_at=datetime(2026, 11, 5, 16, 5, 0),
                    elapsed_s=1.0,
                    rows=(Row("beta", "main", Outcome.UPDATED, 1, ""),),
                ),
                log_dir,
            )

            snapshot = load_latest_report(log_dir)

            self.assertIsNotNone(snapshot)
            rows = {row.label: row for row in snapshot.rows}
            self.assertEqual(set(rows), {"alpha", "beta"})
            self.assertIs(rows["alpha"].outcome, Outcome.BEHIND)
            self.assertIs(rows["beta"].outcome, Outcome.UPDATED)

    def test_unknown_outcome_is_rejected(self) -> None:
        data = report_to_dict(_report())
        data["rows"][0]["outcome"] = "exploded"

        with self.assertRaises(ValueError):
            report_from_dict(data)

    def test_render_report_includes_rows_and_totals(self) -> None:
        text = render_report(_report(), color=False)

        self.assertIn("Repository", text)
        self.assertIn("Status", text)
        self.assertIn("alpha", text)
        self.assertIn("behind", text)
        self.assertIn("Totals: 1 behind, 1 skipped", text)
        self.assertIn("Attention:", text)
        self.assertIn("beta: dirty working tree", text)
