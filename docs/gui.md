# Desktop GUI

`repopull` has an optional PySide6 interface. It reads the same `config.toml`,
the same repositories, and the same `logs/latest.json` as the CLI. A run from
either is visible to the other.

![The repopull library](previews/gui-library.webp)

## Run it

From the project folder:

```bash
./bin/repopull-gui
```

The launcher uses the system `python3` when `PySide6` is importable; otherwise
it lets `uv` provide PySide6 for that run. You can also run
`PYTHONPATH=src python3 -m repopull.gui`.

It runs natively on Wayland and X11; the platform choice is left to Qt.

On first run there is **no watched folder**. Open **Settings** and choose one;
the library then fills. Nothing is hard-coded into the app. The initial scan and its root-state identity check
run in a background worker, so a slow or missing mount does not freeze the
window; the empty view says it is scanning until the result arrives.

If the watched folder now resolves to a different filesystem, the library
explains the mismatch and offers **Repair saved root state**. The confirmation
shows the saved and current filesystem identities; repairing replaces only the
saved identity and does not touch the repositories. If the saved state or the
mounted disk changes while the confirmation is open, repair refuses and asks
for a refresh instead of writing the stale identity. A reboot that changes only
an unstable device number is accepted by the filesystem UUID, so the prompt
should not appear for that case once the state file has a UUID.

The last visited page, sidebar filter, and detail repository are remembered in
`ui-state.json` next to `config.toml`. On launch the filter and page are
restored; a detail page is restored only if that repository is still present.

## What it does

- **Sidebar**: All / Behind / Skipped / Errors with live counts, Settings, a
  **Watched folder** link that opens Settings and focuses the folder field,
  **Last check** and **Next check** lines, the running version, and the mark
  beside the wordmark. All of this text shares one column with the navigation
  labels; the pills keep their inset. The full path lives in Settings and in the
  link's tooltip. **Last check** is the last completed run (a sync also counts);
  **Next check** is clickable and opens the Refresh settings section;
  it shows `off`, `paused`, `when visible`, `after resume`, `after this run`,
  `none included`, or the scheduled wall-clock time. It is an estimate and does
  not tick.

- **Library**: one row per repository with its branch, a fixed-width state chip,
  and a subtitle carrying the number or reason. The chip says what is true
  (`Behind`, `Up to date`, `Skipped`, `Error`) or which bulk action is held
  (`No checks`, `No sync`, `No checks/sync`); numbers live in the subtitle so
  long counts cannot overflow the chip. Behind counts use the chip's orange.
  **Rows update as each repository is checked**, not only when the whole sweep
  finishes. Search filters by label. Returning from a detail page keeps the
  list's scroll position; changing the filter or search starts at the top.

  After a sync that moved commits, the chip is `Up to date` and the subtitle
  reads `main · 17 commits pulled at last sync`. That is history, not a claim
  that the remote has not moved since; the next check replaces it. A force sync
  shows `hard reset to upstream at last sync` instead of a pulled count.

- **Clone…** in the library header asks for a repository URL and a new folder
  name, shows the exact destination, and clones in the background with Cancel.
  The status bar tracks git's phases (`Receiving objects 42% (1,234/5,678)`) on
  one 0–100 scale, so it never jumps back when git moves to the next phase.
  Existing folders are never overwritten. Private remotes need an SSH agent or
  a credential helper because repopull never prompts.
- **Banner**: "N repositories can be updated" with a **Sync these** button.
  When some behind repositories are held out of Sync all, the banner reads
  "N can be updated · M held" and the button updates only the N.
- **Refresh status** fetches and reports without changing any working tree.
- **Sync all** rechecks every remote, then fast-forwards what is behind. This is
  the correct full sweep: a remote may have moved since the last report.
- **Sync these** (the banner button) is the fast path: it updates only the
  repositories the **last check** found behind. Up-to-date repositories are not
  contacted at all. Refresh status first if the last check is old.
- **Detail page** (click a row): path, branch, upstream, ahead/behind, working
  tree, Git LFS, submodules, remote URL, and the last result. **Open folder**
  opens the repository in the desktop's default file manager (Dolphin on KDE);
  it uses the same Qt desktop-open call as the Git LFS help link and does not
  spawn a shell.
- **Bulk actions** on the detail page: two switches, off by default, hold the
  repository out of **Refresh status** and/or **Sync all**. The same holds apply
  to automatic checks, the tray refresh, **Sync these**, and CLI/menu bulk runs.
  An explicit **Sync this repo**, **Force sync…**, or CLI `--only` selection
  ignores the holds because it targets the repository directly.
- **Force sync…** on the detail page resets one repository after a confirmation.

### Bulk-action holds

The two switches on a repository's page are stored immediately in `config.toml`
as exact relative labels (`exclude_from_refresh`, `exclude_from_sync`); they are
not kept in `ui-state.json`, and the CLI reads the same lists.

- **No checks** (excluded from Refresh status) also excludes the repository from
  automatic checks and the tray refresh. Its saved report row is stale, so it
  shows no count and is left out of the Behind/Skipped/Errors totals and views.
- **No sync** (excluded from Sync all) still receives status checks, so its
  behind count stays fresh and remains in the Behind totals. The banner counts
  it as held rather than actionable.
