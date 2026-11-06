"""Tests for saving and reloading configuration."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from repopull.config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    project_home,
    save_behavior_settings,
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
            self.assertEqual(loaded.log_retention_days, 30)
            self.assertFalse(loaded.background_mode)
            self.assertEqual(loaded.auto_refresh_s, 0)

    def test_negative_log_retention_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("log_retention_days = -1\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(config_path=path)

    def test_zero_log_retention_disables_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("log_retention_days = 0\n", encoding="utf-8")

            self.assertEqual(load_config(config_path=path).log_retention_days, 0)

    def test_auto_refresh_is_clamped_up_to_the_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("auto_refresh_s = 60\n", encoding="utf-8")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                loaded = load_config(config_path=path)

            self.assertEqual(loaded.auto_refresh_s, 300)
            self.assertIn("clamped", stderr.getvalue())

    def test_auto_refresh_above_max_is_clamped_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("auto_refresh_s = 999999\n", encoding="utf-8")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                loaded = load_config(config_path=path)

            self.assertEqual(loaded.auto_refresh_s, 86_400)
            self.assertIn("clamped", stderr.getvalue())

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
                log_retention_days=7,
                background_mode=True,
                auto_refresh_s=900,
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
            self.assertEqual(loaded.log_retention_days, 7)
            self.assertTrue(loaded.background_mode)
            self.assertEqual(loaded.auto_refresh_s, 900)
            self.assertAlmostEqual(loaded.delay_between_repos_s, 1.5)
            self.assertFalse(loaded.update_submodules)
            self.assertFalse(loaded.require_git_lfs_for_lfs_repos)
            self.assertTrue(loaded.config_found)

    def test_save_behavior_preserves_comments_and_other_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "# keep this comment\n"
                'root = "/tmp/repos"\n'
                "background_mode = false\n"
                "auto_refresh_s = 0\n",
                encoding="utf-8",
            )

            save_behavior_settings(
                path,
                background_mode=True,
                auto_refresh_s=600,
            )
            text = path.read_text(encoding="utf-8")

            self.assertIn("# keep this comment", text)
            self.assertIn('root = "/tmp/repos"', text)
            self.assertIn("background_mode = true", text)
            self.assertIn("auto_refresh_s = 600", text)
            self.assertEqual(text.count("background_mode"), 1)
            self.assertEqual(text.count("auto_refresh_s"), 1)
