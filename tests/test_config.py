"""Tests for saving and reloading configuration."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import repopull.config as config_module
from repopull.config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    project_home,
    save_behavior_settings,
    save_config,
    save_repo_holds,
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

    def test_project_home_falls_back_to_the_checkout(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                project_home(),
                Path(config_module.__file__).resolve().parents[2],
            )


class ConfigValidationTests(unittest.TestCase):
    def load(self, text: str) -> Config:
        directory = tempfile.mkdtemp()
        path = Path(directory) / "config.toml"
        path.write_text(text, encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return load_config(config_path=path)

    def test_boolean_is_not_a_number(self) -> None:
        for text in (
            "fetch_timeout_s = true\n",
            "command_timeout_s = false\n",
            "max_depth = true\n",
            "auto_refresh_s = false\n",
        ):
            with self.assertRaises(ConfigError):
                self.load(text)

    def test_one_is_a_valid_depth(self) -> None:
        self.assertEqual(self.load("max_depth = 1\n").max_depth, 1)

    def test_zero_auto_refresh_is_valid(self) -> None:
        self.assertEqual(self.load("auto_refresh_s = 0\n").auto_refresh_s, 0)

    def test_relative_log_dir_is_under_project_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"REPOPULL_HOME": tmp}):
                loaded = self.load('log_dir = "logs"\n')
            self.assertEqual(loaded.log_dir, Path(tmp) / "logs")

    def test_ignore_must_be_a_list_of_strings(self) -> None:
        for text in ('ignore = "x"\n', "ignore = [1]\n"):
            with self.assertRaises(ConfigError):
                self.load(text)

    def test_exclusions_must_be_lists_of_strings(self) -> None:
        for key in ("exclude_from_refresh", "exclude_from_sync"):
            for text in (f'{key} = "x"\n', f"{key} = [1]\n"):
                with self.assertRaises(ConfigError):
                    self.load(text)

    def test_repopull_config_environment_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("max_depth = 3\n", encoding="utf-8")
            with patch.dict(os.environ, {"REPOPULL_CONFIG": str(path)}):
                self.assertEqual(load_config().max_depth, 3)


class SaveConfigTests(unittest.TestCase):
    def test_defaults_are_stable(self) -> None:
        defaults = Config()

        self.assertEqual(defaults.max_depth, 2)
        self.assertEqual(defaults.ignore, ())
        self.assertEqual(defaults.exclude_from_refresh, ())
        self.assertEqual(defaults.exclude_from_sync, ())
        self.assertEqual(defaults.fetch_timeout_s, 300.0)
        self.assertEqual(defaults.command_timeout_s, 120.0)
        self.assertEqual(defaults.delay_between_repos_s, 0.5)
        self.assertTrue(defaults.update_submodules)
        self.assertTrue(defaults.require_git_lfs_for_lfs_repos)
        self.assertFalse(defaults.background_mode)
        self.assertEqual(defaults.auto_refresh_s, 0)
        self.assertFalse(defaults.auto_refresh_pause_when_hidden)
        self.assertEqual(defaults.log_retention_days, 30)

    def test_empty_file_uses_the_same_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("", encoding="utf-8")

            loaded = load_config(config_path=path)

            self.assertEqual(loaded.max_depth, 2)
            self.assertEqual(loaded.fetch_timeout_s, 300.0)
            self.assertEqual(loaded.command_timeout_s, 120.0)
            self.assertEqual(loaded.delay_between_repos_s, 0.5)
            self.assertTrue(loaded.update_submodules)
            self.assertTrue(loaded.require_git_lfs_for_lfs_repos)
            self.assertFalse(loaded.background_mode)
            self.assertEqual(loaded.auto_refresh_s, 0)
            self.assertFalse(loaded.auto_refresh_pause_when_hidden)
            self.assertEqual(loaded.log_retention_days, 30)

    def test_missing_explicit_config_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.toml"

            with self.assertRaises(ConfigError):
                load_config(config_path=missing)

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
            self.assertFalse(loaded.auto_refresh_pause_when_hidden)

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
                auto_refresh_pause_when_hidden=True,
                update_submodules=False,
                require_git_lfs_for_lfs_repos=False,
                exclude_from_refresh=("vendor/one",),
                exclude_from_sync=("vendor/two", "vendor/one"),
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
            self.assertTrue(loaded.auto_refresh_pause_when_hidden)
            self.assertAlmostEqual(loaded.delay_between_repos_s, 1.5)
            self.assertFalse(loaded.update_submodules)
            self.assertFalse(loaded.require_git_lfs_for_lfs_repos)
            self.assertEqual(
                loaded.exclude_from_refresh, ("vendor/one",)
            )
            self.assertEqual(
                loaded.exclude_from_sync, ("vendor/two", "vendor/one")
            )
            self.assertTrue(loaded.config_found)
            self.assertTrue(loaded.skips_refresh("vendor/one"))
            self.assertFalse(loaded.skips_refresh("vendor/two"))
            self.assertTrue(loaded.skips_sync("vendor/two"))

    def test_save_behavior_updates_compact_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "background_mode=false\nmax_depth = 2\n",
                encoding="utf-8",
            )

            save_behavior_settings(
                path,
                background_mode=True,
                auto_refresh_s=900,
                auto_refresh_pause_when_hidden=True,
            )

            text = path.read_text(encoding="utf-8")
            self.assertIn("background_mode = true", text)
            self.assertIn("auto_refresh_s = 900", text)
            self.assertNotIn("background_mode=false", text)

    def test_save_behavior_preserves_comments_and_other_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "# keep this comment\n"
                'root = "/tmp/repos"\n'
                "background_mode = false\n"
                "auto_refresh_s = 0\n"
                "auto_refresh_pause_when_hidden = false\n",
                encoding="utf-8",
            )

            save_behavior_settings(
                path,
                background_mode=True,
                auto_refresh_s=600,
                auto_refresh_pause_when_hidden=True,
            )
            text = path.read_text(encoding="utf-8")

            self.assertIn("# keep this comment", text)
            self.assertIn('root = "/tmp/repos"', text)
            self.assertIn("background_mode = true", text)
            self.assertIn("auto_refresh_s = 600", text)
            self.assertIn("auto_refresh_pause_when_hidden = true", text)
            self.assertEqual(text.count("background_mode"), 1)
            self.assertEqual(text.count("auto_refresh_s"), 1)
            self.assertEqual(
                text.count("auto_refresh_pause_when_hidden"), 1
            )

    def test_save_repo_holds_preserves_comments_and_other_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "# keep this comment\n"
                'root = "/tmp/repos"\n'
                "exclude_from_refresh = []\n",
                encoding="utf-8",
            )

            save_repo_holds(
                path,
                exclude_from_refresh=("alpha", "beta"),
                exclude_from_sync=("beta",),
            )
            text = path.read_text(encoding="utf-8")
            loaded = load_config(config_path=path)

            self.assertIn("# keep this comment", text)
            self.assertIn('root = "/tmp/repos"', text)
            self.assertEqual(loaded.exclude_from_refresh, ("alpha", "beta"))
            self.assertEqual(loaded.exclude_from_sync, ("beta",))
            self.assertEqual(text.count("exclude_from_refresh"), 1)
            self.assertEqual(text.count("exclude_from_sync"), 1)
