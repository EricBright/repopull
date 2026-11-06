# Workflow: Watched-repo sync

**Loop:** keeping local mirrors of third-party repositories current with their remotes.
**Trigger:** manual, from a terminal menu. No schedule.
**AI:** none. This is deterministic tooling; no model is involved.

## Why this exists

The user watches a folder of third-party repos (currently 43: 39 top-level, 4
under `LEAP 71/`; the count changes as repos are added) and keeps local copies so
they can read the latest upstream code. They are **not** an owner or contributor
of any of them. The job is therefore **pull-only**: fetch, fast-forward, report.
Never push, commit, branch, tag, open a PR, or modify a remote.

## Trigger

- **Primary:** the user runs `repopull` and picks an action from the menu.
- **Secondary (future, not built):** a systemd timer may run
  `repopull sync --all --json`. The CLI is non-interactive, so this needs no redesign.
- The GUI's optional automatic status refresh is separate: it never syncs, so
  this loop's trigger remains manual.

## Preconditions

- The watched root exists and is a directory, or the user has not chosen one yet
  (the tool then explains how to set it).
- `git` is on `PATH`.
- Network access to the remote hosts.

## The loop

1. Discover repositories.
2. Inspect local state (no network).
3. Fetch remotes, one at a time, politely.
4. Recompute ahead/behind.
5. Classify each repo.
6. Apply only safe updates.
7. Write and show the brief.
8. Return to the menu.

## Step detail

### 1. Discover

- Walk the root to depth `max_depth` (default 2, inclusive).
- A directory is a repository when it contains `.git` (directory **or** file).
- Do not descend into a repository.
- Ignore any directory whose label or basename matches an `ignore` glob.
- Sort by label. The label is the path relative to the root, POSIX style.
- The `LEAP 71` container (name contains U+202F) must work; paths are handled as
  `pathlib.Path`, never by string splitting.

### 2. Inspect local state (no network)

For each repo, collect:

| Field | Source |
|---|---|
| branch | `git rev-parse --abbrev-ref HEAD`; `HEAD` means detached |
| upstream | `@{u}` if set, else `origin/<branch>` if that ref exists |
| dirty | `git status --porcelain --untracked-files=no` is non-empty |
| ahead / behind | `git rev-list --left-right --count HEAD...<upstream>` |
| shallow | `git rev-parse --is-shallow-repository` |
| uses_lfs | a tracked `.gitattributes` contains `filter=lfs` (working tree, plus the upstream tree when behind) |
| has_submodules | `.gitmodules` exists |

Untracked files do **not** count as dirty: build artefacts are expected and must
survive every run.

### 3. Fetch

One repo at a time, in discovery order:

```
git -C <repo> fetch --prune --quiet --no-progress origin
```

- Timeout: `fetch_timeout_s` (default 300 s).
- No automatic retries. A failure is reported and the run moves on.
- Sleep `delay_between_repos_s` (default 0.5 s) between repos, never after the last.
- Environment forces `GIT_TERMINAL_PROMPT=0` and `GIT_ASKPASS=/bin/true` so an
  interactive credential prompt can never hang the run.

### 4. Classify
After a successful fetch the state is inspected again. Classification is:

| Condition | Normal sync | Force sync | Status preview |
|---|---|---|---|
| inspection error | error | error | error |
| detached HEAD | skip | skip | skip |
| no upstream | skip | skip | skip |
| LFS repo, Git LFS not ready (missing or not enabled) | skip | skip | skip |
| dirty and not force | skip | — | skip |
| ahead = 0, behind = 0 | up-to-date | up-to-date if clean, else reset | up-to-date |
| ahead = 0, behind > 0 | fast-forward | hard reset | behind (N) |
| ahead > 0, behind = 0 | up-to-date (local commits noted) | hard reset | up-to-date (local commits noted) |
| ahead > 0, behind > 0 | skip (diverged) | hard reset | skip (diverged) |

`skip` always carries a human-readable reason into the brief.

### 5. Apply

