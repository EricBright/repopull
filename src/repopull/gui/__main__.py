"""Allow `python -m repopull.gui`."""

from __future__ import annotations

from repopull.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
