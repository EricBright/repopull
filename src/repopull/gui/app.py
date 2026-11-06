"""GUI entry point."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from repopull.config import ConfigError, load_config

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon


def build_app_icon() -> QIcon:
    """Window/taskbar icon, with optical cuts for the sizes Qt requests."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    icon = QIcon()
    assets = Path(__file__).resolve().parent / "assets"
    for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
        path = assets / f"repopull-{size}.png"
        if path.is_file():
            icon.addFile(str(path), QSize(size, size))
    return icon


def main(argv: Sequence[str] | None = None) -> int:
    """Run the desktop interface and return a process exit code."""
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="repopull-gui",
        description="Desktop interface for repopull.",
    )
    parser.add_argument("--root", type=Path, help="watched repositories directory")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start offscreen, print a row count, and exit",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        metavar="PNG",
        help="render the window to a PNG and exit",
    )
    args = parser.parse_args(raw)

    if args.smoke_test or args.screenshot is not None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    elif sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        # Qt defaults to XCB on some images; XEmbed tray icons are not shown by
        # KDE Plasma's Wayland tray. Prefer Wayland, then fall back to XCB.
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

    # Imported after QT_QPA_PLATFORM is set, so the offscreen platform is used.
    from PySide6.QtWidgets import QApplication

    from repopull.gui.theme import stylesheet
    from repopull.gui.window import MainWindow

    app = QApplication(["repopull-gui"])
    app.setApplicationName("repopull")
    app.setDesktopFileName("repopull")
    app.setWindowIcon(build_app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    app.setQuitOnLastWindowClosed(False)

    try:
        config = load_config(config_path=args.config, root_override=args.root)
    except ConfigError as exc:
        print(f"repopull-gui: {exc}", file=sys.stderr)
        return 2

    try:
        config.log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"repopull-gui: cannot create log directory: {exc}",
            file=sys.stderr,
        )
        return 2

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox

    instance = QLockFile(str(config.log_dir / ".gui.lock"))
    if not instance.tryLock(100):
        QMessageBox.warning(None, "repopull", "repopull is already running.")
        return 1

    try:
        window = MainWindow(config)

        def request_quit(*_args: object) -> None:
            window.request_quit()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, request_quit)

        if args.screenshot is not None:
            window.show()
            app.processEvents()
            if not window.grab().save(str(args.screenshot)):
                print(
                    f"repopull-gui: could not write {args.screenshot}",
                    file=sys.stderr,
                )
                return 2
            return 0

        if args.smoke_test:
            window.show()
            app.processEvents()
            print(f"GUI smoke test: {window.visible_row_count()} rows visible")
            return 0

        window.show()
        return int(app.exec())
    finally:
        instance.unlock()
