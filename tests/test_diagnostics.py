"""Tests for path/root diagnostics and their CLI surface."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repopull import diagnostics
from repopull.cli import main
from repopull.config import Config
from repopull.diagnostics import (
    describe_paths,
    lfs_install_hint,
    lfs_status,
    missing_root_advice,
    no_repos_advice,
)


def _config(
    base: Path,
    root: Path,
    *,
    config_path: Path | None = None,
    root_source: str = "test",
) -> Config:
    return Config(
        root=root,
        log_dir=base / "logs",
        config_path=config_path,
        config_found=bool(config_path and config_path.is_file()),
        root_source=root_source,
    )


class DescribePathsTests(unittest.TestCase):
    def test_unconfigured_root_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = Config(
                root=None,
                log_dir=base / "logs",
                config_path=base / "config.toml",
                config_found=False,
                root_source="not configured",
            )

            text = describe_paths(config)
            advice = missing_root_advice(config)

            self.assertIn("not configured", text)
            self.assertIn("Settings", advice)
            self.assertIn("--root", advice)

    def test_missing_root_is_called_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = _config(
                base,
                base / "missing",
                config_path=base / "config.toml",
                root_source='config.toml key "root"',
            )

            text = describe_paths(config)

            self.assertIn("MISSING", text)
            self.assertIn(str(base / "missing"), text)
            self.assertIn('config.toml key "root"', text)
            self.assertIn("only link", text)

    def test_existing_root_reports_repo_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repos"
            for name in ("alpha", "beta"):
                (root / name / ".git").mkdir(parents=True)

            text = describe_paths(_config(base, root))

            self.assertIn("found, 2 repos", text)
            self.assertNotIn("MISSING", text)

    def test_root_override_hint_matches_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = _config(
                base,
                base / "repos",
                config_path=base / "config.toml",
                root_source="--root",
            )

            text = describe_paths(config)

            self.assertIn("This run uses --root", text)
            self.assertIn("permanent", text)

    def test_missing_config_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = _config(
                base,
                base / "repos",
                config_path=base / "config.toml",
                root_source="built-in default",
            )

            text = describe_paths(config)

            self.assertIn("(MISSING)", text)


class AdviceTests(unittest.TestCase):
    def test_lfs_help_is_read_only_and_has_a_hint(self) -> None:
        status = lfs_status()

        self.assertTrue(lfs_install_hint())
        self.assertTrue(status.install_hint)
        self.assertEqual(status.docs_url, "https://git-lfs.com/")

    def test_lfs_install_hint_prefers_brew_on_bazzite(self) -> None:
        with (
            patch.object(
                diagnostics.Path,
                "read_text",
                return_value='ID=bazzite\nID_LIKE="fedora"\n',
            ),
            patch.object(diagnostics.Path, "exists", return_value=True),
            patch.object(
                diagnostics.shutil, "which", return_value="/usr/bin/brew"
            ),
        ):
            self.assertEqual(
                diagnostics.lfs_install_hint(), "brew install git-lfs"
            )

    def test_lfs_install_hint_uses_apt_on_debian(self) -> None:
        with (
            patch.object(
                diagnostics.Path, "read_text", return_value="ID=debian\n"
            ),
            patch.object(diagnostics.Path, "exists", return_value=False),
            patch.object(diagnostics.shutil, "which", return_value=None),
        ):
            self.assertEqual(
                diagnostics.lfs_install_hint(), "sudo apt install git-lfs"
            )

    def test_lfs_status_reports_version_and_enabled(self) -> None:
        with (
            patch.object(
                diagnostics.git,
                "git_lfs_version",
                return_value="git-lfs/3.7.0 (test)",
            ),
            patch.object(
                diagnostics.git, "git_lfs_enabled_global", return_value=True
            ),
        ):
            status = diagnostics.lfs_status()

        self.assertTrue(status.installed)
        self.assertTrue(status.enabled)
        self.assertEqual(status.version, "git-lfs/3.7.0 (test)")

    def test_missing_root_advice_names_the_link_and_the_knobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = _config(
                base,
                base / "missing",
                config_path=base / "config.toml",
                root_source='config.toml key "root"',
            )

            text = missing_root_advice(config)

            self.assertIn("Next steps", text)
            self.assertIn(str(base / "config.toml"), text)
            self.assertIn("--root", text)
            self.assertIn("mount", text)
            self.assertIn("repopull where", text)

    def test_no_repos_advice_mentions_depth_and_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = _config(base, base / "repos")

            text = no_repos_advice(config)

            self.assertIn("max_depth", text)
            self.assertIn("ignore", text)


class WhereCommandTests(unittest.TestCase):
    def _write_config(self, base: Path, root: Path) -> Path:
        config_path = base / "config.toml"
        config_path.write_text(
            f'root = "{root}"\nlog_dir = "{base / "logs"}"\n',
            encoding="utf-8",
        )
        return config_path

    def test_where_succeeds_even_when_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._write_config(base, base / "missing")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                code = main(["--config", str(config_path), "where"])

            self.assertEqual(code, 0)
            self.assertIn("MISSING", output.getvalue())

    def test_status_with_missing_root_explains_and_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_path = self._write_config(base, base / "missing")
            errors = io.StringIO()

            with contextlib.redirect_stderr(errors):
                code = main(["--config", str(config_path), "status"])

            self.assertEqual(code, 2)
            text = errors.getvalue()
            self.assertIn("does not exist", text)
            self.assertIn("Next steps", text)
            self.assertIn("--root", text)
