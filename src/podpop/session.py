"""Lock and unlock notifications for the current Windows session.

Registers a hidden native window with WTSRegisterSessionNotification; the
WM_WTSSESSION_CHANGE messages arrive through Qt's nativeEvent hook on the
UI thread.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

_WM_WTSSESSION_CHANGE = 0x02B1
_WTS_SESSION_LOCK, _WTS_SESSION_UNLOCK = 0x7, 0x8
_NOTIFY_FOR_THIS_SESSION = 0


class SessionWatcher(QWidget):
    locked = Signal()
    unlocked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._hwnd = int(self.winId())  # never shown; just a native message target
        self._wtsapi = ctypes.windll.wtsapi32
        self._wtsapi.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        self._wtsapi.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        self._registered = bool(self._wtsapi.WTSRegisterSessionNotification(self._hwnd, _NOTIFY_FOR_THIS_SESSION))
        if not self._registered:
            log.warning("Lock/unlock notifications unavailable (error %d)", ctypes.GetLastError())

    def stop(self) -> None:
        if self._registered:
            self._wtsapi.WTSUnRegisterSessionNotification(self._hwnd)
            self._registered = False

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_WTSSESSION_CHANGE:
                if msg.wParam == _WTS_SESSION_LOCK:
                    self.locked.emit()
                elif msg.wParam == _WTS_SESSION_UNLOCK:
                    self.unlocked.emit()
        return super().nativeEvent(event_type, message)
