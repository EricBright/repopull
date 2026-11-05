"""Tests for the shared model types."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from repopull.models import Outcome, RepoRef, RepoState, Report, Row


def _state(**overrides: object) -> RepoState:
    values: dict[str, object] = {
        "ref": RepoRef(Path("/repos/alpha"), "alpha"),
        "branch": "main",
        "upstream": "origin/main",
        "dirty": False,
        "ahead": 0,
        "behind": 0,
        "shallow": False,
        "uses_lfs": False,
        "has_submodules": False,
    }
    values.update(overrides)
    return RepoState(**values)  # type: ignore[arg-type]


class RepoRefTests(unittest.TestCase):
    def test_name_is_the_basename(self) -> None:
        self.assertEqual(
            RepoRef(Path("/repos/alpha"), "label").name, "alpha"
        )


class RepoStateTests(unittest.TestCase):
    def test_upstream_and_detached_predicates(self) -> None:
        self.assertTrue(_state().has_upstream)
        self.assertFalse(_state(upstream=None).has_upstream)
        self.assertFalse(_state().is_detached)
        self.assertTrue(_state(branch=None).is_detached)


class ReportTests(unittest.TestCase):
    def test_counts_include_zeroes_and_detect_errors(self) -> None:
        report = Report(
            mode="status",
            started_at=datetime(2026, 11, 5, 16, 0, 0),
            elapsed_s=1.0,
            rows=(
                Row("a", "main", Outcome.UPDATED, 1, ""),
                Row("b", "main", Outcome.ERROR, 0, "boom"),
                Row("c", "main", Outcome.ERROR, 0, "boom"),
            ),
        )

        self.assertEqual(report.count(Outcome.ERROR), 2)
        self.assertEqual(report.totals[Outcome.SKIPPED], 0)
        self.assertTrue(report.has_errors)

    def test_a_clean_report_has_no_errors(self) -> None:
        report = Report(
            mode="status",
            started_at=datetime(2026, 11, 5, 16, 0, 0),
            elapsed_s=1.0,
            rows=(Row("a", "main", Outcome.UPDATED, 1, ""),),
        )

        self.assertFalse(report.has_errors)
