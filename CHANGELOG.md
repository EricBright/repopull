# Changelog

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
