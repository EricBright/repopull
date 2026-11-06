# AppGlider lessons: GitHub's allowance and a GUI direction

> Historical research note from 2026-11-05. The GUI and many of these ideas now
> exist; this remains the source-linked research record.

Notes from reading [AppGlider](https://github.com/Vyrnexis/AppGlider) (a Python +
PySide6 AppImage manager) on 2026-11-05. Two questions: how does it stay inside
GitHub's request allowance, and how is its interface put together?

This was a design note, not a dependency. The GUI now exists; this remains the
research record.

## 1. GitHub's allowance — what is actually true

The limit is on **REST API requests**, not on `git fetch`.

| Caller | Primary limit |
|---|---|
| Unauthenticated (public data) | **60 requests/hour per IP address** |
| Authenticated (token) | **5,000 requests/hour** |
| GitHub App / OAuth (enterprise) | up to 15,000 requests/hour |

It is a rolling hourly window with a reset timestamp, not a per-call cooldown.
Secondary limits also exist: no more than 100 concurrent requests, 900 points per
minute per REST endpoint, 90 seconds of CPU per 60 seconds, and content-creation
limits. Every response carries `x-ratelimit-limit`, `x-ratelimit-remaining`,
`x-ratelimit-used`, `x-ratelimit-reset` and `x-ratelimit-resource`. A limited
request returns 403 or 429; wait until `x-ratelimit-reset`, or until `retry-after`
for a secondary limit, otherwise at least one minute with exponential backoff.
`GET /rate_limit` does not count against the primary limit but can count against
the secondary one.

