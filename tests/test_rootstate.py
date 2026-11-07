"""Tests for persisted watched-root identity."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repopull.rootstate import (
    ROOT_STATE_FILE,
    ROOT_STATE_VERSION,
    RootIdentity,
    RootState,
    _filesystem_uuid,
    _mount_source,
    check_root_state,
    load_root_state,
    root_state_problem,
    save_root_state,
    verify_root_state,
)


class RootStateTests(unittest.TestCase):
    def test_round_trip_and_first_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            self.assertIsNone(verify_root_state(logs, root, 3))
            state = load_root_state(logs)

            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.root, str(root))
            self.assertEqual(state.repo_count, 3)
            self.assertEqual(state.device, root.stat().st_dev)
            self.assertTrue((logs / ROOT_STATE_FILE).is_file())

    def test_different_device_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous, root=Path("/repos"), device=2, repo_count=3
        )

        self.assertIsNotNone(problem)
        self.assertIn("different device", problem or "")

    def test_empty_after_nonempty_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous, root=Path("/repos"), device=1, repo_count=0
        )

        self.assertIsNotNone(problem)
        self.assertIn("empty", problem or "")

    def test_changed_root_path_starts_a_new_identity(self) -> None:
        previous = RootState(root="/old", device=1, repo_count=3)

        self.assertIsNone(
            root_state_problem(
                previous, root=Path("/new"), device=2, repo_count=4
            )
        )

    def test_malformed_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            (logs / ROOT_STATE_FILE).write_text("{not json", encoding="utf-8")

            self.assertIsNone(load_root_state(logs))

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            save_root_state(logs, root, 7)

            state = load_root_state(logs)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.repo_count, 7)
            self.assertEqual(state.device, root.stat().st_dev)

    def test_saved_state_uses_versioned_filesystem_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            save_root_state(logs, root, 2)

            data = json.loads((logs / ROOT_STATE_FILE).read_text())
            self.assertEqual(data["version"], ROOT_STATE_VERSION)
            self.assertEqual(data["root"], str(root))
            self.assertEqual(data["repo_count"], 2)
            self.assertIn("device", data)
            # A UUID may be unavailable on overlay/tmpfs test filesystems.
            self.assertIn("filesystem_uuid", data)

    def test_same_filesystem_uuid_accepts_changed_device_number(self) -> None:
        previous = RootState(
            root="/repos",
            device=116,
            repo_count=43,
            filesystem_uuid="f19840d3-0c86-43c3-9170-6f3ebb94c971",
        )

        problem = root_state_problem(
            previous,
            root=Path("/repos"),
            device=114,
            repo_count=43,
            filesystem_uuid="f19840d3-0c86-43c3-9170-6f3ebb94c971",
        )

        self.assertIsNone(problem)

    def test_different_filesystem_uuid_is_refused_even_if_device_matches(
        self,
    ) -> None:
        previous = RootState(
            root="/repos",
            device=114,
            repo_count=43,
            filesystem_uuid="old-uuid",
        )

        problem = root_state_problem(
            previous,
            root=Path("/repos"),
            device=114,
            repo_count=43,
            filesystem_uuid="new-uuid",
        )

        self.assertIsNotNone(problem)
        self.assertIn("different filesystem", problem or "")

    def test_legacy_device_mismatch_offers_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "root": str(root),
                        "device": root.stat().st_dev + 1,
                        "repo_count": 3,
                    }
                ),
                encoding="utf-8",
            )

            check = check_root_state(logs, root, 3)

            self.assertIsNotNone(check.problem)
            self.assertTrue(check.repairable)
            self.assertIsNotNone(check.current)
            self.assertEqual(load_root_state(logs).device, root.stat().st_dev + 1)  # type: ignore[union-attr]

    def test_check_rewrites_legacy_state_after_a_matching_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "root": str(root),
                        "device": root.stat().st_dev,
                        "repo_count": 3,
                    }
                ),
                encoding="utf-8",
            )

            check = check_root_state(logs, root, 3)

            self.assertIsNone(check.problem)
            data = json.loads((logs / ROOT_STATE_FILE).read_text())
            self.assertEqual(data["version"], ROOT_STATE_VERSION)

    def test_same_uuid_is_accepted_even_when_device_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "version": 2,
                        "root": str(root),
                        "device": 116,
                        "repo_count": 3,
                        "filesystem_uuid": "same-uuid",
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "repopull.rootstate.root_identity",
                return_value=RootIdentity(
                    device=114,
                    filesystem_uuid="same-uuid",
                    mount_source="/dev/sdb1",
                ),
            ):
                check = check_root_state(logs, root, 3)

            self.assertIsNone(check.problem)
            state = load_root_state(logs)
            self.assertEqual(state.device, 114)  # type: ignore[union-attr]
            self.assertEqual(state.filesystem_uuid, "same-uuid")  # type: ignore[union-attr]

    def test_mount_source_uses_longest_matching_mount_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            mountinfo = base / "mountinfo"
            mountinfo.write_text(
                "\n".join(
                    [
                        "1 2 0:1 / / rw shared:1 - overlay overlay rw",
                        f"2 1 0:133 / {root} rw shared:2 - btrfs /dev/sdb1 rw",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                _mount_source(root, mountinfo=mountinfo), "/dev/sdb1"
            )

    def test_filesystem_uuid_resolves_a_by_uuid_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            by_uuid = Path(tmp)
            (by_uuid / "f19840d3-0c86-43c3-9170-6f3ebb94c971").symlink_to(
                "/dev/sdb1"
            )

            self.assertEqual(
                _filesystem_uuid("/dev/sdb1", by_uuid=by_uuid),
                "f19840d3-0c86-43c3-9170-6f3ebb94c971",
            )

    def test_mountinfo_octal_escapes_are_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "with space"
            root.mkdir()
            escaped = str(root).replace(" ", "\\040")
            mountinfo = base / "mountinfo"
            mountinfo.write_text(
                f"1 2 0:1 / {escaped} rw - btrfs /dev/sdb1 rw",
                encoding="utf-8",
            )

            self.assertEqual(
                _mount_source(root, mountinfo=mountinfo), "/dev/sdb1"
            )
