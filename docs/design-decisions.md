# Design decisions

Short records of the choices that shape `repopull`, and why they were made.

## 1. Pull-only, by construction

**Context:** The user owns none of the watched repositories and contributes to
none of them.

**Decision:** The tool has no push, commit, branch, tag, or PR code path at all.
It fetches and moves branches forward. `git clean` is never invoked.

**Consequences:** The tool is safe to run unattended. Force sync can still discard
local state, so it is always explicit and confirmed.

## 2. Python 3.11+, standard library only

**Context:** The user wants something easy to update and maintain, with type
annotations.

**Decision:** One typed Python package, no runtime dependencies. `mypy --strict`
is the only development dependency.

**Consequences:** No virtualenv to manage, no supply-chain surface, and the code
runs with the system `python3`. The trade-off is a text UI rather than a GUI,
which matches the "run it in a terminal" requirement.

## 3. Skip dirty repositories by default

**Context:** One watched repo (`egui`) currently has a modified tracked file, and
the user never edits these copies.

**Decision:** A normal sync skips any repo with tracked modifications and reports
it. Force sync resets it.

**Consequences:** A sync can never silently destroy a file. The cost is that a
dirty repo stays stale until the user looks at it or forces it. Untracked files
are ignored entirely, because build artefacts are normal and must survive.

## 4. Fast-forward by default; hard reset only on force

**Context:** Local commits are "incidental", but silently rewriting history is a
sharp edge.

**Decision:** Normal sync uses `git merge --ff-only`. Diverged repos are skipped
with a reason. Force sync uses `git reset --hard` on explicitly selected repos
after a typed confirmation.

**Consequences:** The default is non-destructive; the destructive path exists and
is one menu choice away. A force-pushed remote leaves a stale copy until the user
chooses force, which is the intended safety trade-off.

## 5. Sequential fetches with a delay

**Context:** Dozens of repositories on a shared network. The user asked not to
hammer GitHub.

**Decision:** One fetch at a time, `0.5 s` default pause, no retries, per-command
timeouts. A failure is recorded and the sweep continues.

**Consequences:** A full run is slower than a parallel one but predictable and
polite. The delay and timeouts are configurable.

## 6. Skip LFS repos when Git LFS is not ready

**Context:** `egui` tracks PNGs through LFS. A checkout without LFS writes pointer
text into the working tree, and having the binary on `PATH` is not enough:
`git lfs install` must also write the `filter.lfs.*` configuration.

**Decision:** Detect `filter=lfs` in tracked `.gitattributes`; require both the
`git-lfs` binary and the effective LFS filters. Otherwise skip the update and
report which of the two is missing.

**Consequences:** The repo is stale but intact. The GUI offers a read-only
**Git LFS** help dialog with the install command for the detected distribution
and `git lfs install`; it never installs or runs anything. Installing and
enabling LFS makes the repo syncable with no config change. This is better than a
"successful" pull that silently replaces images with 130-byte pointers.

## 7. Update submodules after a successful pull

**Context:** `VoiceStudio` declares a submodule (`omnivoice-gallery`).

**Decision:** When `.gitmodules` exists and `update_submodules` is true, run
`git submodule update --init --recursive` after the branch update. A failure is a
warning on an otherwise updated row.

**Consequences:** Watched repositories are complete mirrors, not just top-level
checkouts. The extra network calls are bounded and configurable.

## 8. Discover at depth 1–2

**Context:** `LEAP 71/` is a container folder holding four repositories, and its
name contains U+202F (a narrow no-break space).

**Decision:** Walk to `max_depth` (default 2), treat `.git` (file or directory) as
a repository marker, never descend into a repository, and handle paths with
`pathlib` rather than string manipulation.

**Consequences:** All repos are found, including the nested LEAP ones. The
depth is configurable if the layout changes.

## 9. Never `git clean`

**Context:** Watched repos accumulate build outputs and caches.

**Decision:** Untracked files are never deleted.

**Consequences:** Force sync reclaims tracked state but leaves build artefacts.
This is the conservative choice for a backup disk.

## 10. One run at a time

**Context:** A menu, a manual command, and a future timer can overlap.

