"""Tests for repository discovery."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repopull.discovery import (
    CLONE_TEMP_MAX_AGE_S,
    CLONE_TEMP_PREFIX,
    DiscoveryError,
    discover_repos,
    sweep_stale_clones,
)


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

    def test_read_only_root_raises(self) -> None:
        root = self._root()

        with (
            patch("repopull.discovery.os.access", return_value=False),
            self.assertRaisesRegex(DiscoveryError, "not writable"),
        ):
            discover_repos(root)

    def test_low_free_space_raises(self) -> None:
        root = self._root()

        with (
            patch(
                "repopull.discovery.shutil.disk_usage",
                return_value=SimpleNamespace(free=0),
            ),
            self.assertRaisesRegex(DiscoveryError, "less than"),
        ):
            discover_repos(root)

    def test_results_are_sorted(self) -> None:
        root = self._root()
        for name in ("zeta", "alpha", "mike"):
            (root / name / ".git").mkdir(parents=True)

        labels = [ref.label for ref in discover_repos(root, max_depth=2)]

        self.assertEqual(labels, ["alpha", "mike", "zeta"])

    def test_sweep_removes_only_abandoned_clone_folders(self) -> None:
        root = self._root()
        now = 1_000_000.0
        abandoned = root / f"{CLONE_TEMP_PREFIX}abandoned"
        running = root / f"{CLONE_TEMP_PREFIX}running"
        repository = root / "alpha"
        for path in (abandoned, running):
            (path / "partial").mkdir(parents=True)
        (repository / ".git").mkdir(parents=True)
        old = now - 2 * CLONE_TEMP_MAX_AGE_S
        for path in (abandoned, running):
            stamp = old if path is abandoned else now
            os.utime(path, (stamp, stamp))

        removed = sweep_stale_clones(root, now=now)

        self.assertEqual(removed, [abandoned])
        self.assertFalse(abandoned.exists())
        self.assertTrue(running.exists())
        self.assertTrue(repository.exists())

    def test_sweep_leaves_a_symlinked_folder_and_its_target(self) -> None:
        root = self._root()
        outside = root / "outside"
        outside.mkdir()
        link = root / f"{CLONE_TEMP_PREFIX}link"
        link.symlink_to(outside, target_is_directory=True)
        old = 1_000_000.0 - 2 * CLONE_TEMP_MAX_AGE_S
        os.utime(link, (old, old), follow_symlinks=False)

        removed = sweep_stale_clones(root, now=1_000_000.0)

        self.assertEqual(removed, [])
        self.assertTrue(link.is_symlink())
        self.assertTrue(outside.is_dir())
