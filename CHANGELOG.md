# Changelog

## Unreleased

- Shell completions for bash and fish: `repopull completions bash` and
  `repopull completions fish` print a script to eval or install. Commands,
  global options, per-command options and paths complete; repository labels do
  not, because offering them would scan the watched root on every TAB.

## 0.7.0 — 2026-11-11

- Clone reports progress. The GUI status bar and `repopull clone` on a terminal
  follow git's phases (`Receiving objects 42% (1,234/5,678)`) on one 0–100
  scale, instead of showing an indeterminate spinner for the whole clone.
- CI pins both actions to a commit SHA and installs its tools from
  `packaging/ci-requirements.txt`, so a moved tag or a bad PyPI publish cannot
  change what a run executes. Dependabot proposes the updates. Nothing about
  the shipped image changes: it is still built locally from checksummed inputs.

## 0.6.0 — 2026-11-10

- Add **Clone…** to the library header and `repopull clone URL [--name NAME]`.
  It clones into a hidden temporary folder, then renames it into place, so an
  interrupted clone is never discovered and an existing folder is never
  overwritten. Only ordinary web, SSH, git, file and local-path addresses are
  accepted; `ext::` and unknown transports are rejected. Clone runs under the
  same lock as sync, can be cancelled, and never prompts for credentials.
- The AppImage is about half its previous size (95 MB → 46 MB). The staged
  AppDir now drops Qt modules, QML assets, designer tools, type stubs,
  translations for unused modules, the bundled pip, and Python's Tk/SQLite,
  then keeps only the Qt shared libraries that the retained bindings and
  plugins load. A build fails above a 60 MB ceiling, and a test ties the
  keep-list to the Qt modules repopull imports.
- The image now ships third-party notices for Python, PySide6/Qt, certifi and
  OpenSSL, with the LGPL-3.0 text.

## 0.5.2 — 2026-11-09

- Harden `run_git()` so an exception from `communicate()` still kills and reaps
  the git process group; escalation from SIGTERM to SIGKILL is tested. A SIGKILL
  of repopull itself can still orphan a process that git forked; that residual
  gap is documented.
- Root-state repair re-reads the saved state and the mounted filesystem identity
  before writing, so a stale confirmation cannot overwrite a newer observation.
- Add a resource soak harness (`make soak`, `make soak-qt`) plus process-tree,
  Qt lifetime, close-while-running, TOCTOU, and cancellation coverage.
- CI runs tests in development mode with warnings as errors and faulthandler,
  and audits both packaging requirement files with `pip-audit`.

## 0.5.1 — 2026-11-08

- Returning from a repository's detail page keeps the library's scroll
  position. A status run finishing or a hold changing while the detail page is
  open no longer jumps the list back to the top. Changing the filter or the
  search still starts at the top.
- Sidebar text now shares one column: Watched folder, Last check, Next check,
  and the version align with All / Behind / Skipped / Errors and Settings. The
  navigation pills keep their 12 px inset, and the checked tab's accent bar no
  longer shifts its label by 3 px.

## 0.5.0 — 2026-11-08

- The repository page has **Open folder**, which opens the local clone in the
  desktop's default file manager through Qt rather than spawning a shell.
- Two per-repository switches hold a repository out of **Refresh status** and/or
  **Sync all**. Holds are stored immediately in `config.toml`, apply to automatic
  checks, the tray, the banner, and CLI/menu bulk runs, and are overridden by an
  explicit `--only` selection or the page's own sync buttons.
- Row chips now carry a state or hold only (`Behind`, `Up to date`,
  `No checks`, `No sync`, `No checks/sync`); counts live in the subtitle so long
  numbers cannot overflow, and sync counts read as history (`N commits pulled at
  last sync`).
- The sidebar shows **Last check** and a clickable **Next check** line that opens
  the Refresh settings. The next line reports off, paused, hidden, resume, and
  in-flight states instead of pretending a timer is always running.

## 0.4.16 — 2026-11-07

- Root-state checks now save the identity they actually verified instead of
  reading the filesystem a second time. A remount between check and write can no
  longer bless an unseen disk.
- A transient UUID lookup failure preserves the previous UUID and mount source
  instead of downgrading the state to device-only comparison.
- Repair is refused when the current root contains no repositories, so an empty
  disk cannot replace a positive saved count and disable the empty-root guard.
- Malformed, unreadable, and newer-version state files are reported and left in
  place instead of being overwritten. The GUI again tells users which state file
  to remove when a mismatch is not repairable.
- Root-state writes now use a unique temporary file, and `repair-root` holds the
  same run lock as status/sync.
- The GUI's root-state read and check now run in the discovery worker instead of
  the UI thread.
- Split mount probing into `mounts.py`; `rootstate.py` now owns only persistence
  and comparison. The comparison takes one `RootIdentity`, and the test-only
  wrappers `verify_root_state` and `load_root_state` are gone.

## 0.4.15 — 2026-11-07

- Watched-root identity now uses the filesystem UUID and mount source, with the
  device number only as a fallback. This fixes a false "different device" refusal
  after a reboot when btrfs reallocates its anonymous `0:N` device number for the
  same disk. State files from 0.4.14 and earlier are upgraded after a matching
  check.
- Added **Repair saved root state** to the GUI mismatch view and
  `repopull repair-root` to the CLI. Both show the saved and current identities;
  `--yes` accepts the current one. Legacy state files can need this once.

## 0.4.14 — 2026-11-07

- Fixed the field padding that 0.4.13 did not actually deliver for
  `QLineEdit` and spin boxes: QSS padding moves the widget frame but not the
  text. The watched-folder/search fields now use a 12 px text margin, and spin
  boxes add 4 px inside their line edit. The ignore box already had visible
  padding.

## 0.4.13 — 2026-11-07

- Added QSS padding to the manually editable fields. It was effective for the
  ignore text area but not for `QLineEdit` or spin boxes; fixed in 0.4.14.
- Reran the test-falsifiability audit against the 224-test suite. Fixed seven
  tests that could not fail, added 16 tests for config defaults, validation,
  scheduler constants, jitter, and boundary cases, and recorded the remaining
  mutation survivors in `docs/test-falsifiability.md`.
- Updated CI to `actions/checkout@v7` and `actions/setup-python@v7`, which run
  on Node 24.

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
