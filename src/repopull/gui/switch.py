"""A compact on/off switch built from a checkable Qt widget."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFocusEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QCheckBox, QWidget

from repopull.gui.theme import PALETTE


def _mix(off: QColor, on: QColor, position: float) -> QColor:
    """Blend two colours without pulling in another dependency."""
    return QColor(
        round(off.red() + (on.red() - off.red()) * position),
        round(off.green() + (on.green() - off.green()) * position),
        round(off.blue() + (on.blue() - off.blue()) * position),
    )


class Switch(QCheckBox):
    """A checkbox that paints as an animated switch.

    The widget keeps `QCheckBox` semantics for keyboard handling, focus, and
    accessibility; only its appearance and animation are custom.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(48, 28)
        self._position = 1.0 if self.isChecked() else 0.0
        self._hover = False
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(130)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to_state)

    def sizeHint(self) -> QSize:
        return QSize(48, 28)

    def minimumSizeHint(self) -> QSize:
        return QSize(48, 28)

    def hitButton(self, pos: QPoint) -> bool:
        return bool(self.rect().contains(pos))

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, position: float) -> None:
        self._position = position
        self.update()

    position = Property(float, _get_position, _set_position)

    def _animate_to_state(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not self.isVisible():
            self._animation.stop()
            self._set_position(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(3.0, 3.0, self.width() - 6.0, self.height() - 6.0)
        radius = rect.height() / 2.0
        position = max(0.0, min(1.0, self._position))
        enabled = self.isEnabled()

        if enabled:
            off_track = QColor(PALETTE.raised)
            on_track = QColor(PALETTE.accent)
            off_thumb = QColor(PALETTE.muted)
            on_thumb = QColor(PALETTE.text)
        else:
            off_track = QColor(PALETTE.surface2)
            on_track = QColor(PALETTE.raised)
            off_thumb = QColor(PALETTE.faint)
            on_thumb = QColor(PALETTE.faint)

        track = _mix(off_track, on_track, position)
        thumb = _mix(off_thumb, on_thumb, position)
        if enabled and self._hover:
            track = track.lighter(112)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)

        inset = 3.0
        diameter = rect.height() - inset * 2.0
        travel = rect.width() - inset * 2.0 - diameter
        thumb_position = position
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            thumb_position = 1.0 - position
        thumb_rect = QRectF(
            rect.left() + inset + travel * thumb_position,
            rect.top() + inset,
            diameter,
            diameter,
        )
        painter.setBrush(thumb)
        painter.drawEllipse(thumb_rect)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(PALETTE.text), 1.5))
            painter.drawRoundedRect(
                QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0),
                radius + 1.0,
                radius + 1.0,
            )
