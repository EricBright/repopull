"""Guards for the documentation system: entry load, registry, backlinks."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PROSE_DOCS = (
    Path("README.md"),
    Path("NOTES.md"),
    Path("CHANGELOG.md"),
    Path("AUTHORS.md"),
    *sorted(Path("docs").rglob("*.md")),
    *sorted(Path("workflows").rglob("*.md")),
)

_FENCED = re.compile(r"(?ms)^(?:```|~~~)[^\n]*\n.*?^(?:```|~~~)\s*$")
_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")


def broken_local_links(path: Path, root: Path) -> list[str]:
    """Return repo-relative links in *path* whose targets do not exist.

    Fenced blocks are blanked rather than removed so line numbers stay
    accurate. Images use the same `](target)` form and are included.
    """
    text = path.read_text(encoding="utf-8")
    masked = _FENCED.sub(lambda match: "\n" * match.group(0).count("\n"), text)
    broken: list[str] = []
    for match in _LINK.finditer(masked):
        target = match.group(1)
        if target.startswith(("#", "mailto:")):
            continue
        parsed = urlsplit(target)
        if parsed.scheme:
            continue
        relative = unquote(parsed.path)
        if not relative:
            continue
        destination = (path.parent / relative).resolve()
        if not destination.exists():
            line = masked.count("\n", 0, match.start()) + 1
            broken.append(f"{path.relative_to(root)}:{line}: {target}")
    return broken


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

    def test_local_markdown_links_resolve(self) -> None:
        broken = [
            problem
            for relative in PROSE_DOCS
            for problem in broken_local_links(ROOT / relative, ROOT)
        ]

        self.assertEqual(broken, [], "broken local links:\n" + "\n".join(broken))


class LinkCheckTests(unittest.TestCase):
    def test_a_missing_target_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = root / "doc.md"
            document.write_text("[missing](nowhere.md)\n", encoding="utf-8")

            self.assertEqual(
                broken_local_links(document, root),
                ["doc.md:1: nowhere.md"],
            )

    def test_external_anchors_and_existing_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.md").write_text("", encoding="utf-8")
            document = root / "doc.md"
            document.write_text(
                "[web](https://example.com)\n"
                "[anchor](#section)\n"
                "[mail](mailto:test@example.invalid)\n"
                "[file](present.md)\n",
                encoding="utf-8",
            )

            self.assertEqual(broken_local_links(document, root), [])
