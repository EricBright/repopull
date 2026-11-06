"""Colour tokens and the Qt stylesheet for the optional GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Palette:
    """One place for every colour the interface uses."""

    bg: str = "#14171d"
    surface: str = "#1b1f27"
    surface2: str = "#222834"
    raised: str = "#2a3140"
    line: str = "#2e3542"
    text: str = "#e6e9f0"
    muted: str = "#9aa3b2"
    faint: str = "#6b7382"
    accent: str = "#7aa2f7"
    accent_text: str = "#10141b"
    ok: str = "#6fcf97"
    warn: str = "#f0b860"
    held: str = "#c7a6ff"
    danger: str = "#ff8a8a"


PALETTE = Palette()

STATUS_COLORS: dict[str, str] = {
    "ok": PALETTE.ok,
    "warn": PALETTE.warn,
    "held": PALETTE.held,
    "danger": PALETTE.danger,
    "neutral": PALETTE.muted,
    "accent": PALETTE.accent,
}


def rgba(hex_color: str, alpha: float) -> str:
    """Turn `#rrggbb` into a Qt `rgba()` string."""
    value = hex_color.lstrip("#")
    red, green, blue = (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )
    return f"rgba({red}, {green}, {blue}, {alpha:g})"


def stylesheet(palette: Palette = PALETTE) -> str:
    """The application stylesheet, generated from `palette`."""
    p = palette
    check = (Path(__file__).resolve().parent / "assets" / "checkmark.png").as_posix()
    return f"""
    * {{
        font-family: "Inter", "Cantarell", "Noto Sans", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QWidget#Root {{
        background: {p.bg};
        color: {p.text};
    }}
    QDialog {{
        background: {p.bg};
        color: {p.text};
    }}
    QDialog QLabel {{
        color: {p.text};
    }}
    QWidget#Sidebar {{
        background: {p.surface};
        border-right: 1px solid {p.line};
    }}
    QStatusBar {{
        background: {p.surface};
        border-top: 1px solid {p.line};
        color: {p.muted};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QLabel#Brand {{
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#PageTitle {{
        font-size: 20px;
        font-weight: 700;
    }}
    QLabel#Muted {{
        color: {p.muted};
    }}
    QLabel#Faint {{
        color: {p.faint};
        font-size: 12px;
    }}
    QPushButton {{
        background: {p.surface2};
        color: {p.text};
        border: 1px solid {p.line};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        background: {p.raised};
    }}
    QPushButton:pressed {{
        background: {p.line};
    }}
    QPushButton:disabled {{
        color: {p.faint};
        background: {p.surface};
    }}
    QPushButton#Primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: none;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background: #93b6ff;
    }}
    QPushButton#Primary:disabled {{
        background: {p.raised};
        color: {p.faint};
    }}
    QPushButton#Danger {{
        color: {p.danger};
        border: 1px solid {p.danger};
        background: transparent;
    }}
    QPushButton#Danger:hover {{
        background: {rgba(p.danger, 0.12)};
    }}
    QPushButton#Ghost {{
        background: transparent;
        border: none;
        color: {p.muted};
        padding: 6px 8px;
    }}
    QPushButton#Ghost:hover {{
        color: {p.text};
        background: {p.surface2};
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {p.accent};
        text-align: left;
        padding: 2px 0;
        font-weight: 600;
    }}
    QPushButton#Link:hover {{
        color: #93b6ff;
    }}
    QPushButton#Nav {{
        text-align: left;
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 9px 12px;
        color: {p.muted};
        font-weight: 500;
    }}
    QPushButton#Nav:hover {{
        background: {p.surface2};
        color: {p.text};
    }}
    QPushButton#Nav:checked {{
        background: {p.surface2};
        color: {p.text};
        border-left: 3px solid {p.accent};
    }}
    QLineEdit {{
        background: {p.surface2};
        border: 1px solid {p.line};
        border-radius: 8px;
        padding: 8px 10px;
        color: {p.text};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus {{
        border: 1px solid {p.accent};
    }}
    QPlainTextEdit {{
        background: {p.surface2};
        border: 1px solid {p.line};
        border-radius: 8px;
        padding: 6px;
        color: {p.text};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QPlainTextEdit:focus {{
        border: 1px solid {p.accent};
    }}
    QSpinBox, QDoubleSpinBox {{
        background: {p.surface2};
        border: 1px solid {p.line};
        border-radius: 8px;
        padding: 6px 8px;
        color: {p.text};
    }}
    QCheckBox {{
        color: {p.text};
        spacing: 8px;
    }}
    QCheckBox:disabled {{
        color: {p.faint};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.faint};
        border-radius: 4px;
        background: {p.surface2};
    }}
    QCheckBox::indicator:hover {{
        border-color: {p.accent};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        image: url("{check}");
    }}
    QCheckBox::indicator:disabled {{
        background: {p.surface};
        border-color: {p.line};
    }}
    QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.line};
        border-radius: 10px;
        margin-top: 12px;
        padding: 16px 12px 12px 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {p.muted};
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget::item {{
        border: none;
        padding: 0;
        margin: 0;
    }}
    QListWidget::item:selected {{
        background: transparent;
    }}
    QFrame#RepoRow {{
        background: {p.surface};
        border: 1px solid {p.line};
        border-radius: 10px;
    }}
    QFrame#RepoRow:hover {{
        background: {p.surface2};
    }}
    QFrame#Banner {{
        background: {rgba(p.warn, 0.12)};
        border: 1px solid {rgba(p.warn, 0.35)};
        border-radius: 10px;
    }}
    QFrame#Card {{
        background: {p.surface};
        border: 1px solid {p.line};
        border-radius: 10px;
    }}
    QProgressBar {{
        background: {p.surface2};
        border: none;
        border-radius: 4px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {p.accent};
        border-radius: 4px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.raised};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QToolTip {{
        background: {p.surface2};
        color: {p.text};
        border: 1px solid {p.line};
        padding: 4px;
    }}
    """
