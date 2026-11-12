"""Tests for the generated shell completion scripts."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from repopull import cli
from repopull.completions import (
    COMMAND_OPTIONS,
    COMMANDS,
    GLOBAL_OPTIONS,
    SHELLS,
    render,
    render_bash,
    render_fish,
)

BASH = shutil.which("bash")
FISH = shutil.which("fish")

# Feeds one command line to the generated function and prints what it offers,
# which is the only way to test the script without a terminal.
BASH_DRIVER = """
source "$1" || exit 3
shift
COMP_WORDS=("$@")
COMP_CWORD=$(( $# - 1 ))
COMPREPLY=()
_repopull
printf '%s\\n' "${COMPREPLY[@]}"
"""


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the parser has no subcommands")


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    }


class TableTests(unittest.TestCase):
    """The declared table is what the parser actually accepts."""

    def test_commands_match_the_parser(self) -> None:
        self.assertEqual(set(COMMANDS), set(_subparsers(cli._build_command_parser())))

    def test_every_command_option_is_declared(self) -> None:
        # A subcommand declares only its own options; the global ones are
        # parsed separately, which is why they are offered to every command.
        subparsers = _subparsers(cli._build_command_parser())
        for name, parser in subparsers.items():
            with self.subTest(command=name):
                expected = set(COMMAND_OPTIONS.get(name, {}))
                self.assertEqual(_options(parser), expected)

    def test_global_options_match_the_parser(self) -> None:
        self.assertEqual(set(GLOBAL_OPTIONS), _options(cli._build_global_parser()))

    def test_undeclared_options_are_not_offered_for_other_commands(self) -> None:
        # `--force` belongs to sync only, so clone must not advertise it.
        self.assertNotIn("--force", COMMAND_OPTIONS.get("clone", {}))
        self.assertIn("--force", COMMAND_OPTIONS["sync"])


class RenderTests(unittest.TestCase):
    def test_every_shell_renders(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.assertTrue(render(shell).strip())

    def test_unknown_shell_raises(self) -> None:
        with self.assertRaises(KeyError):
            render("zsh")

    def test_bash_mentions_every_command_and_option(self) -> None:
        script = render_bash()
        for name in COMMANDS:
            self.assertIn(f"            {name})", script)
        for option in (*GLOBAL_OPTIONS, "--help"):
            self.assertIn(option, script)
        self.assertIn("complete -F _repopull repopull", script)

    def test_fish_mentions_every_command_and_option(self) -> None:
        script = render_fish()
        for name in COMMANDS:
            self.assertIn(f"-a {name} ", script)
        for option in GLOBAL_OPTIONS:
            self.assertIn(f"-l {option.lstrip('-')} ", script)
        self.assertIn("complete -c repopull -f", script)

    def test_no_script_contains_an_unescaped_quote_in_a_description(self) -> None:
        # A description is emitted inside single quotes in fish, so an
        # apostrophe there would truncate the line.
        for text in (*COMMANDS.values(), *GLOBAL_OPTIONS.values()):
            self.assertNotIn("'", text)
        for options in COMMAND_OPTIONS.values():
            for text in options.values():
                self.assertNotIn("'", text)


@unittest.skipUnless(BASH, "bash is not installed")
class BashScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.script = Path(self.directory.name) / "repopull.bash"
        self.script.write_text(render_bash(), encoding="utf-8")

    def _complete(self, *words: str) -> list[str]:
        result = subprocess.run(
            [BASH, "-c", BASH_DRIVER, "bash", str(self.script), *words],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "HOME": self.directory.name},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines() if line]

    def test_script_has_valid_syntax(self) -> None:
        result = subprocess.run(
            [BASH, "-n", str(self.script)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_word_offers_commands(self) -> None:
        self.assertEqual(set(self._complete("repopull", "")), set(COMMANDS))

    def test_a_prefix_narrows_the_commands(self) -> None:
        self.assertEqual(self._complete("repopull", "cl"), ["clone"])

    def test_options_follow_the_command(self) -> None:
        offered = set(self._complete("repopull", "sync", "--"))
        self.assertIn("--force", offered)
        self.assertNotIn("--name", offered)

    def test_a_global_option_is_offered_after_the_command(self) -> None:
        self.assertIn("--root", self._complete("repopull", "sync", "--r"))

    def test_an_option_value_is_not_mistaken_for_the_command(self) -> None:
        # `--root /tmp` puts a non-option word before the command slot.
        self.assertEqual(
            self._complete("repopull", "--root", "/tmp", "li"), ["list"]
        )

    def test_the_shell_argument_completes(self) -> None:
        self.assertEqual(
            set(self._complete("repopull", "completions", "")), set(SHELLS)
        )


@unittest.skipUnless(FISH, "fish is not installed")
class FishScriptTests(unittest.TestCase):
    def test_script_has_valid_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "repopull.fish"
            script.write_text(render_fish(), encoding="utf-8")
            result = subprocess.run(
                [FISH, "-n", str(script)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class CommandTests(unittest.TestCase):
    def test_completions_are_printed_without_touching_the_config(self) -> None:
        # A broken config would otherwise print an error at every shell start.
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text("this is not toml", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(
                    ["--config", str(config), "completions", "bash"]
                )

        self.assertEqual(code, 0)
        self.assertTrue(output.getvalue().startswith("# bash completion"))

    def test_an_unknown_shell_is_a_usage_error(self) -> None:
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.main(["completions", "zsh"])
        self.assertEqual(raised.exception.code, 2)
