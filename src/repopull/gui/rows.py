"""Row and status-chip widgets for the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from repopull.gui.theme import STATUS_COLORS, rgba
from repopull.models import Outcome, Row


@dataclass(frozen=True, slots=True)
class RowView:
    """What one library row should say.

    The chip carries only a state or a per-repository policy; numbers live in
    the subtitle, where long values cannot overflow the fixed-width chip.
    """

    label: str
    branch: str
    status: str
    kind: str
    detail: str
    count_text: str = ""
    count_color: str = ""
    hint: str = ""


_CHIP_TEXT: dict[Outcome, str] = {
    Outcome.UPDATED: "Up to date",
    Outcome.UP_TO_DATE: "Up to date",
    Outcome.BEHIND: "Behind",
    Outcome.SKIPPED: "Skipped",
    Outcome.ERROR: "Error",
}

_CHIP_KIND: dict[Outcome, str] = {
    Outcome.UPDATED: "ok",
    Outcome.UP_TO_DATE: "ok",
    Outcome.BEHIND: "warn",
    Outcome.SKIPPED: "held",
    Outcome.ERROR: "danger",
}


def _count(value: int) -> str:
    return f"{value:,}"


def _commits(value: int) -> str:
    return f"{_count(value)} commit" + ("" if value == 1 else "s")


def _event_text(row: Row) -> str:
    """Describe what the last sync did, as history rather than fresh state."""
    if row.detail:
        return f"{row.detail} at last sync"
    if row.commits:
        return f"{_commits(row.commits)} pulled at last sync"
    return ""


def row_view(
    row: Row,
    *,
    no_checks: bool = False,
    no_sync: bool = False,
) -> RowView:
    """Turn a report row into a display row, honouring bulk-action holds.

    A repository excluded from Refresh status has a stale report row, so it
    never shows a number. One excluded only from Sync all is still refreshed,
    so its behind count is trustworthy and moves to the subtitle.
    """
    count_text = ""
    count_color = ""
    detail = row.detail

    if no_checks:
        status = "No checks/sync" if no_sync else "No checks"
        hint = (
            "Excluded from both bulk actions. Use the buttons on this page."
            if no_sync
            else "Excluded from Refresh status and automatic checks. "
            "Sync all can still update this repo."
        )
        return RowView(
            label=row.label,
            branch=row.branch,
            status=status,
            kind="neutral",
            detail="",
            hint=hint,
        )

    if no_sync:
        if row.outcome is Outcome.BEHIND and row.commits:
            count_text = f"{_commits(row.commits)} behind"
            count_color = STATUS_COLORS["warn"]
        elif row.outcome is Outcome.UPDATED:
            detail = ""
        return RowView(
            label=row.label,
            branch=row.branch,
            status="No sync",
            kind="neutral",
            detail=detail,
            count_text=count_text,
            count_color=count_color,
            hint="Excluded from Sync all and Sync these. Refresh status still "
            "runs; Sync this repo still works.",
        )

    status = _CHIP_TEXT[row.outcome]
    if row.outcome is Outcome.BEHIND and row.commits:
        count_text = f"{_commits(row.commits)} behind"
        count_color = STATUS_COLORS["warn"]
    elif row.outcome is Outcome.UPDATED:
        count_text = _event_text(row)
        detail = ""

    return RowView(
        label=row.label,
        branch=row.branch,
        status=status,
        kind=_CHIP_KIND[row.outcome],
        detail=detail,
        count_text=count_text,
        count_color=count_color,
    )


def unchecked_view(
    label: str,
    *,
    no_checks: bool = False,
    no_sync: bool = False,
) -> RowView:
    """A repository with no saved result yet."""
    if no_checks:
        status = "No checks/sync" if no_sync else "No checks"
    elif no_sync:
        status = "No sync"
    else:
        status = "Not checked"
    hint = ""
    if no_checks and no_sync:
        hint = "Excluded from both bulk actions."
    elif no_checks:
        hint = "Excluded from Refresh status and automatic checks."
    elif no_sync:
        hint = "Excluded from Sync all and Sync these."
    return RowView(
        label=label,
        branch="-",
        status=status,
        kind="neutral",
        detail="",
        hint=hint,
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

        self.chip = QLabel()
        self.chip.setFixedWidth(132)
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.chip)

        self.chevron = QLabel("›")
        self.chevron.setObjectName("Faint")
        layout.addWidget(self.chevron)

        for label in (
            self.name_label,
            self.sub_label,
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
        parts = [escape(view.branch)]
        if view.detail:
            parts.append(escape(view.detail))
        if view.count_text:
            count = escape(view.count_text)
            if view.count_color:
                count = (
                    f'<span style="color:{view.count_color}; '
                    f'font-weight:600;">{count}</span>'
                )
            parts.append(count)
        self.sub_label.setTextFormat(Qt.TextFormat.RichText)
        self.sub_label.setText(" · ".join(parts))
        color = STATUS_COLORS.get(view.kind, STATUS_COLORS["neutral"])
        self.chip.setText(view.status)
        self.chip.setStyleSheet(
            f"background: {rgba(color, 0.14)}; color: {color};"
            "border-radius: 10px; padding: 3px 9px;"
            "font-size: 12px; font-weight: 600;"
        )
        self.setToolTip(
            " · ".join(
                part
                for part in (view.branch, view.detail, view.count_text)
                if part
            )
            + (f"\n{view.hint}" if view.hint else "")
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit(self.view.label)
        super().mousePressEvent(event)
