"""Settings window: every option in one place. Changes apply immediately."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, autostart
from ..hotkeys import parse_hotkey
from ..settings import Settings, log_dir

log = logging.getLogger(__name__)

THEMES = (("dark", "Dark"), ("light", "Light"), ("system", "Match Windows"))


class SettingsWindow(QWidget):
    changed = Signal()

    def __init__(self, settings: Settings, save: Callable[[], None]) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self._settings = settings
        self._save = save
        self._loading = False
        self._checks: list[tuple[QCheckBox, str]] = []
        self.setWindowTitle(f"{APP_NAME} Settings")
        self.resize(460, 680)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        popup = self._group(layout, "Popup")
        self._on_connect = self._check(popup, "Show when AirPods connect", "popup_on_connect")
        self._on_case = self._check(popup, "Show when the case opens", "popup_on_case_open")
        self._intro = self._check(popup, "Play opening animation", "popup_intro_animation")
        self._duration = QDoubleSpinBox(suffix=" seconds", minimum=2, maximum=30, singleStep=1, decimals=0)
        self._duration.valueChanged.connect(lambda v: self._set("popup_duration_s", float(v)))
        popup.addRow("Stay on screen for", self._duration)
        self._monitor = QComboBox()
        self._monitor.addItems(["Main monitor", "Monitor with the mouse"])
        self._monitor.currentIndexChanged.connect(lambda i: self._set("popup_follows_mouse", i == 1))
        popup.addRow("Show on", self._monitor)
        self._theme = QComboBox()
        for _, label in THEMES:
            self._theme.addItem(label)
        self._theme.currentIndexChanged.connect(lambda i: self._set("theme", THEMES[i][0]))
        popup.addRow("Theme", self._theme)

        connection = self._group(layout, "Connection")
        self._auto_connect = self._check(connection, "Connect automatically when the case opens", "auto_connect_on_case_open")
        self._auto_fix = self._check(connection, "Fix stuck audio after walking away", "auto_fix_audio")
        self._auto_pause = self._check(connection, "Pause media when you take an AirPod out", "auto_pause_on_removal")

        battery = self._group(layout, "Battery")
        self._alerts = self._check(battery, "Low battery alerts", "low_battery_alerts")
        self._first = QSpinBox(suffix=" %", minimum=10, maximum=50, singleStep=10)
        self._second = QSpinBox(suffix=" %", minimum=0, maximum=40, singleStep=10, specialValueText="Off")
        for box in (self._first, self._second):
            box.valueChanged.connect(self._thresholds_changed)
        row = QHBoxLayout()
        row.addWidget(self._first)
        row.addWidget(QLabel("and again at"))
        row.addWidget(self._second)
        row.addStretch(1)
        battery.addRow("Alert at", row)

        shortcuts = self._group(layout, "Keyboard shortcuts")
        self._hotkey_show = self._hotkey_row(shortcuts, "Show battery", "hotkey_show_popup")
        self._hotkey_connect = self._hotkey_row(shortcuts, "Connect / fix audio", "hotkey_connect")
        self._hotkey_error = QLabel()
        self._hotkey_error.setStyleSheet("color: #FF453A;")
        self._hotkey_error.hide()
        shortcuts.addRow(self._hotkey_error)

        advanced = self._group(layout, "Advanced")
        self._rssi = QSlider(Qt.Orientation.Horizontal, minimum=-90, maximum=-50, singleStep=1, pageStep=5)
        self._rssi_label = QLabel()
        self._rssi.valueChanged.connect(self._rssi_changed)
        advanced.addRow("Signal threshold", self._rssi)
        advanced.addRow("", self._rssi_label)
        self._startup = QCheckBox("Start with Windows")
        self._startup.toggled.connect(self._set_autostart)
        advanced.addRow(self._startup)
        logs = QPushButton("Open log folder")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir()))))
        advanced.addRow(logs)

        layout.addStretch(1)
        scroll = QScrollArea(widgetResizable=True, frameShape=QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        footer = QHBoxLayout()
        footer.setContentsMargins(18, 8, 18, 14)
        footer.addWidget(QLabel("Changes are saved automatically."))
        footer.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        outer.addLayout(footer)

    # ----------------------------------------------------------------- API

    def open(self) -> None:
        self.reload()
        self.show()
        self.raise_()
        self.activateWindow()

    def reload(self) -> None:
        """Copy the current settings into the controls (e.g. after a tray change)."""
        s = self._settings
        self._loading = True
        try:
            for box, field in self._checks:
                box.setChecked(getattr(s, field))
            self._duration.setValue(s.popup_duration_s)
            self._monitor.setCurrentIndex(1 if s.popup_follows_mouse else 0)
            self._theme.setCurrentIndex(next((i for i, (v, _) in enumerate(THEMES) if v == s.theme), 0))
            thresholds = sorted(s.low_battery_thresholds, reverse=True) + [0, 0]
            self._first.setValue(thresholds[0] or 20)
            self._second.setValue(thresholds[1])
            self._hotkey_show.setKeySequence(QKeySequence(s.hotkey_show_popup))
            self._hotkey_connect.setKeySequence(QKeySequence(s.hotkey_connect))
            self._rssi.setValue(s.min_rssi)
            self._rssi_changed(s.min_rssi)
            self._startup.setChecked(autostart.is_enabled())
        finally:
            self._loading = False

    # ------------------------------------------------------------ builders

    def _group(self, layout: QVBoxLayout, title: str) -> QFormLayout:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setVerticalSpacing(8)
        layout.addWidget(box)
        return form

    def _check(self, form: QFormLayout, label: str, field: str) -> QCheckBox:
        box = QCheckBox(label)
        box.toggled.connect(lambda checked: self._set(field, checked))
        form.addRow(box)
        self._checks.append((box, field))
        return box

    def _hotkey_row(self, form: QFormLayout, label: str, field: str) -> QKeySequenceEdit:
        edit = QKeySequenceEdit()
        edit.setMaximumSequenceLength(1)
        edit.editingFinished.connect(lambda: self._hotkey_changed(edit, field))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: (edit.clear(), self._hotkey_changed(edit, field)))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(clear)
        form.addRow(label, row)
        return edit

    # ------------------------------------------------------------ handlers

    def _set(self, field: str, value) -> None:
        if self._loading or getattr(self._settings, field) == value:
            return
        setattr(self._settings, field, value)
        self._save()
        self.changed.emit()

    def _thresholds_changed(self) -> None:
        values = tuple(v for v in (self._first.value(), self._second.value()) if v > 0)
        self._set("low_battery_thresholds", tuple(sorted(set(values), reverse=True)))

    def _hotkey_changed(self, edit: QKeySequenceEdit, field: str) -> None:
        text = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if text and parse_hotkey(text) is None:
            self._hotkey_error.setText(f"{text} won't work: use Ctrl, Alt or Win plus a letter, digit or F-key.")
            self._hotkey_error.show()
            return
        self._hotkey_error.hide()
        self._set(field, text)

    def _rssi_changed(self, value: int) -> None:
        self._rssi_label.setText(f"Ignore AirPods weaker than {value} dBm (raise it if a neighbour's show up)")
        self._set("min_rssi", value)

    def _set_autostart(self, enabled: bool) -> None:
        if self._loading:
            return
        try:
            autostart.set_enabled(enabled)
        except OSError:
            log.exception("Could not update the startup entry")
        self.changed.emit()
