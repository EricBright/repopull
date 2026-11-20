# repopull 0.8.4

The **Sync these** strip stops disappearing after a single update, and saved
results now belong to the watched folder that produced them.

## The fast path survives a single sync

The strip above the library is the fast path: it updates only what the last
check found behind, without contacting repositories that are up to date. It
used to be counted from the last run's report, and a one-repository sync
replaces that report with a single row — so updating one repository from its
detail page hid the strip even though other repositories were still behind and
the **Behind** count still listed them.

- The strip counts each repository's saved result, the same table the button
  acts on, so the number and the target set cannot disagree.
- Its count drops as each repository finishes, and it disappears only when
  nothing syncable is left.
- The count survives a restart: the window reads the merged per-repository
  snapshot in `logs/latest.json`, which a single-repo sync adds to rather than
  replaces.

## Saved results belong to one watched folder

The snapshot keys rows by label, and a label is only unique inside one folder.
After the watched folder changed, a repository in the new folder that reused a
name could show the previous folder's "behind" count, and the strip offered to
update it.

- The folder recorded with the last scan is compared with the configured one.
  If they differ, the window starts from "Not checked" instead of another
  library's rows.
- The merged `latest.json` and `latest.log` are discarded, for the window and
  before a CLI run, and the next scan rebuilds them. Timestamped run logs stay.
- [Decision 49](https://github.com/EricBright/repopull/blob/main/docs/design-decisions.md#49-saved-results-belong-to-the-watched-folder-that-produced-them)
  records the rule.

## A reproducible check environment

- `make dev-env` builds a `.venv` from the pinned runtime and test
  requirements, so the GUI tests and `mypy` are always present.
- `make check` refuses to run without PySide6 instead of letting the GUI tests
  skip silently, and type checking and the audit use the interpreter named by
  `PYTHON`.
- CI runs the suite on Python 3.15 in addition to 3.11 and 3.13. The package
  still supports 3.11+, and the image still bundles the pinned 3.13 runtime.

## Verifying

459 tests and `mypy` strict pass, `make audit` is clean, and the window started
from the saved state after a one-repository sync still lists the remaining
behind repositories. A changed watched folder starts with no saved rows.

## Installing

```bash
chmod +x repopull-0.8.4-x86_64.AppImage
./repopull-0.8.4-x86_64.AppImage
```

Gear Lever and AppImageUpdate can update an installed copy from the release
assets, using the embedded `gh-releases-zsync` information and the published
`.zsync`. repopull still never replaces its own image.

`SHA256SUMS.txt` covers the image and its `.zsync`.
