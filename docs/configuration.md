# Configuration reference

## Where settings come from

Resolution order for the config file:

1. `--config PATH`
2. `$REPOPULL_CONFIG`
3. `$REPOPULL_HOME/config.toml`
4. `<project>/config.toml` (local, gitignored; copy `config.example.toml`)

The repository ships `config.example.toml`; a populated `config.toml` is
intentionally not tracked.

A missing config file is fine when no explicit path was given: built-in defaults
apply to everything except the watched folder. With no `root`, `list`, `status`
and `sync` explain how to set one (GUI Settings, `root` in the file, or
`--root`), and `where` prints `(not configured)`.

The resolved `root` is the single link to the watched data. `repopull where`
prints it, where it came from (`config.toml key "root"`, `--root`, or
`not configured`), whether it exists and is writable, and how many repos it
contains. Discovery also requires at least 64 MiB free on that filesystem.
The last filesystem identity and repository count are kept in
`logs/root-state.json`. repopull records the filesystem UUID and mount source,
with the device number as a fallback, and refuses a different filesystem at the
same path or an unexpectedly empty root. A reboot can change a device number
without changing the disk (btrfs uses an anonymous `0:N` device); the UUID keeps
that from looking like a replacement.

A state file written by 0.4.14 or earlier has no UUID, so its first device
change may still be refused. Repair it with **Repair saved root state** in the
GUI, or preview and accept it from the CLI:

```bash
./repopull.sh repair-root
./repopull.sh repair-root --yes
```

The preview prints the saved and current identities. Only use `--yes` when the
current disk is the one you expect; deleting `logs/root-state.json` also works,
but skips the comparison.

Command-line flags override the file. `--root` overrides `root`.

## Keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `root` | string | **not configured** | Directory holding the watched repositories. The GUI's Settings page writes it; `--root` overrides it. |
| `max_depth` | integer ≥ 1 | `2` | How deep to look for `.git`. `1` = direct children, `2` = grandchildren too. |
| `ignore` | list of strings | `[]` | `fnmatch` globs. A directory is skipped when its relative label (`LEAP 71/PicoGK`) **or** basename (`PicoGK`) matches. |
| `fetch_timeout_s` | number ≥ 0 | `300` | Seconds before a `git fetch` is abandoned. Network-level failures are collected and can stop the sweep. |
| `command_timeout_s` | number ≥ 0 | `120` | Seconds before any other git command is abandoned. |
| `delay_between_repos_s` | number ≥ 0 | `0.5` | Pause between consecutive fetches. |
| `update_submodules` | boolean | `true` | Run `git submodule update --init --recursive` after a successful update. |
| `require_git_lfs_for_lfs_repos` | boolean | `true` | Skip repos whose tracked `.gitattributes` uses `filter=lfs` when Git LFS is not installed or not enabled (`git lfs install`). |
| `log_dir` | string | `"logs"` | Where reports are written. Relative paths resolve against the project root. It must be writable and have at least 16 MiB free. |
| `background_mode` | boolean | `false` | Keep running in the system tray when the window is closed. |
| `auto_refresh_s` | integer (`0` or 300–86400) | `0` | Automatic **status** refresh interval. `0` is off; 1–299 clamp to 300, above 86400 clamps down. |
| `auto_refresh_pause_when_hidden` | boolean | `false` | Stop automatic status refresh while the window is closed to the tray or minimized. The next check runs when the window returns, if the interval is due. |
| `log_retention_days` | integer ≥ 0 | `30` | Delete timestamped run logs older than this after each run. `0` keeps forever; `latest.*` and `.lock` are never deleted. |

Unknown keys are reported on stderr and ignored, so a newer config does not break
an older checkout.

## Log retention

Only top-level `logs/YYYYMMDD-HHMMSS[-ffffff]-<mode>.log` files are eligible
for deletion. `latest.log`, `latest.json`, `.lock`, unrelated files, and
symlinks are never touched. Pruning runs after the new run's log and both
`latest` files are written, so a failed write never destroys old evidence.
Run names use microseconds, with a numeric suffix if a timestamp still
collides.

## Automatic refresh

`auto_refresh_s = 0` disables it. Values 1–299 are clamped to 300 s and values
above 86400 s are clamped down. When enabled, only a **status** run (fetch and
preview) is started; sync is never automatic. Manual runs reset the timer, an
active run is never overlapped, and failures double the next delay up to one
hour. The countdown runs from the last completed check; showing or hiding the
window, changing the interval, or saving another setting does not restart it.
The GUI edits minutes, warns below 15 minutes, and uses a hard 5-minute floor.

