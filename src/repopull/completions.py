"""Render shell completion scripts for the command line.

The names below are declared here instead of being read back out of the parser,
because argparse exposes its subparsers only through a private attribute. The
table is kept honest by `tests/test_completions.py`, which walks the real parser
and fails when a command or option exists in one place and not the other.

Zsh is served by its `bashcompinit` emulation rather than a native script: the
bash script can be checked by `bash -n` on any machine that runs the tests,
whereas a native `_arguments` body cannot be checked without zsh installed.
"""

from __future__ import annotations

SHELLS = ("bash", "fish")

COMMANDS: dict[str, str] = {
    "list": "list discovered repositories",
    "where": "show the config file, the watched root, and whether they exist",
    "clone": "clone one repository into the watched folder",
    "repair-root": "accept the watched folder identity",
    "status": "fetch and show what a sync would do",
    "sync": "fetch and fast-forward safely",
    "report": "print the last report",
    "version": "print the version",
    "completions": "print a shell completion script",
}

# Accepted before or after the command, so they are offered everywhere.
GLOBAL_OPTIONS: dict[str, str] = {
    "--root": "watched repositories directory",
    "--config": "path to config.toml",
    "--no-color": "disable colour",
    "--json": "emit JSON instead of a table",
    "--verbose": "print per-repo progress",
}

COMMAND_OPTIONS: dict[str, dict[str, str]] = {
    "clone": {
        "--name": "folder name (default: from the URL)",
        "--timeout": "seconds before the clone is abandoned",
    },
    "repair-root": {"--yes": "write the new identity"},
    "status": {"--only": "limit to labels matching this glob"},
    "sync": {
        "--only": "limit to labels matching this glob",
        "--force": "hard reset selected repositories",
        "--behind": "sync only repositories the last report found behind",
    },
}

# Options whose value is a path, so completion should offer files.
PATH_OPTIONS = ("--root", "--config", "--name")


def _option_words(command: str) -> list[str]:
    """Every option word offered once *command* has been entered."""
    words = [*GLOBAL_OPTIONS, *COMMAND_OPTIONS.get(command, {})]
    return [*words, "--help"]


def render_bash() -> str:
    """A bash function plus the `complete` registration."""
    lines = [
        "# bash completion for repopull.",
        '# Load it with: eval "$(repopull completions bash)"',
        "# zsh: autoload -U bashcompinit && bashcompinit, then the same line.",
        "_repopull() {",
        "    local cur command word words skip=0",
        "    COMPREPLY=()",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        "",
        '    command=""',
        # Words before the one being completed only, so a half-typed command
        # is not mistaken for a finished one.
        '    for word in "${COMP_WORDS[@]:1:COMP_CWORD-1}"; do',
        '        if [ "$skip" = 1 ]; then',
        "            skip=0",
        "            continue",
        "        fi",
        '        case "$word" in',
        # An option value must not be mistaken for the command, so the words
        # that take one are skipped along with the word after them.
        "            " + "|".join((*PATH_OPTIONS, "--timeout", "--only")) + ")",
        "                skip=1",
        "                continue",
        "                ;;",
        "            -*) continue ;;",
        '            *) command="$word"; break ;;',
        "        esac",
        "    done",
        "",
        '    if [ -z "$command" ]; then',
        "        mapfile -t COMPREPLY < <(compgen -W "
        f'"{" ".join(COMMANDS)}" -- "$cur")',
        "        return",
        "    fi",
        "",
        '    case "${COMP_WORDS[COMP_CWORD-1]}" in',
        f"        {'|'.join(PATH_OPTIONS)})",
        '            mapfile -t COMPREPLY < <(compgen -f -- "$cur")',
        "            return",
        "            ;;",
        "    esac",
        "",
        '    if [[ "$cur" == -* ]]; then',
        '        case "$command" in',
    ]

    for name in COMMANDS:
        words = " ".join(_option_words(name))
        lines.append(f'            {name}) words="{words}" ;;')
    lines += [
        '            *) words="' + " ".join(_option_words("")) + '" ;;',
        "        esac",
        '        mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")',
        "        return",
        "    fi",
        "",
        '    if [ "$command" = completions ]; then',
        f'        mapfile -t COMPREPLY < <(compgen -W "{" ".join(SHELLS)}" -- "$cur")',
        "        return",
        "    fi",
        "",
        # `clone` is the only command with a positional argument, and it is an
        # address that may also be a local path.
        '    if [ "$command" = clone ]; then',
        '        mapfile -t COMPREPLY < <(compgen -f -- "$cur")',
        "    fi",
        "}",
        "",
        "complete -F _repopull repopull",
        "",
    ]
    return "\n".join(lines)


def render_fish() -> str:
    """`complete` lines; fish keeps them in one file per command."""
    lines = [
        "# fish completion for repopull.",
        "# Install: repopull completions fish > "
        "~/.config/fish/completions/repopull.fish",
        "complete -c repopull -f",
        "",
        "# Commands",
    ]
    for name, description in COMMANDS.items():
        lines.append(
            "complete -c repopull -n __fish_use_subcommand "
            f"-a {name} -d '{description}'"
        )

    lines += ["", "# Global options"]
    for option, description in GLOBAL_OPTIONS.items():
        lines.append(_fish_option("", option, description))

    for command, options in COMMAND_OPTIONS.items():
        if not options:
            continue
        lines += ["", f"# {command}"]
        for option, description in options.items():
            lines.append(_fish_option(command, option, description))

    lines += ["", "# Shell names for the completions command"]
    for shell in SHELLS:
        lines.append(
            "complete -c repopull -n "
            f"'__fish_seen_subcommand_from completions' -a {shell}"
        )
    lines.append("")
    return "\n".join(lines)


def _fish_option(command: str, option: str, description: str) -> str:
    """One `complete` line for an option, with a path hint where it has one."""
    parts = ["complete -c repopull"]
    if command:
        parts.append(f"-n '__fish_seen_subcommand_from {command}'")
    parts.append(f"-l {option.lstrip('-')}")

    if option == "--root":
        parts.append("-r -a '(__fish_complete_directories)'")
    elif option in ("--config", "--name"):
        parts.append("-r -a '(__fish_complete_path)'")
    elif option in ("--timeout", "--only"):
        parts.append("-r")

    parts.append(f"-d '{description}'")
    return " ".join(parts)


def render(shell: str) -> str:
    """Return the completion script for *shell*.

    Raises `KeyError` for an unknown shell; the CLI turns that into a usage
    error before this is reached, because argparse validates the choice.
    """
    if shell == "bash":
        return render_bash()
    if shell == "fish":
        return render_fish()
    raise KeyError(shell)