- Normal: `git merge --ff-only <upstream>`.
- Force: `git reset --hard <upstream>`.
- After a successful update, when `.gitmodules` exists and `update_submodules` is
  true: `git submodule update --init --recursive`.
- `git clean` is never run. Untracked files are never deleted.
- A failing fast-forward (for example an untracked file in the way) becomes an
  error row; the repository is left untouched.

### 5b. Fast path (`--behind`)

`sync --behind` reads `logs/latest.json` and runs only the rows marked `behind`.
Repositories marked up-to-date are not contacted. This is a deliberate staleness
trade-off: use it after a status run, and use the full `sync` when the last check
is old.

### 6. Brief

Counts-only table, one row per repository. This example is from an earlier run,
before Git LFS was installed:

```
Repository                    Branch   Status      Commits  Detail
logseq                        master   updated           12
egui                          main     skipped            0  uses Git LFS but git-lfs is not installed
fieldcraft                    develop  up-to-date         0
```

Then:

```
Totals: 12 updated, 28 up-to-date, 2 skipped, 1 error in 34.2s
Attention:
  - egui: uses Git LFS but git-lfs is not installed
```

No commit subjects, no diffs. The brief is written to
`logs/YYYYMMDD-HHMMSS-<mode>.log` and `logs/latest.log`, and the same text is
printed. `--json` emits the same data as JSON instead.

### 7. Menu

```
1) Fetch status (no changes)
2) Sync all
3) Sync selected
4) Force sync selected
5) View last report
6) Quit
```

- "Sync selected" and "Force sync selected" accept numbers, ranges (`1,3,5-8`),
  `all`, and `none`.
- Force sync prints the selected repos and requires the literal word `reset`
  before doing anything.
- After every action the menu shows the brief and waits for Enter.
- The menu loops until Quit, Ctrl-C, or EOF.

## Safety rules (hard)

1. Never push, commit, branch, tag, or open a PR.
2. Never modify a dirty working tree during a normal sync; skip and report.
3. Never discard commits during a normal sync; skip and report.
4. Hard reset only through "Force sync", after explicit confirmation.
5. Never run `git clean`; untracked files survive every run.
6. Never touch an LFS repo when Git LFS is not ready (binary missing or filters
   not enabled); a checkout would replace real files with pointer text.
7. One run at a time, enforced with an `flock` on `logs/.lock`.

## Failure handling

| Failure | Behaviour |
|---|---|
| root missing / not a directory | fatal, exit 2, with the config source and next steps |
| config unreadable or invalid | fatal, exit 2 |
| another run holds the lock | fatal, exit 2 |
| fetch timeout or failure | that repo is `error`; run continues |
| fast-forward refused | that repo is `error`; run continues |
| submodule update fails | repo is `updated` with a warning in Detail |
| discovery finds no repos | fatal, exit 2 |

Exit codes: `0` no errors, `1` at least one error row, `2` fatal.

## Checkpoint

The brief **is** the checkpoint. It is pushed as late as possible: every fetch and
every safe update happens first, then one summary is shown. The only early
checkpoint is the destructive one — Force sync confirms before resetting.

The user reads the brief and decides whether any skipped/errored repo needs a
manual look or a targeted Force sync.

## Out of scope

- Cloning missing repos.
- Branch switching, or fetching branches other than the current tracking branch.
- Installing `git-lfs`.
- Scheduling, desktop notifications, or background daemons.
- Pushing anywhere, for any reason.

## Acceptance criteria

1. `bin/repopull list` prints every discovered label, including `LEAP 71/PicoGK`.
2. `bin/repopull status` fetches, changes no working tree, and prints the table.
3. `bin/repopull sync` fast-forwards clean, behind repos; skips dirty and
   diverged ones with reasons.
4. A repo with an untracked file is not treated as dirty.
5. A repo with no configured upstream but a matching `origin/<branch>` still syncs.
6. `--json` is valid JSON and contains the same rows and totals.
7. Two concurrent runs: the second exits 2 with a lock message.
8. `mypy --strict` passes on `src/repopull`.
9. The unit and integration tests pass with `make test`.
For the full documentation index, see [README.md](../README.md#documentation-index).
