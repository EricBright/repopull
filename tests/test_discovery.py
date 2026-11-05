"""Tests for repository discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repopull.discovery import DiscoveryError, discover_repos


class DiscoveryTests(unittest.TestCase):
    def _root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_finds_top_level_and_nested_repositories(self) -> None:
        root = self._root()
        (root / "alpha" / ".git").mkdir(parents=True)
        (root / "container" / "beta" / ".git").mkdir(parents=True)
        (root / "container" / "not-a-repo").mkdir(parents=True)
        (root / "plain").mkdir()

        refs = discover_repos(root, max_depth=2)

        self.assertEqual([ref.label for ref in refs], ["alpha", "container/beta"])

    def test_git_file_counts_as_repository(self) -> None:
        root = self._root()
        worktree = root / "linked"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

        refs = discover_repos(root, max_depth=2)

        self.assertEqual([ref.label for ref in refs], ["linked"])

    def test_ignore_matches_label_or_basename(self) -> None:
        root = self._root()
        (root / "keep" / ".git").mkdir(parents=True)
        (root / "skip-me" / ".git").mkdir(parents=True)
        (root / "nested" / "also-skip" / ".git").mkdir(parents=True)

        refs = discover_repos(root, max_depth=2, ignore=["skip-me", "also-skip"])

        self.assertEqual([ref.label for ref in refs], ["keep"])

    def test_depth_limit(self) -> None:
        root = self._root()
        (root / "a" / "b" / ".git").mkdir(parents=True)

        self.assertEqual(discover_repos(root, max_depth=1), [])

    def test_missing_root_raises(self) -> None:
        with self.assertRaisesRegex(DiscoveryError, "does not exist"):
            discover_repos(Path("/definitely/not/here"))

    def test_results_are_sorted(self) -> None:
        root = self._root()
        for name in ("zeta", "alpha", "mike"):
            (root / name / ".git").mkdir(parents=True)

        labels = [ref.label for ref in discover_repos(root, max_depth=2)]

        self.assertEqual(labels, ["alpha", "mike", "zeta"])
