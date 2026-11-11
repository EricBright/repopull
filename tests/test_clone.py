"""Tests for cloning a remote into the watched folder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from repopull.clone import (
    CloneCancelled,
    CloneError,
    CloneProgress,
    clone_repository,
    derive_name,
    parse_progress,
    validate_name,
    validate_url,
)
from repopull.discovery import CLONE_TEMP_PREFIX, discover_repos

import support


class UrlTests(unittest.TestCase):
    def test_ordinary_addresses_are_accepted(self) -> None:
        for url in (
            "https://github.com/owner/repo.git",
            "http://example.invalid/owner/repo",
            "ssh://git@example.invalid/owner/repo.git",
            "git://example.invalid/owner/repo.git",
            "file:///tmp/repo.git",
            "git@example.invalid:owner/repo.git",
            "example.invalid:owner/repo.git",
        ):
            self.assertEqual(validate_url(url), url)

    def test_local_path_is_accepted_when_it_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "repo"
            local.mkdir()
            self.assertEqual(validate_url(str(local)), str(local))

    def test_dangerous_or_unknown_addresses_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            for url in (
                "",
                "   ",
                "-upload-pack=sh",
                "ext::sh -c touch /tmp/pwned",
                "fd::3",
                "ftp://example.invalid/repo",
                "https://example.invalid/repo\nrm -rf /",
                str(missing),
            ):
                with self.assertRaises(CloneError, msg=url):
                    validate_url(url)

    def test_derive_name_handles_urls_paths_and_scp(self) -> None:
        cases = {
            "https://github.com/owner/repo.git": "repo",
            "https://github.com/owner/repo/": "repo",
            "https://github.com/owner/repo": "repo",
            "git@github.com:owner/repo.git": "repo",
            "example.invalid:repo.git": "repo",
            "/tmp/remotes/repo.git": "repo",
            "https://github.com/owner/repo.git?tab=readme": "repo",
        }
        for url, expected in cases.items():
            self.assertEqual(derive_name(url), expected, url)

    def test_folder_names_cannot_escape_or_hide(self) -> None:
        for name in (".", "..", ".hidden", "-option", "a/b", "a\\b", "", "  "):
            with self.assertRaises(CloneError, msg=name):
                validate_name(name)
        self.assertEqual(validate_name("my repo_1"), "my repo_1")


class CloneTests(unittest.TestCase):
    def test_clones_a_local_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()

            result = clone_repository(
                str(remote), "cloned", root, timeout=60
            )

            self.assertFalse(result.empty)
            self.assertEqual(result.destination, root / "cloned")
            self.assertEqual(
                (result.destination / "file.txt").read_text(encoding="utf-8"),
                "one\n",
            )

    def test_clones_an_empty_remote_and_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote = base / "empty.git"
            support.git(
                "init", "--bare", "--initial-branch=main", str(remote), cwd=base
            )
            root = base / "watched"
            root.mkdir()

            result = clone_repository(
                str(remote), "empty", root, timeout=60
            )

            self.assertTrue(result.empty)
            self.assertTrue((root / "empty" / ".git").is_dir())

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()
            (root / "cloned").mkdir()

            with self.assertRaisesRegex(CloneError, "already exists"):
                clone_repository(str(remote), "cloned", root, timeout=60)

    def test_failed_clone_leaves_no_temporary_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            not_a_repo = base / "not-a-repo"
            not_a_repo.mkdir()
            root = base / "watched"
            root.mkdir()

            with self.assertRaises(CloneError):
                clone_repository(str(not_a_repo), "cloned", root, timeout=60)

            self.assertEqual(list(root.iterdir()), [])

    def test_cancelled_clone_leaves_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()
            cancel = Event()
            cancel.set()

            with self.assertRaises(CloneCancelled):
                clone_repository(
                    str(remote), "cloned", root, timeout=60, cancel=cancel
                )

            self.assertFalse((root / "cloned").exists())
            self.assertEqual(list(root.iterdir()), [])


class ProgressParsingTests(unittest.TestCase):
    def test_a_phase_percentage_maps_onto_the_overall_scale(self) -> None:
        update = parse_progress(
            "Receiving objects:  87% (1234/1418), 2.30 MiB | 1.20 MiB/s"
        )

        assert update is not None
        self.assertEqual(update.label, "Receiving objects")
        self.assertEqual(update.percent, 87)
        self.assertEqual((update.count, update.total), (1234, 1418))
        self.assertEqual(update.overall, 75)
        self.assertEqual(
            update.text, "Receiving objects 87% (1,234/1,418)"
        )

    def test_the_remote_prefix_is_part_of_git_s_output_not_the_label(self) -> None:
        update = parse_progress("remote: Counting objects: 42% (12/28)")

        assert update is not None
        self.assertEqual(update.label, "Counting objects")
        self.assertEqual(update.overall, 4)

    def test_every_phase_advances_the_same_scale(self) -> None:
        overalls: list[int] = []
        for label in (
            "Enumerating objects",
            "Counting objects",
            "Compressing objects",
            "Receiving objects",
            "Resolving deltas",
            "Updating files",
        ):
            update = parse_progress(f"{label}: 100% (3/3)")
            assert update is not None, label
            overalls.append(update.overall)

        self.assertEqual(overalls, sorted(overalls))
        self.assertEqual(overalls[0], 3)
        self.assertEqual(overalls[-1], 100)

    def test_counts_are_optional(self) -> None:
        update = parse_progress("Resolving deltas: 100%")

        assert update is not None
        self.assertEqual(update.text, "Resolving deltas 100%")
        self.assertIsNone(update.count)

    def test_percentages_are_clamped_to_the_scale(self) -> None:
        update = parse_progress("Receiving objects: 150% (1/1)")

        assert update is not None
        self.assertEqual(update.percent, 100)
        self.assertEqual(update.overall, 85)

    def test_plain_git_output_produces_no_progress(self) -> None:
        for line in (
            "Cloning into '/tmp/x'...",
            "remote: Enumerating objects: 5813, done.",
            "remote: Total 5813 (delta 3646), reused 5780",
            "Updating files: 3 files",
            "fatal: repository not found",
            "",
        ):
            self.assertIsNone(parse_progress(line), line)


class ProgressCloneTests(unittest.TestCase):
    def test_a_streamed_clone_reports_progress_and_finishes_at_100(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()
            updates: list[CloneProgress] = []

            clone_repository(
                f"file://{remote}",
                "cloned",
                root,
                timeout=60,
                on_progress=updates.append,
            )

            self.assertTrue(updates)
            overalls = [update.overall for update in updates]
            self.assertEqual(overalls, sorted(overalls))
            self.assertEqual(overalls[-1], 100)
            self.assertEqual(updates[-1].label, "Finishing")

    def test_cancelling_from_the_progress_stream_leaves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()
            cancel = Event()

            def stop(_update: CloneProgress) -> None:
                cancel.set()

            with self.assertRaises(CloneCancelled):
                clone_repository(
                    f"file://{remote}",
                    "cloned",
                    root,
                    timeout=60,
                    cancel=cancel,
                    on_progress=stop,
                )

            self.assertFalse((root / "cloned").exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_a_timeout_during_the_stream_leaves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote, _seed, _watched = support.make_pair(base)
            root = base / "clone-root"
            root.mkdir()

            with self.assertRaises(CloneError):
                clone_repository(
                    f"file://{remote}",
                    "cloned",
                    root,
                    timeout=0.001,
                    on_progress=lambda _update: None,
                )

            self.assertFalse((root / "cloned").exists())
            self.assertEqual(list(root.iterdir()), [])


class DiscoveryGuardTests(unittest.TestCase):
    def test_clone_work_in_progress_is_not_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            partial = root / CLONE_TEMP_PREFIX / "repo"
            (partial / ".git").mkdir(parents=True)
            (root / "real" / ".git").mkdir(parents=True)

            refs = discover_repos(root)

            self.assertEqual([ref.label for ref in refs], ["real"])


if __name__ == "__main__":
    unittest.main()
