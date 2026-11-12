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

**Decision:** One fetch at a time, `0.5 s` default pause, no retries within a
sweep, and per-command timeouts. A failure is recorded and the sweep continues.
(Automatic status refresh later got its own retry ladder in decision 26.)

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
released automatically when the process exits. Root-state writes are atomic and
last-writer-wins; they do not participate in this lock except `repair-root`,
which takes it as a mutating command.

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
now, Pause/Resume automatic refresh, and Quit. Quit cancels the active git
command, waits for the worker to unwind, releases the locks, and then exits.
A cancelled git command can leave the current repository locked or partially
checked out; the next run reports it rather than forcing a repair. The GUI is
single-instance. With background mode off, closing quits.

**Consequences:** No surprise resident process on first run. Normal minimize
stays in the taskbar; only close goes to the tray. The user always has an
explicit Quit path. See [gui.md](gui.md).

## 25. A suspend resumes with one settled status check

**Context:** A laptop may sleep for hours. The scheduler must not queue every
missed interval, must not start while the network is still coming back, and must
not treat a wall-clock jump as elapsed work. CPU load and network throughput are
tempting readiness signals, but both can be idle while the link is unusable, and
waiting for "calm" can be indefinite.

**Decision:** On Linux, detect a suspend by comparing `CLOCK_BOOTTIME` with
`CLOCK_MONOTONIC`; the difference is the time spent suspended. A gap of 5 s or
more is a resume; platforms without `CLOCK_BOOTTIME` simply skip the gate. When
automatic refresh is on, cancel the pending timer, wait a fixed 60 s settle
period, then run one status check. An in-flight run finishes first. We do not
gate on CPU load, Wi-Fi traffic, or NetworkManager state: a fixed grace is simple
and deterministic, and the normal fetch timeout plus failure backoff covers a
network that is still down.

**Consequences:** A wake produces one resume check, not a catch-up sweep. The
check lands about 60–90 s after wake (30 s poll plus 60 s grace), and it may still
fail if the network is not back; the usual backoff applies. The trade-off is a
short stale window instead of a burst of fetches.

## 26. Network failures stop the sweep and use a short retry ladder

**Context:** A long Wi-Fi drop or a blackholed connection can make every
repository pay its own fetch timeout. Retrying only at the normal 15-minute (or
longer) interval also leaves a restored connection idle for too long.

**Decision:** Classify DNS, connection, proxy, reset, and timeout failures as
network outages. Stop the sweep after two consecutive failures (one bad remote
should not starve the rest); mark the remaining repositories "not attempted:
network unavailable". Automatic retries use 2, 5, 15, 30, and 60 minutes, with
jitter, and a successful run returns to the normal interval. Manual runs still work and reset the ladder. The fetch timeout still
bounds a single attempt.

