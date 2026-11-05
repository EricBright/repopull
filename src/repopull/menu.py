"""Interactive numbered menu."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime

from repopull.config import Config
from repopull.diagnostics import missing_root_advice
from repopull.discovery import DiscoveryError, discover_repos
from repopull.models import RepoRef, Report
from repopull.report import render_report
from repopull.sync import status_report, sync_report


class SelectionError(ValueError):
    """Raised when a selection string cannot be parsed."""


def parse_selection(text: str, total: int) -> list[int]:
    """Parse `1,3,5-8`, `all`, or `none` into sorted 1-based numbers."""
    if total < 1:
        raise SelectionError("there are no repositories to select")

    cleaned = text.strip().lower()
    if cleaned in ("", "none"):
        return []
    if cleaned == "all":
        return list(range(1, total + 1))

    numbers: set[int] = set()
    for token in re.split(r"[,\s]+", cleaned):
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                raise SelectionError(f"invalid range: {token}")
            candidates = range(start, end + 1)
        elif token.isdigit():
            number = int(token)
            candidates = range(number, number + 1)
        else:
            raise SelectionError(f"unrecognised selection: {token!r}")

        for number in candidates:
            if not 1 <= number <= total:
                raise SelectionError(f"out of range: {number} (valid: 1-{total})")
            numbers.add(number)

    return sorted(numbers)


def _color_enabled() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _progress(index: int, total: int, label: str) -> None:
    print(f"  [{index:>2}/{total}] fetching {label}", flush=True)


def _pause() -> None:
    try:
        input("\nPress Enter to continue… ")
    except (EOFError, KeyboardInterrupt):
        print()


def _show(report: Report, *, color: bool) -> None:
    print()
    print(render_report(report, color=color))
    _pause()


def _print_header(config: Config, refs: list[RepoRef]) -> None:
    print()
    print("repopull — watched repository sync")
    print(f"Root:  {config.root}  ({config.root_source})")
    print(f"Repos: {len(refs)}")
    latest = config.log_dir / "latest.log"
    if latest.is_file():
        stamp = datetime.fromtimestamp(latest.stat().st_mtime)
        print(f"Last:  {stamp:%Y-%m-%d %H:%M:%S}")
    print()
    print("1) Fetch status (no changes)")
    print("2) Sync all")
    print("3) Sync selected")
    print("4) Force sync selected")
    print("5) View last report")
    print("6) Quit")


def _print_refs(refs: list[RepoRef]) -> None:
    print()
    for index, ref in enumerate(refs, start=1):
        print(f"  {index:>2}. {ref.label}")


def _choose(refs: list[RepoRef], *, prompt: str) -> list[RepoRef]:
    _print_refs(refs)
    try:
        text = input(prompt)
    except (EOFError, KeyboardInterrupt):
        return []
    try:
        numbers = parse_selection(text, len(refs))
    except SelectionError as exc:
        print(f"  ! {exc}")
        return []
    return [refs[number - 1] for number in numbers]


def _confirm_and_force(
    selected: list[RepoRef],
    config: Config,
    *,
    color: bool,
) -> None:
    print("\nThis will discard local commits and tracked changes in:")
    for ref in selected:
        print(f"  - {ref.label}")
    try:
        answer = input("Type 'reset' to confirm: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    if answer != "reset":
        print("Cancelled.")
        return
    _show(sync_report(selected, config, force=True, progress=_progress), color=color)


def _view_last_report(config: Config) -> None:
    path = config.log_dir / "latest.log"
    if not path.is_file():
        print("\nNo report yet.")
        _pause()
        return
    print()
    print(path.read_text(encoding="utf-8"), end="")
    _pause()


def run_menu(config: Config) -> int:
    """Run the interactive loop until the user quits."""
    color = _color_enabled()
    while True:
        if config.root is None:
            print("repopull: no watched folder configured", file=sys.stderr)
            print(missing_root_advice(config), file=sys.stderr)
            return 2
        try:
            refs = discover_repos(
                config.root, max_depth=config.max_depth, ignore=config.ignore
            )
        except DiscoveryError as exc:
            print(f"repopull: {exc}", file=sys.stderr)
            print(missing_root_advice(config), file=sys.stderr)
            return 2

        _print_header(config, refs)
        try:
            choice = input("Select an action [1-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice in ("6", "q", "quit"):
            return 0
        if choice == "1":
            _show(status_report(refs, config, progress=_progress), color=color)
        elif choice == "2":
            _show(sync_report(refs, config, progress=_progress), color=color)
        elif choice == "3":
            selected = _choose(
                refs,
                prompt="Select repos to sync (numbers/ranges, 'all', 'none'): ",
            )
            if selected:
                _show(sync_report(selected, config, progress=_progress), color=color)
        elif choice == "4":
            selected = _choose(
                refs,
                prompt="Select repos to hard-reset (numbers/ranges, 'all', 'none'): ",
            )
            if selected:
                _confirm_and_force(selected, config, color=color)
        elif choice == "5":
            _view_last_report(config)
        else:
            print("  ! Unknown choice.")
