"""Tests for saving and reloading configuration."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repopull.config import (
    Config,
    default_config_path,
    load_config,
    project_home,
    save_config,
)


class ProjectHomeTests(unittest.TestCase):
    def test_project_home_follows_repopull_home(self) -> None:
        with patch.dict(os.environ, {"REPOPULL_HOME": "/tmp/repopull-home"}):
            self.assertEqual(project_home(), Path("/tmp/repopull-home"))
            self.assertEqual(
                Config().log_dir, Path("/tmp/repopull-home/logs")
            )

    def test_default_config_path_is_under_project_home(self) -> None:
        with patch.dict(os.environ, {"REPOPULL_HOME": "/tmp/repopull-home"}):
            self.assertEqual(
                default_config_path(),
                Path("/tmp/repopull-home/config.toml"),
            )


class SaveConfigTests(unittest.TestCase):
    def test_missing_root_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "config.toml"
            path.write_text("max_depth = 2\n", encoding="utf-8")

            loaded = load_config(config_path=path)

            self.assertIsNone(loaded.root)
            self.assertEqual(loaded.root_source, "not configured")

    def test_save_without_root_writes_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "config.toml"

            save_config(
                Config(
                    root=None,
                    log_dir=base / "logs",
                    config_path=path,
                    config_found=False,
                ),
                path,
            )
            loaded = load_config(config_path=path)

            self.assertIsNone(loaded.root)
            self.assertIn("# root =", path.read_text(encoding="utf-8"))

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "config.toml"
            config = Config(
                root=base / "repos",
                log_dir=base / "logs",
                delay_between_repos_s=1.5,
                update_submodules=False,
                require_git_lfs_for_lfs_repos=False,
                config_path=path,
                config_found=False,
                root_source="test",
            )

            save_config(config, path)
            loaded = load_config(config_path=path)

            self.assertEqual(loaded.root, config.root)
            self.assertEqual(loaded.log_dir, config.log_dir)
            self.assertAlmostEqual(loaded.delay_between_repos_s, 1.5)
            self.assertFalse(loaded.update_submodules)
            self.assertFalse(loaded.require_git_lfs_for_lfs_repos)
            self.assertTrue(loaded.config_found)
