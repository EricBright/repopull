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
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
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
    QDialog,
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

from repopull import __version__, autostart, git
from repopull.clone import CloneResult
from repopull.config import (
    Config,
    ConfigError,
    default_config_path,
    load_config,
    save_behavior_settings,
    save_config,
    save_repo_holds,
)
from repopull.discovery import DiscoveryError, discover_repos
from repopull.diagnostics import LfsStatus, lfs_status
from repopull.gui.clone_dialog import CloneDialog
from repopull.gui.instance import Channel
from repopull.gui.jobs import CloneTask, RunTask
from repopull.gui.lfs_help import LfsHelpDialog
from repopull.gui.rows import RepoRow, RowView, row_view, unchecked_view
from repopull.gui.settings import (
    SETTINGS_SECTIONS,
    SettingRow,
    SettingsCard,
)
from repopull.gui.switch import Switch
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
from repopull.rootstate import (
    ROOT_STATE_FILE,
    RootStateChanged,
    RootStateCheck,
    check_root_state,
    describe_identity,
    describe_state,
    repair_root_state,
)
from repopull.uistate import UiState, load_ui_state, save_ui_state
from repopull.updates import Release, UpdateError, is_newer, latest_release
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
    checked = Signal(list, object)
    failed = Signal(str)


class DiscoveryTask(QRunnable):
    """Scan the watched root without blocking the window."""

    def __init__(
        self,
        root: Path,
        max_depth: int,
        ignore: tuple[str, ...],
        *,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.root = root
        self.max_depth = max_depth
        self.ignore = ignore
        self.log_dir = log_dir
        self.signals = DiscoverySignals()

    def run(self) -> None:
        try:
            refs = discover_repos(
                self.root,
                max_depth=self.max_depth,
                ignore=self.ignore,
            )
            if self.log_dir is None:
                self.signals.finished.emit(refs)
                return
            check = check_root_state(self.log_dir, self.root, len(refs))
        except Exception as exc:  # noqa: BLE001 - report to the UI
            self.signals.failed.emit(str(exc))
            return
        self.signals.checked.emit(refs, check)


class UpdateSignals(QObject):
    """Signals from a background release check."""

    finished = Signal(object)
    failed = Signal(str)


class UpdateTask(QRunnable):
    """Ask GitHub for the newest release without blocking the window."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = UpdateSignals()

    def run(self) -> None:
        try:
            release = latest_release()
        except UpdateError as exc:
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - report to the UI
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(release)


class MainWindow(QMainWindow):
    """One window that reads the same config and report files as the CLI."""

    def __init__(
        self,
        config: Config,
        *,
        discover_async: bool = False,
        hidden: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self._discover_async = discover_async
        self._hidden_requested = hidden
        self._channel: Channel | None = None
        self._update_task: UpdateTask | None = None
        self._release: Release | None = None
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
        self.root_state_check: RootStateCheck | None = None
        self.filter = (
            self._ui_state.filter
            if self._ui_state is not None
            else "all"
        )
        self.search = ""
        self.task: RunTask | None = None
        self.clone_task: CloneTask | None = None
        self._quit_requested = False
        self._loading_settings = False
        self._loading_autostart = False
        self._loading_holds = False
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
        self._apply_field_insets()
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

        meta = QWidget()
        meta_layout = QVBoxLayout(meta)
        # Match QPushButton#Nav's horizontal padding so every sidebar text
        # starts on the same column (the pill backgrounds keep their inset).
        meta_layout.setContentsMargins(12, 0, 0, 0)
        meta_layout.setSpacing(6)

        self.watched_link = QPushButton("Watched folder")
        self.watched_link.setObjectName("Link")
        self.watched_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watched_link.clicked.connect(self._open_watched_settings)
        meta_layout.addWidget(self.watched_link)

        self.last_label = QLabel("Last check —")
        self.last_label.setObjectName("Faint")
        self.last_label.setToolTip(
            "The last completed run; a sync also counts as a check."
        )
        meta_layout.addWidget(self.last_label)

        self.next_label = QPushButton("Next check —")
        self.next_label.setObjectName("FaintLink")
        self.next_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_label.setToolTip(
            "Open the Refresh settings to change automatic checks."
        )
        self.next_label.clicked.connect(self._open_refresh_settings)
        meta_layout.addWidget(self.next_label)

        version = QLabel(f"v{__version__}")
        version.setObjectName("Faint")
        meta_layout.addWidget(version)

        box.addWidget(meta)

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

        self.clone_button = QPushButton("Clone…")
        self.clone_button.setObjectName("Ghost")
        self.clone_button.setToolTip(
            "Clone a remote repository into the watched folder"
        )
        self.clone_button.clicked.connect(self._clone)
        header.addWidget(self.clone_button)

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

        self.repair_button = QPushButton("Repair saved root state…")
        self.repair_button.setObjectName("Primary")
        self.repair_button.setToolTip(
            "Review the saved and current disk identities, then accept the "
            "current one if this is the disk you expect."
        )
        self.repair_button.clicked.connect(self._repair_root_state)
        self.repair_button.hide()
        layout.addWidget(
            self.repair_button, 0, Qt.AlignmentFlag.AlignHCenter
        )

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
            if key == "path":
                self.detail_open = QPushButton("Open folder")
                self.detail_open.setObjectName("Link")
                self.detail_open.setToolTip(
                    "Open this repository in your default file manager."
                )
                self.detail_open.clicked.connect(self._open_folder_current)
                grid.addWidget(self.detail_open, index, 2)
        grid.setColumnStretch(1, 1)
        layout.addWidget(card)

        holds = SettingsCard("Bulk actions")
        self.detail_exclude_refresh = Switch()
        self.detail_exclude_refresh.setAccessibleName(
            "Exclude from Refresh status"
        )
        self.detail_exclude_refresh.toggled.connect(self._on_hold_toggled)
        holds.add(
            SettingRow(
                "Exclude from Refresh status",
                "Skip this repository when Refresh status or automatic "
                "checks run.",
                self.detail_exclude_refresh,
            )
        )
        self.detail_exclude_sync = Switch()
        self.detail_exclude_sync.setAccessibleName("Exclude from Sync all")
        self.detail_exclude_sync.toggled.connect(self._on_hold_toggled)
        holds.add(
            SettingRow(
                "Exclude from Sync all",
                "Skip this repository during Sync all and Sync these.",
                self.detail_exclude_sync,
            )
        )
        holds_note = QLabel(
            "These switches only affect bulk actions. Sync this repo and "
            "Force sync… on this page always work."
        )
        holds_note.setObjectName("SettingHint")
        holds_note.setWordWrap(True)
        holds.add_note(holds_note)
        layout.addWidget(holds)

        self.detail_note = QLabel("")
        self.detail_note.setObjectName("Muted")
        self.detail_note.setWordWrap(True)
        layout.addWidget(self.detail_note)
        layout.addStretch(1)

        return page

    def _apply_field_insets(self) -> None:
        """Give text fields a visible inset; QSS padding alone misses QLineEdit."""
        for field in (self.search_box, self.settings_root):
            field.setTextMargins(12, 0, 12, 0)
        for spin in (
            self.settings_max_depth,
            self.settings_auto_minutes,
            self.settings_delay,
            self.settings_fetch_timeout,
            self.settings_command_timeout,
            self.settings_retention,
        ):
            edit = spin.lineEdit()
            if edit is not None:
                edit.setTextMargins(4, 0, 0, 0)

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
            self._build_settings_startup,
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
            "Restore the shipped defaults in the form, then save them with the "
            "footer button. Startup switches apply immediately and are left "
            "alone."
        )
        self.reset_button.clicked.connect(self._reset_settings)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.save_button = QPushButton("Saved")
        self.save_button.setObjectName("SaveButton")
        self.save_button.setProperty("saveState", "clean")
        self.save_button.setToolTip("No unsaved settings.")
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

        self.settings_background = Switch()
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
                "When on, closing hides the window instead of quitting.",
                self.settings_background,
            )
        )

        self.settings_tray_status = QLabel(
            "System tray is available. The tray icon is visible while repopull "
            "runs; closing keeps it there only when this switch is on."
            if self._tray_available
            else "System tray is not available in this session; background mode "
            "is disabled and closing quits."
        )
        self.settings_tray_status.setObjectName("SettingHint")
        self.settings_tray_status.setWordWrap(True)
        card.add_note(self.settings_tray_status)

        self.settings_auto = Switch()
        self.settings_auto.setAccessibleName("Refresh status automatically")
        card.add(
            SettingRow(
                "Refresh status automatically",
                "Status only — it never syncs or changes a working tree.",
                self.settings_auto,
            )
        )

        self.settings_hidden_pause = Switch()
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

        self.settings_interval_hint = QLabel("Applies and saves immediately.")
        self.settings_interval_hint.setObjectName("SettingHint")
        self.settings_interval_hint.setWordWrap(True)
        card.add_note(self.settings_interval_hint)

        self.settings_auto_warning = QLabel(
            "Frequent fetches increase load on remote servers; "
            "15 minutes or longer is recommended."
        )
        self.settings_auto_warning.setObjectName("SettingWarning")
        self.settings_auto_warning.setWordWrap(True)
        self.settings_auto_warning.setVisible(False)
        card.add_note(self.settings_auto_warning)

        self.settings_auto_next = QLabel("")
        self.settings_auto_next.setObjectName("SettingHint")
        self.settings_auto_next.setWordWrap(True)
        card.add_note(self.settings_auto_next)

        self.settings_background.toggled.connect(self._on_background_toggled)
        self.settings_auto.toggled.connect(self._on_auto_toggled)
        self.settings_hidden_pause.toggled.connect(
            self._on_hidden_pause_toggled
        )
        self.settings_auto_minutes.valueChanged.connect(
            self._on_auto_minutes_changed
        )
        column.addWidget(card)

    def _build_settings_startup(self, column: QVBoxLayout) -> None:
        card = SettingsCard("Startup")

        self.settings_login = Switch()
        self.settings_login.setAccessibleName("Launch at login")
        card.add(
            SettingRow(
                "Launch at login",
                "Adds repopull to this desktop's autostart list.",
                self.settings_login,
            )
        )

        self.settings_login_hidden = Switch()
        self.settings_login_hidden.setAccessibleName("Open hidden in the tray")
        card.add(
            SettingRow(
                "Open hidden in the tray",
                "Starts without a window; the tray icon is the only sign it is "
                "running.",
                self.settings_login_hidden,
            )
        )

        self.settings_update_open = QPushButton("Open release page")
        self.settings_update_open.setObjectName("Ghost")
        self.settings_update_open.setAccessibleName("Open the release page")
        self.settings_update_open.setVisible(False)
        self.settings_update_open.clicked.connect(self._open_release_page)

        self.settings_update = QPushButton("Check now")
        self.settings_update.setObjectName("Ghost")
        self.settings_update.setAccessibleName("Check for a newer repopull")
        self.settings_update.setToolTip(
            "Ask GitHub for the latest release. Nothing is downloaded."
        )
        self.settings_update.clicked.connect(self._check_for_updates)

        update_controls = QWidget()
        update_layout = QHBoxLayout(update_controls)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.setSpacing(8)
        update_layout.addWidget(self.settings_update_open)
        update_layout.addWidget(self.settings_update)
        card.add(
            SettingRow(
                "repopull updates",
                "Asks GitHub for the newest release. This build never installs "
                "anything by itself.",
                update_controls,
            )
        )

        self.settings_update_note = QLabel("Not checked in this session.")
        self.settings_update_note.setObjectName("SettingHint")
        self.settings_update_note.setWordWrap(True)
        card.add_note(self.settings_update_note)

        self.settings_login_note = QLabel("")
        self.settings_login_note.setObjectName("SettingHint")
        self.settings_login_note.setWordWrap(True)
        card.add_note(self.settings_login_note)

        self.settings_login.toggled.connect(self._on_launch_at_login_toggled)
        self.settings_login_hidden.toggled.connect(
            self._on_launch_hidden_toggled
        )
        column.addWidget(card)

    def _autostart_note(
        self, state: autostart.State, target: autostart.Target | None
    ) -> str:
        location = autostart.entry_path().parent
        if target is None:
            return (
                "No stable command to start from here. Run the AppImage, or "
                "install repopull with pip, then reopen Settings."
            )
        if not state.installed:
            return f"Not in {location}."
        hidden = " It opens hidden." if state.hidden else ""
        return f"Listed in {location}.{hidden}"

    def _apply_autostart(
        self, state: autostart.State, target: autostart.Target | None
    ) -> None:
        # A guard flag, not QSignalBlocker: the Switch animates from its own
        # toggled signal, so blocking it would leave the knob drawn as off.
        self._loading_autostart = True
        try:
            self.settings_login.setChecked(state.installed)
            self.settings_login_hidden.setChecked(state.hidden)
        finally:
            self._loading_autostart = False
        self.settings_login.setEnabled(target is not None)
        self.settings_login_hidden.setEnabled(
            target is not None and state.installed
        )
        if target is None:
            self.settings_login.setToolTip(
                "repopull cannot find a command that will still exist at the "
                "next login."
            )
        else:
            self.settings_login.setToolTip(
                f"Starts {target.argv[0]} when you log in."
            )
        self.settings_login_note.setText(self._autostart_note(state, target))

    def _refresh_autostart(self) -> None:
        target = autostart.resolve_target()
        self._apply_autostart(autostart.read(autostart.entry_path()), target)

    def _on_launch_at_login_toggled(self, enabled: bool) -> None:
        if self._loading_settings or self._loading_autostart:
            return
        target = autostart.resolve_target()
        if target is None:
            self._refresh_autostart()
            return
        path = autostart.entry_path()
        try:
            if enabled:
                state = autostart.install(
                    path, target, hidden=self.settings_login_hidden.isChecked()
                )
            else:
                state = autostart.uninstall(path)
        except OSError as exc:
            self._flash(f"Could not update the autostart entry: {exc}")
            self._refresh_autostart()
            return
        self._apply_autostart(state, target)

    def _on_launch_hidden_toggled(self, hidden: bool) -> None:
        if self._loading_settings or self._loading_autostart:
            return
        if not self.settings_login.isChecked():
            return
        target = autostart.resolve_target()
        if target is None:
            self._refresh_autostart()
            return
        try:
            state = autostart.install(
                autostart.entry_path(), target, hidden=hidden
            )
        except OSError as exc:
            self._flash(f"Could not update the autostart entry: {exc}")
            self._refresh_autostart()
            return
        self._apply_autostart(state, target)

    def _check_for_updates(self) -> None:
        """Ask GitHub in the background; the window never waits on the network."""
        if self._update_task is not None:
            return
        self.settings_update.setEnabled(False)
        self.settings_update_note.setText("Checking GitHub…")
        task = UpdateTask()
        task.signals.finished.connect(self._on_update_finished)
        task.signals.failed.connect(self._on_update_failed)
        self._update_task = task
        QThreadPool.globalInstance().start(task)

    def _on_update_finished(self, release: object) -> None:
        self._update_task = None
        self.settings_update.setEnabled(True)
        if not isinstance(release, Release):
            self._on_update_failed("unexpected answer from GitHub")
            return
        self._release = release
        if is_newer(release):
            self.settings_update_open.setVisible(True)
            self.settings_update_note.setText(
                f"{release.version} is available; this build is {__version__}."
            )
            return
        self.settings_update_open.setVisible(False)
        self.settings_update_note.setText(
            f"repopull {__version__} is the latest release."
        )

    def _on_update_failed(self, message: str) -> None:
        self._update_task = None
        self.settings_update.setEnabled(True)
        self.settings_update_open.setVisible(False)
        self.settings_update_note.setText(f"Could not check: {message}")

    def _open_release_page(self) -> None:
        if self._release is None:
            return
        QDesktopServices.openUrl(QUrl(self._release.page))

    def _check_updates_from_tray(self) -> None:
        """Show where the answer will appear, then ask."""
        self._show_settings()
        self._select_settings_section(SETTINGS_SECTIONS.index("Startup"))
        self._check_for_updates()

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
            "Save unsaved settings rewrites config.toml and removes comments you added to it."
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
        self._render_library(preserve_scroll=False)
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
            self._refresh_autostart()
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
        self._render_library(preserve_scroll=False)

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
        self.root_state_check = None
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
            root,
            self.config.max_depth,
            self.config.ignore,
            log_dir=self.config.log_dir,
        )
        task.signals.checked.connect(
            lambda refs, check: self._on_discovery_checked(
                generation, refs, check
            )
        )
        task.signals.failed.connect(
            lambda message: self._on_discovery_failed(generation, message)
        )
        self._discovery_task = task
        QThreadPool.globalInstance().start(task)

    def _on_discovery_checked(
        self,
        generation: int,
        refs: list[RepoRef],
        check: object,
    ) -> None:
        if generation != self._discovery_generation or self._quit_requested:
            return
        self._discovery_task = None
        found = [ref for ref in refs if isinstance(ref, RepoRef)]
        self.refs = found
        if not isinstance(check, RootStateCheck):
            self.refs = []
            self.root_state_check = None
            self.discovery_error = "root-state check returned no result"
        else:
            self.root_state_check = check
            if check.problem is not None:
                self.refs = []
                self.discovery_error = self._root_state_message(check)
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
        self.root_state_check = None
        self.discovery_error = message
        self._render_library()
        self._update_status_block()
        self._schedule_auto_refresh()
        self._flash(message)

    def _root_state_message(self, check: RootStateCheck) -> str:
        """Turn a failed root check into the action the library can offer."""
        message = check.problem or "saved root state does not match"
        separator = " " if message.endswith((".", "?", "!")) else ". "
        if check.repairable:
            return (
                message
                + separator
                + "Use Repair saved root state to accept this disk."
            )
        return (
            message
            + separator
            + f"Remove {self.config.log_dir / ROOT_STATE_FILE} "
            "if this is intentional."
        )

    def _reload_refs(self) -> None:
        root = self.config.root
        if root is None:
            self.refs = []
            self.root_state_check = None
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
            self.root_state_check = None
            self.discovery_error = str(exc)
            return
        check = check_root_state(
            self.config.log_dir, root, len(self.refs)
        )
        self.root_state_check = check
        if check.problem is not None:
            self.refs = []
            self.discovery_error = self._root_state_message(check)
            return
        self.discovery_error = None

    def _repair_root_state(self) -> None:
        """Accept the current identity after the user confirms it."""
        check = self.root_state_check
        root = self.config.root
        if check is None or root is None or not check.repairable:
            return
        text = (
            "repopull records which filesystem the watched folder is on.\n\n"
            f"Watched folder:\n{root}\n\n"
            f"Saved: {describe_state(check.previous)}\n"
            f"Current: {describe_identity(check.current)}\n\n"
            "Only repair if this is the disk you expect. This replaces the "
            "saved identity; it does not touch the repositories."
        )
        answer = QMessageBox.question(
            self,
            "Repair saved root state",
            text,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            repair_root_state(self.config.log_dir, root, check)
        except RootStateChanged as exc:
            QMessageBox.warning(
                self,
                "repopull",
                f"{exc}. Run Refresh status and try again.",
            )
            self.root_state_check = None
            if self._discover_async:
                self._start_discovery()
            else:
                self._reload_refs()
                self._render_library()
            return
        except OSError as exc:
            QMessageBox.warning(
                self,
                "repopull",
                f"Could not repair the saved root state: {exc}",
            )
            return
        self.root_state_check = None
        self.discovery_error = None
        if self._discover_async:
            self._start_discovery()
        else:
            self._reload_refs()
            self._render_library()
            self._update_status_block()
            self._restore_detail()
        self._flash("Repaired saved root state")

    def _report_rows(self) -> dict[str, Row]:
        return self.rows_by_label

    def _visible_rows(self) -> list[RowView]:
        report_rows = self._report_rows()
        visible: list[RowView] = []
        for ref in self.refs:
            row = report_rows.get(ref.label)
            no_checks = self.config.skips_refresh(ref.label)
            no_sync = self.config.skips_sync(ref.label)
            if no_checks and self.filter != "all":
                # A stale report row must not appear under Behind/Errors.
                continue
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
                row_view(row, no_checks=no_checks, no_sync=no_sync)
                if row is not None
                else unchecked_view(
                    ref.label, no_checks=no_checks, no_sync=no_sync
                )
            )
        return visible

    def visible_row_count(self) -> int:
        """Number of rows the current filter and search would show."""
        return len(self._visible_rows())

    def _render_library(self, *, preserve_scroll: bool = True) -> None:
        """Rebuild the list, keeping the scroll position for data updates.

        Filter and search changes pass `preserve_scroll=False` because a new
        view should start at the top. A run finishing or a hold changing while
        the detail page is open must not destroy the position the user had.
        """
        self._update_nav_counts()
        visible = self._visible_rows()
        bar = self.list.verticalScrollBar()
        previous_scroll = bar.value() if preserve_scroll else 0

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
            self.repair_button.hide()
        else:
            if self.discovery_error is not None:
                self.empty_label.setText(self.discovery_error)
            elif self.search:
                self.empty_label.setText("No repositories match the search.")
            elif not self.refs:
                self.empty_label.setText(
                    "No repositories yet. Use Clone… to add one."
                )
            else:
                self.empty_label.setText("No repositories in this view.")
            self.empty_label.show()
            self.repair_button.setVisible(
                self.root_state_check is not None
                and self.root_state_check.repairable
            )

        self._update_banner()
        if preserve_scroll:
            bar.setValue(min(previous_scroll, bar.maximum()))
        else:
            bar.setValue(0)

    def _update_nav_counts(self) -> None:
        report_rows = self._report_rows()
        counts = {Outcome.BEHIND: 0, Outcome.SKIPPED: 0, Outcome.ERROR: 0}
        for ref in self.refs:
            if self.config.skips_refresh(ref.label):
                # Its saved outcome is stale; keep it out of live totals.
                continue
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
        actionable = 0
        held = 0
        if self.report is not None:
            labels = {
                ref.label
                for ref in self.refs
                if not self.config.skips_refresh(ref.label)
            }
            behind_rows = [
                row
                for row in self.report.rows
                if row.outcome is Outcome.BEHIND and row.label in labels
            ]
            actionable = sum(
                1
                for row in behind_rows
                if not self.config.skips_sync(row.label)
            )
            held = len(behind_rows) - actionable
        if actionable:
            noun = "repository" if actionable == 1 else "repositories"
            text = (
                f"{actionable} {noun} can be updated "
                "(from the last check)."
            )
            if held:
                text = (
                    f"{actionable} {noun} can be updated · "
                    f"{held} held (from the last check)."
                )
            self.banner_label.setText(text)
            self.banner_button.show()
            self.banner.show()
        elif held:
            noun = "repository" if held == 1 else "repositories"
            verb = "is" if held == 1 else "are"
            self.banner_label.setText(
                f"{held} {noun} {verb} held from Sync all "
                "(from the last check)."
            )
            self.banner_button.hide()
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
                f"Last check {self.report.started_at:%Y-%m-%d %H:%M}"
            )
        else:
            self.last_label.setText("Last check —")
        self._update_next_check_label()

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
        self._refresh_autostart()
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
        self._populate_detail_holds(label)
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

    def _open_folder_current(self) -> None:
        ref = self._current_ref()
        if ref is None:
            return
        if not ref.path.is_dir():
            self._flash(f"Folder not found: {ref.path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(ref.path))):
            self._flash(f"Could not open folder: {ref.path}")

    def _populate_detail_holds(self, label: str) -> None:
        self._loading_holds = True
        self.detail_exclude_refresh.setChecked(
            self.config.skips_refresh(label)
        )
        self.detail_exclude_sync.setChecked(self.config.skips_sync(label))
        self._loading_holds = False

    def _on_hold_toggled(self, _checked: bool) -> None:
        if self._loading_holds or self.current_label is None:
            return
        label = self.current_label
        previous = self.config
        exclude_refresh = set(previous.exclude_from_refresh)
        exclude_sync = set(previous.exclude_from_sync)
        if self.detail_exclude_refresh.isChecked():
            exclude_refresh.add(label)
        else:
            exclude_refresh.discard(label)
        if self.detail_exclude_sync.isChecked():
            exclude_sync.add(label)
        else:
            exclude_sync.discard(label)
        updated = dataclasses.replace(
            previous,
            exclude_from_refresh=tuple(sorted(exclude_refresh)),
            exclude_from_sync=tuple(sorted(exclude_sync)),
        )
        target = updated.config_path
        if target is None:
            self.config = previous
            self._populate_detail_holds(label)
            self._flash("No config file is available to save this exclusion.")
            return
        self.config = updated
        try:
            save_repo_holds(
                target,
                exclude_from_refresh=updated.exclude_from_refresh,
                exclude_from_sync=updated.exclude_from_sync,
            )
        except OSError as exc:
            self.config = previous
            self._populate_detail_holds(label)
            self._flash(f"Could not save the exclusion: {exc}")
            return
        self._render_library()
        self._flash(f"Saved bulk-action exclusions for {label}.")

    def _open_refresh_settings(self) -> None:
        self._show_settings()
        self._select_settings_section(1)

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
        """Update the Save button for deferred fields."""
        self._settings_dirty = dirty
        self.save_button.setEnabled(dirty)
        self.save_button.setText(
            "Save unsaved settings" if dirty else "Saved"
        )
        self._set_save_state("dirty" if dirty else "clean")

    def _set_save_state(self, state: str) -> None:
        self.save_button.setProperty("saveState", state)
        style = self.save_button.style()
        style.unpolish(self.save_button)
        style.polish(self.save_button)
        self.save_button.update()
        if state == "error":
            self.save_button.setToolTip(
                "The last save failed. Try again."
            )
        elif state == "dirty":
            self.save_button.setToolTip(
                "Write these settings to config.toml. Hand-written comments "
                "are removed."
            )
        else:
            self.save_button.setToolTip("No unsaved settings.")

    def _set_save_error(self) -> None:
        self.save_button.setEnabled(True)
        self.save_button.setText("Couldn't save — Retry")
        self._set_save_state("error")

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
                self._set_save_error()
                self._flash(f"Could not save refresh settings: {exc}")
            else:
                self._set_settings_dirty(self._settings_dirty)
        self._apply_background_mode()
        self._schedule_auto_refresh()

    def _clock_label(self, seconds: float) -> str:
        """Format a future local time without a ticking countdown."""
        target = time.time() + max(0.0, seconds)
        when = time.localtime(target)
        clock = time.strftime("%H:%M", when)
        target_day = time.strftime("%Y-%m-%d", when)
        today = time.strftime("%Y-%m-%d", time.localtime())
        if target_day == today:
            return f"today at {clock}"
        tomorrow = time.strftime(
            "%Y-%m-%d", time.localtime(time.time() + 86_400)
        )
        if target_day == tomorrow:
            return f"tomorrow at {clock}"
        return time.strftime("%a at %H:%M", when)

    def _auto_next_text(self) -> str:
        if self.config.auto_refresh_s <= 0:
            return "Automatic refresh is off."
        if not self._status_refs() and self.refs:
            return "No repositories are included in automatic checks."
        if self._auto_paused:
            return "Automatic refresh is paused."
        if (
            self.config.auto_refresh_pause_when_hidden
            and not self._auto_visible_allowed()
        ):
            return (
                "Paused while hidden; the next check runs after the window "
                "returns, if due."
            )
        if self._resume_pending:
            return "Checking shortly after resume."
        if self._background_active:
            return (
                "A git operation is running; the next interval starts when it "
                "finishes."
            )
        remaining = self.auto_timer.remainingTime()
        if remaining < 0:
            return "No automatic check is scheduled."
        return (
            "Next automatic status check: "
            f"{self._clock_label(remaining / 1_000)}."
        )

    def _next_check_text(self) -> str:
        """A compact sidebar form of the next automatic status check."""
        if self.config.auto_refresh_s <= 0:
            return "Next check — off"
        if not self._status_refs() and self.refs:
            return "Next check — none included"
        if self._auto_paused:
            return "Next check — paused"
        if (
            self.config.auto_refresh_pause_when_hidden
            and not self._auto_visible_allowed()
        ):
            return "Next check — when visible"
        if self._resume_pending:
            return "Next check — after resume"
        if self._background_active:
            return "Next check — after this run"
        remaining = self.auto_timer.remainingTime()
        if remaining < 0:
            return "Next check —"
        target = time.localtime(time.time() + remaining / 1_000)
        return f"Next check {time.strftime('%Y-%m-%d %H:%M', target)}"

    def _update_next_check_label(self) -> None:
        label = getattr(self, "next_label", None)
        if label is None:
            return
        label.setText(self._next_check_text())
        label.setToolTip(self._auto_next_text())

    def _update_auto_feedback(self) -> None:
        label = getattr(self, "settings_auto_next", None)
        if label is not None:
            label.setText(self._auto_next_text())
        self._update_next_check_label()

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
            self._set_save_error()
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
        self._flash(
            "Defaults restored; press Save unsaved settings to write them."
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

    def _status_refs(self) -> list[RepoRef]:
        """Repositories included in Refresh status and automatic checks."""
        return [
            ref
            for ref in self.refs
            if not self.config.skips_refresh(ref.label)
        ]

    def _sync_refs(self) -> list[RepoRef]:
        """Repositories included in Sync all."""
        return [
            ref for ref in self.refs if not self.config.skips_sync(ref.label)
        ]

    @property
    def _background_active(self) -> bool:
        """True while a status/sync run or a clone is in flight."""
        return self.task is not None or self.clone_task is not None

    def _clone(self) -> None:
        if self._background_active:
            return
        if self.config.root is None:
            self._flash("Choose a watched folder in Settings first.")
            self._show_settings()
            return
        dialog = CloneDialog(self.config.root, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url, name = dialog.values()
        self._start_clone(url, name)

    def _start_clone(self, url: str, name: str) -> None:
        root = self.config.root
        if root is None or self._background_active:
            return
        problem = check_log_dir(self.config.log_dir)
        if problem is not None:
            self._flash(problem)
            return
        self.auto_timer.stop()
        self._resume_timer.stop()
        self._resume_pending = False
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self._flash(f"Cloning {name}…")

        task = CloneTask(
            url,
            name,
            root,
            timeout=self.config.clone_timeout_s,
            log_dir=self.config.log_dir,
        )
        task.signals.progress.connect(self._on_clone_progress)
        task.signals.finished.connect(self._on_clone_finished)
        task.signals.failed.connect(self._on_clone_failed)
        task.signals.cancelled.connect(self._on_clone_cancelled)
        self.clone_task = task
        QThreadPool.globalInstance().start(task)

    def _on_clone_progress(self, percent: int, text: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percent)))
        self._flash(text)

    def _on_clone_finished(self, result: object) -> None:
        if not isinstance(result, CloneResult):
            return
        self.clone_task = None
        self._set_busy(False)
        if result.empty:
            self._flash(f"Cloned {result.destination.name} (empty repository)")
        else:
            self._flash(f"Cloned {result.destination.name}")
        self._start_discovery(lambda: self._open_cloned(result.destination))
        self._schedule_auto_refresh()
        self._maybe_quit_after_task()

    def _open_cloned(self, destination: Path) -> None:
        root = self.config.root
        if root is None:
            return
        try:
            label = destination.relative_to(root.resolve()).as_posix()
        except ValueError:
            return
        if any(ref.label == label for ref in self.refs):
            self._open_detail(label)

    def _on_clone_failed(self, message: str) -> None:
        self.clone_task = None
        self._set_busy(False)
        self._flash("Clone failed")
        self._schedule_auto_refresh()
        if self._quit_requested:
            self._maybe_quit_after_task()
            return
        QMessageBox.warning(self, "Clone failed", message)

    def _on_clone_cancelled(self) -> None:
        self.clone_task = None
        self._set_busy(False)
        self._flash("Clone cancelled")
        self._schedule_auto_refresh()
        self._maybe_quit_after_task()

    def _refresh_status(self) -> None:
        refs = self._status_refs()
        if not refs:
            self._flash("Every repository is excluded from Refresh status.")
            return
        self._start_run(refs, force=False, mode="status")

    def _sync_all(self) -> None:
        refs = self._sync_refs()
        if not refs:
            self._flash("Every repository is excluded from Sync all.")
            return
        self._start_run(refs, force=False, mode="sync")

    def _behind_refs(self) -> list[RepoRef]:
        """Repositories the last check found behind and bulk sync may update."""
        selected: list[RepoRef] = []
        for ref in self.refs:
            if self.config.skips_refresh(ref.label):
                continue
            if self.config.skips_sync(ref.label):
                continue
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
        if self._background_active:
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
            if not self._background_active:
                self._quit_application()
            return
        self._quit_requested = True
        if self._background_active:
            if self.task is not None:
                self.task.cancel.set()
            if self.clone_task is not None:
                self.clone_task.cancel.set()
            self.cancel_button.setEnabled(False)
            self._flash("Stopping the current git command…")
            return
        self._quit_application()

    def _quit_application(self) -> None:
        if self._channel is not None:
            self._channel.stop()
            self._channel = None
        if self.tray is not None:
            self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _maybe_quit_after_task(self) -> None:
        if self._quit_requested:
            self._quit_application()

    @property
    def starts_hidden(self) -> bool:
        """`--hidden` only hides when a tray icon can bring the window back."""
        return self._hidden_requested and self._tray_available

    def start_instance_channel(self) -> None:
        """Answer a second launch by showing this window instead of a dialog."""
        if self._channel is not None:
            return
        channel = Channel(self.config.log_dir, self._show_from_tray, self)
        channel.start()
        self._channel = channel

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
        update_action = QAction("Check for updates…", self)
        update_action.triggered.connect(self._check_updates_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._begin_quit)
        menu.addAction(open_action)
        menu.addAction(refresh_action)
        menu.addAction(self._auto_pause_action)
        menu.addSeparator()
        menu.addAction(update_action)
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
        self._update_auto_feedback()
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
            in_flight=self._background_active,
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
            self._update_auto_feedback()
            return
        if decision.action is RefreshAction.WAIT:
            self.auto_timer.start(max(1, int(decision.delay_s * 1000)))
            self._update_auto_feedback()
            return
        self.auto_timer.stop()
        refs = self._status_refs()
        if not refs:
            self._schedule_auto_refresh()
            return
        self._start_run(refs, force=False, mode="status", auto=True)
        self._update_auto_feedback()

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
        self._update_auto_feedback()
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
        if self._background_active:
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
        if self._background_active:
            return
        refs = self._status_refs()
        if not refs:
            self._schedule_auto_refresh()
            return
        self._start_run(refs, force=False, mode="status", auto=True)

    def _update_tray_tooltip(self) -> None:
        if self.tray is None:
            return
        if self.report is None:
            text = "repopull — no check yet"
        else:
            text = f"repopull — {self._summary(self.report)}"
        if self.config.auto_refresh_s > 0:
            if not self._auto_visible_allowed():
                text += "\nAutomatic refresh paused while hidden"
            elif self._network_offline:
                text += "\nNetwork unavailable; retrying"
            else:
                text += "\nAutomatic refresh on"
                remaining = self.auto_timer.remainingTime()
                if remaining >= 0:
                    text += (
                        " · next check "
                        f"{self._clock_label(remaining / 1_000)}"
                    )
        self.tray.setToolTip(text)

    def _start_run(
        self,
        refs: list[RepoRef],
        *,
        force: bool,
        mode: str,
        auto: bool = False,
    ) -> None:
        if self._background_active:
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
        self._update_auto_feedback()
        QThreadPool.globalInstance().start(task)

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.clone_button,
            self.refresh_button,
            self.sync_button,
            self.banner_button,
            self.detail_sync,
            self.detail_force,
            self.detail_exclude_refresh,
            self.detail_exclude_sync,
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
        if self.clone_task is not None:
            self.clone_task.cancel.set()
            self.cancel_button.setEnabled(False)
            self._flash("Cancelling clone…")
            return
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
