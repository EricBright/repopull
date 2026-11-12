"""A local socket that lets a second launch raise the running window.

A hidden window needs an answer to "I clicked the launcher and nothing
happened". The single-instance lock already refuses the second process, so it
asks the first one to come forward instead of exiting with a dialog.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SHOW = b"show\n"


def channel_name(log_dir: Path) -> str:
    """One channel per configuration, so two profiles never talk."""
    digest = hashlib.sha256(str(log_dir).encode("utf-8")).hexdigest()[:12]
    return f"repopull-{digest}"


def ask_to_show(log_dir: Path, timeout_ms: int = 300) -> bool:
    """Ask a running window to come forward; False when nobody answered."""
    socket = QLocalSocket()
    socket.connectToServer(channel_name(log_dir))
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(SHOW)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


class Channel(QObject):
    """Serve "show" requests until the window quits."""

    def __init__(
        self,
        log_dir: Path,
        on_show: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_show = on_show
        self._name = channel_name(log_dir)
        self._clients: list[QLocalSocket] = []
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def start(self) -> bool:
        """Listen, clearing the socket file a crashed run may have left.

        Safe because the caller holds the run lock, so no other repopull
        process is serving this name.
        """
        QLocalServer.removeServer(self._name)
        return bool(self._server.listen(self._name))

    def stop(self) -> None:
        for client in self._clients:
            client.deleteLater()
        self._clients.clear()
        self._server.close()

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            self._clients.append(client)
            client.readyRead.connect(lambda current=client: self._read(current))
            client.disconnected.connect(
                lambda current=client: self._forget(current)
            )

    def _read(self, client: QLocalSocket) -> None:
        if SHOW not in client.readAll().data():
            return
        client.disconnectFromServer()
        self._on_show()

    def _forget(self, client: QLocalSocket) -> None:
        if client in self._clients:
            self._clients.remove(client)
        client.deleteLater()
