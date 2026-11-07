# Test falsifiability audit

**Date:** 2026-11-05
**Version audited:** 0.2.3
**Scope:** the engine and diagnostics modules in `src/repopull/`, plus the menu
parser and GUI row mapping. Raw artifacts live in `_temp/` (gitignored).

This audit covered the 0.2.3 suite of 80 tests. Four icon tests, a docs-version
sync test, three documentation-system checks, five log-retention tests, one
lock-durability test, seventeen auto-refresh/config tests, seven tray/settings
tests, and one checkbox-asset test were added later; the suite at 0.4.3 was
119 tests.

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
## 2026-11-07 re-audit (0.4.13 development tree)

**Suite:** 224 tests at audit time; all running, no skips. The 0.4.14 padding
test brings the current suite to 225. The conditional parent-death test
ran because `setpriv` is present. No test lacked an assertion, no assertion was
swallowed by `try/except`, and no assertion was hidden inside a loop over a
possibly-empty collection.

**Scope:** mutation testing covered nine engine modules: `refresh`, `config`,
`sync`, `discovery`, `report`, `models`, `rootstate`, `runtime`, and `uistate`.
GUI, CLI, diagnostics, menu, git wrappers, and icon/docs tests were read in
phase 1 but not mutated. This is an engine audit, not a whole-project one.

### Phase 2 — mutation

The first complete run produced **306 killed, 168 survived, 13 hung** from 487
mutants. The seven refresh properties below were then strengthened and the config
suite was extended; targeted re-runs of those two modules produced the final
per-module figures:

| Module | Mutants | Killed | Survived | Hung |
|---|---:|---:|---:|---:|
| `refresh.py` | 115 | 99 | 16 | 0 |
| `config.py` | 65 | 51 | 1 | 13 |
| `sync.py` | 114 | 73 | 41 | 0 |
| `report.py` | 92 | 42 | 50 | 0 |
| `rootstate.py` | 39 | 20 | 19 | 0 |
| `discovery.py` | 31 | 17 | 14 | 0 |
| `models.py` | 15 | 12 | 3 | 0 |
| `uistate.py` | 15 | 9 | 6 | 0 |
| `runtime.py` | 1 | 1 | 0 | 0 |
| **Adjusted total** | **487** | **324** | **150** | **13** |

The adjusted total replaces the first run's config and refresh rows with the
re-run results; the other modules were not re-run. Kill rate is a shape, not a
grade: `report.py` is dominated by formatting strings, and many `sync.py`
survivors are integration paths rather than pure branches. A survivor is a
worklist item, not proof that a test is worthless.

The 13 hung mutants are all in `config.py`'s type validators and the
`log_dir`/`ignore` checks. A mutation there makes the suite time out rather than
fail. They are recorded as `hung`, never as killed; no test-falsifiability claim
rests on them.

### Phase 3 — direct sabotage

Ten properties were broken by hand. Seven were initially **not caught**:

| Property | Defect | Test verdict before | After |
|---|---|---|---|
| In-flight retry is 60 s | `60.0` → `66.0` | missed: test asserted the imported constant | caught by a literal 60.0 assertion |
| Suspend detection threshold is 5 s | `5.0` → `5.5` | missed: test derived its input from the constant | caught by literal 4.0/5.0/5.2 cases |
| Warning starts above zero | `0 < seconds` → `1 < seconds` | missed: interval 1 was untested | caught by `should_warn(1)` |
| Cooldown jitter is added | `remaining + jitter` → `remaining - jitter` | missed: cooldown test used no jitter | caught by a 410 s jitter case |
| `SHOW` catches up only when due | `<= 0` → `<= 1` | missed: no sub-second remainder case | caught by a 0.5 s remainder case |
| Suspend gap threshold is strict | `gap < threshold` → `gap <= threshold` | missed: exact boundary untested | caught by a gap exactly at 5.0 s |
| Default decision delay is zero | `0.0` → `0.5` | missed: STOP did not assert delay | caught by asserting `delay_s == 0.0` |

The other three cases — the network retry cap, `wait_remaining` addition, and
the in-flight constant after the literal assertion — were caught before and
after. Final result: **10 of 10 sabotaged properties caught**.

The fixes added 16 tests: five in `tests/test_refresh.py` and eleven in
`tests/test_config.py`. They cover literal scheduler constants, jitter,
sub-second `SHOW` timing, the exact suspend boundary, config defaults, empty
and missing config files, boolean-as-number rejection, depth 1, zero
auto-refresh, relative log directories, `ignore` type validation, the
`REPOPULL_CONFIG` environment path, project-home fallback, and compact
`key=value` updates.

### What remains

- 150 mutation survivors remain. Most are equivalent mutants, untested
  formatting constants, or behaviour in layers this run did not mutate. The
  `report.py` and `sync.py` survivors are the largest groups and are an
  explicit open worklist, not a pass.
- 13 config mutants hung. They need individual inspection before treating the
  validator coverage as complete.
- The 43 "never killed a mutant" tests from the full run include many in
  unmutated layers (GUI, CLI, diagnostics, menu, git, docs, icons); their
  presence is not evidence that the engine tests are weak.

This re-audit changed tests and documentation only; no production behaviour was
changed for it.

For the full documentation index, see [README.md](../README.md#documentation-index).
