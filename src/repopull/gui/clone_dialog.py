"""The Clone dialog: one URL, one folder name, and a clear destination."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from repopull.clone import (
    CloneError,
    derive_name,
    destination_for,
    validate_name,
    validate_url,
)


class CloneDialog(QDialog):
    """Ask for a repository address and a new folder name."""

    def __init__(self, root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root = root
        self._name_touched = False
        self.setWindowTitle("Clone repository")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)

        intro = QLabel(
            "Clone a repository into the watched folder. Existing folders "
            "are never overwritten, and repopull never pushes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addSpacing(4)
        layout.addWidget(QLabel("Repository URL"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://github.com/owner/repo.git  or  git@host:owner/repo.git"
        )
        self.url_edit.setClearButtonEnabled(True)
        layout.addWidget(self.url_edit)

        layout.addWidget(QLabel("Folder name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("derived from the URL")
        layout.addWidget(self.name_edit)

        self.preview = QLabel("")
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        layout.addSpacing(4)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.clone_button = self.buttons.addButton(
            "Clone", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.url_edit.textChanged.connect(self._on_url_changed)
        self.name_edit.textChanged.connect(self._refresh)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self._refresh()

    def values(self) -> tuple[str, str]:
        """Validated URL and folder name; only call after `accept()`."""
        url, name, error = self._validate()
        if error:
            raise CloneError(error)
        return url, name

    def _on_url_changed(self) -> None:
        if not self._name_touched:
            suggestion = derive_name(self.url_edit.text())
            with QSignalBlocker(self.name_edit):
                self.name_edit.setText(suggestion)
        self._refresh()

    def _on_name_edited(self) -> None:
        self._name_touched = True
        self._refresh()

    def _validate(self) -> tuple[str, str, str]:
        try:
            url = validate_url(self.url_edit.text())
        except CloneError as exc:
            return "", "", str(exc)

        try:
            name = validate_name(self.name_edit.text())
        except CloneError as exc:
            return url, "", str(exc)

        try:
            destination = destination_for(self._root, name)
        except CloneError as exc:
            return url, name, str(exc)
        if not os.access(self._root, os.W_OK | os.X_OK):
            return url, name, f"The watched folder is not writable: {self._root}"
        if os.path.lexists(destination):
            return url, name, f"A folder already exists at {destination}"
        return url, name, ""

    def _refresh(self) -> None:
        _url, name, error = self._validate()
        self.preview.setText(
            f"Creates {self._root / name}" if name else f"Inside {self._root}"
        )
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.clone_button.setEnabled(not error)

    def accept(self) -> None:
        _url, _name, error = self._validate()
        if error:
            self._refresh()
            return
        super().accept()
