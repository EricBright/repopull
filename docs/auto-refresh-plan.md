# Auto-refresh and system tray plan (0.4.0)

**Status:** implemented in 0.4.0; 0.4.1 tray/Wayland; 0.4.2 checkbox cosmetics; 0.4.3 immediate persistence; kept as the plan record.

## Current local state / session handoff (2026-11-05)

0.4.3 is accepted, released, and remote `main` was fast-forwarded. No force was
used.

- `dev`, `main`, and `stable` are aligned on 0.4.3; remote `main` contains the
  follow-up documentation commit.
- Tag/release: `v0.4.3` (`b099ea1`), the latest release at the time.
- 119 tests; mypy clean on 21 files; GitHub Actions CI green.
- Local AppImage: `dist/repopull-0.4.3-x86_64.AppImage`,
  SHA-256 `26e5f40a4ef65059b095aa25bd7fdfb1d20b39a89d9f2c6ca6e0737806872045`;
  the release asset matches.
- 0.4.3 makes background and automatic-refresh controls apply and persist
  immediately. It also carries the visible checkbox indicators, literal
  `Background & refresh`, editable interval, always-visible tray icon, and
  Wayland preference with XCB fallback.
- No known release blockers.
- Next session: run `make check`; then choose the next QoL or test-coverage
  item. The 0.2.3 audit's surviving mutants are the largest known coverage gap.
  Start from [README.md](../README.md) and this plan.


## Phases

1. **Durable lifecycle:** atomic report writes, lock regression test, graceful
   shutdown, single-instance guard. No tray/auto UI yet.
2. **Policy/config:** refresh module, config fields, clamp, scheduler, tests.
3. **Settings/tray:** Background & refresh controls, symbolic asset, tray,
   close-to-tray, availability fallback, tests/docs.
4. **Verify/release:** soak, CI, AppImage, 0.4.0, release.

## Out of scope

- Login/autostart (systemd user service).
- Desktop notifications (tray tooltip only for now).
- Auto-sync or tray-triggered sync.
- Log compression/archiving.
- Minimize-to-tray; this plan uses close-to-tray only.

For the full documentation index, see [README.md](../README.md#documentation-index).
