# NOTES — remote-repo-pull-automation

> Historical snapshot from 2026-11-05. It is kept for the original survey and
> terminology; current settings and behavior live in [README.md](README.md) and
> [docs/](docs/).

Raw notes on the user's world, tools, and terminology. Decisions live in
`workflows/*.md`; this file is the original factual substrate.

## The world (surveyed 2026-11-05)

- **Repos root**: `<watched-root>` (local, not tracked).
  - External disk; large (≈6.8 GB total).
- **43 git repos** (44 when `AppGlider` was added; `AniCraft`, an empty clone, was later deleted):
  - 39 at depth 1 under the root.
  - 4 nested under `LEAP 71/` — folder name contains **U+202F NARROW NO-BREAK SPACE**
    (`LEAP 71`), which breaks naive string matching.
    - `PicoGK` → https://github.com/leap71/PicoGK (`main`)
    - `LEAP71_ShapeKernel` → https://github.com/leap71/LEAP71_ShapeKernel (`main`)
    - `LEAP71_LatticeLibrary` → https://github.com/leap71/LEAP71_LatticeLibrary (`main`)
    - `LEAP71_QuasiCrystals` → https://github.com/leap71/LEAP71_QuasiCrystals (`main`)
- **Remotes**: every repo has exactly one remote, `origin`. No forks/upstreams configured.
- **Branches in use**: `main` for almost all; `master` for `logseq`; `develop`
  for `fieldcraft`.
- **Dirty at survey time**: `egui` — one modified file, an LFS-tracked PNG
  (`tests/egui_tests/tests/snapshots/visuals/text_edit_prefix_suffix.png`).
- **Git LFS**: `egui` tracks `*.png`/`*.gif` via LFS, but **`git-lfs` was not
  installed at survey time** (`git lfs` → unknown command). It was installed
  later; current status is in Settings → Updates.
- **Submodules**: `VoiceStudio` declares `omnivoice-gallery`
  (https://github.com/debpalash/omnivoice-gallery.git), **uninitialized at
  survey time**.
- **No shallow clones**, no other worktrees, no multiple remotes.

## Toolchain on the machine

- git 2.56.0
- Python 3.15.0, `uv` available, `curses` available
- `fzf` and `gum` installed; `rich`, `pipx`, `dialog`, `whiptail` absent
- git-lfs **absent at survey time** (installed later)

## User's relationship to the repos

- User is **not** an owner, maintainer, or contributor of any repo.
- Local copies exist **only to watch/sync** remote development.
- Therefore: **no push, no PRs, no branch creation, no commits** by this tooling.
- Local edits are not expected, but one dirty file existed at survey time.

## Terminology

- **watched repos** — local mirrors of third-party remote repos the user does not own.
- **sync** — fetch remote state and bring the local tracking branch up to date.
- **brief** — the decision-ready summary shown after a sync (what changed, what was skipped, why).

## Resolved decisions (2026-11-05)

The full specification lives in `workflows/watched-repo-sync.md`; rationale is in
`docs/design-decisions.md`.

- Dirty trees → skipped by default and reported; Force sync resets on demand.
- Diverged history → fast-forward only by default; Force sync hard-resets.
- Language → Python 3.11+, standard library only, fully type-annotated
  (`mypy --strict` passes).
- Menu → numbered ANSI menu plus scriptable subcommands.
- Discovery → depth 1–2, nested `LEAP 71/*` included, optional ignore globs.
- Submodules → updated after a successful pull.
- LFS → repos skipped when Git LFS is not ready (binary missing or filters not
  enabled).
- Network → sequential, 0.5 s between fetches, no retries within a sweep, and
  timeouts. Automatic status refresh later added the 2/5/15/30/60 minute
  network retry ladder.
- Trigger → manual menu at survey time. GUI status-only automatic refresh was
  added later; the CLI still has no scheduler.
- Brief → counts only, with skip/error reasons, logged to `logs/`.

## Operational surface (2026-11-05)

- The `root` → repos link is surfaced in three places: the `THE LINK` comment in
  `config.toml`, the `Root: ... (config.toml key "root")` line in the menu header,
  and `repopull where` (config file, root, source, existence, repo count).
- A missing root prints the attempted path, its source, the config file, and next
  steps (mount the disk, edit `root`, or pass `--root`), then exits 2.
- An empty root prints advice about `max_depth` / `ignore`, then exits 2.

## GUI and AppImage (2026-11-05)

- Optional PySide6 GUI in `src/repopull/gui/`; it reads the same `config.toml`
  and `logs/latest.json` as the CLI.
- Rows update per repository while a sweep runs; `latest.json` is a merged
  per-repository snapshot so a one-repo sync does not erase the other chips.
- Runs natively on Wayland and X11; both Qt platform plugins are bundled in the
  AppImage.
- `make appimage` builds the image with Python 3.13.17 + PySide6 6.12.0, using
  `python-appimage` 1.4.6 and pinned `appimagetool` 1.9.1. Version and output
  are in [docs/packaging.md](docs/packaging.md).
- The AppImage stores config and logs in `$XDG_CONFIG_HOME/repopull` (default
  `~/.config/repopull`); `REPOPULL_HOME` overrides. `--cli` dispatches to the
  command line inside the image.
- The image ships `packaging/default-config.toml` with **no** watched folder; a
  first run asks for one in Settings. The development `config.toml` keeps this
  machine's path, but it is not baked into the build.
- The image bundles Python and PySide6, not `git`; host `git` is required.

## Versioning (2026-11-05)

- The version lives in `pyproject.toml` and `src/repopull/__init__.py`;
  `make bump` updates both.
- `make bump` increments it (patch by default; `PART=minor` or `PART=major`).
- `make release` runs the checks, bumps the patch, and rebuilds the AppImage.
- `CHANGELOG.md` records user-visible changes.

## Additional findings (2026-11-05)

- `AppGlider` (https://github.com/Vyrnexis/AppGlider, `main`) appeared at the top
  level mid-session and was picked up by discovery with no config change. A
  live demonstration that the count is dynamic.
- `AniCraft` was an **empty repository** (no commits, refs, or objects); the user
  deleted it on 2026-11-05. The count is now 43.
- `egui`'s working file is a real 10,540-byte image while `HEAD` stores a
  130-byte LFS pointer, so Git sees it as modified even without local edits.
  Installing `git-lfs` is the fix.
- `LEAP 71` uses U+202F NARROW NO-BREAK SPACE; paths are handled with `pathlib`.
For the full documentation index, see [README.md](README.md#documentation-index).
