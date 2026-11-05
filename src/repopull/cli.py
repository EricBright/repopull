"""Command-line entry point."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from repopull import __version__
from repopull.config import Config, ConfigError, load_config
from repopull.diagnostics import (
    describe_paths,
    missing_root_advice,
    no_repos_advice,
)
from repopull.discovery import DiscoveryError, discover_repos
from repopull.menu import run_menu
from repopull.models import Outcome, RepoRef
from repopull.report import load_latest_report, render_report, report_to_dict
from repopull.runtime import LockError, run_lock
from repopull.sync import status_report, sync_report


def _build_global_parser() -> argparse.ArgumentParser:
    """Options accepted before *or* after the subcommand.

    Parsed separately so a subparser cannot reset their defaults, which is
    what happens when the same options are attached to both parsers.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", type=Path, help="watched repositories directory")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--no-color", action="store_true", help="disable colour")
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of a table"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="print per-repo progress"
    )
    return parser


def _build_command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repopull",
        description="Keep local mirrors of watched remote repositories current.",
        epilog=(
            "Global options (before or after the command): "
            "--root, --config, --no-color, --json, --verbose."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="list discovered repositories")
    sub.add_parser(
        "where", help="show the config file, the watched root, and whether they exist"
    )

    status = sub.add_parser("status", help="fetch and show what a sync would do")
    status.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="GLOB",
        help="limit to labels matching this glob (repeatable)",
    )

    sync = sub.add_parser("sync", help="fetch and fast-forward safely")
    sync.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="GLOB",
        help="limit to labels matching this glob (repeatable)",
    )
    sync.add_argument(
        "--force",
        action="store_true",
        help="hard reset selected repositories instead of fast-forwarding",
    )
    sync.add_argument(
        "--behind",
        action="store_true",
        help="sync only repositories the last report found behind",
    )

    sub.add_parser("report", help="print the last report")
    sub.add_parser("version", help="print the version")
    return parser


def _fail(message: str) -> int:
    print(f"repopull: {message}", file=sys.stderr)
    return 2


def _progress(index: int, total: int, label: str) -> None:
    print(f"[{index}/{total}] fetching {label}", file=sys.stderr, flush=True)


def _select_refs(config: Config, patterns: Sequence[str]) -> list[RepoRef] | None:
    root = config.root
    if root is None:
        print("repopull: no watched folder configured", file=sys.stderr)
        print(missing_root_advice(config), file=sys.stderr)
        return None
    try:
        refs = discover_repos(
            root, max_depth=config.max_depth, ignore=config.ignore
        )
    except DiscoveryError as exc:
        print(f"repopull: {exc}", file=sys.stderr)
        print(missing_root_advice(config), file=sys.stderr)
        return None

    if not refs:
        print(
            f"repopull: no git repositories found under {config.root}",
            file=sys.stderr,
        )
        print(no_repos_advice(config), file=sys.stderr)
        return None

    if not patterns:
        return refs

    selected = [
        ref
        for ref in refs
        if any(
            fnmatch.fnmatch(ref.label, pattern)
            or fnmatch.fnmatch(ref.name, pattern)
            for pattern in patterns
        )
    ]
    if not selected:
        _fail(f"no repositories matched: {', '.join(patterns)}")
        return None
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    """Run repopull and return a process exit code."""
    raw = list(sys.argv[1:] if argv is None else argv)
    global_args, remaining = _build_global_parser().parse_known_args(raw)
    args = _build_command_parser().parse_args(remaining)

    try:
        config = load_config(
            config_path=global_args.config, root_override=global_args.root
        )
    except ConfigError as exc:
        return _fail(str(exc))

    if args.command is None:
        try:
            with run_lock(config.log_dir):
                return run_menu(config)
        except LockError as exc:
            return _fail(str(exc))

    if args.command == "version":
        print(f"repopull {__version__}")
        return 0

    if args.command == "report":
        path = config.log_dir / "latest.log"
        if not path.is_file():
            return _fail(f"no report yet in {config.log_dir}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0

    if args.command == "where":
        print(describe_paths(config))
        return 0

    patterns = [str(item) for item in getattr(args, "only", [])]
    refs = _select_refs(config, patterns)
    if refs is None:
        return 2

    if args.command == "list":
        for ref in refs:
            print(ref.label)
        return 0

    if args.command == "sync" and bool(getattr(args, "behind", False)):
        previous = load_latest_report(config.log_dir)
        if previous is None:
            return _fail(
                "no previous report; run `repopull status` first"
            )
        behind = {
            row.label
            for row in previous.rows
            if row.outcome is Outcome.BEHIND
        }
        refs = [ref for ref in refs if ref.label in behind]
        if not refs:
            print("No repositories are behind in the last report.")
            return 0

    color = (
        not global_args.no_color
        and sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
    )
    progress = (
        _progress if (global_args.verbose or sys.stderr.isatty()) else None
    )

    try:
        with run_lock(config.log_dir):
            if args.command == "status":
                report = status_report(refs, config, progress=progress)
            else:
                report = sync_report(
                    refs,
                    config,
                    force=bool(getattr(args, "force", False)),
                    progress=progress,
                )
    except LockError as exc:
        return _fail(str(exc))

    if global_args.json:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        print(render_report(report, color=color))
    return 1 if report.has_errors else 0