- **No checks/sync** combines both and behaves like No checks for totals.
- Holds affect only bulk actions. Opening the repository and pressing **Sync this
  repo** or **Force sync…** still works, as does an explicit `--only` selection
  in the CLI.

A repository held from checks stays visible under **All** with its gray policy
chip; after a fresh launch it can show `No checks` even without a stored result.

### Settings

Settings has its own section rail beside the settings content. Switching sections
keeps any draft edits, and the whole page fits without scrolling at the default
window size.

| Section | Controls |
|---|---|
| **Watching** | Watched folder with Browse and Check, search depth, ignore globs |
| **Refresh** | Tray switch, automatic status refresh switch, pause-while-hidden switch, interval |
| **Network** | Delay between fetches, fetch timeout, other git timeout |
| **Updates** | Submodules, LFS skip policy, LFS status and Help |
| **Storage** | Config file, logs directory, log retention |

The footer button reads **Saved** when there is nothing to write and
**Save unsaved settings** when deferred edits exist. It turns amber for unsaved
changes and red after a failed save; **Reset to defaults** restores the shipped
values in the form first. Refresh uses switches, and the interval field says
**Applies and saves immediately**. Saving any other change rewrites
`config.toml` and drops hand-written comments.

The logs path is resolved at runtime from `$XDG_CONFIG_HOME` (or `~/.config`).
**Keep run logs** sets `log_retention_days`; `0` keeps every run log.
**Keep running in the system tray** is close-to-tray; the tray icon is visible
whenever the app runs, and its switch controls whether closing hides to it.
Normal minimize stays in the taskbar. **Check folder** also scans in the
background.

**Refresh status automatically** is status-only, off by default, has a 5-minute
hard floor, and shows an orange warning below 15 minutes. The countdown runs
from the last completed check; showing the window or changing the interval does
not restart it. The sidebar, Refresh section, and tray tooltip show the next
scheduled check.
A manual status or sync resets the next automatic run. On Linux, when automatic
refresh is on, a wake from suspend is detected and the app waits 60 seconds for
the desktop and network to settle before running one status check; missed
intervals are not queued. If a run was in flight, that run finishes first. Two
consecutive network-level fetch failures stop that sweep and mark the remaining
repositories "not attempted";
automatic retries are 2, 5, 15, 30, and 60 minutes, so a reconnect is noticed
quickly without repeatedly timing out every repository.

**Pause while hidden** is opt-in. It stops automatic checks when the window is
closed to the tray or minimized, so a background repopull does not wake a
spinning hard disk. Manual runs still work. When the window returns, one check
runs if the interval is due. In-flight runs are not cancelled.

With background mode on, the symbolic tray menu offers Open, Refresh status now,
Pause/Resume automatic refresh, and Quit. Quit cancels the current git command,
waits for the worker to unwind, and releases the locks. A cancelled git command
can leave that repository with a lock or partial checkout; the next run reports
it rather than forcing a repair. A second GUI launch refuses to start.

The **Git LFS** row shows whether `git-lfs` is installed and enabled; **Help…**
explains what LFS is and shows the install command for the detected distribution
plus `git lfs install`. Nothing is installed or run automatically. Until LFS is
installed and enabled, the status is rechecked when Settings is shown, when the
window becomes active with Settings open, and after a run. Once it is ready,
repopull stops rechecking it for that session; **Check again** forces a fresh
read, and the next launch checks once. There is no background filesystem
watcher. The same help appears on a repository's page when LFS is why it cannot
sync.

The window/taskbar icon and the sidebar mark are documented in
[branding.md](branding.md).

![Git LFS help](previews/gui-lfs-help.png)

![Settings with the Watching section selected](previews/gui-settings.png)

## Safety

The GUI calls the same `status_report` and `sync_report` functions as the CLI. It
never pushes, commits, or cleans. A normal run skips dirty and diverged
repositories; Force sync is the only destructive path and asks first. Updates
are refused if the repository path no longer resolves inside the watched root.
The GUI holds the same `logs/.lock` as the CLI, so two runs cannot overlap.

## Limitations

- No desktop notifications.
- No per-repository selection for a normal sync; use Sync all, or Force sync one.
- Saving general settings rewrites `config.toml` and drops hand-written
  comments; background and refresh changes use a targeted writer that preserves
  them.
- General settings are not autosaved. Quitting with unsaved changes discards
  them; the footer button reads **Save unsaved settings** while any are pending.
  Refresh switches and the interval save immediately.
- The window is dark-only.
- Keyboard navigation is basic.

## Window lifetime

The window and its background task are separate. Closing while a run is active
cancels the task, ignores the close, and quits after the task reports; the
window stays alive until then. Worker signals are connected to the window and
auto-disconnect when it is destroyed, so a finished task cannot keep a deleted
window alive. Dialogs are modal and parented to the window, except the
"already running" warning shown before a window exists.

`make soak-qt` creates and destroys the real window 100 times and fails if a
Python wrapper, C++ object, or child widget survives. `tests/test_gui.py` covers
close-while-running, task collectability, and signal ownership.

## Tests

`make test` runs the GUI tests offscreen (`QT_QPA_PLATFORM=offscreen`) and skips
them when PySide6 is absent.
For the full documentation index, see [README.md](../README.md#documentation-index).
