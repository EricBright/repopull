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
- Autostart is a per-user XDG `.desktop` entry, not a systemd unit: repopull
  starts once at login and is not restarted if it later exits. Moving the
  AppImage is repaired on the next launch, but deleting it leaves an entry that
  fails until it is removed in the desktop's autostart panel.
- Starting hidden (`--hidden`) needs a tray host. Without one repopull shows the
  window instead, and a hidden window whose tray host appears later is not
  resurrected in that session.

For the full documentation index, see [README.md](../README.md#documentation-index).
