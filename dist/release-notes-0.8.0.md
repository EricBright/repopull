# repopull 0.8.0

This release is about living with the app between runs: completing its
commands, starting it with your session, and telling you when there is a newer
repopull — without ever replacing itself.

## Shell completions

```bash
eval "$(repopull completions bash)"                 # bash
repopull completions fish > ~/.config/fish/completions/repopull.fish
```

Zsh uses `bashcompinit`:

```bash
autoload -U bashcompinit && bashcompinit && eval "$(repopull completions bash)"
```

Commands, global options, per-command options and paths complete. Repository
labels deliberately do not: offering them would scan the watched root on every
TAB, which stalls when it lives on an external disk. Use `--only GLOB` to narrow
a run instead.

## Starting with your desktop

**Settings → Startup** writes or deletes `repopull.desktop` in your autostart
folder, and **Open hidden in the tray** adds `--hidden` so it starts without a
window. The entry is the only record of the setting, so disabling it in your
desktop's own autostart panel shows up as off here, and repopull never
resurrects it.

- The entry points at the running AppImage (`$APPIMAGE`), not at the temporary
  mount that would be gone by the next login.
- If the AppImage moves, the entry is repaired on the next launch; a working
  entry is never repointed just because a different build was launched.
- Without a tray icon, `--hidden` shows the window rather than starting
  unreachable.
- A second launch now brings the running window forward instead of refusing
  with an "already running" dialog, which is what makes a hidden window
  reachable from the launcher.

## Checking for a newer release

```bash
repopull version --check      # exit 3 when a newer release exists
```

The same check is **Check now** under Settings → Startup and "Check for
updates…" in the tray. It reads the GitHub releases API, shows the version and
the release page, and downloads nothing.

Separately, this image now carries `gh-releases-zsync` update information and
ships a `.zsync` beside it, so AppImageUpdate and Gear Lever can update an
installed copy with a delta download instead of fetching all 46 MB again. That
is the intended path for installing a new version: repopull itself only tells
you one exists. An updater that pulls and executes code would be the most
valuable attack surface in a project whose artifact is built by hand and whose
CI holds no secrets, so it stays out until there is a signing key and a stable
installed filename.

## Checks

414 tests pass (1 expected failure for the documented SIGKILL descendant gap),
mypy strict is clean, and `make audit` reports no known vulnerabilities.

**AppImage:** `repopull-0.8.0-x86_64.AppImage`, SHA-256 `0fac3b9b1a6037417a13ea1c546e8bbb7dc105ff428c032ebedad0c2550fc5a8`.
The `.zsync` and `SHA256SUMS.txt` are published beside it.

See [CHANGELOG.md](https://github.com/EricBright/repopull/blob/main/CHANGELOG.md).
