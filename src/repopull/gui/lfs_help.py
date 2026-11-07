"""Read-only Git LFS help: explain it, show the commands, run nothing."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from repopull.diagnostics import LfsStatus


class LfsHelpDialog(QDialog):
    """What Git LFS is, and the commands to install and enable it."""

    def __init__(self, status: LfsStatus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Git LFS")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "Git LFS stores large files (images, audio, CAD files) outside the "
            "normal Git history. Without it, an LFS repository checks out small "
            "pointer files instead of the real content."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        version = f" ({status.version})" if status.version else ""
        detail = QLabel()
        detail.setWordWrap(True)
        if not status.installed:
            detail.setText("Git LFS is not installed.")
        elif not status.enabled:
            detail.setText(
                f"Git LFS is installed{version}, but it is not enabled yet."
            )
        else:
            detail.setText(f"Git LFS is installed and enabled{version}.")
        layout.addWidget(detail)

        step = 1
        if not status.installed:
            self._command(layout, f"{step}. Install it", status.install_hint)
            step += 1
        if not status.installed or not status.enabled:
            self._command(layout, f"{step}. Enable it once", "git lfs install")
            after = QLabel("Then use Refresh status in repopull to check again.")
            after.setObjectName("Muted")
            after.setWordWrap(True)
            layout.addWidget(after)

        links = QHBoxLayout()
        learn = QPushButton("Learn more")
        learn.setObjectName("Ghost")
        learn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(status.docs_url))
        )
        links.addWidget(learn)
        links.addStretch(1)
        layout.addLayout(links)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _command(
        self, layout: QVBoxLayout, title: str, command: str
    ) -> None:
        layout.addWidget(QLabel(title))
        row = QHBoxLayout()
        field = QLineEdit(command)
        field.setTextMargins(12, 0, 12, 0)
        field.setReadOnly(True)
        field.setToolTip("Select and copy this command")
        row.addWidget(field, 1)
        copy = QPushButton("Copy")
        copy.setObjectName("Ghost")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(command)
        )
        row.addWidget(copy)
        layout.addLayout(row)
