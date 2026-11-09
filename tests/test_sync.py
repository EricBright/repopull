"""Integration and classification tests for the sync pipeline."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch

import support
from repopull import git
from repopull.config import Config
from repopull.models import Outcome, RepoRef, RepoState, Row
from repopull.sync import (
    _run,
    _within_root,
    classify,
    inspect_repo,
    status_report,
    sync_report,
)


def _config(base: Path) -> Config:
    return Config(
        root=base / "watched",
        fetch_timeout_s=30,
        command_timeout_s=30,
        delay_between_repos_s=0,
        update_submodules=False,
        log_dir=base / "logs",
    )


def _state(**overrides: object) -> RepoState:
    values: dict[str, object] = {
        "ref": RepoRef(Path("/tmp/example"), "example"),
        "branch": "main",
        "upstream": "origin/main",
        "dirty": False,
        "ahead": 0,
        "behind": 0,
        "shallow": False,
        "uses_lfs": False,
        "has_submodules": False,
        "lfs_enabled": False,
        "error": None,
    }
    values.update(overrides)
    return RepoState(**values)  # type: ignore[arg-type]


class ClassifyTests(unittest.TestCase):
    def test_behind_previews_as_behind(self) -> None:
        verdict = classify(
            _state(behind=2),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=True,
        )
        self.assertIs(verdict.outcome, Outcome.BEHIND)
        self.assertEqual(verdict.commits, 2)

    def test_behind_applies_as_updated(self) -> None:
        verdict = classify(
            _state(behind=2),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.UPDATED)
        self.assertEqual(verdict.commits, 2)

    def test_dirty_is_skipped(self) -> None:
        verdict = classify(
            _state(behind=2, dirty=True),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("dirty", verdict.detail)
        self.assertEqual(verdict.commits, 0)

    def test_diverged_is_skipped(self) -> None:
        verdict = classify(
            _state(ahead=1, behind=1),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("diverged", verdict.detail)
        self.assertEqual(verdict.commits, 0)

    def test_force_overrides_dirty_and_diverged(self) -> None:
        verdict = classify(
            _state(ahead=1, behind=1, dirty=True),
            force=True,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.UPDATED)

    def test_lfs_without_binary_is_skipped(self) -> None:
        verdict = classify(
            _state(behind=3, uses_lfs=True),
            force=False,
            lfs_ok=False,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("git-lfs", verdict.detail)
        self.assertEqual(verdict.commits, 0)

    def test_lfs_with_binary_is_syncable(self) -> None:
        verdict = classify(
            _state(behind=3, uses_lfs=True, lfs_enabled=True),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.UPDATED)

    def test_lfs_installed_but_not_enabled_is_skipped(self) -> None:
        verdict = classify(
            _state(behind=3, uses_lfs=True, lfs_enabled=False),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("not enabled", verdict.detail)
        self.assertEqual(verdict.commits, 0)

    def test_detached_head_is_skipped(self) -> None:
        verdict = classify(
            _state(branch=None),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("detached", verdict.detail)
        self.assertEqual(verdict.commits, 0)

    def test_no_upstream_is_skipped(self) -> None:
        verdict = classify(
            _state(upstream=None),
            force=False,
            lfs_ok=True,
            require_lfs=True,
            preview=False,
        )
        self.assertIs(verdict.outcome, Outcome.SKIPPED)
        self.assertIn("upstream", verdict.detail)
        self.assertEqual(verdict.commits, 0)


class ContainmentTests(unittest.TestCase):
    def test_path_inside_root_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "watched"
            repo = root / "repo"
            repo.mkdir(parents=True)

            self.assertTrue(_within_root(repo, root))

    def test_path_outside_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "watched"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()

            self.assertFalse(_within_root(outside, root))


class NetworkFailFastTests(unittest.TestCase):
    def test_one_network_failure_does_not_stop_the_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            refs = [
                RepoRef(base / name, name) for name in ("alpha", "beta", "gamma")
            ]
            states = [_state(ref=ref) for ref in refs]
            failure = git.GitResult(
                args=("git", "fetch"),
                returncode=128,
                stdout="",
                stderr="fatal: unable to access: Could not resolve host: example",
                timeout_s=30,
            )
            success = git.GitResult(
                args=("git", "fetch"),
                returncode=0,
                stdout="",
                stderr="",
                timeout_s=30,
            )

            with (
                patch("repopull.sync._collect", return_value=states),
                patch(
                    "repopull.sync.git.git_lfs_available", return_value=True
                ),
                patch(
                    "repopull.sync.git.fetch",
                    side_effect=[failure, success, success],
                ) as fetch,
                patch(
                    "repopull.sync.inspect_repo",
                    side_effect=lambda ref, timeout: _state(ref=ref),
                ),
            ):
                rows, network_error = _run(
                    refs,
                    _config(base),
                    force=False,
                    preview=True,
                    progress=None,
                    on_row=None,
                    cancel=None,
                )

            self.assertFalse(network_error)
            self.assertIs(rows[0].outcome, Outcome.ERROR)
            self.assertIs(rows[1].outcome, Outcome.UP_TO_DATE)
            self.assertIs(rows[2].outcome, Outcome.UP_TO_DATE)
            self.assertEqual(fetch.call_count, 3)

    def test_two_network_failures_skip_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            refs = [
                RepoRef(base / name, name) for name in ("alpha", "beta", "gamma")
            ]
            states = [_state(ref=ref) for ref in refs]
            failure = git.GitResult(
                args=("git", "fetch"),
                returncode=128,
                stdout="",
                stderr=(
                    "fatal: unable to access: Could not resolve host: example"
                ),
                timeout_s=30,
            )

            with (
                patch("repopull.sync._collect", return_value=states),
                patch(
                    "repopull.sync.git.git_lfs_available", return_value=True
                ),
                patch(
                    "repopull.sync.git.fetch", return_value=failure
                ) as fetch,
            ):
                rows, network_error = _run(
                    refs,
                    _config(base),
                    force=False,
                    preview=True,
                    progress=None,
                    on_row=None,
                    cancel=None,
                )

            self.assertTrue(network_error)
            self.assertEqual(len(rows), 3)
            self.assertIs(rows[0].outcome, Outcome.ERROR)
            self.assertIn("fetch failed", rows[0].detail)
            self.assertIs(rows[1].outcome, Outcome.ERROR)
            self.assertEqual(rows[2].detail, "not attempted: network unavailable")
            self.assertEqual(
                [row.label for row in rows], ["alpha", "beta", "gamma"]
            )
            self.assertEqual(fetch.call_count, 2)


class SyncIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)

    def _pair(self, name: str = "repo") -> tuple[Path, Path, Path]:
        return support.make_pair(self.base, name)

    def test_fast_forward_pulls_one_commit(self) -> None:
        _remote, seed, watched = self._pair()
        support.commit_upstream(seed, "two\n", "two")

        report = sync_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.UPDATED)
        self.assertEqual(report.rows[0].commits, 1)
        self.assertEqual((watched / "file.txt").read_text(encoding="utf-8"), "two\n")

    def test_up_to_date_does_nothing(self) -> None:
        _remote, _seed, watched = self._pair()

        report = sync_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.UP_TO_DATE)
        self.assertEqual(report.rows[0].commits, 0)

    def test_dirty_repository_is_skipped_and_untouched(self) -> None:
        _remote, seed, watched = self._pair()
        (watched / "file.txt").write_text("local\n", encoding="utf-8")
        support.commit_upstream(seed, "two\n", "two")

        report = sync_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("dirty", report.rows[0].detail)
        self.assertEqual((watched / "file.txt").read_text(encoding="utf-8"), "local\n")

    def test_diverged_is_skipped_until_forced(self) -> None:
        _remote, seed, watched = self._pair()
        (watched / "file.txt").write_text("local\n", encoding="utf-8")
        support.git("add", "file.txt", cwd=watched)
        support.git("commit", "-m", "local", cwd=watched)
        support.commit_upstream(seed, "two\n", "two")

        skipped = sync_report([RepoRef(watched, "repo")], _config(self.base))
        self.assertIs(skipped.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("diverged", skipped.rows[0].detail)

        forced = sync_report([RepoRef(watched, "repo")], _config(self.base), force=True)
        self.assertIs(forced.rows[0].outcome, Outcome.UPDATED)
        self.assertEqual((watched / "file.txt").read_text(encoding="utf-8"), "two\n")
        count = support.git("rev-list", "--count", "HEAD", cwd=watched).strip()
        self.assertEqual(count, "2")

    def test_untracked_file_does_not_block_sync(self) -> None:
        _remote, seed, watched = self._pair()
        (watched / "scratch.bin").write_text("junk", encoding="utf-8")
        support.commit_upstream(seed, "two\n", "two")

        report = sync_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.UPDATED)
        self.assertTrue((watched / "scratch.bin").exists())

    def test_missing_tracking_config_falls_back_to_origin_branch(self) -> None:
        _remote, seed, watched = self._pair()
        support.git("branch", "--unset-upstream", cwd=watched)
        support.commit_upstream(seed, "two\n", "two")

        report = sync_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.UPDATED)
        self.assertEqual((watched / "file.txt").read_text(encoding="utf-8"), "two\n")

    def test_lfs_repository_is_skipped_without_git_lfs(self) -> None:
        _remote, seed, watched = self._pair("lfsrepo")
        (seed / ".gitattributes").write_text("*.png filter=lfs\n", encoding="utf-8")
        support.git("add", ".gitattributes", cwd=seed)
        support.git("commit", "-m", "lfs", cwd=seed)
        support.git("push", "origin", "main", cwd=seed)

        with patch("repopull.git.git_lfs_available", return_value=False):
            sync_report([RepoRef(watched, "lfsrepo")], _config(self.base))

            support.commit_upstream(seed, "two\n", "two")
            report = sync_report(
                [RepoRef(watched, "lfsrepo")], _config(self.base)
            )

        self.assertIs(report.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("LFS", report.rows[0].detail)

    def test_incoming_lfs_attributes_are_detected_before_checkout(self) -> None:
        _remote, seed, watched = self._pair("incoming-lfs")
        (seed / ".gitattributes").write_text("*.png filter=lfs\n", encoding="utf-8")
        support.git("add", ".gitattributes", cwd=seed)
        support.git("commit", "-m", "add lfs", cwd=seed)
        support.git("push", "origin", "main", cwd=seed)

        with patch("repopull.git.git_lfs_available", return_value=False):
            report = sync_report(
                [RepoRef(watched, "incoming-lfs")], _config(self.base)
            )

        self.assertIs(report.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("LFS", report.rows[0].detail)
        self.assertFalse((watched / ".gitattributes").exists())

    def test_status_changes_nothing(self) -> None:
        _remote, seed, watched = self._pair()
        support.commit_upstream(seed, "two\n", "two")

        report = status_report([RepoRef(watched, "repo")], _config(self.base))

        self.assertIs(report.rows[0].outcome, Outcome.BEHIND)
        self.assertEqual(report.rows[0].commits, 1)
        self.assertEqual((watched / "file.txt").read_text(encoding="utf-8"), "one\n")

    def test_inspect_reports_branch_and_upstream(self) -> None:
        _remote, _seed, watched = self._pair()

        state = inspect_repo(RepoRef(watched, "repo"), timeout=30)

        self.assertEqual(state.branch, "main")
        self.assertEqual(state.upstream, "origin/main")
        self.assertFalse(state.dirty)
        self.assertIsNone(state.error)

    def test_empty_clone_is_reported_clearly(self) -> None:
        remote = self.base / "remotes" / "empty.git"
        remote.parent.mkdir(parents=True, exist_ok=True)
        support.git(
            "init", "--bare", "--initial-branch=main", str(remote), cwd=self.base
        )
        watched = self.base / "watched" / "empty"
        support.git("clone", str(remote), str(watched), cwd=self.base)

        state = inspect_repo(RepoRef(watched, "empty"), timeout=30)

        self.assertIsNotNone(state.error)
        self.assertIn("no commits", state.error or "")
        self.assertEqual(state.ahead, 0)
        self.assertEqual(state.behind, 0)
        self.assertFalse(state.dirty)

    def test_cancelled_run_skips_without_fetching(self) -> None:
        _remote, _seed, watched = self._pair()
        cancel = Event()
        cancel.set()

        report = sync_report(
            [RepoRef(watched, "repo")], _config(self.base), cancel=cancel
        )

        self.assertIs(report.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("cancelled", report.rows[0].detail)

    def test_cancellation_during_fetch_leaves_the_worktree_alone(self) -> None:
        _remote, seed, watched = self._pair()
        support.commit_upstream(seed, "two\n", "two")
        cancel = Event()
        started = Event()

        def slow_fetch(
            _repo: Path, *, timeout: float, cancel: Event | None = None
        ) -> git.GitResult:
            started.set()
            if cancel is not None:
                cancel.wait(2)
            return git.GitResult(
                args=("git", "fetch"),
                returncode=130,
                stdout="",
                stderr="cancelled",
                timeout_s=timeout,
                cancelled=True,
            )

        timer = Timer(0.05, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with patch("repopull.sync.git.fetch", slow_fetch):
            report = sync_report(
                [RepoRef(watched, "repo")],
                _config(self.base),
                cancel=cancel,
            )

        self.assertTrue(started.is_set())
        self.assertIs(report.rows[0].outcome, Outcome.SKIPPED)
        self.assertIn("cancelled", report.rows[0].detail)
        self.assertEqual(
            (watched / "file.txt").read_text(encoding="utf-8"), "one\n"
        )

    def test_on_row_emits_each_repository_as_it_finishes(self) -> None:
        _remote, seed, watched = self._pair()
        support.commit_upstream(seed, "two\n", "two")
        seen: list[Row] = []

        report = sync_report(
            [RepoRef(watched, "repo")],
            _config(self.base),
            on_row=seen.append,
        )

        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0].outcome, Outcome.UPDATED)
        self.assertEqual(seen[0].commits, 1)
        self.assertIs(report.rows[0].outcome, Outcome.UPDATED)

    def test_on_row_reports_two_repositories_in_order(self) -> None:
        _remote_a, seed_a, watched_a = self._pair("a")
        _remote_b, _seed_b, watched_b = self._pair("b")
        support.commit_upstream(seed_a, "two\n", "two")
        seen: list[Row] = []

        sync_report(
            [RepoRef(watched_a, "a"), RepoRef(watched_b, "b")],
            _config(self.base),
            on_row=seen.append,
        )

        self.assertEqual([row.label for row in seen], ["a", "b"])
        self.assertIs(seen[0].outcome, Outcome.UPDATED)
        self.assertIs(seen[1].outcome, Outcome.UP_TO_DATE)


class LfsConfigTests(unittest.TestCase):
    def test_detects_local_lfs_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _remote, _seed, watched = support.make_pair(base)

            isolated = {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            }
            with patch.dict(os.environ, isolated):
                self.assertFalse(git.git_lfs_enabled(watched, timeout=10))
                support.git(
                    "config",
                    "filter.lfs.clean",
                    "git-lfs clean -- %f",
                    cwd=watched,
                )
                support.git(
                    "config",
                    "filter.lfs.smudge",
                    "git-lfs smudge -- %f",
                    cwd=watched,
                )

                self.assertTrue(git.git_lfs_enabled(watched, timeout=10))