A status run reads each repository's `.git` directory and may wake a spinning
hard disk, whether it is internal or external. SSDs and NVMe drives do not have
that spin-up cost. Automatic refresh is off by default for that reason. If the
watched root is on a hard disk, prefer an interval measured in hours and use
**Refresh status** when you sit down; repopull does not change the disk's
power-management settings.

`auto_refresh_pause_when_hidden = true` stops the automatic timer when the
window is closed to the tray or minimized. No automatic fetch, network retry, or
resume check runs while hidden. When the window returns, the remaining interval
continues, and one check runs if it is already due; a manual run from the tray
or window still works at any time. The setting is off by default and only
affects automatic runs.

A DNS, connection, proxy, reset, or timeout failure is treated as a network
outage. Two consecutive such failures stop the sweep; the remaining
repositories are reported as not attempted instead of each waiting for its own
timeout. One failure is recorded but does not stop the other repositories. Automatic
retries then use a short ladder: 2, 5, 15, 30, and 60 minutes. A successful run
returns to the normal interval, so a reconnect is picked up within two minutes
without hammering a long outage.

## Environment variables

| Variable | Effect |
|---|---|
| `REPOPULL_HOME` | Project root. Set by `bin/repopull`; override to run from another location. |
| `REPOPULL_CONFIG` | Config file path, between `--config` and `REPOPULL_HOME/config.toml`. |
| `NO_COLOR` | Disable ANSI colour when set to any value. |
| `GIT_TERMINAL_PROMPT` | Forced to `0` for every git call; an interactive credential prompt cannot hang a run. |
| `GIT_ASKPASS` | Forced to `/bin/true` for every git call. |

Repo-locating variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, and the
object/config equivalents) are removed before every git call, so launching
repopull from a Git hook or IDE cannot redirect it to another repository. Git
hooks and `core.fsmonitor` are disabled for these calls; URL userinfo in git
errors is replaced with `***` before it reaches a log. On Linux, git is launched
through `setpriv --pdeathsig TERM` when `setpriv` supports it, so a SIGKILL of
repopull also terminates git; otherwise the direct launch is used.

## Command line

```
repopull [global options] [command] [command options]
```

Global options may appear before or after the command:

| Option | Meaning |
|---|---|
| `--root PATH` | Override the watched root. |
| `--config PATH` | Use this config file. |
| `--no-color` | Disable colour. |
| `--json` | Emit JSON instead of a table (status and sync). |
| `--verbose` | Print per-repo progress to stderr. |

Commands:

| Command | Behaviour |
|---|---|
| *(none)* | Interactive menu. Holds the run lock. |
| `list` | Print discovered labels, no network. |
| `where` | Print the config file, resolved root, its source, whether it exists and is writable, and the repo count. |
| `repair-root` | Show the saved and current watched-filesystem identities without changing anything. |
| `repair-root --yes` | Accept the current identity after checking the preview. |
| `status` | Fetch, then report what a sync would do. Changes no working tree. |
| `sync` | Fetch, then fast-forward every clean, behind repo. |
| `sync --behind` | Sync only repositories the last report found behind; up-to-date ones are not rechecked. |
| `sync --force` | Fetch, then hard-reset selected repos to their upstream. |
| `report` | Print `logs/latest.log`. |
| `version` | Print the version. |

`status` and `sync` accept repeatable `--only GLOB`, matched against the relative
label and the basename:

```bash
./bin/repopull status --only 'craft-*'
./bin/repopull sync --only 'LEAP*'
./bin/repopull sync --only AppGlider --only fieldcraft
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No errors. Skips are fine. |
| `1` | At least one repository ended in `error`. |
| `2` | Fatal: bad config, missing root, no repos, or the lock is held. |

## Examples

```toml
# Skip a corpus you never read.
ignore = ["photocraft-corpus"]

# Be extra gentle on a shared connection.
delay_between_repos_s = 2.0
fetch_timeout_s = 600

# Keep submodules frozen.
update_submodules = false
```

```bash
# Machine-readable summary for a timer or notification.
./bin/repopull --json sync | jq '.totals'

# Inspect a single repo without touching anything.
./bin/repopull status --only egui
```
For the full documentation index, see [README.md](../README.md#documentation-index).
