"""Tests for cloning a remote into the watched folder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from repopull.clone import (
    CloneCancelled,
    CloneError,
    clone_repository,
    derive_name,
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
