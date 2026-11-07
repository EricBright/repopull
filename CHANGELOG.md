# Changelog

## 0.4.12 — 2026-11-07

- Replaced the three immediate Refresh checkboxes with animated switches. Off
  is a muted track with a left thumb; on is an accent-blue track with a right
  thumb. The off state does not fade the label.
- Redesigned the deferred-save control: **Saved** when clean, amber **Save
  unsaved settings** when dirty, and red **Couldn't save — Retry** after a
  failure. The duplicate header status is gone.
- The interval field keeps a single **Applies and saves immediately.**
  hint; the shared Refresh note is removed. Other sections have no save hint.

## 0.4.11 — 2026-11-07

- Automatic refresh now waits only the time remaining since the last completed
  run. Showing or hiding the window, changing the interval, or saving an
  unrelated setting no longer restarts the full countdown; an overdue check
  runs promptly. This also removes a one-millisecond timer loop when the
  repository list is empty.
- Clarified the Settings hint: background and refresh changes save and apply
  immediately, so **Save settings** stays disabled for them.
- Added a next-check line to Settings → Refresh and the tray tooltip, so the
  countdown is visible instead of inferred from a disabled Save button.

## 0.4.10 — 2026-11-06

- Refactored automatic-refresh decisions into a pure `decide_refresh` table in
  `refresh.py`. Behavior is unchanged; the hidden, pause, cooldown, network,
  in-flight, resume, and no-repository cases now have direct tests.

## 0.4.9 — 2026-11-06

- Stop re-reading Git LFS after it is installed and enabled. **Check again** or
  a new launch re-reads it; there is no polling.
- Clarified the automatic-refresh hint: a check may wake a spinning hard disk,
  whether internal or external; SSDs and NVMe drives do not have that cost.

## 0.4.8 — 2026-11-06

- Recheck Git LFS status when Settings is shown, when the app window becomes
  active with Settings open, after a run, or via the new **Check again** button.
  The check is event-driven; there is no background filesystem watcher and no
  new timer.
- The automatic-refresh interval hint now notes that each check may spin up an
  external drive.
- Added opt-in **Pause while hidden**: automatic status refresh stops when the
  window is closed to the tray or minimized, and catches up when the window
  returns. Manual runs still work; in-flight runs finish.

## 0.4.7 — 2026-11-06

- Rebuilt the GUI Settings page as five sections (Watching, Refresh, Network,
  Updates, Storage) with a local section rail, title/hint rows, and a sticky
  Save/Reset footer. Every section fits without scrolling at the default window
  size; draft edits survive switching sections.
- The Settings header now shows **Unsaved changes** or **All changes saved**,
  and Save is disabled when clean. Refresh changes still apply immediately.

## 0.4.6 — 2026-11-06

- Remember the last GUI page, sidebar filter, and detail repository across
  launches in `ui-state.json`; a missing detail repository falls back to the
  library.
- Moved the README Troubleshooting and Limitations sections into
  [docs/troubleshooting.md](docs/troubleshooting.md) and
  [docs/limitations.md](docs/limitations.md), and registered both in the
  documentation index.

## 0.4.5 — 2026-11-06

- Removed the duplicate numeric commit column from library rows. The status
  chip now carries the count for both behind and updated rows, with comma
  separators for large values.
- All status chips use one fixed width, so counts no longer resize the row.

## 0.4.4 — 2026-11-06

- Detect resume from suspend with `CLOCK_BOOTTIME` versus `CLOCK_MONOTONIC`;
  wait 60 seconds for the desktop and network to settle, then run one status
  check instead of queueing missed intervals.
- Treat DNS, connection, proxy, reset, and timeout failures as network outages:
  stop the sweep after two consecutive failures, mark the rest not attempted,
  and retry after 2, 5, 15, 30, then 60 minutes.
- Kill the git process group when a command times out or is cancelled, and scrub
  repo-locating `GIT_*` variables before every call. Hooks and `core.fsmonitor`
  are disabled for these calls. A cancelled command may leave a repo locked or
  partially checked out; the next run reports it.
- Launch git through `setpriv --pdeathsig TERM` when available, so SIGKILLing
  repopull also terminates its git process.
- Redact URL credentials from git errors, fsync config writes, and reject a
  watched root that is not writable or has less than 64 MiB free.
- Remember the watched root device and repo count in `logs/root-state.json`;
  refuse a different device or an unexpectedly empty root.
- Put microseconds in run-log names, fall back to a numeric suffix on collision,
  and require 16 MiB free in the log directory.
- Scan the watched root in a background worker in the GUI, and fsync/verify the
  root identity file.
