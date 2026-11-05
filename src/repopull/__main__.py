"""Allow `python -m repopull`."""

from __future__ import annotations

from repopull.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
