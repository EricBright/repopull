"""The repopull main window: sidebar, repository list, detail and settings."""

from __future__ import annotations

import dataclasses
import random
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRunnable,
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QHideEvent,
    QIcon,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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
from repopull.diagnostics import LfsStatus, lfs_status
from repopull.gui.jobs import RunTask
from repopull.gui.lfs_help import LfsHelpDialog
from repopull.gui.rows import RepoRow, RowView, row_view, unchecked_view
from repopull.gui.settings import (
    SETTINGS_SECTIONS,
    SettingRow,
    SettingsCard,
)
from repopull.models import Outcome, RepoRef, Report, Row
from repopull.refresh import (
    AUTO_REFRESH_JITTER_S,
    SUSPEND_POLL_INTERVAL_S,
    SUSPEND_RESUME_GRACE_S,
    RefreshAction,
    RefreshDecision,
    RefreshEvent,
    RefreshState,
    SuspendDetector,
    clamp_auto_refresh_s,
    decide_refresh,
    should_warn,
)
from repopull.report import check_log_dir, load_latest_report
from repopull.rootstate import ROOT_STATE_FILE, verify_root_state
from repopull.uistate import UiState, load_ui_state, save_ui_state
_ASSETS = Path(__file__).resolve().parent / "assets"

from repopull.sync import (
    ProgressFn,
    RowCallback,
    inspect_repo,
    status_report,
    sync_report,
)


def _boottime() -> float | None:
    """Seconds since boot including suspend, when the platform exposes it."""
    clock = getattr(time, "CLOCK_BOOTTIME", None)
    if clock is None:
        return None
    try:
        return time.clock_gettime(clock)
    except OSError:
        return None


class DiscoverySignals(QObject):
    """Signals from a background repository scan."""

    finished = Signal(list)
    failed = Signal(str)


class DiscoveryTask(QRunnable):
    """Scan the watched root without blocking the window."""

    def __init__(
        self, root: Path, max_depth: int, ignore: tuple[str, ...]
    ) -> None:
        super().__init__()
        self.root = root
        self.max_depth = max_depth
        self.ignore = ignore
        self.signals = DiscoverySignals()

    def run(self) -> None:
        try:
            refs = discover_repos(
                self.root,
                max_depth=self.max_depth,
                ignore=self.ignore,
            )
        except Exception as exc:  # noqa: BLE001 - report to the UI
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(refs)


