# repopull 0.8.3

Two related fixes for starting up: the app now recognises a watched folder
that is not ready yet, and it gives a freshly started system a moment to
settle before asking it for anything.

## An unreadable watched folder means "not ready yet", not a failure

A scan that lands while a removable disk is still mounting fails with
permission denied rather than not found: the kernel cannot search a path whose
mount has not finished. repopull already had a recovery path for "not found" —
probe every 5 seconds for up to 10 minutes and rescan when the folder appears
— but the readiness check used `Path.exists()`, which raises
`PermissionError` on some Python versions and returns `False` on others, and it
ran inside the scan-failure handler. On a raising version the handler died
before arming the probe, so the window sat on a raw errno until **Try again**
was clicked.

- Every caller now asks one question through `root_condition()`: a single raw
  `os.stat` classified as ready, missing, inaccessible, or not a directory.
  Anything other than ready means "not usable yet" — wait and retry.
- The message says what is happening: "`<path>` isn't accessible yet — the disk
  may still be mounting", with the usual "checking again every 5 s" note
  underneath, and giving up says "still not accessible" rather than "still
  missing".
- A sweep that hits an unreadable root stops like one that hits a vanished
  disk — the remaining repositories are `not attempted: watched folder
  disappeared` — and `repopull where` reports `inaccessible`.
- [Decision 47](https://github.com/EricBright/repopull/blob/main/docs/design-decisions.md#47-an-unreadable-watched-root-is-not-ready-yet-not-a-failure)
  records the rule.

## A quiet period after start

Login is the busiest moment of a session: disks are still mounting and session
services are still starting. The new `startup_delay_s` (Settings → **Startup**,
10–30 seconds, default 10, and no way to turn it off) holds back the first
scan — and with it anything due to run, since refresh and sync cannot start
until discovery returns repositories — from the moment a GUI window starts.
During the wait the library says "Starting up — the watched folder will be
scanned in N s…". Unattended runs (`--screenshot`, `--smoke-test`) scan
immediately.
[Decision 48](https://github.com/EricBright/repopull/blob/main/docs/design-decisions.md#48-let-the-system-settle-before-the-first-demand)
records the rule.

## Verifying the fix

The unreadable-root tests reproduce a mid-mount path with a real unsearchable
directory at every seam — classification, discovery, the window's wait and
give-up, the sweep, and `where` — and skip only when running as a privileged
user, whom directory modes do not restrict. An end-to-end launch held its
first scan for the full delay and completed it right after. 450 tests,
mypy strict, `make audit` clean.

## Installing

```bash
chmod +x repopull-0.8.3-x86_64.AppImage
./repopull-0.8.3-x86_64.AppImage
```

Gear Lever and AppImageUpdate can update an installed copy from the release
assets, using the embedded `gh-releases-zsync` information and the published
`.zsync`. repopull still never replaces its own image.

`SHA256SUMS.txt` covers the image and its `.zsync`.
