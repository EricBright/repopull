"""Background work for the GUI; results return through Qt signals."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal

from repopull.clone import CloneCancelled, clone_repository
from repopull.models import Report
from repopull.runtime import run_lock
from repopull.sync import RowCallback

ProgressFn = Callable[[int, int, str], None]


class RunSignals(QObject):
    """Signals emitted by a `RunTask`."""

    progress = Signal(int, int, str)
    row = Signal(object)
    finished = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)


class RunTask(QRunnable):
    """One cancellable status or sync run, holding the same lock as the CLI."""

    def __init__(
        self,
        operation: Callable[[Event, ProgressFn, RowCallback], Report],
        log_dir: Path,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.log_dir = log_dir
        self.cancel = Event()
        self.signals = RunSignals()

    def run(self) -> None:
        try:
            with run_lock(self.log_dir):
                report = self.operation(
                    self.cancel,
                    self.signals.progress.emit,
                    self.signals.row.emit,
                )
        except Exception as exc:  # LockError, git errors, anything the run can raise
            self.signals.failed.emit(str(exc))
            return
        if self.cancel.is_set():
            self.signals.cancelled.emit(report)
        else:
            self.signals.finished.emit(report)


class CloneSignals(QObject):
    """Signals emitted by a `CloneTask`."""

    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class CloneTask(QRunnable):
    """One cancellable clone, holding the same lock as a sync run."""

    def __init__(
        self,
        url: str,
        name: str,
        root: Path,
        *,
        timeout: float,
        log_dir: Path,
    ) -> None:
        super().__init__()
        self.url = url
        self.name = name
        self.root = root
        self.timeout = timeout
        self.log_dir = log_dir
        self.cancel = Event()
        self.signals = CloneSignals()

    def run(self) -> None:
        try:
            with run_lock(self.log_dir):
                result = clone_repository(
                    self.url,
                    self.name,
                    self.root,
                    timeout=self.timeout,
                    cancel=self.cancel,
                )
        except CloneCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # LockError, CloneError, anything the clone raises
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)
