"""Notification-area icon with live battery tooltip and settings menu."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME, autostart
from ..catalog import Family
from ..presenter import LOW_LEVEL, DeviceView
from ..settings import Settings, log_dir
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
    settings_changed = Signal()
    connect_requested = Signal()
    repair_requested = Signal()

    def __init__(self, settings: Settings, save_settings: Callable[[], None]) -> None:
        super().__init__()
        self._settings = settings
        self._save = save_settings
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
        menu.addSeparator()
        self._add_setting(menu, "Pop up when AirPods connect", "popup_on_connect")
        self._add_setting(menu, "Pop up when the case opens", "popup_on_case_open")
        self._add_setting(menu, "Connect automatically when the case opens", "auto_connect_on_case_open")
        self._add_setting(menu, "Fix stuck audio after walking away", "auto_fix_audio")
        self._add_setting(menu, "Pause when you take an AirPod out", "auto_pause_on_removal")
        self._add_setting(menu, "Low battery alerts", "low_battery_alerts")
        self._add_setting(menu, "Pop up on the monitor with the mouse", "popup_follows_mouse")
        self._add_setting(menu, "Play opening animation", "popup_intro_animation")
        themes = menu.addMenu("Theme")
        group = QActionGroup(themes)
        for value, label in (("dark", "Dark"), ("light", "Light"), ("system", "Match Windows")):
            action = themes.addAction(label)
            action.setCheckable(True)
            action.setChecked(settings.theme == value)
            action.setActionGroup(group)
            action.triggered.connect(lambda _checked, v=value: self._set("theme", v))
        startup = menu.addAction("Start with Windows")
        startup.setCheckable(True)
        startup.setChecked(autostart.is_enabled())
        startup.toggled.connect(self._set_autostart)
        menu.addSeparator()
        menu.addAction("Open log folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir()))))
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

    def set_link_actions(self, *, can_connect: bool, can_repair: bool) -> None:
        self._connect.setEnabled(can_connect)
        self._repair.setEnabled(can_repair)

    def notify(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, render_icon(), 6000)

    def _add_setting(self, menu: QMenu, label: str, field: str) -> QAction:
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(getattr(self._settings, field))

        action.toggled.connect(lambda checked: self._set(field, checked))
        return action

    def _set(self, field: str, value) -> None:
        setattr(self._settings, field, value)
        self._save()
        self.settings_changed.emit()

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError:
            log.exception("Could not update the startup entry")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()
