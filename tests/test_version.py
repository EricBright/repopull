"""Guard against the two version declarations drifting."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_DOCS = ("README.md", "docs/packaging.md")


class VersionTests(unittest.TestCase):
    def test_pyproject_and_package_versions_match(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        init_text = (ROOT / "src" / "repopull" / "__init__.py").read_text()
        match = re.search(r'__version__ = "([^"]+)"', init_text)

        self.assertIsNotNone(match)
        self.assertEqual(pyproject["project"]["version"], match.group(1))

    def test_live_docs_match_version(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = pyproject["project"]["version"]

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        release = re.search(
            r"Current release: \*{0,2}(\d+\.\d+\.\d+)", readme
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.group(1), version)

        for name in LIVE_DOCS:
            text = (ROOT / name).read_text(encoding="utf-8")
            refs = re.findall(r"repopull-(\d+\.\d+\.\d+)-x86_64", text)
            self.assertTrue(refs, name)
            for found in refs:
                self.assertEqual(found, version, name)
