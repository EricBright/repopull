# repopull 0.8.2

This release is about a countdown that started in the wrong place. The app
found the watched folder at login and then, for hours, did nothing.

## The interval restarted at every launch

Status refresh is a countdown from the last completed check. On 2026-11-15 the
window started at 12:06, found the watched folder six seconds later, said
"Watched folder found; scanning it now.", listed all 41 repositories — and did
not touch the network again. The last completed check was two days old and the
interval is three hours, so it should have run at once. It was armed for 15:07.

The anchor for that countdown lived only in memory, and it was empty at every
start. Worse, the decision table read the empty anchor two different ways: the
timer event treated it as due, the schedule event as "wait a whole interval".
Two days of history were on disk in `logs/latest.json` the whole time; nothing
read them back for scheduling.

- The saved check is read at startup and converted once into the monotonic
  clock the timers use, so a launch continues the countdown instead of
  restarting it. An overdue check now runs within a minute of the window
  opening, and a launch minutes after a check waits only the remainder.
- "No completed check" means due now, in both events. A first run with no saved
  brief checks at once rather than one interval later.
- A check that is due but cannot start — every repository held out of status
  refresh, or a log directory that refuses a run — waits a full interval
  instead of re-deciding the same due state every few seconds and re-flashing
  the same message.
- The interval counts the repositories that survive the refresh exclusions, so
  a library where everything is held no longer looks like work waiting to run.

The scheduling policy is still a pure table with no Qt and no clock of its own:
[decision 46](https://github.com/EricBright/repopull/blob/main/docs/design-decisions.md#46-measure-the-interval-from-the-last-completed-check-not-from-launch)
records the rule.

## Verifying the fix

The bug reproduced before the change: three repositories, a three-hour
interval, no anchor in the session — the timer was armed 10,805 seconds out.
After it: no saved check and a two-day-old check both arm at zero, a check ten
minutes old arms 10,201 seconds out, a clock that jumped backwards arms the full
interval, and an all-excluded or unwritable library defers one interval without
spinning. 437 tests, mypy strict, `make audit` clean.

End to end on the real watched root: with the brief from two days earlier in
place, a hidden launch of this image took the run lock 40 seconds later and
completed a status sweep in 193 s (25 behind, 20 up to date, 1 error). The same
launch before the fix would have waited out the whole three-hour interval.

## Installing

```bash
chmod +x repopull-0.8.2-x86_64.AppImage
./repopull-0.8.2-x86_64.AppImage
```

Gear Lever and AppImageUpdate can update an installed copy from the release
assets, using the embedded `gh-releases-zsync` information and the published
`.zsync`. repopull still never replaces its own image.

`SHA256SUMS.txt` covers the image and its `.zsync`.
