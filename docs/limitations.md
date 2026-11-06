# Limitations

- Does not clone missing repositories; it only syncs what exists.
- Does not switch local branches or fast-forward any local branch other than the
  current tracking branch. A normal `git fetch` still updates the remote's
  configured remote-tracking refs.
- Does not install `git-lfs`.
- The CLI has no scheduler; the GUI's status-only automatic refresh runs only while the app is running.
- No desktop notifications; status is in the window, tray, and logs.
- The GUI is dark-only, with no per-repository normal-sync selection.
- Not intended for repositories you own or contribute to, since there is no push path.

For the full documentation index, see [README.md](../README.md#documentation-index).
