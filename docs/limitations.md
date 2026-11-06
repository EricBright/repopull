# Limitations

- Does not clone missing repositories; it only syncs what exists.
- Does not switch branches or fetch branches other than the current tracking branch.
- Does not install `git-lfs`.
- The CLI has no scheduler; the GUI's status-only automatic refresh runs only while the app is running.
- No desktop notifications; status is in the window, tray, and logs.
- The GUI is still a dark-only prototype, with no per-repository normal-sync selection.
- Not intended for repositories you own or contribute to, since there is no push path.

For the full documentation index, see [README.md](../README.md#documentation-index).
