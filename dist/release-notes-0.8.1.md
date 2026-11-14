# repopull 0.8.1

This release is about hardware that goes away: a removable disk that is not
mounted yet when repopull starts at login, or one that vanishes while it is
watching. Both used to leave the window showing a wall of errors until you
touched something. They now recover on their own.

## A watched disk that is late or unplugged

Starting at login puts the first scan in a race with the mount of a removable
disk. On 2026-11-12 the window started 1.3 s before the disk was mounted, found
no watched folder, showed the error, and — because a run with no repositories
waits a whole refresh interval — did not look again for three hours. Reselecting
the same folder "fixed" it only because that rescans.

- While the path is missing, repopull probes it every 5 s for up to 10 minutes
  and scans the moment it appears.
- A sweep that finds the folder gone (an unplugged USB cable, a driver hiccup)
  stops at once instead of reporting every repository as broken: the rest are
  `not attempted: watched folder disappeared`, the status bar says the folder is
  missing, and the same probe waits for it.
- The probe also starts after a resume from suspend and after any failed run.
- **Try again** in the empty library rescans immediately, for any failed scan.
- The reason a scan failed, and the give-up, are written to stderr, which
  systemd keeps in the journal for `app-repopull@autostart.service`.

## Surviving a power cut

The state files were already safe: `config.toml`, `root-state.json`,
`latest.json` and the UI state are written through a temp file and a rename, so
a cut leaves the old file or the new one, never half of either. Three loose ends
are closed:

- The autostart entry is fsynced before its rename. It was the one file a cut
  could leave empty, which starts nothing at the next login.
- A `.repopull-clone-*` folder left by a clone that was killed is removed by the
  next scan once it is a day old. Discovery skipped these folders but nothing
  deleted them, so a partial clone could sit in the watched root for good.
- A failure caused by a stale `.git/*.lock` now names the file and says what
  leaves one behind. repopull still never deletes a lock: another process may
  hold it, and a pull-only tool should not repair a repository behind your back.
  For the same reason an interrupted fast-forward that left a worktree dirty is
  still reported as skipped, not reset.

The "watched root is not writable" message now also names a read-only mount,
which is what an unclean shutdown can leave behind.

## Installing

```bash
chmod +x repopull-0.8.1-x86_64.AppImage
./repopull-0.8.1-x86_64.AppImage
```

Gear Lever and AppImageUpdate can update an installed copy from the release
assets, using the embedded `gh-releases-zsync` information and the published
`.zsync`. repopull still never replaces its own image.

`SHA256SUMS.txt` covers the image and its `.zsync`.