**Decision:** `flock` on `logs/.lock`; a second run exits 2 with a clear message.

**Consequences:** No interleaved fetches or half-written reports. The lock is
released automatically when the process exits.

## 11. Counts-only brief

**Context:** Dozens of repos produce a lot of output.

**Decision:** One row per repo with status, commit count, and a short reason;
totals; an "Attention" list for skips and errors. No commit subjects or diffs.

**Consequences:** The brief is scannable in seconds. Users who need detail read
the log or the repo. `--json` provides the same data for scripts.

## 12. Report empty clones, do not repair them

**Context:** An empty clone (AniCraft at the time; later deleted) has no commits,
no refs, no objects — an interrupted clone.

**Decision:** Detect an unborn HEAD and report `empty repository: no commits
(incomplete clone?)`.

**Consequences:** The user gets a clear, actionable message instead of a cryptic
`rev-parse` failure. Repair (re-clone or fetch + reset) is left to the user,
because it is a one-off structural fix, not a sync.

## 13. Global flags parsed separately

**Context:** `argparse` subparsers reset inherited defaults, so `status --verbose`
would either fail or silently clobber a pre-command `--verbose`.

**Decision:** Parse global options with a separate `parse_known_args` pass, then
parse the command from the remainder.

**Consequences:** `--root`, `--config`, `--json`, `--verbose`, and `--no-color`
work on either side of the subcommand, with no duplicated defaults.

## 14. The GUI is a thin optional layer

**Context:** The user wanted a desktop interface after seeing AppGlider's.

**Decision:** PySide6 lives in `src/repopull/gui/` and calls the same
`status_report()` / `sync_report()` functions as the CLI. The core stays
standard-library only; PySide6 is an optional extra (`repopull[gui]`).

**Consequences:** The CLI and GUI cannot drift apart, and the GUI can be omitted.
The cost is a large optional dependency and a Qt-typed module that needs a scoped
mypy override because PySide6 ships no `py.typed` marker.

## 15. AppImage config lives outside the image

**Context:** An AppImage is a read-only squashfs mount, so `config.toml` and logs
cannot live inside it.

**Decision:** `AppRun` sets `REPOPULL_HOME` to
`${XDG_CONFIG_HOME:-$HOME/.config}/repopull`, copies a bundled default
`config.toml` on first run, and keeps logs there. `REPOPULL_HOME` overrides the
location.

**Consequences:** Settings and logs survive an image replacement, and the same
config is used by the CLI. A new install has no watched folder and asks for one.

## 16. A repository's row appears as soon as it is decided

**Context:** The first GUI fetched every remote before classifying any of them,
so all chips changed at once at the end of the sweep.

**Decision:** `status_report()` and `sync_report()` process one repository
end-to-end (fetch, re-inspect, classify, apply) and call an optional `on_row`
callback immediately. The GUI updates that row in place.

**Consequences:** The window is useful during a 60-second sweep instead of only
after it. The final `Report` and the logs are unchanged.

## 17. `latest.json` is a per-repository snapshot

**Context:** "Sync this repo" runs one repository and returns a one-row report.
Replacing `latest.json` with it made every other status chip disappear, both
immediately and on the next launch.

**Decision:** `write_log()` merges a run's rows into the previous
`latest.json` by label. The timestamped log remains exactly that run.

**Consequences:** A partial sync updates one row and preserves the rest. Stale
labels from a removed repository can remain in the snapshot; the GUI ignores
labels it did not discover.

## 18. No watched folder is baked into the app

**Context:** Publishing the AppImage would otherwise ship the developer's
`/run/media/...` path to every user.

**Decision:** `Config.root` is optional. The AppImage ships
`packaging/default-config.toml`, which has no root. The GUI shows "No watched
folder configured" and Settings asks for one; the CLI prints the same advice and
accepts `--root`.

**Consequences:** The build is portable. A first run has no repositories until
the user chooses a folder, which is the correct trade-off for a shared image.
The development `config.toml` keeps this machine's path for convenience.

## 19. Two sync paths: recheck all, or trust the last check

**Context:** "Sync all" contacts every remote, including repositories the last
check marked up-to-date. The user asked whether that rechecking can be avoided.

