"""Guards for the documentation system: entry load, registry, backlinks."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PROSE_DOCS = (
    Path("README.md"),
    Path("NOTES.md"),
    Path("CHANGELOG.md"),
    *sorted(Path("docs").rglob("*.md")),
    *sorted(Path("workflows").rglob("*.md")),
)


class DocumentationTests(unittest.TestCase):
    def test_readme_entry_load_is_bounded(self) -> None:
        words = len(README.read_text(encoding="utf-8").split())

        self.assertLessEqual(
            words,
            2000,
            f"README is {words} words; move detail to its on-demand doc and leave a "
            "link, or raise the cap deliberately",
        )

    def test_registry_lists_every_prose_document(self) -> None:
        text = README.read_text(encoding="utf-8")
        section = text.split("## Documentation Index", 1)[1].split("\n## ", 1)[0]

        for path in PROSE_DOCS:
            if path == Path("README.md"):
                continue
            self.assertIn(
                f"]({path.as_posix()})",
                section,
                f"{path} is missing from the README index",
            )
            self.assertTrue((ROOT / path).is_file(), path)

    def test_every_document_links_back_to_the_registry(self) -> None:
        for path in PROSE_DOCS:
            if path == Path("README.md"):
                continue
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(
                "For the full documentation index",
                text,
                f"{path} lacks a registry backlink",
            )