- Refuse an update when the repository path no longer resolves inside the
  watched root.
- Corrected the README and GUI limitations, and added an authorship note.

## 0.4.3 — 2026-11-05

- Background mode and automatic refresh now apply and persist immediately
  when toggled; closing to the tray no longer depends on pressing Save.
  A targeted writer updates only `background_mode` and `auto_refresh_s`,
  preserving other keys and comments.

## 0.4.2 — 2026-11-05

- Fixed the invisible unchecked checkbox indicator in the dark theme; both
  states now have an explicit border/fill and the checked state uses a
  generated checkmark.
- Escaped the `&` in the Background & refresh group title so Qt displays it
  literally instead of treating it as a mnemonic.
- The interval field is always editable; changing it enables automatic refresh
  rather than leaving a disabled-looking control.

## 0.4.1 — 2026-11-05

- Moved Background & refresh above Network and added a tray-availability
  line, so close-to-tray is visible without deep scrolling.
- The tray icon is now created whenever the app runs (when the tray is
  available); background mode only controls whether closing hides to it.
- Prefer Qt Wayland with an XCB fallback on Wayland sessions, so KDE
  Plasma's Wayland tray can show the icon.

## 0.4.0 — 2026-11-05

- Added opt-in resident mode: closing can hide to a symbolic system-tray
  icon instead of quitting. Tray menu: Open, Refresh status now, Pause/Resume
  automatic refresh, Quit.
- Added automatic status refresh, off by default. When enabled it has a
  5-minute hard floor, warns below 15 minutes, only ever runs status, never
  overlaps a manual run, and backs off after errors.
- Added `background_mode` and `auto_refresh_s` config keys and GUI controls.
- Hardened shutdown: cancel active runs, wait for the current repository,
  release locks, and make `latest.log`/`latest.json`/run logs atomic.
- Added a single-instance GUI guard.

## 0.3.0 — 2026-11-05

- Run logs older than 30 days are pruned after each run. `log_retention_days`
  (default 30; `0` keeps forever) is configurable in Settings → Storage.
- Added GitHub Actions CI: `make check` (mypy + tests) on every push and pull
  request.

## 0.2.5 — 2026-11-05

- Restored the B1t branches at every icon size, including 16/22/24 and the
  sidebar. Those sizes use a slightly larger, thicker, lighter B1t cut instead of
  the branchless caption.

## 0.2.4 — 2026-11-05

- Added the Convergence icon: B1t two-tone for 32–512 px and a blue/white
  caption cut for 16–24 px.
- The GUI now sets the window/taskbar icon and desktop file name, and shows the
  mark beside the sidebar wordmark.

## 0.2.3 — 2026-11-05

- Added read-only Git LFS help in Settings and on a repository's page: what LFS
  is, the install command for the detected distribution, and `git lfs install`.
  Nothing is installed or run automatically.
- LFS repositories are now also skipped when `git-lfs` is installed but not
  enabled, not only when the binary is missing.
- The install hint recognizes immutable Fedora (Bazzite/Silverblue/Kinoite) and
  prefers Homebrew when available instead of suggesting `dnf`.

## 0.2.2 — 2026-11-05

- Removed the explanatory note under Settings → Storage → Logs; the row now shows
  the path with a short tooltip.
- Reworded the Settings header to describe the save behaviour rather than the
  GUI/CLI architecture.

## 0.2.1 — 2026-11-05

- The sidebar shows a **Watched folder** link that opens Settings and focuses the
  folder field, instead of spelling out the full path.
- The sidebar shows the running version; the "no API allowance" line was removed
  because `repopull` uses only `git fetch`, never the REST API.
- The Settings page states that the logs path is resolved from
  `$XDG_CONFIG_HOME` at runtime; it is not baked into the image.

## 0.2.0 — 2026-11-05

- Status rows update as each repository is checked, instead of only at the end.
- Settings expanded into Watching (folder, depth, ignore globs), Network (delay,
  timeouts), Updates (submodules, LFS), and Storage, with Reset to defaults.
- Fixed "Sync this repo" wiping every other repository's status chip; partial
  runs now merge into `latest.json`.
- The watched folder is no longer baked in; a new install starts unconfigured and
  asks for one in Settings.
- Added the **Sync these** / `sync --behind` fast path: update only what the last
  check found behind, without contacting up-to-date repositories.
- AppImage: ships a template config, runs natively on Wayland and X11.

## 0.1.0 — 2026-11-05

- Initial CLI, PySide6 GUI, and AppImage.
For the full documentation index, see [README.md](README.md#documentation-index).
