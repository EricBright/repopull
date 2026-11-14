# Limitations

- Runs on Linux: the CLI takes its run lock with `fcntl.flock` and reads
  `/proc/self/mountinfo` for root identity, and the GUI targets Linux desktops.
- A SIGKILL of repopull may leave a process that `git` forked, such as a remote
  helper. Timeout and cancellation kill the whole process group; only a SIGKILL
  of repopull itself is outside that path.
- Clone needs a non-interactive address: public HTTPS repositories work, while
  private ones need an SSH agent or a configured credential helper because
  repopull never prompts. A remote that requires a password fails.
- Clone is bounded by `clone_timeout_s` (default 30 minutes); very large
  repositories need a higher value or the CLI. Submodules initialize on the
  first sync, not during the clone.
- Clone creates one new folder; it cannot replace an existing repository or
  clone several repositories at once.
- Clone progress comes from git on stderr, so a local clone that git serves
  with hardlinks (same filesystem) reports only start and finish; there is
  nothing for it to report in between.
- Does not switch local branches or fast-forward any local branch other than the
  current tracking branch. A normal `git fetch` still updates the remote's
  configured remote-tracking refs.
- Does not install `git-lfs`.
- The CLI has no scheduler; the GUI's status-only automatic refresh runs only while the app is running.
- No desktop notifications; status is in the window, tray, and logs.
- The GUI is dark-only, with no per-repository normal-sync selection.
- Not intended for repositories you own or contribute to, since there is no push path.
- Shell completion covers commands, options and paths, not repository labels.
  Offering labels would scan the watched root on every TAB, which stalls when
  the library is on an external disk; narrow a run with `--only GLOB` instead.
- Completion ships for bash and fish. Zsh uses its `bashcompinit` emulation of
  the bash script; there is no native zsh completion.
- repopull never replaces its own image. **version --check** and the Settings
  check only report; installing the new AppImage is the user's job, or Gear
  Lever's once it sees the embedded update information.
- The update check is a GitHub API call: it needs network, the unauthenticated
  rate limit applies, and a failed check says so instead of retrying in the
  background.
- Autostart is a per-user XDG `.desktop` entry, not a systemd unit: repopull
  starts once at login and is not restarted if it later exits. Moving the
  AppImage is repaired on the next launch, but deleting it leaves an entry that
  fails until it is removed in the desktop's autostart panel.
- Starting hidden (`--hidden`) needs a tray host. Without one repopull shows the
  window instead, and a hidden window whose tray host appears later is not
  resurrected in that session.
- After a power cut, git can leave `.git/*.lock` files or a half-applied
  fast-forward behind. repopull names the lock file in the error and never
  deletes it: removing another process's lock, or resetting a worktree, is how
  a tool destroys work. A repository left dirty by an interrupted update keeps
  reporting as skipped until you look at it with `git status`.
- A watched folder on a removable disk can be missing when the window starts at
  login. repopull then probes the path every 5 s for up to 10 minutes and scans
  as soon as it appears, but a disk that mounts later than that stays
  unwatched until the next refresh or **Try again**. The probe is a path
  check, not a udev or udisks subscription, so there is a delay of up to 5 s
  even after the mount lands.

For the full documentation index, see [README.md](../README.md#documentation-index).
