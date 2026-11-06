# Auto-refresh and system tray plan (0.4.0)

**Status:** implemented in 0.4.0; 0.4.1 tray/Wayland; 0.4.2 checkbox cosmetics; 0.4.3 immediate persistence; kept as the plan record.

## Current local state / handoff (2026-11-05)

0.4.3 was accepted and remote `main` was fast-forwarded from the 0.4.1 WIP
commit. No force was used.

- `dev`, `main`, and `stable` are aligned at 0.4.3; remote `main` is current.
- 119 tests; mypy clean on 21 files; GitHub Actions CI is green.
- Latest release is still 0.4.0; there is no 0.4.3 tag or release yet.
- Local 0.4.3 AppImage: `dist/repopull-0.4.3-x86_64.AppImage`,
  SHA-256 `26e5f40a4ef65059b095aa25bd7fdfb1d20b39a89d9f2c6ca6e0737806872045`.
- 0.4.3 makes background and automatic-refresh controls apply and persist
  immediately (targeted writer preserves comments/other keys).
- Tray icon is shown whenever the app runs; Wayland preferred with XCB fallback.
- Next: decide whether to publish 0.4.3 (tag + AppImage release). Future work
  stays local-first; push only accepted stable changes.


## Phases

1. **Durable lifecycle:** atomic report writes, lock regression test, graceful
   shutdown, single-instance guard. No tray/auto UI yet.
2. **Policy/config:** refresh module, config fields, clamp, scheduler, tests.
3. **Settings/tray:** Background & refresh controls, symbolic asset, tray,
   close-to-tray, availability fallback, tests/docs.
4. **Verify/release:** soak, CI, AppImage, 0.4.0, private release.

## Out of scope

- Login/autostart (systemd user service).
- Desktop notifications (tray tooltip only for now).
- Auto-sync or tray-triggered sync.
- Log compression/archiving.
- Minimize-to-tray; this plan uses close-to-tray only.

For the full documentation index, see [README.md](../README.md#documentation-index).
