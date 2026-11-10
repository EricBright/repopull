# Architecture

`repopull` is a small, dependency-free Python package with a strict separation
between discovery, git access, decision-making, and presentation.

## Modules

| Module | Responsibility |
|---|---|
| `models.py` | Frozen dataclasses: `RepoRef`, `RepoState`, `Row`, `Report`, `Outcome`. |
| `config.py` | TOML loading, validation, defaults, path resolution, and per-repository bulk-action holds. |
| `discovery.py` | Finds `.git` directories at depth 1–2, applies ignore globs, skips clone work-in-progress. |
| `git.py` | Typed wrappers around the git CLI; the only place that spawns processes. |
| `clone.py` | Validates a clone address and folder name, clones into a temporary folder, then renames it into place. |
| `sync.py` | Inspection, fetching, classification, and applying updates. |
| `refresh.py` | Pure automatic-refresh policy: interval clamping, delays, backoff, suspend detection, and the GUI decision table. |
| `report.py` | Table rendering, log persistence, JSON serialization. |
| `mounts.py` | Probes the watched path's mount source, filesystem UUID, and device identity. |
| `rootstate.py` | Persists and compares the watched root's filesystem identity and repository count. |
| `uistate.py` | Remembers the last GUI page, filter, and detail selection. |
| `diagnostics.py` | Human-readable path/root explanations and fix-it advice. |
| `menu.py` | Interactive loop and selection parsing. |
| `cli.py` | Argument parsing, dispatch, exit codes, the run lock. |
| `runtime.py` | `flock`-based single-run guard. |

`git.py` is deliberately the only module that runs subprocesses. Everything else
works with plain data, which is what makes the sync logic testable without a
network.

## Data flow

```
discover_repos()
      │ list[RepoRef]
      ▼
_collect() ──────────────► inspect_repo() ───► git.* (local reads)
      │ list[RepoState]
      ▼
_fetch_all() ────────────► git.fetch()        (sequential, polite delay)
      │ dict[label, GitResult]
      ▼
_refresh() ──────────────► inspect_repo()     (ahead/behind after fetch)
      │
      ▼
classify() ──────────────► Verdict
      │
      ├── status ────────► Row(BEHIND / UP_TO_DATE / SKIPPED / ERROR)
      │
      └── sync ──────────► git.fast_forward()
                           git.hard_reset()      (force only)
                           git.update_submodules()
                                │
                                ▼
                          Row(UPDATED / ...)
      │
      ▼
Report ──► write_log() ──► logs/
      └──► render_report() / report_to_dict()
```

## State model

`RepoState` is a snapshot:

| Field | Meaning |
|---|---|
| `branch` | Current branch, or `None` when detached. |
| `upstream` | Tracking ref from `@{u}`, or the `origin/<branch>` fallback. |
| `dirty` | Tracked files differ from HEAD. Untracked files are ignored. |
| `ahead` | Commits on HEAD not on upstream. |
| `behind` | Commits on upstream not on HEAD. |
| `shallow` | Whether the clone is shallow. |
| `uses_lfs` | A tracked `.gitattributes` enables `filter=lfs`, in the working tree or in the upstream tree when behind. |
| `lfs_enabled` | The effective git config has `filter.lfs.clean`/`smudge`; required along with the binary. |
| `has_submodules` | `.gitmodules` exists. |
| `error` | Set when inspection failed; the repo is reported, not acted on. |

## Classification

`classify(state, force, lfs_ok, require_lfs, preview)` is a pure function. It is
the single source of truth for "what happens to this repo", and it is unit-tested
directly. The `preview` flag turns a would-be update into `BEHIND` so the status
table can describe intent without applying it.

Order of checks matters:

1. inspection error
2. detached HEAD
3. no upstream
4. LFS not ready (binary missing or filters not enabled)
5. dirty (normal mode only)
6. force: reset unless already clean and current
7. up-to-date
8. diverged (normal mode only)
9. behind → `BEHIND` (preview) or `UPDATED` (apply)

## Network politeness

- One fetch at a time, never parallel.
- `delay_between_repos_s` (default 0.5 s) between fetches.
- No per-repository retry: a single failure is reported and the sweep continues;
  two consecutive network-level failures stop it. Automatic status refresh has
  its own 2/5/15/30/60 minute network retry ladder.
