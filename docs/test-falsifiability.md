# Test falsifiability audit

**Date:** 2026-11-05
**Version audited:** 0.2.3
**Scope:** the engine and diagnostics modules in `src/repopull/`, plus the menu
parser and GUI row mapping. Raw artifacts live in `_temp/` (gitignored).

This audit covered the 0.2.3 suite of 80 tests. Four icon tests, a docs-version
sync test, three documentation-system checks, five log-retention tests, one
lock-durability test, sixteen auto-refresh/config tests, and five tray/settings
tests were added later; the current suite is 115 at 0.4.1.

**Question:** for each test, is there a defect it would catch?

## Result

Yes for the core suite, but not uniformly on the first pass.

- **Phase 1** found no structurally non-falsifiable tests: no missing
  assertions, tautologies, skipped tests, or assertions swallowed by `except:
  pass`. Two loop flags were fixture-construction loops, not empty test loops.
- **Phase 2** generated 447 mutants: **188 killed, 250 survived, 9 hung**. 68 of
  the 70 pre-existing tests killed at least one mutant.
- **Phase 3** hand-broke five properties that survived or looked narrow. **Four
  were not caught**: phantom commit counts, phantom ahead counts on a broken
  repo, the updated chip text, and a wrong LFS install hint. A fifth hand-break
  found that `test_missing_root_raises` asserted only the exception *type*, so
  deleting the missing-root check still raised a different `DiscoveryError`.
  All five were fixed; the control was caught before and after.
- After the fixes, **7/7 sabotage cases are caught** (five main plus two no-kill
  guards), and the suite is **80 tests** (10 new).

What this does **not** say: that the code is correct, or that the suite is
exhaustive. 250 mutants still survive; most are in untested helpers or are
equivalent mutants.

## Phase 1 — structural read

70 tests at audit time, all running. GUI tests run offscreen with PySide6
present.

- No test without an assertion.
- No `assertTrue(True)`, `x == x`, or assertion about a just-built fixture.
- No `@skip` / `skipUnless`; the GUI class is conditional on PySide6, which is
  installed in this environment.
- No assertion inside a `try` with `except: pass`.
- Two `LOOP-NO-ASSERT` flags (`test_existing_root_reports_repo_count`,
  `test_results_are_sorted`) were fixture-setup loops over non-empty literals;
  their assertions are outside the loop. Not defects.

## Phase 2 — mutation

Tool: `mutation_check.py` from the test-falsifiability skill, against the
throwaway copy `_temp/audit/`, with `PYTHONPATH=src` **relative to each worker**.

| Run | Modules | Mutants | Killed | Survived | Hung |
|---|---|---:|---:|---:|---:|
| Engine | `models`, `config`, `discovery`, `git`, `runtime`, `report`, `diagnostics`, `sync` | 368 | 162 | 197 | 9 |
| Parser/rows | `menu`, `gui/rows` | 79 | 26 | 53 | 0 |
| **Total** | | **447** | **188** | **250** | **9** |

