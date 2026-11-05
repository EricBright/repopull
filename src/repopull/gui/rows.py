"""Row and status-chip widgets for the GUI."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from repopull.gui.theme import STATUS_COLORS, rgba
from repopull.models import Outcome, Row


@dataclass(frozen=True, slots=True)
class RowView:
    """What one library row should say."""

    label: str
    branch: str
    status: str
    kind: str
    commits: int
    detail: str


_CHIP_TEXT: dict[Outcome, str] = {
    Outcome.UPDATED: "✓ Updated",
    Outcome.UP_TO_DATE: "✓ Up to date",
    Outcome.BEHIND: "↑ Behind",
    Outcome.SKIPPED: "‖ Skipped",
    Outcome.ERROR: "⚠ Error",
}

_CHIP_KIND: dict[Outcome, str] = {
    Outcome.UPDATED: "ok",
    Outcome.UP_TO_DATE: "ok",
    Outcome.BEHIND: "warn",
    Outcome.SKIPPED: "held",
    Outcome.ERROR: "danger",
}


def row_view(row: Row) -> RowView:
    """Turn a report row into a display row."""
    status = _CHIP_TEXT[row.outcome]
    if row.outcome is Outcome.BEHIND and row.commits:
        status = f"↑ {row.commits} behind"
    return RowView(
        label=row.label,
        branch=row.branch,
        status=status,
        kind=_CHIP_KIND[row.outcome],
        commits=row.commits,
        detail=row.detail,
    )


def unchecked_view(label: str) -> RowView:
    """A repository with no saved result yet."""
    return RowView(
        label=label,
        branch="-",
        status="○ Not checked",
        kind="neutral",
        commits=0,
        detail="",
    )


class RepoRow(QFrame):
    """One clickable repository row; `apply` updates it in place."""

    clicked = Signal(str)

    def __init__(self, view: RowView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = view
        self.setObjectName("RepoRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.sub_label = QLabel()
        self.sub_label.setObjectName("Faint")
        text.addWidget(self.name_label)
        text.addWidget(self.sub_label)
        layout.addLayout(text, 1)

        self.commits_label = QLabel()
        self.commits_label.setObjectName("Muted")
        self.commits_label.setFixedWidth(52)
        self.commits_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.commits_label)

        self.chip = QLabel()
        layout.addWidget(self.chip)

        self.chevron = QLabel("›")
        self.chevron.setObjectName("Faint")
        layout.addWidget(self.chevron)

        for label in (
            self.name_label,
            self.sub_label,
            self.commits_label,
            self.chip,
            self.chevron,
        ):
            label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

        self.apply(view)

    def apply(self, view: RowView) -> None:
        """Update this row without rebuilding the list."""
        self.view = view
        self.name_label.setText(view.label)
        subtitle = view.branch
        if view.detail:
            subtitle = f"{view.branch} · {view.detail}"
        self.sub_label.setText(subtitle)
        self.commits_label.setText(str(view.commits) if view.commits else "")
        color = STATUS_COLORS.get(view.kind, STATUS_COLORS["neutral"])
        self.chip.setText(view.status)
        self.chip.setStyleSheet(
            f"background: {rgba(color, 0.14)}; color: {color};"
            "border-radius: 10px; padding: 3px 9px;"
            "font-size: 12px; font-weight: 600;"
        )
        self.setToolTip(view.detail)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit(self.view.label)
        super().mousePressEvent(event)
