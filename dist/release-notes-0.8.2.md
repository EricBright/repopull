# repopull 0.8.2

This release is about a countdown that started in the wrong place: the app
found the watched folder at login and then, for hours, did nothing.

## The interval restarted at every launch

Status refresh is a countdown from the last completed check. The window kept
that anchor only in memory, so it was empty at every start, and the decision
table read that empty anchor two different ways: the timer event treated it as
due, the schedule event as "wait a whole interval". A launch long after the
last check still waited the full interval before touching the network, and the
window's own "watched folder found; scanning it now." was the last thing that
happened. The record of the last check existed on disk all along in
`logs/latest.json`; nothing read it back for scheduling.

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

The bug reproduced before the change: a fixture of three repositories, a
three-hour interval, and no anchor in the session — the timer was armed 10,805
seconds out. After it: no saved check and a two-day-old check both arm at zero,
a check ten minutes old arms 10,201 seconds out, a clock that jumped backwards
arms the full interval, and an all-excluded or unwritable library defers one
interval without spinning. 437 tests, mypy strict, `make audit` clean.

End to end on a real watched root: with an old saved brief in place, a hidden
launch of this image took the run lock within a minute and completed a status
sweep in about three minutes. The same launch before the fix would have waited
out the whole three-hour interval.

## Installing

```bash
chmod +x repopull-0.8.2-x86_64.AppImage
./repopull-0.8.2-x86_64.AppImage
```

Gear Lever and AppImageUpdate can update an installed copy from the release
assets, using the embedded `gh-releases-zsync` information and the published
`.zsync`. repopull still never replaces its own image.

`SHA256SUMS.txt` covers the image and its `.zsync`.
