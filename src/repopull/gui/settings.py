"""Building blocks for the Settings page: titled cards and title/hint rows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

SETTINGS_SECTIONS = ("Watching", "Refresh", "Network", "Updates", "Storage")


class SettingsCard(QFrame):
    """A titled surface holding one or more setting rows."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsCard")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 14, 18, 14)
        self._layout.setSpacing(10)

        heading = QLabel(title.upper())
        heading.setObjectName("CardHeading")
        self._layout.addWidget(heading)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(10)
        self._layout.addLayout(self._body)
        self._rows = 0

    def add(self, widget: QWidget) -> None:
        """Add a row, with a hairline separator between rows."""
        if self._rows:
            separator = QFrame()
            separator.setObjectName("SettingSeparator")
            separator.setFixedHeight(1)
            self._body.addWidget(separator)
        self._body.addWidget(widget)
        self._rows += 1

    def add_note(self, label: QLabel) -> None:
        """Add explanatory text at this point in the card."""
        self._body.addWidget(label)


class SettingRow(QWidget):
    """A setting title and hint, with its control beside or below them."""

    def __init__(
        self,
        title: str,
        hint: str = "",
        control: QWidget | None = None,
        *,
        below: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("SettingTitle")
        self.title_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("SettingHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(hint))
        text_layout.addWidget(self.hint_label)

        layout: QBoxLayout
        if below:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(text)
            if control is not None:
                control.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                layout.addWidget(control)
        else:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(16)
            layout.addWidget(text, 1)
            if control is not None:
                layout.addWidget(
                    control, 0, Qt.AlignmentFlag.AlignVCenter
                )

        self.control = control