- `--prune --quiet --no-progress` keeps output and ref churn minimal.
- `GIT_TERMINAL_PROMPT=0` and `GIT_ASKPASS=/bin/true` make an interactive
  credential prompt impossible, so an unattended run can never hang.
- Timeouts on every git command.

## Error model

- Per-repo failures become `ERROR` rows; the sweep continues.
- Fatal conditions (missing root, bad config, lock held) return exit code 2.
- Skips are not errors and do not affect the exit code.
- Exit code 1 means at least one `ERROR` row.

## Logging

`report.write_log()` writes the colour-free brief to
`logs/YYYYMMDD-HHMMSS-<mode>.log` and overwrites `logs/latest.log`. Both status
and sync runs log. `--json` emits the same data as structured JSON without
writing a separate JSON file.

## Testing

- `tests/test_sync.py` — classification unit tests plus integration tests that
  build bare remotes and clones in temporary directories: fast-forward, dirty
  skip, divergence, force reset, untracked files, missing tracking config, LFS
  skip, empty clone, and status-is-read-only.
- `tests/test_discovery.py` — nested discovery, ignore globs, depth limits,
  clone temporary folders.
- `tests/test_clone.py` — URL and folder-name validation, local and empty
  remotes, failed/cancelled cleanup, and discovery of a partial clone.
- `tests/test_config.py`, `tests/test_report.py`, `tests/test_models.py`,
  `tests/test_runtime.py` — config round-trip, report JSON/render, model
  predicates/counts, run lock.
- `tests/test_diagnostics.py`, `tests/test_cli.py`, `tests/test_gui.py` —
  path/root advice, CLI exit paths, offscreen GUI.
- `tests/test_gui_clone.py` — Clone dialog validation, background task signals,
  busy state, and close-while-cloning.
- `tests/test_packaging.py` — AppImage trim policy and the source-import guard.
- `tests/test_refresh.py` — interval clamps, delay/backoff, suspend detection,
  and the pure automatic-refresh decision table.
- `tests/test_mounts.py`, `tests/test_rootstate.py`, `tests/test_uistate.py` —
  mount probing, root identity, and remembered GUI state.
- `tests/test_selection.py`, `tests/test_version.py` — menu parser and version
  consistency.
- `tests/test_icons.py`, `tests/test_docs.py` — icon assets/window icon; README
  entry-load cap, registry completeness, and registry backlinks.

No test touches the real watched repositories or the network. The
[test falsifiability audit](test-falsifiability.md) records the 0.2.3 run
(80 tests, 188 mutants killed, 7/7 sabotage cases caught after the fixes); the
current suite adds the icon, docs-version, and documentation-system checks; the
audit records the totals.

## GUI layer (optional)

`src/repopull/gui/` is a thin PySide6 layer over the same core:

| Module | Responsibility |
|---|---|
| `app.py` | QApplication, icon, argument parsing, screenshot and smoke-test modes |
| `window.py` | Sidebar, library, detail, settings, run orchestration |
| `rows.py` | Repository row and status chip |
| `lfs_help.py` | Read-only Git LFS install/enable dialog |
| `jobs.py` | `RunTask(QRunnable)` holding the same lock; Qt signals |
| `settings.py` | Settings cards, title/hint rows, and section widgets |
| `switch.py` | Animated immediate-effect switch painted on `QCheckBox` |
| `theme.py` | Palette tokens and generated stylesheet |
| `assets/` | B1t icon family (display and small optical cuts) and the sidebar mark; see [branding.md](branding.md) |

The GUI calls `status_report()` / `sync_report()` in a worker thread. Both accept
an `on_row` callback, which fires as soon as one repository has been fetched and
classified, so the window paints each chip while the sweep is still running.
`logs/latest.json` is a **per-repository snapshot**: a single-repo sync merges its
row into the previous snapshot instead of replacing it. A run holds
`logs/.lock`, so the GUI and the CLI cannot overlap.

## Packaging

`packaging/build_appimage.py` builds the AppImage: `python-appimage` stages an
AppDir with a bundled Python 3.13 and PySide6, `AppRun` is replaced with the
writable-home launcher, and a pinned `appimagetool` packs it. See
[packaging.md](packaging.md).
For the full documentation index, see [README.md](../README.md#documentation-index).
