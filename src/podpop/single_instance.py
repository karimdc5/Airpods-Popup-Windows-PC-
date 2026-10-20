"""Keeps one PodPop running; launching it again shows the popup instead."""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, key: str) -> None:
        super().__init__()
        self._name = f"{key}-{getpass.getuser()}"
        self._server: QLocalServer | None = None

    def claim(self) -> bool:
        """True if this is the first instance. Otherwise pings the running one."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._name)  # clear a stale pipe left by a crash
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self._name)
        return True

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            self._server.nextPendingConnection().deleteLater()
        self.activated.emit()