**Runner lesson.** The first pass used an absolute `PYTHONPATH` pointing at the
original `src`. Every worker therefore imported the unmutated source, and all
368 mutants "survived". Rerunning with `PYTHONPATH=src` (resolved against each
worker's cwd) produced the table above. A mutation run that kills nothing is a
harness failure, not a perfect suite.

### Tests with no mutation kill

68 of the 70 pre-existing tests killed at least one mutant. The two that did
not:

- `test_missing_root_raises` — no operator landed on the `exists()` guard, and
  Phase 3 showed the test was too narrow: deleting the guard still raises
  `DiscoveryError` from the `is_dir()` check. It now asserts the message.
- `test_pyproject_and_package_versions_match` — `__init__.py` was outside the
  mutation sources; Phase 3 confirms it catches a version drift.

The 10 new tests were added after the mutation run and are not counted in the
68; seven key properties are covered by the Phase 3 cases.

## Phase 3 — hand sabotage

Cases: `_temp/sabotage-cases.json` and `_temp/sabotage-extra.json`.

### Main cases

| Property broken | Test | Before | After |
|---|---|---|---|
| `Verdict.commits` default `0 → 1` | `test_up_to_date_does_nothing` | NOT CAUGHT | caught |
| `_broken` `ahead` `0 → 1` | `test_empty_clone_is_reported_clearly` | NOT CAUGHT | caught |
| `Outcome.UPDATED` chip `✓ Updated → WRONG` | `test_chip_text_and_kind` | NOT CAUGHT | caught |
| Bazzite hint `brew → dnf` | `test_lfs_install_hint_prefers_brew_on_bazzite` | NOT CAUGHT* | caught |
| control: report `mode` corrupted | `test_dict_round_trip` | caught | caught |

\* Before the fix, `test_lfs_help_is_read_only_and_has_a_hint` only asserted
that the hint was non-empty, so a wrong package manager passed. The new test
asserts the Bazzite branch.

### Extra no-kill guards

| Property broken | Test | Before | After |
|---|---|---|---|
| missing-root guard removed | `test_missing_root_raises` | NOT CAUGHT (wrong `DiscoveryError` accepted) | caught |
| `__version__` drifts from `pyproject.toml` | `test_pyproject_and_package_versions_match` | caught | caught |

**7/7 caught after fixes.** The control was caught before and after, so the
harness can distinguish "the test noticed" from "the test happened to pass."

## Fixes

- `tests/test_sync.py`: skipped verdicts assert `commits == 0`; up-to-date
  asserts `commits == 0`; broken repo asserts `ahead == 0`, `behind == 0`,
  `dirty is False`.
- `tests/test_gui.py`: updated chip text and kind asserted.
- `tests/test_discovery.py`: missing root asserted by message, not just
  exception class.
- `tests/test_diagnostics.py`: Bazzite/brew, Debian/apt, and installed+enabled
  LFS status tests.
- `tests/test_report.py`: rendered header, row, totals, and attention section.
- `tests/test_config.py`: `default_config_path()` under `REPOPULL_HOME`.
- `tests/test_models.py` (new): `RepoRef.name`, state predicates, report
  counts/totals/errors.
- `tests/test_runtime.py` (new): `.lock` path and second-holder exclusion.
- 70 → 80 tests; all pass; mypy clean.

## Survivors and open items

250 survived, 9 hung. These are a worklist, not a score. At audit time:

| Module | Non-killed | Notes |
|---|---:|---|
| `git.py` | 50 | LFS version/global-enable, protocol/remote helpers, error branches; mostly exercised indirectly through sync. |
| `diagnostics.py` | 45 | Advice text and LFS branches; the new LFS tests cover the hint/status, not every `describe_paths` branch. |
| `menu.py` | 41 | The interactive menu loop; `parse_selection` is covered (its tests killed mutants), the loop is not. |
| `sync.py` | 38 | Submodule update, some apply/LFS/force branches. |
| `report.py` | 28 | Formatting and merge branches; the new render test covers the table, not every clip/paint branch. |
| `config.py` | 28 | 19 survived + 9 hung; validation extremes and template choices. |
| `models.py` | 12 | Properties; now covered by `test_models.py`, but not rerun through mutation. |
| `gui/rows.py` | 12 | Chip/row rendering branches beyond the asserted ones. |
| `discovery.py` | 4 | Depth/ignore branches. |
| `runtime.py` | 1 | Lock path; covered by `test_runtime.py`, but not rerun through mutation. |

Not every survivor is a defect: some are equivalent mutants (a default or format
with no observable effect), some are untested code, and the 9 hung config
mutants could not be evaluated. The new tests were verified by sabotage, not by
a second full mutation run.

## Reproduce

```bash
tmp=_temp/audit
rm -rf "$tmp" && mkdir -p "$tmp"
cp -a src tests pyproject.toml "$tmp/"
cd "$tmp"
PYTHONPATH=src python3 <skill>/scripts/mutation_check.py \
  --sources 'src/repopull/sync.py,src/repopull/models.py,...' \
  --workers 4 --timeout 60 .
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tests \
  python3 <skill>/scripts/check_sabotage.py \
  . --cases ../sabotage-cases.json --runner unittest
```

`_temp/` is gitignored; the verdicts live here, the raw logs do not.
For the full documentation index, see [README.md](../README.md#documentation-index).
