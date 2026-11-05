"""Increment the project version in pyproject.toml and repopull/__init__.py.

Usage:
    python3 packaging/bump_version.py [major|minor|patch]
    python3 packaging/bump_version.py --check
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "repopull" / "__init__.py"

VERSION_RE = re.compile(r'^version = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)
INIT_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "part",
        choices=("major", "minor", "patch"),
        nargs="?",
        default="patch",
        help="which number to increment (default: patch)",
    )
    parser.add_argument(
        "--check", action="store_true", help="print the current version and exit"
    )
    args = parser.parse_args()

    text = PYPROJECT.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if match is None:
        raise SystemExit("no version line in pyproject.toml")
    major, minor, patch = (int(value) for value in match.groups())
    current = f"{major}.{minor}.{patch}"

    if args.check:
        print(current)
        return

    if args.part == "major":
        major, minor, patch = major + 1, 0, 0
    elif args.part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new = f"{major}.{minor}.{patch}"

    PYPROJECT.write_text(
        VERSION_RE.sub(f'version = "{new}"', text, count=1),
        encoding="utf-8",
    )

    init_text = INIT.read_text(encoding="utf-8")
    if INIT_RE.search(init_text) is None:
        raise SystemExit("no __version__ line in src/repopull/__init__.py")
    INIT.write_text(
        INIT_RE.sub(f'__version__ = "{new}"', init_text, count=1),
        encoding="utf-8",
    )

    print(f"{current} -> {new}")


if __name__ == "__main__":
    main()