**Decision:** Keep `Sync all` as the correct full sweep. Add a fast path —
**Sync these** in the GUI banner and `sync --behind` in the CLI — that selects
only rows the last report marked behind. Both are labelled "from the last check".

**Consequences:** A full sweep is the safe default; a remote may have moved since
the last report. The fast path skips up-to-date repositories entirely, but it can
miss a change that happened after the last check. Refresh status first when in
doubt.

## 20. Semantic version bumps, not a hidden build counter

**Context:** Several rebuilds kept the same `0.1.0` name, so an installed copy
could not tell builds apart.

**Decision:** The version lives in `pyproject.toml` and
`src/repopull/__init__.py`. `make bump` increments it (patch by default;
`PART=minor` or `PART=major`), and `make release` runs the checks, bumps the
patch, and rebuilds. The AppImage name carries the version. `CHANGELOG.md` records
user-visible changes.

**Consequences:** Each release has a distinct, meaningful identity. A local
rebuild of the same version is still possible with `make appimage`; bump before
publishing.

## 21. Branches at every icon size

**Context:** The first icon pass used a branchless blue/white caption at 16–24
px. It was legible, but it dropped the Convergence branches, and the sidebar
read as a download/tray icon rather than the chosen mark.

**Decision:** Keep B1t's branches at every size. 32–512 px use the standard mark;
16–24 px use an optical B1t cut with thicker, lighter branches and a slightly
larger mark. The sidebar uses the full mark at 28 px. There is no branchless
caption.

**Consequences:** The small icon is softer than the caption but recognizably the
same mark, so the brand stays consistent. The 16 px icon is the compromise: it
keeps the branches at the cost of some clarity. Assets and regeneration are in
[branding.md](branding.md).
## 22. Retention by age, not run count

**Context:** Every status or sync writes a timestamped run log. Without a policy,
`logs/` grows forever. A run-count cap would keep stale logs for a light user and
erase useful history for a busy one.

**Decision:** Keep run logs for `log_retention_days` (default 30; `0` keeps
forever). Prune timestamped logs after a successful write. Only
`YYYYMMDD-HHMMSS-<mode>.log` is eligible; `latest.log`, `latest.json`, `.lock`,
unrelated files, and symlinks are never touched.

**Consequences:** Old run logs expire by default; the setting can disable it and
is exposed in the GUI's Storage section. The latest snapshot and lock survive, so
the GUI and a running sync are unaffected. See
[configuration.md](configuration.md#log-retention).

## 23. Automatic refresh is status-only and floor-limited

**Context:** A resident app could fetch the watched repositories indefinitely.
That is a load on third-party servers and could overlap a manual status or sync.

**Decision:** `auto_refresh_s` is off by default (`0`). When enabled it is
status-only, never syncs, never overlaps another run, and resets after any
manual run. The hard floor is 300 s, the GUI presets 900 s, and the GUI warns in
orange below 900 s. Failures back off exponentially to one hour; jitter prevents
lockstep fetches.

**Consequences:** The default is respectful and quiet. Users who want freshness
opt in and cannot accidentally choose a sub-5-minute cadence. A CLI run holding
the lock simply postpones the next auto attempt. See
[configuration.md](configuration.md#automatic-refresh).

## 24. Close-to-tray is opt-in and quits gracefully

**Context:** Automatic refresh only helps if the app can outlive its window. A
process that quits immediately on close cannot keep a schedule; a process that
never quits needs a reliable exit and a visible control.

**Decision:** `background_mode = false` by default. The symbolic tray icon is
created whenever the app runs and the tray is available; `background_mode`
controls only whether closing hides to it. The tray has Open, Refresh status
now, Pause/Resume automatic refresh, and Quit. Quit cancels the active run, waits for
the current repository, releases the locks, and then exits. The GUI is
single-instance. With background mode off, closing quits.

**Consequences:** No surprise resident process on first run. Normal minimize
stays in the taskbar; only close goes to the tray. The user always has an
explicit Quit path. See [gui.md](gui.md).

For the full documentation index, see [README.md](../README.md#documentation-index).
