"""Notification-area icon with live battery tooltip and settings menu."""

from __future__ import annotations

import dataclasses
import logging

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME
from ..catalog import Family
from ..presenter import LOW_LEVEL, DeviceView
from .artwork import paint_bud
from .theme import DARK

log = logging.getLogger(__name__)

_ICON_THEME = dataclasses.replace(DARK, art_outline=QColor(0, 0, 0, 210))


def render_icon(low: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        half = size * 0.56
        paint_bud(p, QRectF(-size * 0.04, 0, half, size), Family.PRO, True, _ICON_THEME)
        paint_bud(p, QRectF(size - half + size * 0.04, 0, half, size), Family.PRO, False, _ICON_THEME)
        if low:
            r = size * 0.2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FF453A"))
            p.drawEllipse(QRectF(size - 2 * r, size - 2 * r, 2 * r, 2 * r))
        p.end()
        icon.addPixmap(pixmap)
    return icon


class Tray(QObject):
    show_requested = Signal()
    quit_requested = Signal()
    settings_requested = Signal()
    connect_requested = Signal()
    repair_requested = Signal()
    release_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._low: bool | None = None

        self._tray = QSystemTrayIcon()
        self._tray.setIcon(render_icon())
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(self._on_activated)

        menu = QMenu()
        self._status = menu.addAction("Searching for AirPods…")
        self._status.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Show battery", self.show_requested.emit)
        self._connect = menu.addAction("Connect AirPods to this PC", self.connect_requested.emit)
        self._connect.setEnabled(False)
        self._repair = menu.addAction("Reconnect audio (fixes no sound)", self.repair_requested.emit)
        self._repair.setEnabled(False)
        self._release = menu.addAction("Disconnect (hand to phone)", self.release_requested.emit)
        self._release.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Settings…", self.settings_requested.emit)
        menu.addAction(f"Quit {APP_NAME}", self.quit_requested.emit)
        self._menu = menu
        self._tray.setContextMenu(menu)

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def update(self, view: DeviceView, note: str | None = None) -> None:
        has_data = any(i.level is not None for i in view.items)
        self._status.setText(note or (view.summary().replace("\n", " — ") if has_data else "Searching for AirPods…"))
        tooltip = view.summary() if has_data else f"{APP_NAME}\nSearching for AirPods…"
        if note:
            tooltip += f"\n{note}"
        self._tray.setToolTip(tooltip[:127])  # Windows truncates longer tooltips

        lowest = view.lowest_pod_level
        low = lowest is not None and lowest <= LOW_LEVEL
        if low != self._low:
            self._low = low
            self._tray.setIcon(render_icon(low))

    def set_link_actions(self, *, can_connect: bool, can_repair: bool, can_release: bool) -> None:
        self._connect.setEnabled(can_connect)
        self._repair.setEnabled(can_repair)
        self._release.setEnabled(can_release)

    def notify(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, render_icon(), 6000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()
