"""System-wide keyboard shortcuts via the Win32 RegisterHotKey API.

Hotkeys are registered against a hidden native window, whose WM_HOTKEY
messages arrive through Qt's nativeEvent hook on the UI thread.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

_WM_HOTKEY = 0x0312
_MOD_ALT, _MOD_CONTROL, _MOD_SHIFT, _MOD_WIN, _MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODIFIERS = {"ctrl": _MOD_CONTROL, "control": _MOD_CONTROL, "alt": _MOD_ALT, "shift": _MOD_SHIFT, "win": _MOD_WIN, "meta": _MOD_WIN}
_NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
               "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdown": 0x22, "insert": 0x2D, "ins": 0x2D,
               "del": 0x2E, "delete": 0x2E, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


@dataclass(frozen=True, slots=True)
class Hotkey:
    modifiers: int
    vk: int


def parse_hotkey(text: str) -> Hotkey | None:
    """'Ctrl+Alt+A' -> Hotkey. None for an empty or invalid combo.

    At least one of Ctrl/Alt/Win is required so a shortcut can't swallow
    ordinary typing.
    """
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    *mods, key = parts
    modifiers = 0
    for mod in mods:
        if mod not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[mod]
    if not modifiers & (_MOD_CONTROL | _MOD_ALT | _MOD_WIN):
        return None
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return Hotkey(modifiers, vk)


class HotkeyManager(QWidget):
    """Owns the registrations; emits ``triggered(name)`` when one is pressed."""

    triggered = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._hwnd = int(self.winId())  # never shown; just a native message target
        self._ids: dict[int, str] = {}
        self._user32 = ctypes.windll.user32
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

    def set_hotkeys(self, combos: dict[str, str]) -> list[str]:
        """Replace all registrations. Returns combos that couldn't be registered."""
        self.clear()
        failed = []
        for index, (name, text) in enumerate(combos.items(), start=1):
            if not text.strip():
                continue
            hotkey = parse_hotkey(text)
            if hotkey is None or not self._user32.RegisterHotKey(
                self._hwnd, index, hotkey.modifiers | _MOD_NOREPEAT, hotkey.vk
            ):
                log.warning("Could not register hotkey %s for %s (invalid or used by another app)", text, name)
                failed.append(text)
                continue
            self._ids[index] = name
            log.info("Hotkey %s -> %s", text, name)
        return failed

    def clear(self) -> None:
        for hotkey_id in self._ids:
            self._user32.UnregisterHotKey(self._hwnd, hotkey_id)
        self._ids.clear()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam in self._ids:
                self.triggered.emit(self._ids[msg.wParam])
                return True, 0
        return super().nativeEvent(event_type, message)
