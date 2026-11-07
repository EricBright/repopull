# Troubleshooting

**A repo reports "empty repository: no commits".**
It is an incomplete clone (no objects, no refs). Re-clone it, or repair it with
the repo's actual branch:

```bash
git -C <path-to-repo> fetch origin
git -C <path-to-repo> reset --hard origin/<branch>
```

**A repo reports "uses Git LFS but git-lfs is not installed" or "not enabled".**
Git LFS stores large files outside normal Git history. In the GUI, open
**Settings → Updates → Git LFS → Help…** for the install command for your
distribution; then run `git lfs install` once and press **Check again** in
Settings → Updates (or reopen Settings). From the CLI:

```bash
brew install git-lfs      # Bazzite/Fedora atomic; use your package manager elsewhere
git lfs install
./repopull.sh status
```

Until then the repo is skipped on purpose: checking it out without LFS would
replace its images with pointer text.

**A repo is skipped as "dirty" or "diverged".**
Inspect it (`git -C <repo> status`, `git -C <repo> log --oneline @{u}..`), then use
**Force sync** if the local state is incidental. The user never edits these repos,
so force is usually the right repair.

**"another repopull run is in progress".**
A previous run still holds `logs/.lock`. Wait for it, or check for a stuck
`repopull` process.

**"watched root does not exist" / `where` says `MISSING`.**
The watched disk is probably not mounted, or the folder moved. Run
`./repopull.sh where` to see the exact path and where it came from, then either
mount the disk, copy [`config.example.toml`](../config.example.toml) to
`config.toml`, and edit `root`, or run with `--root PATH` for one run.
`repopull` prints those same steps when it fails.

**"watched root is on a different device/filesystem than last time".**
This guard catches a different disk mounted at the watched path. Device numbers
can also change after a reboot without the disk changing; btrfs in particular
uses an anonymous `0:N` device number. Newer state files compare the filesystem
UUID, so that case is accepted automatically. A state file from 0.4.14 or
earlier has no UUID and may need one repair:

- In the GUI, click **Repair saved root state** and compare the saved and
  current identities before confirming.
- From the CLI, run `./repopull.sh repair-root` to preview, then
  `./repopull.sh repair-root --yes` only if the current disk is the expected
  one.

If the current filesystem UUID differs, stop: the wrong disk may be mounted.
Deleting `logs/root-state.json` also accepts the current disk, but skips the
comparison.

For the full documentation index, see [README.md](../README.md#documentation-index).