class MainWindow(QMainWindow):
    """One window that reads the same config and report files as the CLI."""

    def __init__(
        self, config: Config, *, discover_async: bool = False
    ) -> None:
        super().__init__()
        self.config = config
        self._discover_async = discover_async
        self._discovery_generation = 0
        self._discovery_task: DiscoveryTask | None = None
        self._discovery_callback: Callable[[], None] | None = None
        self._check_task: DiscoveryTask | None = None
        self._check_generation = 0
        self._ui_state = load_ui_state(config.config_path)
        self.report: Report | None = load_latest_report(config.log_dir)
        self.rows_by_label: dict[str, Row] = (
            {row.label: row for row in self.report.rows}
            if self.report is not None
            else {}
        )
        self.row_widgets: dict[str, RepoRow] = {}
        self.refs: list[RepoRef] = []
        self.discovery_error: str | None = None
        self.filter = (
            self._ui_state.filter
            if self._ui_state is not None
            else "all"
        )
        self.search = ""
        self.task: RunTask | None = None
        self._quit_requested = False
        self._loading_settings = False
        self._settings_section = 0
        self._settings_dirty = False
        self._lfs_status: LfsStatus | None = None
        self._lfs_last_check = 0.0
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        self._auto_pause_action: QAction | None = None
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_refresh_due)
        boottime = _boottime()
        self._suspend_detector: SuspendDetector | None = (
            SuspendDetector(max(0.0, boottime - time.monotonic()))
            if boottime is not None
            else None
        )
        self.suspend_timer = QTimer(self)
        self.suspend_timer.setInterval(int(SUSPEND_POLL_INTERVAL_S * 1000))
        self.suspend_timer.timeout.connect(self._check_suspend)
        if self._suspend_detector is not None:
            self.suspend_timer.start()
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._resume_check_due)
        self._resume_pending = False
        self._auto_run = False
        self._auto_paused = False
        self._auto_failures = 0
        self._network_offline = bool(
            self.report is not None and self.report.network_error
        )
        self._last_network_finished: float | None = None
        self.current_label: str | None = None

        self.setWindowTitle("repopull")
        self.resize(1040, 720)
        self.setMinimumSize(860, 560)

        if discover_async:
            self.discovery_error = (
                "No watched folder configured. Open Settings and choose one."
                if config.root is None
                else "Scanning the watched folder…"
            )
        else:
            self._reload_refs()
        self._build()
        if self.filter in self.nav_buttons:
            self.nav_buttons[self.filter].setChecked(True)
        self._populate_settings()
        self._render_library()
        self._update_status_block()
        self._apply_background_mode()
        self._schedule_auto_refresh()
        if self._ui_state is not None and self._ui_state.page == "settings":
            self._show_settings()
        if discover_async:
            self._start_discovery()
        elif self._ui_state is not None and self._ui_state.page == "detail":
            self._restore_detail()

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

        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.settings_status = QLabel("All changes saved")
        self.settings_status.setObjectName("SettingsStatus")
        self.settings_status.setAccessibleName("Settings save status")
        header.addWidget(self.settings_status)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        nav = QWidget()
        nav.setFixedWidth(140)
        nav.setAccessibleName("Settings sections")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)
        self.settings_nav_group = QButtonGroup(self)
        self.settings_nav_group.setExclusive(True)
        self.settings_nav_buttons: list[QPushButton] = []
        for index, name in enumerate(SETTINGS_SECTIONS):
            button = QPushButton(name)
            button.setObjectName("SettingsNav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"{name} settings")
            self.settings_nav_group.addButton(button, index)
            nav_layout.addWidget(button)
            self.settings_nav_buttons.append(button)
        nav_layout.addStretch(1)
        body.addWidget(nav)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.settings_scroll.setStyleSheet("background: transparent;")
        self.settings_scroll.viewport().setStyleSheet("background: transparent;")

        self.settings_stack = QStackedWidget()
        self.settings_pages: list[QWidget] = []
        builders = (
            self._build_settings_watching,
            self._build_settings_refresh,
            self._build_settings_network,
            self._build_settings_updates,
            self._build_settings_storage,
        )
        for build in builders:
            section = QWidget()
            column = QVBoxLayout(section)
            column.setContentsMargins(0, 0, 8, 0)
            column.setSpacing(14)
            build(column)
            column.addStretch(1)
            self.settings_stack.addWidget(section)
            self.settings_pages.append(section)
        self.settings_scroll.setWidget(self.settings_stack)
        body.addWidget(self.settings_scroll, 1)
        layout.addLayout(body, 1)

        actions = QHBoxLayout()
        self.reset_button = QPushButton("Reset to defaults")
        self.reset_button.setObjectName("Ghost")
        self.reset_button.setToolTip(
            "Restore the shipped defaults in the form; Save writes them."
        )
        self.reset_button.clicked.connect(self._reset_settings)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.save_button = QPushButton("Save settings")
        self.save_button.setObjectName("Primary")
        self.save_button.setToolTip(
            "Write these settings to config.toml. Hand-written comments are removed."
        )
        self.save_button.clicked.connect(self._save_settings)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

        self.settings_nav_group.idToggled.connect(
            self._settings_section_toggled
        )
        self.settings_nav_buttons[0].setChecked(True)
        self.settings_stack.setCurrentIndex(0)
        self._set_settings_dirty(False)
        return page

    def _build_settings_watching(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Watching")

        root_controls = QWidget()
        root_layout = QVBoxLayout(root_controls)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        root_row = QHBoxLayout()
        root_row.setSpacing(8)
        self.settings_root = QLineEdit()
        self.settings_root.setPlaceholderText("/path/to/repositories")
        self.settings_root.setAccessibleName("Watched folder")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(self.settings_root, 1)
        root_row.addWidget(browse)
        root_layout.addLayout(root_row)

        check_row = QHBoxLayout()
        check_row.setSpacing(8)
        self.check_button = QPushButton("Check folder")
        self.check_button.clicked.connect(self._check_root)
        self.check_result = QLabel("")
        self.check_result.setObjectName("SettingHint")
        self.check_result.setWordWrap(True)
        check_row.addWidget(self.check_button)
        check_row.addWidget(self.check_result, 1)
        root_layout.addLayout(check_row)

        card.add(
            SettingRow(
                "Watched folder",
                "The folder scanned for Git repositories.",
                root_controls,
                below=True,
            )
        )

        self.settings_max_depth = QSpinBox()
        self.settings_max_depth.setRange(1, 4)
        self.settings_max_depth.setFixedWidth(120)
        self.settings_max_depth.setAccessibleName("Search depth")
        card.add(
            SettingRow(
                "Depth",
                "1 = direct children; 2 = grandchildren too.",
                self.settings_max_depth,
            )
        )

        self.settings_ignore = QPlainTextEdit()
        self.settings_ignore.setPlaceholderText(
            "One glob per line, e.g.\nphotocraft-corpus\n*.old"
        )
        self.settings_ignore.setFixedHeight(92)
        self.settings_ignore.setTabChangesFocus(True)
        self.settings_ignore.setAccessibleName("Ignored repository globs")
        card.add(
            SettingRow(
                "Ignore",
                "Matches the relative label and the repository name.",
                self.settings_ignore,
                below=True,
            )
        )
        column.addWidget(card)

        self.settings_root.textChanged.connect(self._on_settings_edited)
        self.settings_max_depth.valueChanged.connect(
            self._on_settings_edited
        )
        self.settings_ignore.textChanged.connect(self._on_settings_edited)

    def _build_settings_refresh(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Refresh")

        self.settings_background = QCheckBox()
        self.settings_background.setAccessibleName(
            "Keep running in the system tray"
        )
        self.settings_background.setEnabled(self._tray_available)
        if not self._tray_available:
            self.settings_background.setToolTip(
                "The system tray is not available in this session."
            )
        card.add(
            SettingRow(
                "Keep running in the system tray",
                "When checked, closing hides the window instead of quitting.",
                self.settings_background,
            )
        )

        self.settings_tray_status = QLabel(
            "System tray is available. The tray icon is visible while repopull "
            "runs; closing keeps it there only when this box is checked."
            if self._tray_available
            else "System tray is not available in this session; background mode "
            "is disabled and closing quits."
        )
        self.settings_tray_status.setObjectName("SettingHint")
        self.settings_tray_status.setWordWrap(True)
        card.add_note(self.settings_tray_status)

        self.settings_auto = QCheckBox()
        self.settings_auto.setAccessibleName("Refresh status automatically")
        card.add(
            SettingRow(
                "Refresh status automatically",
                "Status only — it never syncs or changes a working tree.",
                self.settings_auto,
            )
        )

        self.settings_hidden_pause = QCheckBox()
        self.settings_hidden_pause.setAccessibleName(
            "Pause automatic refresh while hidden"
        )
        self.settings_hidden_pause.setToolTip(
            "No automatic checks while the window is closed to the tray or "
            "minimized. The next check runs when the window returns, if due."
        )
        card.add(
            SettingRow(
                "Pause while hidden",
                "Automatic checks stop when the window is closed to the tray "
                "or minimized.",
                self.settings_hidden_pause,
            )
        )

        self.settings_auto_minutes = QSpinBox()
        self.settings_auto_minutes.setRange(5, 1440)
        self.settings_auto_minutes.setSuffix(" minutes")
        self.settings_auto_minutes.setValue(15)
        self.settings_auto_minutes.setFixedWidth(150)
        self.settings_auto_minutes.setAccessibleName(
            "Automatic refresh interval"
        )
        card.add(
            SettingRow(
                "Check every",
                "5-minute floor. Each check may wake a spinning hard disk.",
                self.settings_auto_minutes,
            )
        )

        self.settings_auto_warning = QLabel(
            "Frequent fetches increase load on remote servers; "
            "15 minutes or longer is recommended."
        )
        self.settings_auto_warning.setObjectName("SettingWarning")
        self.settings_auto_warning.setWordWrap(True)
        self.settings_auto_warning.setVisible(False)
        card.add_note(self.settings_auto_warning)

        immediate = QLabel(
            "Background and refresh changes apply immediately."
        )
        immediate.setObjectName("SettingHint")
        immediate.setWordWrap(True)
        card.add_note(immediate)

        self.settings_background.toggled.connect(self._on_background_toggled)
        self.settings_auto.toggled.connect(self._on_auto_toggled)
        self.settings_hidden_pause.toggled.connect(
            self._on_hidden_pause_toggled
        )
        self.settings_auto_minutes.valueChanged.connect(
            self._on_auto_minutes_changed
        )
        column.addWidget(card)

    def _build_settings_network(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Network")

        self.settings_delay = QDoubleSpinBox()
        self.settings_delay.setRange(0.0, 60.0)
        self.settings_delay.setSingleStep(0.5)
        self.settings_delay.setSuffix(" s")
        self.settings_delay.setFixedWidth(140)
        self.settings_delay.setAccessibleName(
            "Delay between fetches"
        )
        card.add(
            SettingRow(
                "Delay between fetches",
                "Polite pause between repositories.",
                self.settings_delay,
            )
        )

        self.settings_fetch_timeout = QSpinBox()
        self.settings_fetch_timeout.setRange(10, 3600)
        self.settings_fetch_timeout.setSuffix(" s")
        self.settings_fetch_timeout.setFixedWidth(140)
        self.settings_fetch_timeout.setAccessibleName("Fetch timeout")
        card.add(
            SettingRow(
                "Fetch timeout",
                "A fetch that takes longer is abandoned.",
                self.settings_fetch_timeout,
            )
        )

        self.settings_command_timeout = QSpinBox()
        self.settings_command_timeout.setRange(10, 600)
        self.settings_command_timeout.setSuffix(" s")
        self.settings_command_timeout.setFixedWidth(140)
        self.settings_command_timeout.setAccessibleName(
            "Other git command timeout"
        )
        card.add(
            SettingRow(
                "Other git timeout",
                "Inspection and submodule commands.",
                self.settings_command_timeout,
            )
        )
        column.addWidget(card)

        self.settings_delay.valueChanged.connect(self._on_settings_edited)
        self.settings_fetch_timeout.valueChanged.connect(
            self._on_settings_edited
        )
        self.settings_command_timeout.valueChanged.connect(
            self._on_settings_edited
        )

    def _build_settings_updates(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Updates")

        self.settings_submodules = QCheckBox()
        self.settings_submodules.setAccessibleName(
            "Run git submodule update after a pull"
        )
        card.add(
            SettingRow(
                "Update submodules",
                "Runs git submodule update --init --recursive after a "
                "fast-forward.",
                self.settings_submodules,
            )
        )

        self.settings_lfs = QCheckBox()
        self.settings_lfs.setAccessibleName(
            "Skip LFS repositories when Git LFS is not ready"
        )
        self.settings_lfs.setToolTip(
            "Requires git-lfs to be installed and enabled (git lfs install)"
        )
        card.add(
            SettingRow(
                "Skip LFS repositories when Git LFS is not ready",
                "Keeps pointer files from replacing real content.",
                self.settings_lfs,
            )
        )

        lfs_row = QHBoxLayout()
        lfs_row.setContentsMargins(0, 0, 0, 0)
        lfs_row.setSpacing(8)
        self.settings_lfs_status = QLabel("-")
        self.settings_lfs_status.setObjectName("SettingHint")
        lfs_row.addWidget(self.settings_lfs_status)
        lfs_row.addStretch(1)
        self.settings_lfs_check = QPushButton("Check again")
        self.settings_lfs_check.setObjectName("Ghost")
        self.settings_lfs_check.setAccessibleName(
            "Check Git LFS status again"
        )
        self.settings_lfs_check.setToolTip(
            "Re-read git-lfs and the Git LFS filters now."
        )
        self.settings_lfs_check.clicked.connect(
            lambda: self._refresh_lfs_status(force=True)
        )
        lfs_row.addWidget(self.settings_lfs_check)
        lfs_help = QPushButton("Help…")
        lfs_help.setObjectName("Ghost")
        lfs_help.clicked.connect(lambda: self._show_lfs_help())
        lfs_row.addWidget(lfs_help)
        lfs_widget = QWidget()
        lfs_widget.setLayout(lfs_row)
        card.add(
            SettingRow(
                "Git LFS",
                "Whether git-lfs is installed and enabled.",
                lfs_widget,
                below=True,
            )
        )
        column.addWidget(card)

        self.settings_submodules.toggled.connect(self._on_settings_edited)
        self.settings_lfs.toggled.connect(self._on_settings_edited)

    def _build_settings_storage(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Storage")

        self.settings_config_label = QLabel("-")
        self.settings_config_label.setObjectName("SettingValue")
        self.settings_config_label.setAccessibleName("Config file path")
        self.settings_config_label.setWordWrap(True)
        self.settings_config_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card.add(
            SettingRow(
                "Config file",
                "The TOML file the GUI and CLI share.",
                self.settings_config_label,
                below=True,
            )
        )

        self.settings_logs_label = QLabel("-")
        self.settings_logs_label.setObjectName("SettingValue")
        self.settings_logs_label.setAccessibleName("Logs directory")
        self.settings_logs_label.setWordWrap(True)
        self.settings_logs_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card.add(
            SettingRow(
                "Logs",
                "Where run reports are written.",
                self.settings_logs_label,
                below=True,
            )
        )

        self.settings_retention = QSpinBox()
        self.settings_retention.setRange(0, 3650)
        self.settings_retention.setSuffix(" days")
        self.settings_retention.setSpecialValueText("Keep all")
        self.settings_retention.setFixedWidth(150)
        self.settings_retention.setAccessibleName("Keep run logs")
        self.settings_retention.setToolTip(
            "Delete run logs older than this; 0 keeps every run log."
        )
        card.add(
            SettingRow(
                "Keep run logs",
                "0 keeps every run log.",
                self.settings_retention,
            )
        )

        comments = QLabel(
            "Saving rewrites config.toml and removes comments you added to it."
        )
        comments.setObjectName("SettingHint")
        comments.setWordWrap(True)
        card.add_note(comments)
        column.addWidget(card)

        self.settings_retention.valueChanged.connect(
            self._on_settings_edited
        )

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

    def _save_ui_state(self) -> None:
        current = self.stack.currentWidget()
        if current is self.settings_page:
            page = "settings"
            repo = ""
        elif current is self.detail_page:
            page = "detail"
            repo = self.current_label or ""
        else:
            page = "library"
            repo = ""
        state = UiState(page=page, filter=self.filter, repo=repo)
        self._ui_state = state
        save_ui_state(self.config.config_path, state)

    def _restore_detail(self) -> None:
        state = self._ui_state
        if state is None or state.page != "detail" or not state.repo:
            return
        if any(ref.label == state.repo for ref in self.refs):
            self._open_detail(state.repo)
            return
        self._ui_state = UiState(page="library", filter=self.filter)
        self._save_ui_state()

    def _set_filter(self, key: str) -> None:
        self.filter = key
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.library_page)
        self._render_library()
        self._save_ui_state()

    def _settings_section_toggled(self, index: int, checked: bool) -> None:
        if not checked:
            return
        self._settings_section = index
        self.settings_stack.setCurrentIndex(index)
        self.settings_scroll.verticalScrollBar().setValue(0)

    def _select_settings_section(self, index: int) -> None:
        """Show one settings section without losing drafts in the others."""
        if not 0 <= index < len(self.settings_nav_buttons):
            return
        self._settings_section = index
        self.settings_nav_buttons[index].setChecked(True)
        self.settings_stack.setCurrentIndex(index)
        self.settings_scroll.verticalScrollBar().setValue(0)

    def _show_settings(self) -> None:
        self.settings_button.setChecked(True)
        if not self._settings_dirty:
            self._populate_settings()
        else:
            self._refresh_lfs_status()
        self.stack.setCurrentWidget(self.settings_page)
        self._select_settings_section(self._settings_section)
        self._save_ui_state()

    def _open_watched_settings(self) -> None:
        """Jump straight to the watched folder field."""
        self._show_settings()
        self._select_settings_section(0)
        self.settings_root.setFocus()
        self.settings_root.selectAll()

    def _back_to_library(self) -> None:
        self.stack.setCurrentWidget(self.library_page)
        self._render_library()
        self._save_ui_state()

    def _on_search(self, text: str) -> None:
        self.search = text.strip()
        self._render_library()

    # --------------------------------------------------------------- rendering

    def _start_discovery(
        self, callback: Callable[[], None] | None = None
    ) -> None:
        """Scan in the background so a dead mount cannot freeze the UI."""
        if self._quit_requested:
            return
        self._discovery_generation += 1
        generation = self._discovery_generation
        self._discovery_callback = callback
        root = self.config.root
        if root is None:
            self.refs = []
            self._discovery_callback = None
            self.discovery_error = (
                "No watched folder configured. Open Settings and choose one."
            )
            self._render_library()
            self._update_status_block()
            self._schedule_auto_refresh()
            return

        self.refs = []
        self.discovery_error = "Scanning the watched folder…"
        self._render_library()
        task = DiscoveryTask(
            root, self.config.max_depth, self.config.ignore
        )
        task.signals.finished.connect(
            lambda refs: self._on_discovery_finished(generation, refs)
        )
        task.signals.failed.connect(
            lambda message: self._on_discovery_failed(generation, message)
        )
        self._discovery_task = task
        QThreadPool.globalInstance().start(task)

    def _on_discovery_finished(
        self, generation: int, refs: list[RepoRef]
    ) -> None:
        if generation != self._discovery_generation or self._quit_requested:
            return
        self._discovery_task = None
        found = [ref for ref in refs if isinstance(ref, RepoRef)]
        self.refs = found
        problem = verify_root_state(
            self.config.log_dir, self.config.root, len(found)
        ) if self.config.root is not None else None
        if problem is not None:
            self.refs = []
            self.discovery_error = (
                f"{problem}. Remove {self.config.log_dir / ROOT_STATE_FILE} "
                "if this is intentional."
            )
        else:
            self.discovery_error = None
        self._render_library()
        self._update_status_block()
        self._schedule_auto_refresh()
        self._restore_detail()
        callback = self._discovery_callback
        self._discovery_callback = None
        if callback is not None and not self._quit_requested:
            callback()

    def _on_discovery_failed(self, generation: int, message: str) -> None:
        if generation != self._discovery_generation or self._quit_requested:
            return
        self._discovery_task = None
        self._discovery_callback = None
        self.refs = []
        self.discovery_error = message
        self._render_library()
        self._update_status_block()
        self._schedule_auto_refresh()
        self._flash(message)

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
        except DiscoveryError as exc:
            self.refs = []
            self.discovery_error = str(exc)
            return
        problem = verify_root_state(
            self.config.log_dir, root, len(self.refs)
        )
        if problem is not None:
            self.refs = []
            self.discovery_error = (
                f"{problem}. Remove {self.config.log_dir / ROOT_STATE_FILE} "
                "if this is intentional."
            )
            return
        self.discovery_error = None

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
        self._refresh_lfs_status()
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
        self.settings_hidden_pause.setChecked(
            self.config.auto_refresh_pause_when_hidden
        )
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
        self._set_settings_dirty(False)

    def _apply_lfs_status(self, status: LfsStatus) -> None:
        if not status.installed:
            self.settings_lfs_status.setText("not installed")
            return
        version = f" · {status.version.split()[0]}" if status.version else ""
        state = "enabled" if status.enabled else "not enabled"
        self.settings_lfs_status.setText(f"installed{version} · {state}")

    def _refresh_lfs_status(self, *, force: bool = False) -> None:
        """Re-read Git LFS state until it is ready; force is the manual escape.

        "Ready" means installed and enabled. Once ready, the result is kept for
        the rest of the session unless the user presses Check again.
        """
        if (
            not force
            and self._lfs_status is not None
            and self._lfs_status.installed
            and self._lfs_status.enabled
        ):
            return
        status = lfs_status()
        self._lfs_status = status
        self._lfs_last_check = time.monotonic()
        self._apply_lfs_status(status)

    def _maybe_refresh_lfs_status(self) -> None:
        """Catch an install completed while Settings stayed open."""
        if self.stack.currentWidget() is not self.settings_page:
            return
        if (
            self._lfs_status is not None
            and self._lfs_status.installed
            and self._lfs_status.enabled
        ):
            return
        if time.monotonic() - self._lfs_last_check < 5.0:
            return
        self._refresh_lfs_status()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._resume_after_visible()
            self._update_tray_tooltip()
        elif (
            event.type() == QEvent.Type.ActivationChange
            and self.isActiveWindow()
        ):
            self._maybe_refresh_lfs_status()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._resume_after_visible()
        self._update_tray_tooltip()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._schedule_auto_refresh()
        self._update_tray_tooltip()

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
        self._save_ui_state()

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

    def _on_settings_edited(self, *_args: object) -> None:
        if not self._loading_settings:
            self._set_settings_dirty(True)

    def _set_settings_dirty(self, dirty: bool) -> None:
        """Update the header status and the Save button for deferred fields."""
        self._settings_dirty = dirty
        self.settings_status.setText(
            "● Unsaved changes" if dirty else "All changes saved"
        )
        self.settings_status.setProperty("dirty", dirty)
        style = self.settings_status.style()
        style.unpolish(self.settings_status)
        style.polish(self.settings_status)
        self.settings_status.update()
        self.save_button.setEnabled(dirty)

    def _on_background_toggled(self, _checked: bool) -> None:
        if self._loading_settings:
            return
        self._sync_behavior_settings()

    def _on_auto_toggled(self, _checked: bool) -> None:
        if self._loading_settings:
            return
        self._sync_behavior_settings()
        self._update_auto_controls()

    def _on_hidden_pause_toggled(self, _checked: bool) -> None:
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
        pause_hidden = self.settings_hidden_pause.isChecked()
        self.config = dataclasses.replace(
            self.config,
            background_mode=background,
            auto_refresh_s=auto,
            auto_refresh_pause_when_hidden=pause_hidden,
        )
        target = self.config.config_path
        if target is not None:
            try:
                save_behavior_settings(
                    target,
                    background_mode=background,
                    auto_refresh_s=auto,
                    auto_refresh_pause_when_hidden=pause_hidden,
                )
            except OSError as exc:
                self._set_settings_dirty(True)
                self._flash(f"Could not save background settings: {exc}")
        self._apply_background_mode()
        self._schedule_auto_refresh()

    def _update_auto_controls(self) -> None:
        self.settings_auto_minutes.setEnabled(True)
        self.settings_hidden_pause.setEnabled(
            self.settings_auto.isChecked()
        )
        warn = self.settings_auto.isChecked() and should_warn(
            self.settings_auto_minutes.value() * 60
        )
        self.settings_auto_warning.setVisible(warn)

    def _save_settings(self) -> None:
        root_text = self.settings_root.text().strip()
        if not root_text:
            self._select_settings_section(0)
            self.settings_root.setFocus()
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
            auto_refresh_pause_when_hidden=(
                self.settings_hidden_pause.isChecked()
            ),
        )
        try:
            save_config(updated, target)
            self.config = load_config(config_path=target)
        except (OSError, ConfigError) as exc:
            self._set_settings_dirty(True)
            QMessageBox.warning(
                self, "repopull", f"Could not save settings: {exc}"
            )
            return
        if self._discover_async:
            self._start_discovery()
        else:
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
        self.settings_hidden_pause.setChecked(False)
        blocker = QSignalBlocker(self.settings_auto_minutes)
        self.settings_auto_minutes.setValue(15)
        del blocker
        self._loading_settings = False
        self._update_auto_controls()
        self.check_result.setText("")
        self._set_settings_dirty(True)
        self._flash("Defaults restored; press Save settings to write them.")

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
        self._check_generation += 1
        generation = self._check_generation
        self.check_button.setEnabled(False)
        self.check_result.setText("Checking…")
        task = DiscoveryTask(
            Path(text).expanduser(),
            int(self.settings_max_depth.value()),
            ignore,
        )
        task.signals.finished.connect(
            lambda refs: self._on_check_finished(generation, refs)
        )
        task.signals.failed.connect(
            lambda message: self._on_check_failed(generation, message)
        )
        self._check_task = task
        QThreadPool.globalInstance().start(task)

    def _on_check_finished(
        self, generation: int, refs: list[RepoRef]
    ) -> None:
        if generation != self._check_generation:
            return
        self._check_task = None
        self.check_button.setEnabled(True)
        self.check_result.setText(
            f"✓ Found {len([ref for ref in refs if isinstance(ref, RepoRef)])} repositories"
        )

    def _on_check_failed(self, generation: int, message: str) -> None:
        if generation != self._check_generation:
            return
        self._check_task = None
        self.check_button.setEnabled(True)
        self.check_result.setText(f"✗ {message}")

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
        self.suspend_timer.stop()
        self._resume_timer.stop()
        self._resume_pending = False
        self._discovery_generation += 1
        self._discovery_callback = None
        self._check_generation += 1
        self._check_task = None
        if self._quit_requested:
            if self.task is None:
                self._quit_application()
            return
        self._quit_requested = True
        if self.task is not None:
            self.task.cancel.set()
            self.cancel_button.setEnabled(False)
            self._flash("Stopping the current git command…")
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
            self._resume_timer.stop()
            self._resume_pending = False
        else:
            self._schedule_auto_refresh()
        self._update_tray_tooltip()

    def _jitter_seconds(self) -> float:
        return float(random.randint(0, AUTO_REFRESH_JITTER_S))

    def _auto_visible_allowed(self) -> bool:
        if not self.config.auto_refresh_pause_when_hidden:
            return True
        return self.isVisible() and not self.isMinimized()

    def _refresh_state(self) -> RefreshState:
        return RefreshState(
            interval_s=self.config.auto_refresh_s,
            quitting=self._quit_requested,
            paused=self._auto_paused,
            window_available=self.isVisible() and not self.isMinimized(),
            pause_when_hidden=self.config.auto_refresh_pause_when_hidden,
            in_flight=self.task is not None,
            has_repos=bool(self.refs),
            network_offline=self._network_offline,
            failures=self._auto_failures,
            last_finished=self._last_network_finished,
            resume_pending=self._resume_pending,
            now=time.monotonic(),
        )

    def _apply_refresh_decision(self, decision: RefreshDecision) -> None:
        if decision.clear_resume:
            self._resume_timer.stop()
            self._resume_pending = False
        if decision.action is RefreshAction.STOP:
            self.auto_timer.stop()
            return
        if decision.action is RefreshAction.WAIT:
            self.auto_timer.start(max(1, int(decision.delay_s * 1000)))
            return
        self.auto_timer.stop()
        self._start_run(self.refs, force=False, mode="status", auto=True)

    def _resume_after_visible(self) -> None:
        """Resume the timer, or catch up one run when the interval is due."""
        self._apply_refresh_decision(
            decide_refresh(
                self._refresh_state(),
                RefreshEvent.SHOW,
                jitter_s=self._jitter_seconds(),
            )
        )

    def _schedule_auto_refresh(self) -> None:
        if self._auto_pause_action is not None:
            self._auto_pause_action.setEnabled(self.config.auto_refresh_s > 0)
        self._apply_refresh_decision(
            decide_refresh(
                self._refresh_state(),
                RefreshEvent.SCHEDULE,
                jitter_s=self._jitter_seconds(),
            )
        )

    def _auto_refresh_due(self) -> None:
        self._check_suspend()
        self._apply_refresh_decision(
            decide_refresh(
                self._refresh_state(),
                RefreshEvent.TIMER,
                jitter_s=self._jitter_seconds(),
            )
        )

    def _check_suspend(self) -> None:
        detector = self._suspend_detector
        boottime = _boottime() if detector is not None else None
        if detector is None or boottime is None or self._quit_requested:
            return
        gap = detector.poll(boottime, time.monotonic())
        if gap > 0:
            self._on_resume(gap)

    def _on_resume(self, gap_s: float) -> None:
        """Defer one status check until the desktop has settled."""
        if not self._auto_visible_allowed():
            self._resume_pending = False
            self.auto_timer.stop()
            return
        if (
            self._quit_requested
            or self.config.auto_refresh_s <= 0
            or self._auto_paused
        ):
            return
        self.auto_timer.stop()
        self._resume_pending = True
        self._resume_timer.start(int(SUSPEND_RESUME_GRACE_S * 1000))
        minutes = max(1, round(gap_s / 60))
        self._flash(f"Resumed after {minutes} min; checking in 60 s…")

    def _resume_check_due(self) -> None:
        if not self._auto_visible_allowed():
            self._resume_pending = False
            self._schedule_auto_refresh()
            return
        if (
            self._quit_requested
            or self.config.auto_refresh_s <= 0
            or self._auto_paused
        ):
            self._resume_pending = False
            return
        if self.task is not None:
            # The pre-sleep run is still winding down; let it finish first.
            self._resume_timer.start(15_000)
            return
        self._resume_pending = False
        if self._discover_async:
            self._start_discovery(callback=self._resume_start_run)
            return
        self._reload_refs()
        self._render_library()
        self._resume_start_run()

    def _resume_start_run(self) -> None:
        if not self._auto_visible_allowed():
            self._schedule_auto_refresh()
            return
        if (
            self._quit_requested
            or self.config.auto_refresh_s <= 0
            or self._auto_paused
            or self._resume_pending
        ):
            return
        if self.task is not None:
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
            if not self._auto_visible_allowed():
                text += "\nAutomatic refresh paused while hidden"
            elif self._network_offline:
                text += "\nNetwork unavailable; retrying"
            else:
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
        if auto and not self._auto_visible_allowed():
            self._schedule_auto_refresh()
            return
        if not refs:
            self._flash("No repositories to run.")
            if auto:
                self._schedule_auto_refresh()
            return
        problem = check_log_dir(self.config.log_dir)
        if problem is not None:
            self._flash(problem)
            if auto:
                self._schedule_auto_refresh()
            return
        if not auto:
            self.auto_timer.stop()
            self._resume_timer.stop()
            self._resume_pending = False
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
        self._network_offline = report.network_error
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
        message = self._summary(report)
        if report.network_error:
            message += " · network unavailable"
        self._flash(message)
        self._update_tray_tooltip()
        self._refresh_lfs_status()
        self._schedule_auto_refresh()
        self._maybe_quit_after_task()

    def _on_cancelled(self, report: object) -> None:
        self._auto_run = False
        self._last_network_finished = time.monotonic()
        self._auto_failures = 0
        self._network_offline = False
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
        self._network_offline = False
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