**Consequences:** A long outage costs two failed fetches, not one timeout per
repository, and a reconnect is normally picked up within two minutes. A very
long outage settles at one attempt per hour. A single bad repository is
recorded but does not stop the others; two in a row stop the sweep, and the
next retry rechecks them. A manual run is always available. See [configuration.md](configuration.md#automatic-refresh).

## 27. Git hooks and fsmonitor are disabled

**Context:** A watched repository's local `.git` metadata is trusted by Git.
Hooks and a configured `fsmonitor` can execute commands during fetch, merge, or
status. A mirror should not run third-party hooks just to update a checkout.

**Decision:** Every git call uses `-c core.hooksPath=/dev/null` and
`-c core.fsmonitor=false`. Repo-locating and config-injection `GIT_*` variables
are removed from the child environment.

**Consequences:** Local hooks no longer fire during a repopull run, including
hooks a user may have installed in a watched repo. LFS smudge filters and
submodule commands still run; this is not a full sandbox. It closes the easiest
local-code-execution path without changing the fetch/fast-forward contract.
On Linux, when `setpriv` is available and supports `--pdeathsig`, git is launched through `setpriv --pdeathsig TERM -- git`, so a
SIGKILL of repopull sends SIGTERM to git as well. It does not necessarily reach
processes git forked; that residual gap is accepted and recorded in
[hardening-backlog.md](hardening-backlog.md). Without `setpriv`, git itself can
also survive the parent. See
[configuration.md](configuration.md#environment-variables).

## 28. Discovery is asynchronous and remembers the root filesystem

**Context:** `os.walk()` on a removed USB mount can block the UI thread. A
path-only root check also cannot tell that a different disk was mounted at the
same path. The CLI has the same path problem without a UI to freeze. `st_dev`
is not a stable disk identity: btrfs and other filesystems can use an anonymous
`0:N` device, and the number can change across reboots while the same disk stays
mounted at the same path.

**Decision:** The GUI scans in a `QRunnable` and checks the saved root state in
that worker, then reports back through Qt signals; the empty view says
"Scanning the watched folder…" until it finishes. On the first healthy
discovery, `logs/root-state.json` records the path, filesystem UUID, mount source, device number, and repository count. The UUID is the
identity; the device number is only a fallback when no UUID is available. A
later different UUID, or an empty root that was non-empty, is refused. Repair is
offered only when the current root still contains a repository, so an empty disk
cannot replace a positive saved count and disable the empty-root guard.
Malformed, unreadable, and newer-version state files are refused rather than
overwritten. Legacy state files without a UUID use the device fallback once,
then are rewritten with the UUID after a successful check. The GUI offers
**Repair saved root state** for a mismatch, and the CLI offers
`repopull repair-root` (preview) and `repopull repair-root --yes` (accept).

**Consequences:** A reboot no longer looks like a disk replacement just because
an anonymous device number changed. A real replacement is still refused when
the UUID differs. The state is written from the identity that was checked, so a
remount between check and write cannot silently bless a different disk; a
transient UUID lookup failure preserves the previous UUID instead of falling
back to device-only comparison. A legacy state file can require one repair after
its first device change; the repair dialog shows both identities so the user can
confirm the disk. The state file lives with the logs, so it cannot detect a
change if the log directory is on the same missing disk. Smoke tests and
screenshots keep synchronous discovery so their output stays deterministic.

## 29. Remember the last GUI page and filter

**Context:** The GUI is a monitor used over many sessions. Always reopening on
an unfiltered All view loses the user's working context, especially when they
left it watching the Behind or Errors view or had Settings open.

**Decision:** Persist the page (`library`, `settings`, or `detail`), sidebar
filter, and detail label in `ui-state.json` next to `config.toml`. Save on every
navigation, not only on quit, so a crash or task-manager kill retains the last
view. Restore the filter and Settings page immediately; restore a detail page
only if its repository is still present, otherwise fall back to the library.

**Consequences:** Relaunching returns to the working view without hiding the
primary library behind a stale detail page. The state file is small and
best-effort; a malformed or unwritable file is ignored. It is deliberately not
in `config.toml`, so UI preferences do not become operator configuration.

## 30. Settings uses a section rail and a hybrid save model

**Context:** The Settings page had grown to five groups in one long form. At the
default 720 px window, Network, Updates, and Storage were below the fold; the
form labels inherited the group-box muted colour and read as disabled; and
Check folder sat below the Save footer, away from the path it checks. AppGlider
uses a compact section rail, one concept per page, and title/hint rows.

**Decision:** Give Settings a 140 px local section rail with five sections:
Watching, Refresh, Network, Updates, and Storage. Each section is a card of
title/hint/control rows, with a shared scroll for short windows. The footer
button reads **Saved** when clean and **Save unsaved settings** when deferred
edits exist; it turns amber for unsaved changes and red after a save failure.
Draft edits survive section switches. Refresh keeps its targeted immediate
writer, with switches for the three binary controls and an interval field that
says **Applies and saves immediately**; the other sections commit through
Save. Do not add
AppGlider-style autosave: its `QSettings` store has no user-edited comments to
lose, while `save_config()` rewrites `config.toml` and drops them. Full autosave
would first need a comment-preserving flat-TOML writer.

**Consequences:** At 1040×720 every section fits without scrolling; the shared
scroll covers unusually small windows or large text. The mixed save model is now
visible in the controls themselves: switches and the interval save immediately,
while the footer button owns the deferred sections. Quitting with unsaved
changes still discards them; a prompt would be a separate change. The section
rail adds a second 140 px column, leaving enough width for path fields at the
minimum window size. See [gui.md](gui.md#settings).

## 31. LFS status is rechecked on demand, not watched

**Context:** Installing `git-lfs` while the GUI is already running does not
change the status line until something reads the environment again. A file
watcher on `PATH` or a polling timer would keep the window updated
automatically, but both add machinery for a rare event and can keep the process
busy for no user-visible gain.

**Decision:** Re-read LFS status when Settings is shown, when the main window
becomes active with Settings open, after a run, or with the **Check again**
button, but only until the status is both installed and enabled. Once ready, the
result is kept for the rest of the session; **Check again** is the escape hatch,
and a new launch checks once. There is no background watcher, no extra timer,
and the check does not touch the watched repositories or their disk.

**Consequences:** Installing or enabling `git-lfs` is picked up as soon as the
user returns to the app with Settings open, opens Settings, or finishes a run.
Once ready, there are no further reads during that session. Removal or a version
change is not noticed until **Check again** or the next launch; that is the
deliberate trade-off for not polling. The normal cost is a `which` lookup when
LFS is absent; checking enabled state reads Git's system and global config only.
See [gui.md](gui.md#settings).

## 32. Automatic refresh can pause while the window is hidden

**Context:** A watched root on a spinning hard disk is woken by every status run;
the cost applies to internal and external HDDs, not to SSDs or NVMe drives. With
background mode and a short interval, a tray-only app can keep spinning the
drive up while nobody is using it. The user should be able to keep automatic
freshness while the window is open without paying that cost all day.

**Decision:** Add opt-in `auto_refresh_pause_when_hidden`. When enabled, the
automatic timer stops whenever the main window is not visible or is minimized.
No automatic fetch, network retry, or suspend-resume check starts while hidden.
When the window returns, the remaining interval continues; if it is already
due, one check runs. Manual runs from the window or tray are unaffected,
and an in-flight run is allowed to finish. The default is `false`, so existing
behavior is unchanged.

**Consequences:** A background repopull can now stay in the tray without waking
a spinning hard disk, at the cost of stale data until the window returns or a
manual refresh is requested. Minimized windows count as hidden; otherwise
minimizing would bypass the option. The setting lives in `config.toml` beside
the other refresh behavior and is written immediately, like background mode.
See [configuration.md](configuration.md#automatic-refresh) and
[gui.md](gui.md#settings).

## 33. Automatic-refresh decisions are a pure table

**Context:** The automatic timer has to account for visibility, the
pause-when-hidden option, manual pause, suspend/resume, an in-flight run, a
network retry ladder, the remaining cooldown, and an empty repository list.
Those conditions had spread across `_schedule_auto_refresh`,
`_auto_refresh_due`, and `_resume_after_visible`, making the combined behavior
hard to see and easy to regress.

**Decision:** Move the decision into `refresh.py` as a pure
`decide_refresh(state, event)` function with three events (`SCHEDULE`, `TIMER`,
`SHOW`) and three actions (`STOP`, `WAIT`, `RUN`). `MainWindow` builds a
`RefreshState` snapshot and applies the decision; it no longer duplicates the
conditions. `SCHEDULE` waits only the remaining interval instead of restarting
it, `TIMER` rechecks the cooldown and runs when due, and `SHOW` catches up only
when pause-when-hidden is on and the interval is already due. A pending resume
leaves the grace timer alone; no repositories waits for the interval or network
retry, not a tight loop.

**Consequences:** The decision table is exercised directly without Qt or real
timers, and future refresh changes have one place to reason about. The window
still owns the timers and the run itself, so the seam is the state snapshot and
the three actions. See [configuration.md](configuration.md#automatic-refresh)
and [gui.md](gui.md#settings).

## 34. Rows show state in the chip and numbers in the subtitle

**Context:** The row chip carried commit counts (`↑ 233 behind`, `✓ 17 updated`)
and also had to carry new per-repository policy labels. Combining a policy and a
count in a fixed 152 px chip forced awkward abbreviations, and a successful sync
left an event (`17 updated`) looking like a persistent state.

**Decision:** The chip carries only a state (`Behind`, `Up to date`, `Skipped`,
`Error`) or a hold (`No checks`, `No sync`, `No checks/sync`). Counts move to the
subtitle, where width is flexible; behind counts keep the chip's orange. A
successful sync renders `Up to date` plus `N commits pulled at last sync`; a force
sync uses its detail (`hard reset to upstream at last sync`). The "at last sync"
phrase is historical, so it needs no expiry timer or per-row timestamp. A held
repository excluded from checks shows no count at all because its row is stale.

**Consequences:** Counts can no longer overflow the chip, and every policy label
fits. Counts are less visually prominent, so behind counts are coloured. The
next check replaces the event text naturally; if an event-aware age is wanted
later, per-row observation timestamps would be required. See
[gui.md](gui.md#what-it-does).

## 35. Bulk-action holds are configuration, not UI state

**Context:** Per-repository "skip this in Refresh status / Sync all" switches
change what a run touches. Keeping them in `ui-state.json` would make them
disappear with cosmetic state and would leave the CLI silently disagreeing with
the GUI.

**Decision:** Store exact relative labels in `config.toml` as
`exclude_from_refresh` and `exclude_from_sync`. The repository page saves them
immediately through a comment-preserving updater. Bulk GUI, tray, automatic,
CLI, and menu runs obey them; explicit per-repository actions and `--only`
override them. Holds from checks are treated as stale for totals; holds from
sync remain live because refresh still runs.

**Consequences:** The terminal and GUI agree. Renaming a repository leaves a
stale label, which is harmless but no longer matches; pruning would risk losing
holds while a disk is unmounted. See
[configuration.md](configuration.md#per-repository-holds).

## 36. Root repair revalidates, and state writes are last-writer-wins

**Context:** A repair dialog can sit on screen while the disk is remounted, or
another process can replace `root-state.json`, between the check and the write.
Writing the confirmed-at-the-time identity would then overwrite a newer
observation with a stale one.

**Decision:** `repair_root_state()` re-reads the saved state and the current
filesystem identity immediately before writing. If either differs from the
values shown in the dialog, it refuses and asks for a refresh. Every state write
is still an atomic replace, so readers never see a partial file. Two concurrent
writers are last-writer-wins.

**Consequences:** A stale confirmation cannot silently accept the wrong disk or
replace a newer state. A real concurrent change requires one retry. A writer
that loses the race leaves a complete, readable state behind. See
[hardening-backlog.md](hardening-backlog.md).

## 37. Bundle only the Qt modules the app imports

**Context:** The AppImage shipped every module in the PySide6-Essentials wheel.
That wheel is built for all Qt applications, so it carried QML, Quick, Designer,
type stubs, the bundled pip, and Tk/SQLite from the Python base. The download was
95 MB, about twice AppGlider's 47 MB, even though repopull imports only QtCore,
QtGui and QtWidgets.

**Decision:** The build trims the staged AppDir before packing. It deletes a
fixed list of known-unused trees, keeps the three imported bindings, and walks
the ELF `NEEDED` entries of the retained bindings and plugins to keep exactly the
Qt shared libraries they load. A missing Qt dependency stops the build. Platform
plugins for X11, Wayland, offscreen and minimal stay. The build refuses an image
above 60 MB. A test compares the keep-list with the Qt modules imported under
`src/`, so a new module fails the suite until the trim is updated.

**Consequences:** The AppImage is about 46 MB instead of 95 MB, with no change in
behaviour; all 43 local repositories render under Wayland, X11 and offscreen.
The cost is a build step that must be revisited when a new Qt module is used,
which the import test makes loud. The trim is an independent implementation,
not a copy of AppGlider's GPL code. Third-party notices and the LGPL text ship
inside the image.

## 38. Clone creates a new folder and nothing else

**Context:** Decision 1 keeps repopull pull-only, but a fresh machine or a new
upstream still needs its first copy. Telling the user to run `git clone` by hand
breaks the "one window" workflow and bypasses the app's safety checks.

**Decision:** There is exactly one write path, **Clone…** / `repopull clone`. It
accepts only http(s), ssh, git, file or local-path addresses; rejects `ext::`
and unknown transports, option-like URLs, path separators and traversal in the
folder name; and clones into a hidden `.repopull-clone-*` folder that discovery
ignores. On success it renames the finished checkout into the requested name; on
failure or cancellation it removes the temporary folder. An existing name is
never overwritten. The clone takes the same run lock as sync, runs without
credential prompts, and is bounded by `clone_timeout_s`.

**Consequences:** A first mirror can be created without leaving the app, and an
interrupted clone never appears as a broken repository. Existing repositories
are still never written to, so the pull-only guarantee holds. Private remotes
need an SSH agent or credential helper, and submodules initialize on the first
sync rather than during the clone.

## 39. Stream clone progress without a second kill path

**Context:** `git clone` writes its progress to stderr, and `run_git` captured
it whole, so the GUI could only show an indeterminate bar for the length of a
clone. The obvious fix — open a `Popen` inside `clone.py` and read the pipe
there — would fork the timeout, cancellation, and process-group termination
logic that the hardening pass exists to keep in one place.

**Decision:** `run_git` takes an optional `on_stderr` callback. Without it,
every command keeps the original captured wait unchanged. With it, a selector
over the pipe descriptors reads fragments as they arrive, splits on CR as well
as LF because git rewrites its progress line in place, and calls the same
`_terminate_process_group` on cancel or timeout. `clone.py` owns the parsing: it
maps git's per-phase percentages onto one 0–100 scale and ignores anything that
is not a progress line. The GUI forwards only changes in the overall figure; the
CLI draws only when stderr is a terminal.

**Consequences:** A clone is observable while it runs, and the kill/reap path
still exists once. Progress stays a display concern: a bad parse cannot change
the clone's outcome, and failing to read progress cannot block the transfer. A
local clone that git serves with hardlinks reports only start and finish,
because git emits nothing in between.

## 40. Pin CI inputs by SHA; keep the published artifact off CI

**Context:** The workflow called `actions/checkout@v7` and
`actions/setup-python@v7`. A tag is a pointer that its owner, or whoever
compromises the owner, can move to a different commit after review, so a
reviewed workflow can later run unreviewed code. `pip install mypy` and
`pip install pip-audit` had the same problem one layer down: they executed
whatever PyPI served on the run's date. GitHub added workflow lockfiles in
October 2026, which keeps readable `vX.Y.Z` references and records the resolved
commit in a separate file.

**Decision:** Pin both actions to a full commit SHA with the release tag in a
trailing comment. The comment is what makes the pin reviewable, and it is what
Dependabot rewrites, so the pins do not rot. CI tools move into
`packaging/ci-requirements.txt` at exact versions, and the project install takes
`runtime-requirements.txt` as a constraint so both legs exercise the PySide6
version the image ships. `persist-credentials: false` keeps the read token out
of `.git/config`. Skip the lockfile for now: with two actions, no reusable
workflows, no composite actions and no Docker references, the machinery adds a
generated file and a verification job to solve a problem two comments solve.

**Consequences:** A moved tag or a hostile publish cannot change what CI runs,
and a PySide6 bump inside the allowed range no longer changes it either. The
cost is that CI now tests the shipped binding rather than the newest one, so
widening the `>=6.8,<7` range needs a manual check instead of showing up as a CI
surprise. What none of this protects is the artifact, because CI does not build
it: `make appimage` runs locally from `downloads.json`, whose three inputs are
verified against pinned SHA-256 digests. A runner compromise can therefore make
a check lie, but it cannot change the AppImage a user downloads, and the job
holds no secret that could be taken.

For the full documentation index, see [README.md](../README.md#documentation-index).