Sources:
- [GitHub: Rate limits for the REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [GitHub docs source: unauthenticated limit](https://github.com/github/docs/blob/main/data/reusables/rest-api/primary-rate-limit-unauthenticated-users.md)
- [GitHub docs source: secondary limits](https://github.com/github/docs/blob/main/data/reusables/rest-api/secondary-rate-limit-rest-graphql.md)

### What this means for `repopull`

**Nothing today.** `repopull` runs `git fetch`, which uses the Git smart HTTP
protocol, not the REST API. The 60/hour bucket does not apply. The relevant
politeness is already in place: one fetch at a time, a 0.5 s gap, no retries, and
timeouts.

The allowance becomes relevant only if we add REST features: release tags,
repository metadata (stars, archived, default branch), open issues, or avatars.
At 43 repos, one request per repo would consume 43 of 60 in a single sweep, so a
naive metadata refresh is not affordable.

## 2. AppGlider's playbook

| Technique | What it buys | Where |
|---|---|---|
| `HEAD github.com/<owner>/<repo>/releases/latest`, read `Location` without following | Latest stable tag with **no API request** | `github/http.py:redirect_location`, `latest_tag` |
| Public Atom feed `<repo>/releases.atom` with an ETag | Preview tags with no API request; a 304 reuses the last tags | `feed_tags` |
| ETag cache of API bodies | A 304 reuses the saved body instead of re-downloading it | `read_metadata`, `_remember_etag` |
| Read `x-ratelimit-*` from every response | Know the remaining budget without a status request | `github/status.py:observe_headers` |
| Persist retry windows to `limits.json` | A restart does not immediately hit a limited host again | `restore_rate_limits`, `save_rate_limits` |
| Quota floor of 30 | Do not start checks that cannot finish | `status.PLENTIFUL_QUOTA` |
| One check at a time, or three while quota is plentiful | Finishes faster without hammering | `ui/release_checks.py` |
| Fall back to public release pages when the API is exhausted | The app still works with zero quota | `github/pages.py` |
| Show `GitHub 49/60` in the sidebar with reset time and retry countdowns | Failure is visible, not silent | `status.describe` |
| Offline retries at 15 s, 30 s, 1, 2, 5 minutes | Survives "no network at login" | `ui/window.py:OFFLINE_RETRY_SECONDS` |
| Show the last saved result first, then refresh | No blank screen while checking | release cache |
| Website caches the last release in `sessionStorage` and keeps a baked-in fallback version | Download button never breaks | `site/site.js` |

The neatest trick is the first one: `HEAD releases/latest` answers "what is the
latest stable tag?" via a redirect that GitHub does not count against the API
allowance. The git-protocol analogue for `repopull` is `git ls-remote --heads
origin <branch>`: it tells us whether a remote ref moved without fetching objects
or touching the REST API. That would make a good `repopull probe` command for a
background timer or a GUI's startup check.

### Ideas worth adopting in `repopull`

Small, independent of any GUI:

1. **Persist the last report as JSON** (`logs/latest.json`), so a GUI or a timer
   can render the previous run instantly and mark it "last checked at".
2. **Distinguish "offline" from "repo error".** A failed fetch because the network
   is down is not the same as a broken repository. AppGlider keeps the last known
   state and says "GitHub: offline"; a `repopull` GUI should show `Offline · last
   checked 16:12` rather than a red error on every row.
3. **Add cancellation** to the sync pipeline (`threading.Event` checked between
   repos). A 43-repo sweep can run for a minute; a GUI needs a Cancel button, and
   Ctrl-C in the CLI becomes cleaner.
4. **A cheap `git ls-remote` probe** before a full fetch, for a "has anything
   changed?" mode that does not touch `.git/FETCH_HEAD`.
5. **Never lie about freshness.** Show when the data was collected, and whether it
   came from a live fetch or the saved report.

If REST metadata is ever added, copy AppGlider's budget model: read the headers,
keep a floor, persist the retry window, and fall back to public pages.

## 3. How AppGlider builds its GUI

- Python 3.11 + **PySide6** (Qt), strict `mypy`, `ruff`.
- **One main window**, a fixed 210 px sidebar, and stacked pages (Library, Updates,
  Add app, App, Settings). No modal dialogs for browsing or settings; dialogs only
  for confirmations, file pickers and blocking choices.
- **Rows** are 60 px: icon, name + one-line subtitle, version, one status chip, one
  primary button, and a `⋯` menu. Chips pair colour with a symbol or word, so colour
  is never the only signal.
- **Banners** above the list for "2 updates ready" and "a new version is available",
  each with one primary action and a dismiss button.
- **Sidebar status block**: last check, next check, and `GitHub 49/60` with a
  tooltip for the reset time and retry countdowns. It makes no network requests.
- **Background work**: `Task(QRunnable)` for one cancellable operation at a time,
  `Lookup(QRunnable)` for small questions, `ReleaseChecks` as a queue with a
  quota-aware concurrency limit. Results return through Qt signals
  (`progress`, `finished`, `failed`).
- **Theme tokens** live in one Python module (`ui/theme.py`); the stylesheet is
  generated from them. No colour or radius is written directly in a widget.
- **Tray** icon, notifications, and a single-instance lock; `QSettings` for
  preferences.
- A written **design brief** ([docs/design.md](https://github.com/Vyrnexis/AppGlider/blob/main/docs/design.md))
  defines layout, tokens and wording before the code changes.
- GUI tests run with `QT_QPA_PLATFORM=offscreen`, disposable settings, and no real
  installs.

## 4. A GUI for `repopull`

The core is already GUI-ready: `sync_report()` returns a `Report` of rows and
totals, and takes a `progress` callback. The GUI should be a thin layer over it,
not a second implementation.

### Layout

```
┌──────────────┬─────────────────────────────────────────────┐
│ repopull     │ Repositories   [Search…………] [All|Behind] [⟳]│
│              │ ┌ 9 behind · 1 skipped · 1 error           ┐ │
│ ▣ All 43     │ │ 9 repositories can be updated [Sync these]│ │
│ ↓ Behind 9   │ └──────────────────────────────────────────┘ │
│ ‖ Skipped 1  │ ┌ repo · branch · chip · commits · [Sync] ┐ │
│ ⚠ Errors 1   │ └──────────────────────────────────────────┘ │
│              │                                             │
│ ⚙ Settings   │                                             │
│ Root: …/repos│                                             │
│ Last: 16:12  │                                             │
│ Fetch only   │                                             │
└──────────────┴─────────────────────────────────────────────┘
```

- **Sidebar**: All, Behind, Skipped, Errors, Settings; status block with the root
  path, the last run, and "git fetch only — no API allowance used".
- **Rows**: label, branch subtitle, status chip (`✓ Up to date`, `↑ 12 behind`,
  `✓ Updated`, `‖ Skipped`, `⚠ No commits`, `⏸ Offline`), commit count, and a
  primary action.
- **Detail page** on click: remote URL, upstream, ahead/behind, dirty, LFS,
  submodules, and the last log for that repo.
- **Sync all** is the one primary button. **Force sync selected** lives in a danger
  area and requires confirmation, exactly like the CLI.
- **Settings**: root path with a **Check** button (runs discovery and shows the
  count), delay, submodules, LFS policy, log directory. Changes apply immediately
  and write `config.toml` atomically; the CLI and GUI share one config file.

### Module map

```
src/repopull/gui/
  __init__.py
  app.py          # QApplication, entry point
  window.py       # sidebar, stacked pages, status block
  rows.py         # RepoRow and status chip widgets
  theme.py        # colour tokens + stylesheet
  jobs.py         # SyncTask / Lookup QRunnables and signals
  pages/
    library.py    # the table/filters
    detail.py     # one repository
    settings.py   # config.toml editor
```

Reuse `discovery`, `sync`, `report`, `config`, `runtime` unchanged.

### Worker and cancellation

`sync_report` is blocking, so wrap it in a `QRunnable`. Progress already arrives
through the `progress(index, total, label)` callback; emit it as a Qt signal.
Add an `Event` parameter to `sync_report`/`status_report` and check it between
repos, so Cancel is responsive without killing a git process mid-write.

### Technology choice

| Option | Feel | Dependencies | Notes |
|---|---|---|---|
| **PySide6** | Native, closest to AppGlider | ~100–200 MB, optional extra | Best fit if you want the AppGlider experience; strict typing works |
| Tkinter | Dated but serviceable | none (stdlib) | Quick prototype, weak theming, no tray |
| Local web UI (`http.server` + HTML/JS) | Browser-based, easy to style | none (stdlib) | Zero Python deps; no tray; one more window |
| Textual / Rich | Terminal TUI | Textual/Rich | Nice, but not a desktop GUI |

**Recommendation:** keep the core stdlib-only and add PySide6 as an optional extra
(`repopull[gui]`). That preserves the current zero-dependency CLI while giving the
GUI the same feel as AppGlider. If you would rather not add a 100 MB dependency, the
local web UI is the strongest zero-dependency option.

### Phased plan

1. Read-only Library: discover, fetch status, rows and chips, "last checked".
2. Sync all + progress + cancel.
3. Detail page and per-repo log.
4. Settings (root path with Check, delay, submodules, LFS).
5. Force sync with confirmation.
6. Tray and notifications (only if the app is meant to run in the background).

## 5. Licensing note

AppGlider is **GPL-3.0-or-later**. Take ideas, architecture and interaction
patterns from it, but do not copy its code into `repopull` unless `repopull`
adopts a GPL-compatible licence. The palette and layout above are our own
restatement, not a copy.
For the full documentation index, see [README.md](../README.md#documentation-index).
