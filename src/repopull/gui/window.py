"""The repopull main window: sidebar, repository list, detail and settings."""

from __future__ import annotations

import dataclasses
import random
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from repopull import __version__, git
from repopull.config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    save_behavior_settings,
    save_config,
)
from repopull.discovery import DiscoveryError, discover_repos
from repopull.diagnostics import lfs_status
from repopull.gui.jobs import RunTask
from repopull.gui.lfs_help import LfsHelpDialog
from repopull.gui.rows import RepoRow, RowView, row_view, unchecked_view
from repopull.models import Outcome, RepoRef, Report, Row
from repopull.refresh import (
    AUTO_REFRESH_JITTER_S,
    clamp_auto_refresh_s,
    cooldown_remaining,
    next_delay,
    should_warn,
)
from repopull.report import load_latest_report
_ASSETS = Path(__file__).resolve().parent / "assets"

from repopull.sync import (
    ProgressFn,
    RowCallback,
    inspect_repo,
    status_report,
    sync_report,
)


class MainWindow(QMainWindow):
    """One window that reads the same config and report files as the CLI."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.report: Report | None = load_latest_report(config.log_dir)
        self.rows_by_label: dict[str, Row] = (
            {row.label: row for row in self.report.rows}
            if self.report is not None
            else {}
        )
        self.row_widgets: dict[str, RepoRow] = {}
        self.refs: list[RepoRef] = []
        self.discovery_error: str | None = None
        self.filter = "all"
        self.search = ""
        self.task: RunTask | None = None
        self._quit_requested = False
        self._loading_settings = False
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        self._auto_pause_action: QAction | None = None
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_refresh_due)
        self._auto_run = False
        self._auto_paused = False
        self._auto_failures = 0
        self._last_network_finished: float | None = None
        self.current_label: str | None = None

        self.setWindowTitle("repopull")
        self.resize(1040, 720)
        self.setMinimumSize(860, 560)

        self._reload_refs()
        self._build()
        self._populate_settings()
        self._render_library()
        self._update_status_block()
        self._apply_background_mode()
        self._schedule_auto_refresh()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.library_page = self._build_library()
        self.detail_page = self._build_detail()
        self.settings_page = self._build_settings()
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.detail_page)
        self.stack.addWidget(self.settings_page)
        layout.addWidget(self.stack, 1)

        self._build_statusbar()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)

        box = QVBoxLayout(sidebar)
        box.setContentsMargins(16, 18, 16, 16)
        box.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(7)
        self.brand_mark = QLabel()
        self.brand_mark.setFixedSize(28, 28)
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_path = (
            Path(__file__).resolve().parent / "assets" / "repopull-mark.png"
        )
        if mark_path.is_file():
            pixmap = QPixmap(str(mark_path))
            if not pixmap.isNull():
                self.brand_mark.setPixmap(
                    pixmap.scaled(
                        28,
                        28,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        brand_row.addWidget(self.brand_mark)

        brand = QLabel("repopull")
        brand.setObjectName("Brand")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        box.addLayout(brand_row)
        box.addSpacing(12)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in (
            ("all", "All"),
            ("behind", "Behind"),
            ("skipped", "Skipped"),
            ("errors", "Errors"),
        ):
            button = QPushButton(text)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.filter_group.addButton(button)
            button.clicked.connect(
                lambda _checked=False, key=key: self._set_filter(key)
            )
            self.nav_buttons[key] = button
            box.addWidget(button)

        box.addStretch(1)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("Nav")
        self.settings_button.setCheckable(True)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_group.addButton(self.settings_button)
        self.settings_button.clicked.connect(self._show_settings)
        box.addWidget(self.settings_button)

        box.addSpacing(10)

        self.watched_link = QPushButton("Watched folder")
        self.watched_link.setObjectName("Link")
        self.watched_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watched_link.clicked.connect(self._open_watched_settings)
        box.addWidget(self.watched_link)

        self.last_label = QLabel("Last run —")
        self.last_label.setObjectName("Faint")
        box.addWidget(self.last_label)

        version = QLabel(f"v{__version__}")
        version.setObjectName("Faint")
        box.addWidget(version)

        self.nav_buttons["all"].setChecked(True)
        return sidebar

    def _build_library(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Repositories")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search repositories…")
        self.search_box.setFixedWidth(240)
        self.search_box.textChanged.connect(self._on_search)
        header.addWidget(self.search_box)

        self.refresh_button = QPushButton("Refresh status")
        self.refresh_button.setToolTip("Fetch every remote without changing a working tree")
        self.refresh_button.clicked.connect(self._refresh_status)
        header.addWidget(self.refresh_button)

        self.sync_button = QPushButton("Sync all")
        self.sync_button.setObjectName("Primary")
        self.sync_button.setToolTip(
            "Recheck every remote, then fast-forward what is behind"
        )
        self.sync_button.clicked.connect(self._sync_all)
        header.addWidget(self.sync_button)
        layout.addLayout(header)

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        self.banner_label = QLabel("")
        self.banner_label.setStyleSheet("font-weight: 600;")
        banner_layout.addWidget(self.banner_label)
        banner_layout.addStretch(1)
        self.banner_button = QPushButton("Sync these")
        self.banner_button.setObjectName("Primary")
        self.banner_button.setToolTip(
            "Fast-forward only the repositories the last check found behind; "
            "up-to-date ones are not rechecked"
        )
        self.banner_button.clicked.connect(self._sync_behind)
        banner_layout.addWidget(self.banner_button)
        self.banner.hide()
        layout.addWidget(self.banner)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list.setSpacing(6)
        layout.addWidget(self.list, 1)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("Muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        return page

    def _build_detail(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton("‹ Back")
        back.setObjectName("Ghost")
        back.clicked.connect(self._back_to_library)
        header.addWidget(back)

        self.detail_title = QLabel("")
        self.detail_title.setObjectName("PageTitle")
        header.addWidget(self.detail_title)
        header.addStretch(1)

        self.detail_lfs_help = QPushButton("Git LFS help…")
        self.detail_lfs_help.setObjectName("Ghost")
        self.detail_lfs_help.clicked.connect(self._lfs_help_current)
        self.detail_lfs_help.hide()
        header.addWidget(self.detail_lfs_help)

        self.detail_sync = QPushButton("Sync this repo")
        self.detail_sync.clicked.connect(self._sync_current)
        header.addWidget(self.detail_sync)

        self.detail_force = QPushButton("Force sync…")
        self.detail_force.setObjectName("Danger")
        self.detail_force.clicked.connect(self._force_current)
        header.addWidget(self.detail_force)
        layout.addLayout(header)

        self.detail_sub = QLabel("")
        self.detail_sub.setObjectName("Muted")
        self.detail_sub.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.detail_sub)

        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)

        self.detail_fields: dict[str, QLabel] = {}
        for index, (name, key) in enumerate(
            (
                ("Path", "path"),
                ("Branch", "branch"),
                ("Upstream", "upstream"),
                ("Ahead / behind", "counts"),
                ("Working tree", "dirty"),
                ("Git LFS", "lfs"),
                ("Submodules", "submodules"),
                ("Remote", "remote"),
            )
        ):
            label = QLabel(name)
            label.setObjectName("Faint")
            value = QLabel("-")
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value.setWordWrap(True)
            grid.addWidget(label, index, 0)
            grid.addWidget(value, index, 1)
            self.detail_fields[key] = value
        grid.setColumnStretch(1, 1)
        layout.addWidget(card)

        self.detail_note = QLabel("")
        self.detail_note.setObjectName("Muted")
        self.detail_note.setWordWrap(True)
        layout.addWidget(self.detail_note)
        layout.addStretch(1)

        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        note = QLabel(
            "Background and refresh changes apply immediately. Other changes "
            "are saved when you press Save settings; saving removes comments "
            "you added to that file."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setStyleSheet("background: transparent;")
        scroll.viewport().setStyleSheet("background: transparent;")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        watching = QGroupBox("Watching")
        watch_form = QFormLayout(watching)
        watch_form.setContentsMargins(16, 18, 16, 14)
        watch_form.setSpacing(10)

        self.settings_config_label = QLabel("-")
        self.settings_config_label.setWordWrap(True)
        self.settings_config_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        watch_form.addRow("Config file", self.settings_config_label)

        root_row = QHBoxLayout()
        self.settings_root = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(self.settings_root, 1)
        root_row.addWidget(browse)
        root_widget = QWidget()
        root_widget.setLayout(root_row)
        watch_form.addRow("Watched folder", root_widget)

        self.settings_max_depth = QSpinBox()
        self.settings_max_depth.setRange(1, 4)
        self.settings_max_depth.setToolTip(
            "1 = direct children, 2 = grandchildren too"
        )
        watch_form.addRow("Depth", self.settings_max_depth)

        self.settings_ignore = QPlainTextEdit()
        self.settings_ignore.setPlaceholderText(
            "One glob per line, e.g.\nphotocraft-corpus\n*.old"
        )
        self.settings_ignore.setFixedHeight(76)
        self.settings_ignore.setTabChangesFocus(True)
        self.settings_ignore.setToolTip(
            "Matches the relative label and the repository name"
        )
        watch_form.addRow("Ignore", self.settings_ignore)
        content_layout.addWidget(watching)

        background = QGroupBox("Background && refresh")
        background_form = QFormLayout(background)
        background_form.setContentsMargins(16, 18, 16, 14)
        background_form.setSpacing(10)

        self.settings_background = QCheckBox(
            "Keep running in the system tray when the window is closed"
        )
        self.settings_background.setEnabled(self._tray_available)
        if not self._tray_available:
            self.settings_background.setToolTip(
                "The system tray is not available in this session."
            )
        background_form.addRow(self.settings_background)

        self.settings_tray_status = QLabel(
            "System tray is available. The tray icon is visible while repopull "
            "runs; closing keeps it there only when the box above is checked."
            if self._tray_available
            else "System tray is not available in this session; background mode "
            "is disabled and closing quits."
        )
        self.settings_tray_status.setObjectName("Muted")
        self.settings_tray_status.setWordWrap(True)
        background_form.addRow(self.settings_tray_status)

        self.settings_auto = QCheckBox("Refresh status automatically")
        background_form.addRow(self.settings_auto)

        self.settings_auto_minutes = QSpinBox()
        self.settings_auto_minutes.setRange(5, 1440)
        self.settings_auto_minutes.setSuffix(" minutes")
        self.settings_auto_minutes.setValue(15)
        background_form.addRow("Every", self.settings_auto_minutes)

        self.settings_auto_warning = QLabel(
            "Frequent fetches increase load on remote servers; "
            "15 minutes or longer is recommended."
        )
        self.settings_auto_warning.setWordWrap(True)
        self.settings_auto_warning.setStyleSheet("color: #d29922;")
        self.settings_auto_warning.setVisible(False)
        background_form.addRow(self.settings_auto_warning)

        auto_note = QLabel(
            "Status only — automatic refresh never syncs. "
            "Closing quits unless the tray setting is enabled."
        )
        auto_note.setWordWrap(True)
        auto_note.setObjectName("Muted")
        background_form.addRow(auto_note)

        self.settings_background.toggled.connect(self._on_background_toggled)
        self.settings_auto.toggled.connect(self._on_auto_toggled)
        self.settings_auto_minutes.valueChanged.connect(
            self._on_auto_minutes_changed
        )
        content_layout.addWidget(background)

        network = QGroupBox("Network")
        network_form = QFormLayout(network)
        network_form.setContentsMargins(16, 18, 16, 14)
        network_form.setSpacing(10)

        self.settings_delay = QDoubleSpinBox()
        self.settings_delay.setRange(0.0, 60.0)
        self.settings_delay.setSingleStep(0.5)
        self.settings_delay.setSuffix(" s")
        network_form.addRow("Delay between fetches", self.settings_delay)

        self.settings_fetch_timeout = QSpinBox()
        self.settings_fetch_timeout.setRange(10, 3600)
        self.settings_fetch_timeout.setSuffix(" s")
        network_form.addRow("Fetch timeout", self.settings_fetch_timeout)

        self.settings_command_timeout = QSpinBox()
        self.settings_command_timeout.setRange(10, 600)
        self.settings_command_timeout.setSuffix(" s")
        network_form.addRow("Other git timeout", self.settings_command_timeout)
        content_layout.addWidget(network)

        updates = QGroupBox("Updates")
        updates_form = QFormLayout(updates)
        updates_form.setContentsMargins(16, 18, 16, 14)
        updates_form.setSpacing(10)

        self.settings_submodules = QCheckBox(
            "Run git submodule update after a pull"
        )
        updates_form.addRow("", self.settings_submodules)

        self.settings_lfs = QCheckBox(
            "Skip LFS repositories when Git LFS is not ready"
        )
        self.settings_lfs.setToolTip(
            "Requires git-lfs to be installed and enabled (git lfs install)"
        )
        updates_form.addRow("", self.settings_lfs)

        lfs_row = QHBoxLayout()
        self.settings_lfs_status = QLabel("-")
        self.settings_lfs_status.setObjectName("Muted")
        lfs_row.addWidget(self.settings_lfs_status)
        lfs_row.addStretch(1)
        lfs_help = QPushButton("Help…")
        lfs_help.setObjectName("Ghost")
        lfs_help.clicked.connect(lambda: self._show_lfs_help())
        lfs_row.addWidget(lfs_help)
        lfs_widget = QWidget()
        lfs_widget.setLayout(lfs_row)
        updates_form.addRow("Git LFS", lfs_widget)

        content_layout.addWidget(updates)


        storage = QGroupBox("Storage")
        storage_form = QFormLayout(storage)
        storage_form.setContentsMargins(16, 18, 16, 14)
        storage_form.setSpacing(10)

        self.settings_logs_label = QLabel("-")
        self.settings_logs_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.settings_logs_label.setToolTip("Where run reports are saved")
        storage_form.addRow("Logs", self.settings_logs_label)

        self.settings_retention = QSpinBox()
        self.settings_retention.setRange(0, 3650)
        self.settings_retention.setSuffix(" days")
        self.settings_retention.setSpecialValueText("Keep all")
        self.settings_retention.setToolTip(
            "Delete run logs older than this; 0 keeps every run log."
        )
        storage_form.addRow("Keep run logs", self.settings_retention)
        content_layout.addWidget(storage)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.reset_button = QPushButton("Reset to defaults")
        self.reset_button.setObjectName("Ghost")
        self.reset_button.clicked.connect(self._reset_settings)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.save_button = QPushButton("Save settings")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self._save_settings)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

        check_row = QHBoxLayout()
        self.check_button = QPushButton("Check folder")
        self.check_button.clicked.connect(self._check_root)
        check_row.addWidget(self.check_button)
        self.check_result = QLabel("")
        self.check_result.setObjectName("Muted")
        check_row.addWidget(self.check_result)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        return page

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)

        self.status_message = QLabel("Ready")
        bar.addWidget(self.status_message, 1)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bar.addPermanentWidget(self.progress)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("Ghost")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        bar.addPermanentWidget(self.cancel_button)

    # ------------------------------------------------------------- navigation

    def _set_filter(self, key: str) -> None:
        self.filter = key
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.library_page)
        self._render_library()

    def _show_settings(self) -> None:
        self.settings_button.setChecked(True)
        self._populate_settings()
        self.stack.setCurrentWidget(self.settings_page)

    def _open_watched_settings(self) -> None:
        """Jump straight to the watched folder field."""
        self._show_settings()
        self.settings_root.setFocus()
        self.settings_root.selectAll()

    def _back_to_library(self) -> None:
        self.stack.setCurrentWidget(self.library_page)
        self._render_library()

    def _on_search(self, text: str) -> None:
        self.search = text.strip()
        self._render_library()

    # --------------------------------------------------------------- rendering

    def _reload_refs(self) -> None:
        root = self.config.root
        if root is None:
            self.refs = []
            self.discovery_error = (
                "No watched folder configured. Open Settings and choose one."
            )
            return
        try:
            self.refs = discover_repos(
                root,
                max_depth=self.config.max_depth,
                ignore=self.config.ignore,
            )
            self.discovery_error = None
        except DiscoveryError as exc:
            self.refs = []
            self.discovery_error = str(exc)

    def _report_rows(self) -> dict[str, Row]:
        return self.rows_by_label

    def _visible_rows(self) -> list[RowView]:
        report_rows = self._report_rows()
        visible: list[RowView] = []
        for ref in self.refs:
            row = report_rows.get(ref.label)
            if self.filter == "behind" and (
                row is None or row.outcome is not Outcome.BEHIND
            ):
                continue
            if self.filter == "skipped" and (
                row is None or row.outcome is not Outcome.SKIPPED
            ):
                continue
            if self.filter == "errors" and (
                row is None or row.outcome is not Outcome.ERROR
            ):
                continue
            if self.search and self.search.casefold() not in ref.label.casefold():
                continue
            visible.append(
                row_view(row) if row is not None else unchecked_view(ref.label)
            )
        return visible

    def visible_row_count(self) -> int:
        """Number of rows the current filter and search would show."""
        return len(self._visible_rows())

    def _render_library(self) -> None:
        self._update_nav_counts()
        visible = self._visible_rows()

        self.list.clear()
        self.row_widgets = {}
        for view in visible:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            widget = RepoRow(view)
            widget.clicked.connect(self._open_detail)
            self.list.setItemWidget(item, widget)
            self.row_widgets[view.label] = widget

        if visible:
            self.empty_label.hide()
        else:
            if self.discovery_error is not None:
                self.empty_label.setText(self.discovery_error)
            elif self.search:
                self.empty_label.setText("No repositories match the search.")
            else:
                self.empty_label.setText("No repositories in this view.")
            self.empty_label.show()

        self._update_banner()

    def _update_nav_counts(self) -> None:
        report_rows = self._report_rows()
        counts = {Outcome.BEHIND: 0, Outcome.SKIPPED: 0, Outcome.ERROR: 0}
        for ref in self.refs:
            row = report_rows.get(ref.label)
            if row is not None and row.outcome in counts:
                counts[row.outcome] += 1
        self.nav_buttons["all"].setText(f"All  {len(self.refs)}")
        self.nav_buttons["behind"].setText(f"Behind  {counts[Outcome.BEHIND]}")
        self.nav_buttons["skipped"].setText(
            f"Skipped  {counts[Outcome.SKIPPED]}"
        )
        self.nav_buttons["errors"].setText(f"Errors  {counts[Outcome.ERROR]}")

    def _update_banner(self) -> None:
        behind = 0
        if self.report is not None:
            labels = {ref.label for ref in self.refs}
            behind = sum(
                1
                for row in self.report.rows
                if row.outcome is Outcome.BEHIND and row.label in labels
            )
        if behind:
            self.banner_label.setText(
                f"{behind} repositories can be updated (from the last check)."
            )
            self.banner.show()
        else:
            self.banner.hide()

    def _update_status_block(self) -> None:
        if self.config.root is None:
            self.watched_link.setText("Watched folder (not set)")
            self.watched_link.setToolTip("Choose a folder in Settings")
        else:
            self.watched_link.setText("Watched folder")
            self.watched_link.setToolTip(str(self.config.root))
        if self.report is not None:
            self.last_label.setText(
                f"Last run {self.report.started_at:%Y-%m-%d %H:%M}"
            )
        else:
            self.last_label.setText("Last run —")

    def _populate_settings(self) -> None:
        self._loading_settings = True
        self.settings_root.setText(
            str(self.config.root) if self.config.root is not None else ""
        )
        self.settings_max_depth.setValue(self.config.max_depth)
        self.settings_ignore.setPlainText("\n".join(self.config.ignore))
        self.settings_delay.setValue(self.config.delay_between_repos_s)
        self.settings_fetch_timeout.setValue(int(self.config.fetch_timeout_s))
        self.settings_command_timeout.setValue(
            int(self.config.command_timeout_s)
        )
        self.settings_submodules.setChecked(self.config.update_submodules)
        self.settings_lfs.setChecked(
            self.config.require_git_lfs_for_lfs_repos
        )
        status = lfs_status()
        if not status.installed:
            self.settings_lfs_status.setText("not installed")
        else:
            version = f" · {status.version.split()[0]}" if status.version else ""
            state = "enabled" if status.enabled else "not enabled"
            self.settings_lfs_status.setText(f"installed{version} · {state}")
        self.settings_config_label.setText(
            str(self.config.config_path or "(built-in defaults)")
        )
        self.settings_logs_label.setText(str(self.config.log_dir))
        self.settings_retention.setValue(self.config.log_retention_days)
        self.settings_background.setChecked(
            self.config.background_mode and self._tray_available
        )
        auto_on = self.config.auto_refresh_s > 0
        self.settings_auto.setChecked(auto_on)
        minutes = (
            max(5, round(self.config.auto_refresh_s / 60))
            if auto_on
            else 15
        )
        blocker = QSignalBlocker(self.settings_auto_minutes)
        self.settings_auto_minutes.setValue(minutes)
        del blocker
        self._loading_settings = False
        self._update_auto_controls()
        self.check_result.setText("")

    # ------------------------------------------------------------------ actions

    def _open_detail(self, label: str) -> None:
        ref = next((item for item in self.refs if item.label == label), None)
        if ref is None:
            return
        state = inspect_repo(ref, timeout=self.config.command_timeout_s)
        remote = git.run_git(
            ref.path,
            "remote",
            "get-url",
            "origin",
            timeout=self.config.command_timeout_s,
        )
        row = self._report_rows().get(label)

        self.current_label = label
        self.detail_title.setText(label)
        self.detail_sub.setText(str(ref.path))
        self.detail_fields["path"].setText(str(ref.path))
        self.detail_fields["branch"].setText(state.branch or "detached")
        self.detail_fields["upstream"].setText(state.upstream or "none")
        self.detail_fields["counts"].setText(
            f"{state.ahead} ahead · {state.behind} behind"
        )
        self.detail_fields["dirty"].setText("dirty" if state.dirty else "clean")
        self.detail_fields["lfs"].setText("yes" if state.uses_lfs else "no")
        needs_lfs_help = state.uses_lfs and (
            not git.git_lfs_available() or not state.lfs_enabled
        )
        self.detail_lfs_help.setVisible(needs_lfs_help)
        self.detail_fields["submodules"].setText(
            "yes" if state.has_submodules else "no"
        )
        self.detail_fields["remote"].setText(
            remote.stdout.strip() if remote.ok else "-"
        )
        if state.error is not None:
            self.detail_note.setText(state.error)
        elif row is not None:
            self.detail_note.setText(
                row.detail or f"Last result: {row.outcome.value}"
            )
        else:
            self.detail_note.setText(
                "No saved result yet. Use Refresh status."
            )
        self.stack.setCurrentWidget(self.detail_page)

    def _lfs_help_current(self) -> None:
        ref = self._current_ref()
        self._show_lfs_help(ref.path if ref is not None else None)

    def _show_lfs_help(self, repo: Path | None = None) -> None:
        dialog = LfsHelpDialog(lfs_status(repo), self)
        dialog.exec()

    def _browse_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the watched repositories folder", str(self.config.root)
        )
        if chosen:
            self.settings_root.setText(chosen)

    def _on_background_toggled(self, _checked: bool) -> None:
        if self._loading_settings:
            return
        self._sync_behavior_settings()

    def _on_auto_toggled(self, _checked: bool) -> None:
        if self._loading_settings:
            return
        self._sync_behavior_settings()
        self._update_auto_controls()

    def _on_auto_minutes_changed(self, _value: int) -> None:
        if self._loading_settings:
            return
        if not self.settings_auto.isChecked():
            self.settings_auto.setChecked(True)
            return
        self._sync_behavior_settings()
        self._update_auto_controls()

    def _sync_behavior_settings(self) -> None:
        background = (
            self.settings_background.isChecked() and self._tray_available
        )
        auto = (
            0
            if not self.settings_auto.isChecked()
            else clamp_auto_refresh_s(
                int(self.settings_auto_minutes.value()) * 60
            )
        )
        self.config = dataclasses.replace(
            self.config,
            background_mode=background,
            auto_refresh_s=auto,
        )
        target = self.config.config_path
        if target is not None:
            try:
                save_behavior_settings(
                    target,
                    background_mode=background,
                    auto_refresh_s=auto,
                )
            except OSError as exc:
                self._flash(f"Could not save background settings: {exc}")
        self._apply_background_mode()
        self._schedule_auto_refresh()

    def _update_auto_controls(self) -> None:
        self.settings_auto_minutes.setEnabled(True)
        warn = self.settings_auto.isChecked() and should_warn(
            self.settings_auto_minutes.value() * 60
        )
        self.settings_auto_warning.setVisible(warn)

    def _save_settings(self) -> None:
        root_text = self.settings_root.text().strip()
        if not root_text:
            QMessageBox.warning(
                self, "repopull", "The watched folder cannot be empty."
            )
            return
        ignore = tuple(
            line.strip()
            for line in self.settings_ignore.toPlainText().splitlines()
            if line.strip()
        )
        target = self.config.config_path or default_config_path()
        updated = dataclasses.replace(
            self.config,
            root=Path(root_text).expanduser(),
            max_depth=int(self.settings_max_depth.value()),
            ignore=ignore,
            fetch_timeout_s=float(self.settings_fetch_timeout.value()),
            command_timeout_s=float(self.settings_command_timeout.value()),
            delay_between_repos_s=float(self.settings_delay.value()),
            update_submodules=self.settings_submodules.isChecked(),
            require_git_lfs_for_lfs_repos=self.settings_lfs.isChecked(),
            log_retention_days=int(self.settings_retention.value()),
            background_mode=(
                self.settings_background.isChecked()
                and self._tray_available
            ),
            auto_refresh_s=(
                0
                if not self.settings_auto.isChecked()
                else clamp_auto_refresh_s(
                    int(self.settings_auto_minutes.value()) * 60
                )
            ),
        )
        try:
            save_config(updated, target)
            self.config = load_config(config_path=target)
        except (OSError, ConfigError) as exc:
            QMessageBox.warning(
                self, "repopull", f"Could not save settings: {exc}"
            )
            return
        self._reload_refs()
        self._populate_settings()
        self._apply_background_mode()
        self._schedule_auto_refresh()
        self._render_library()
        self._update_status_block()
        self._flash(f"Saved {target}")

    def _reset_settings(self) -> None:
        self._loading_settings = True
        defaults = Config()
        self.settings_root.setText(str(defaults.root))
        self.settings_max_depth.setValue(defaults.max_depth)
        self.settings_ignore.setPlainText("\n".join(defaults.ignore))
        self.settings_delay.setValue(defaults.delay_between_repos_s)
        self.settings_fetch_timeout.setValue(int(defaults.fetch_timeout_s))
        self.settings_command_timeout.setValue(
            int(defaults.command_timeout_s)
        )
        self.settings_submodules.setChecked(defaults.update_submodules)
        self.settings_lfs.setChecked(
            defaults.require_git_lfs_for_lfs_repos
        )
        self.settings_retention.setValue(defaults.log_retention_days)
        self.settings_background.setChecked(False)
        self.settings_auto.setChecked(False)
        blocker = QSignalBlocker(self.settings_auto_minutes)
        self.settings_auto_minutes.setValue(15)
        del blocker
        self._loading_settings = False
        self._update_auto_controls()
        self.check_result.setText(
            "Defaults restored; press Save settings to write them."
        )

    def _check_root(self) -> None:
        text = self.settings_root.text().strip()
        if not text:
            self.check_result.setText("✗ Choose a folder first.")
            return
        ignore = tuple(
            line.strip()
            for line in self.settings_ignore.toPlainText().splitlines()
            if line.strip()
        )
        try:
            refs = discover_repos(
                Path(text).expanduser(),
                max_depth=int(self.settings_max_depth.value()),
                ignore=ignore,
            )
        except DiscoveryError as exc:
            self.check_result.setText(f"✗ {exc}")
        else:
            self.check_result.setText(f"✓ Found {len(refs)} repositories")

    # -------------------------------------------------------------- run control

    def _refresh_status(self) -> None:
        self._start_run(self.refs, force=False, mode="status")

    def _sync_all(self) -> None:
        self._start_run(self.refs, force=False, mode="sync")

    def _behind_refs(self) -> list[RepoRef]:
        """Repositories the last check found behind."""
        selected: list[RepoRef] = []
        for ref in self.refs:
            row = self.rows_by_label.get(ref.label)
            if row is not None and row.outcome is Outcome.BEHIND:
                selected.append(ref)
        return selected

    def _sync_behind(self) -> None:
        """Fast path: update only what the last check already knows is behind."""
        refs = self._behind_refs()
        if not refs:
            self._flash(
                "Nothing is behind in the last check. Use Refresh status or "
                "Sync all to recheck."
            )
            return
        self._start_run(refs, force=False, mode="sync")

    def _sync_current(self) -> None:
        ref = self._current_ref()
        if ref is not None:
            self._start_run([ref], force=False, mode="sync")

    def _force_current(self) -> None:
        ref = self._current_ref()
        if ref is None:
            return
        answer = QMessageBox.question(
            self,
            "Force sync",
            f"Discard local commits and tracked changes in {ref.label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_run([ref], force=True, mode="sync")

    def _current_ref(self) -> RepoRef | None:
        if self.current_label is None:
            return None
        return next(
            (ref for ref in self.refs if ref.label == self.current_label), None
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Hide to tray when configured; otherwise cancel and quit cleanly."""
        if self._quit_requested:
            self._begin_quit()
            event.ignore()
            return
        if self.config.background_mode and self.tray is not None:
            event.ignore()
            self.hide()
            self.tray.show()
            return
        self._begin_quit()
        if self.task is not None:
            event.ignore()
        else:
            event.accept()

    def request_quit(self) -> None:
        """Quit from a signal or tray action, bypassing close-to-tray."""
        self._begin_quit()

    def _begin_quit(self) -> None:
        self.auto_timer.stop()
        if self._quit_requested:
            if self.task is None:
                self._quit_application()
            return
        self._quit_requested = True
        if self.task is not None:
            self.task.cancel.set()
            self.cancel_button.setEnabled(False)
            self._flash("Stopping after the current repository…")
            return
        self._quit_application()

    def _quit_application(self) -> None:
        if self.tray is not None:
            self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _maybe_quit_after_task(self) -> None:
        if self._quit_requested:
            self._quit_application()

    def _apply_background_mode(self) -> None:
        if not self._tray_available:
            if self.tray is not None:
                self.tray.hide()
            return
        self._ensure_tray()
        if self.tray is not None:
            self.tray.show()

    def _ensure_tray(self) -> None:
        if self.tray is not None or not self._tray_available:
            return
        icon = QIcon()
        for size in (16, 22, 24, 32):
            path = _ASSETS / f"repopull-symbolic-{size}.png"
            if path.is_file():
                icon.addFile(str(path), QSize(size, size))
        if icon.isNull():
            icon = self.windowIcon()
        icon.setIsMask(True)

        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("repopull")
        menu = QMenu(self)
        open_action = QAction("Open repopull", self)
        open_action.triggered.connect(self._show_from_tray)
        refresh_action = QAction("Refresh status now", self)
        refresh_action.triggered.connect(self._refresh_status)
        self._auto_pause_action = QAction("Pause automatic refresh", self)
        self._auto_pause_action.setCheckable(True)
        self._auto_pause_action.setEnabled(self.config.auto_refresh_s > 0)
        self._auto_pause_action.toggled.connect(self._set_auto_paused)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._begin_quit)
        menu.addAction(open_action)
        menu.addAction(refresh_action)
        menu.addAction(self._auto_pause_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        self.tray = tray
        self.tray_menu = menu
        self._update_tray_tooltip()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(
        self, reason: QSystemTrayIcon.ActivationReason
    ) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _set_auto_paused(self, paused: bool) -> None:
        self._auto_paused = paused
        if self._auto_pause_action is not None:
            self._auto_pause_action.setText(
                "Resume automatic refresh" if paused else "Pause automatic refresh"
            )
        if paused:
            self.auto_timer.stop()
        else:
            self._schedule_auto_refresh()
        self._update_tray_tooltip()

    def _jitter_seconds(self) -> float:
        return float(random.randint(0, AUTO_REFRESH_JITTER_S))

    def _schedule_auto_refresh(self) -> None:
        if self._auto_pause_action is not None:
            self._auto_pause_action.setEnabled(self.config.auto_refresh_s > 0)
        if (
            self.config.auto_refresh_s <= 0
            or self._quit_requested
            or self._auto_paused
        ):
            self.auto_timer.stop()
            return
        now = time.monotonic()
        cooldown = cooldown_remaining(
            self._last_network_finished,
            now,
            self.config.auto_refresh_s,
        )
        base = next_delay(
            self.config.auto_refresh_s,
            self._auto_failures,
        )
        delay = max(base, cooldown) + self._jitter_seconds()
        self.auto_timer.start(int(delay * 1000))

    def _auto_refresh_due(self) -> None:
        if (
            self._quit_requested
            or self.config.auto_refresh_s <= 0
            or self._auto_paused
        ):
            return
        if self.task is not None:
            self.auto_timer.start(60_000)
            return
        now = time.monotonic()
        remaining = cooldown_remaining(
            self._last_network_finished,
            now,
            self.config.auto_refresh_s,
        )
        if remaining > 0:
            self.auto_timer.start(
                int((remaining + self._jitter_seconds()) * 1000)
            )
            return
        if not self.refs:
            self._schedule_auto_refresh()
            return
        self._start_run(self.refs, force=False, mode="status", auto=True)

    def _update_tray_tooltip(self) -> None:
        if self.tray is None:
            return
        if self.report is None:
            text = "repopull — no run yet"
        else:
            text = f"repopull — {self._summary(self.report)}"
        if self.config.auto_refresh_s > 0:
            text += "\nAutomatic refresh on"
        self.tray.setToolTip(text)

    def _start_run(
        self,
        refs: list[RepoRef],
        *,
        force: bool,
        mode: str,
        auto: bool = False,
    ) -> None:
        if self.task is not None:
            return
        if not refs:
            self._flash("No repositories to run.")
            return
        if not auto:
            self.auto_timer.stop()
        self._auto_run = auto
        self._set_busy(True)
        config = self.config

        def operation(
            cancel: Event, progress: ProgressFn, on_row: RowCallback
        ) -> Report:
            if mode == "status":
                return status_report(
                    refs,
                    config,
                    progress=progress,
                    on_row=on_row,
                    cancel=cancel,
                )
            return sync_report(
                refs,
                config,
                force=force,
                progress=progress,
                on_row=on_row,
                cancel=cancel,
            )

        task = RunTask(operation, config.log_dir)
        task.signals.progress.connect(self._on_progress)
        task.signals.row.connect(self._on_row)
        task.signals.finished.connect(self._on_finished)
        task.signals.cancelled.connect(self._on_cancelled)
        task.signals.failed.connect(self._on_failed)
        self.task = task
        QThreadPool.globalInstance().start(task)

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.refresh_button,
            self.sync_button,
            self.banner_button,
            self.detail_sync,
            self.detail_force,
            self.save_button,
            self.reset_button,
        ):
            button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        if busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

    def _cancel(self) -> None:
        if self.task is not None:
            self.task.cancel.set()
            self.cancel_button.setEnabled(False)
            self._flash("Cancelling…")

    def _on_progress(self, index: int, total: int, label: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(index)
        self._flash(f"[{index}/{total}] {label}")

    def _matches(self, label: str, outcome: Outcome | None) -> bool:
        """Whether a row belongs in the current filter and search."""
        if self.search and self.search.casefold() not in label.casefold():
            return False
        if self.filter == "all":
            return True
        if outcome is None:
            return False
        if self.filter == "behind":
            return outcome is Outcome.BEHIND
        if self.filter == "skipped":
            return outcome is Outcome.SKIPPED
        return outcome is Outcome.ERROR

    def _on_row(self, row: object) -> None:
        """Paint one repository's result as soon as the worker decides it."""
        if not isinstance(row, Row):
            return
        previous = self.rows_by_label.get(row.label)
        self.rows_by_label[row.label] = row
        widget = self.row_widgets.get(row.label)
        if widget is not None:
            widget.apply(row_view(row))

        was_visible = self._matches(
            row.label, previous.outcome if previous is not None else None
        )
        is_visible = self._matches(row.label, row.outcome)
        if was_visible != is_visible or (widget is None and is_visible):
            self._render_library()
            return
        self._update_nav_counts()
        self._update_banner()

    def _on_finished(self, report: object) -> None:
        if not isinstance(report, Report):
            return
        auto = self._auto_run
        self._auto_run = False
        self._last_network_finished = time.monotonic()
        if auto:
            self._auto_failures = (
                min(self._auto_failures + 1, 10) if report.has_errors else 0
            )
        else:
            self._auto_failures = 0
        self.report = report
        for row in report.rows:
            self.rows_by_label[row.label] = row
        self.task = None
        self._set_busy(False)
        self._render_library()
        self._update_status_block()
        self._flash(self._summary(report))
        self._update_tray_tooltip()
        self._schedule_auto_refresh()
        self._maybe_quit_after_task()

    def _on_cancelled(self, report: object) -> None:
        self._auto_run = False
        self._last_network_finished = time.monotonic()
        self._auto_failures = 0
        if isinstance(report, Report):
            self.report = report
            for row in report.rows:
                self.rows_by_label[row.label] = row
        self.task = None
        self._set_busy(False)
        self._render_library()
        self._update_status_block()
        self._flash("Cancelled")
        self._update_tray_tooltip()
        self._schedule_auto_refresh()
        self._maybe_quit_after_task()

    def _on_failed(self, message: str) -> None:
        auto = self._auto_run
        self._auto_run = False
        self._last_network_finished = time.monotonic()
        self.task = None
        self._set_busy(False)
        self._flash("Run failed")
        if auto:
            self._auto_failures = min(self._auto_failures + 1, 10)
            if self.tray is not None:
                self.tray.setToolTip("repopull — automatic refresh failed")
            self._schedule_auto_refresh()
            if self._quit_requested:
                self._maybe_quit_after_task()
            return
        self._auto_failures = 0
        self._update_tray_tooltip()
        self._schedule_auto_refresh()
        if self._quit_requested:
            self._maybe_quit_after_task()
            return
        QMessageBox.warning(self, "repopull", message)

    def _summary(self, report: Report) -> str:
        parts = [
            f"{count} {outcome.value}"
            for outcome, count in report.totals.items()
            if count
        ]
        return f"{' · '.join(parts)} in {report.elapsed_s:.1f}s"

    def _flash(self, message: str) -> None:
        self.status_message.setText(message)
