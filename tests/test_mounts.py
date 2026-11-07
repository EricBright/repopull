"""Tests for mount-source and filesystem-UUID probing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repopull.mounts import _filesystem_uuid, _mount_source


class MountTests(unittest.TestCase):
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
