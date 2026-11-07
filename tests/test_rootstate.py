"""Tests for persisted watched-root identity."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repopull.mounts import RootIdentity
from repopull.rootstate import (
    ROOT_STATE_FILE,
    ROOT_STATE_VERSION,
    RootState,
    check_root_state,
    read_root_state,
    root_state_problem,
    save_root_state,
)


class RootStateTests(unittest.TestCase):
    def test_round_trip_and_first_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            self.assertIsNone(check_root_state(logs, root, 3).problem)
            state = read_root_state(logs).state

            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.root, str(root))
            self.assertEqual(state.repo_count, 3)
            self.assertEqual(state.device, root.stat().st_dev)
            self.assertTrue((logs / ROOT_STATE_FILE).is_file())

    def test_different_device_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous,
            root=Path("/repos"),
            current=RootIdentity(2, None, None),
            repo_count=3,
        )

        self.assertIsNotNone(problem)
        self.assertIn("different device", problem or "")

    def test_empty_after_nonempty_is_refused(self) -> None:
        previous = RootState(root="/repos", device=1, repo_count=3)

        problem = root_state_problem(
            previous,
            root=Path("/repos"),
            current=RootIdentity(1, None, None),
            repo_count=0,
        )

        self.assertIsNotNone(problem)
        self.assertIn("empty", problem or "")

    def test_changed_root_path_starts_a_new_identity(self) -> None:
        previous = RootState(root="/old", device=1, repo_count=3)

        self.assertIsNone(
            root_state_problem(
                previous,
                root=Path("/new"),
                current=RootIdentity(2, None, None),
                repo_count=4,
            )
        )

    def test_malformed_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            (logs / ROOT_STATE_FILE).write_text("{not json", encoding="utf-8")

            self.assertIsNone(read_root_state(logs).state)

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            save_root_state(logs, root, 7)

            state = read_root_state(logs).state
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
            current=RootIdentity(
                114,
                "f19840d3-0c86-43c3-9170-6f3ebb94c971",
                None,
            ),
            repo_count=43,
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
            current=RootIdentity(114, "new-uuid", None),
            repo_count=43,
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
            self.assertEqual(read_root_state(logs).state.device, root.stat().st_dev + 1)  # type: ignore[union-attr]

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
            state = read_root_state(logs).state
            self.assertEqual(state.device, 114)  # type: ignore[union-attr]
            self.assertEqual(state.filesystem_uuid, "same-uuid")  # type: ignore[union-attr]

    def test_check_and_save_use_the_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            device = root.stat().st_dev
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "version": 2,
                        "root": str(root),
                        "device": device,
                        "repo_count": 3,
                        "filesystem_uuid": "uuid-A",
                        "mount_source": "/dev/sdb1",
                    }
                ),
                encoding="utf-8",
            )
            checked = RootIdentity(device, "uuid-A", "/dev/sdb1")
            later = RootIdentity(device, "uuid-B", "/dev/sdb2")

            with patch(
                "repopull.rootstate.root_identity",
                side_effect=[checked, later],
            ) as probe:
                check = check_root_state(logs, root, 3)

            self.assertIsNone(check.problem)
            self.assertEqual(probe.call_count, 1)
            state = read_root_state(logs).state
            self.assertEqual(state.filesystem_uuid, "uuid-A")  # type: ignore[union-attr]

    def test_missing_uuid_keeps_the_previous_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            device = root.stat().st_dev
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "version": 2,
                        "root": str(root),
                        "device": device,
                        "repo_count": 3,
                        "filesystem_uuid": "stable-uuid",
                        "mount_source": "/dev/sdb1",
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "repopull.rootstate.root_identity",
                return_value=RootIdentity(device, None, None),
            ):
                check = check_root_state(logs, root, 3)

            self.assertIsNone(check.problem)
            state = read_root_state(logs).state
            self.assertEqual(state.filesystem_uuid, "stable-uuid")  # type: ignore[union-attr]
            self.assertEqual(state.mount_source, "/dev/sdb1")  # type: ignore[union-attr]

    def test_empty_identity_mismatch_is_not_repairable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            device = root.stat().st_dev
            (logs / ROOT_STATE_FILE).write_text(
                json.dumps(
                    {
                        "version": 2,
                        "root": str(root),
                        "device": device + 1,
                        "repo_count": 3,
                        "filesystem_uuid": "uuid-A",
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "repopull.rootstate.root_identity",
                return_value=RootIdentity(device, "uuid-B", "/dev/sdb2"),
            ):
                check = check_root_state(logs, root, 0)

            self.assertIsNotNone(check.problem)
            self.assertIn("no repositories", check.problem or "")
            self.assertFalse(check.repairable)
            state = read_root_state(logs).state
            self.assertEqual(state.repo_count, 3)  # type: ignore[union-attr]

    def test_infinite_state_value_is_refused_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            path = logs / ROOT_STATE_FILE
            original = (
                f'{{"root": "{root}", "device": Infinity, "repo_count": 3}}'
            )
            path.write_text(original, encoding="utf-8")

            check = check_root_state(logs, root, 3)

            self.assertIsNotNone(check.problem)
            self.assertIn("device must be an integer", check.problem or "")
            self.assertFalse(check.repairable)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertIsNone(read_root_state(logs).state)

    def test_unknown_state_version_is_refused_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            path = logs / ROOT_STATE_FILE
            original = json.dumps(
                {
                    "version": 99,
                    "root": str(root),
                    "device": root.stat().st_dev,
                    "repo_count": 3,
                }
            )
            path.write_text(original, encoding="utf-8")

            check = check_root_state(logs, root, 3)

            self.assertIsNotNone(check.problem)
            self.assertIn("unsupported version", check.problem or "")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_malformed_json_is_refused_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            path = logs / ROOT_STATE_FILE
            path.write_text("{not json", encoding="utf-8")

            check = check_root_state(logs, root, 3)

            self.assertIsNotNone(check.problem)
            self.assertIn("malformed JSON", check.problem or "")
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_non_utf8_state_is_refused_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"
            logs.mkdir()
            path = logs / ROOT_STATE_FILE
            path.write_bytes(b"\xff\xfe")

            check = check_root_state(logs, root, 3)

            self.assertIsNotNone(check.problem)
            self.assertIn("not UTF-8", check.problem or "")
            self.assertEqual(path.read_bytes(), b"\xff\xfe")

    def test_atomic_save_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            root.mkdir()
            logs = base / "logs"

            save_root_state(logs, root, 2)

            names = sorted(path.name for path in logs.iterdir())
            self.assertEqual(names, [ROOT_STATE_FILE])
