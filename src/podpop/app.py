"""Wires the BLE listener, Bluetooth watchers, tracker, popup and tray together.

All state lives on the Qt main thread. Background callbacks (bleak thread,
WinRT thread pool, connect worker) only emit signals on ``_Bridge``; Qt
queues them across threads, so handlers here never need locks.

"Connected" means the AirPods' audio endpoint is active on this PC (see
audio_connect.active_devices). The WinRT connection watcher supplies the
paired device's name and address, and nudges an immediate audio check when
Windows reports a link change.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import audio_connect
from .alerts import LowBatteryMonitor
from .ble import Advert, BleListener, ScannerState
from .catalog import guess_from_name
from .connection import ConnectionEvent, ConnectionWatcher
from .doctor import LinkDoctor
from .ear import EarAction, EarDetector
from .handoff import Handoff
from .hotkeys import HotkeyManager
from .media import MediaController
from .presenter import DeviceView, build_view
from .runtime import RuntimeEstimator
from .idle import idle_seconds
from .protocol import Part
from .settings import Settings, config_dir
from .state import Tracker
from .ui.popup import Action, PopupWindow
from .ui.theme import theme_for
from .ui.settings_window import SettingsWindow
from .ui.tray import Tray

log = logging.getLogger(__name__)

# After a connect event, wait this long for the first advert before showing
# the popup anyway, so it usually opens with real numbers.
FIRST_ADVERT_WAIT_MS = 2500
REFRESH_MS = 5000
# A gap this long between refresh ticks means the PC was asleep.
WAKE_GAP_S = 30.0
# Log an ignored case-open packet at most this often.
IGNORED_LID_LOG_S = 30.0
AUDIO_POLL_MS = 1500
# How long to wait for the audio to come up after asking Windows to connect.
CONNECT_TIMEOUT_MS = 35000  # covers a full reconnect cycle
# Let a link that Windows re-opened by itself settle before judging it.
REPAIR_DELAY_MS = 3000
EAR_TICK_MS = 200
AWAY_POLL_MS = 5000


class _Bridge(QObject):
    advert = Signal(object)
    connection = Signal(object)
    scanner = Signal(object, str)
    connect_done = Signal(str)  # error message, empty on success
    media_paused = Signal(bool)  # whether a pause request paused anything
    handoff_checked = Signal(bool)  # whether media was playing when you stepped away


class PodPopApp(QObject):
    def __init__(self, settings: Settings, settings_path: Path) -> None:
        super().__init__()
        self._settings = settings
        self._settings_path = settings_path
        self._tracker = Tracker(min_rssi=settings.min_rssi)
        self._alerts = LowBatteryMonitor(settings.low_battery_thresholds)
        self._alert_thresholds = settings.low_battery_thresholds
        self._name_filter = re.compile(settings.device_name_pattern, re.IGNORECASE)
        self._audio_connected: bool | None = None  # None until the first check
        self._scanner_note: str | None = None
        self._connecting = False
        self._connect_failed = False
        self._doctor = LinkDoctor()
        self._runtime = RuntimeEstimator()
        self._runtime_path = config_dir() / "battery_profile.json"
        self._load_runtime()
        self._ear = EarDetector()
        self._last_ears: tuple[bool, bool] | None = None
        self._media = MediaController()
        self._last_tick = time.monotonic()
        self._ignored_lid_logged = float("-inf")
        self._handoff = Handoff()

        self._bridge = _Bridge()
        queued = Qt.ConnectionType.QueuedConnection
        self._bridge.advert.connect(self._on_advert, queued)
        self._bridge.connection.connect(self._on_connection, queued)
        self._bridge.scanner.connect(self._on_scanner, queued)
        self._bridge.connect_done.connect(self._on_connect_done, queued)
        self._bridge.media_paused.connect(lambda paused: paused or self._ear.forget_pause(), queued)
        self._bridge.handoff_checked.connect(self._on_handoff_checked, queued)
        self._ble = BleListener(self._bridge.advert.emit, self._bridge.scanner.emit)
        self._connections = ConnectionWatcher(self._bridge.connection.emit)

        self._popup = PopupWindow(theme_for(settings.theme))
        self._popup.connect_clicked.connect(self.connect_device)
        self._tray = Tray()
        self._settings_window = SettingsWindow(settings, self._save_settings)
        self._settings_window.changed.connect(self._apply_settings)
        self._tray.settings_requested.connect(self.open_settings)
        self._popup.settings_clicked.connect(self.open_settings)
        self._tray.show_requested.connect(self.show_popup)
        self._tray.connect_requested.connect(self.connect_device)
        self._tray.repair_requested.connect(self.repair_audio)
        self._tray.release_requested.connect(self.release_device)
        self._tray.quit_requested.connect(QApplication.quit)
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self._apply_theme())
        self._hotkeys = HotkeyManager()
        self._hotkeys.triggered.connect(self._on_hotkey)
        self._hotkey_combos: dict[str, str] | None = None
        self._apply_settings()

        self._pending_popup = QTimer(self, singleShot=True, interval=FIRST_ADVERT_WAIT_MS)
        self._pending_popup.timeout.connect(self.show_popup)
        self._refresh_timer = QTimer(self, interval=REFRESH_MS)
        self._refresh_timer.timeout.connect(self._tick)  # lets readings age into "stale"
        self._audio_timer = QTimer(self, interval=AUDIO_POLL_MS)
        self._audio_timer.timeout.connect(self._check_audio)
        self._connect_timeout = QTimer(self, singleShot=True, interval=CONNECT_TIMEOUT_MS)
        self._connect_timeout.timeout.connect(lambda: self._finish_connect(failed=True))
        self._ear_timer = QTimer(self, interval=EAR_TICK_MS)  # runs only while a reading settles
        self._ear_timer.timeout.connect(lambda: self._handle_ear(self._ear.tick()))
        self._away_timer = QTimer(self, interval=AWAY_POLL_MS)
        self._away_timer.timeout.connect(self._check_away)

    def start(self) -> None:
        self._tray.show()
        self._ble.start()
        try:
            self._connections.start()
        except Exception:
            log.exception("Bluetooth connection watcher unavailable")
        self._refresh_timer.start()
        self._audio_timer.start()
        self._away_timer.start()
        self._refresh()

    def shutdown(self) -> None:
        for timer in (
            self._refresh_timer, self._audio_timer, self._connect_timeout, self._pending_popup, self._ear_timer,
            self._away_timer,
        ):
            timer.stop()
        self._connections.stop()
        self._ble.stop()
        self._media.shutdown()
        self._hotkeys.clear()
        self._tray.hide()

    def show_popup(self) -> None:
        self._pending_popup.stop()
        if not self._connecting:
            self._connect_failed = False  # a fresh popup offers Connect again
        self._popup.set_action(self._action())
        self._popup.present(self._view(), self._settings.popup_duration_s)

    def open_settings(self) -> None:
        self._popup.dismiss()
        self._settings_window.open()

    def connect_device(self) -> None:
        """Ask Windows to connect the paired AirPods, e.g. taking them from an iPhone."""
        self._handoff.end_hold()  # you want them here now
        if not self._audio_connected:
            self._start_link_job(audio_connect.connect, "Connecting")

    def repair_audio(self) -> None:
        """Disconnect and reconnect: fixes "connected but no sound"."""
        if self._audio_connected:
            self._start_link_job(audio_connect.reconnect, "Reconnecting")
        else:
            self.connect_device()

    def release_device(self, *, pause_media: bool = True) -> None:
        """Drop this PC's audio link so another device (your iPhone) can take the AirPods."""
        target = self._paired_airpods()
        if not self._audio_connected or self._connecting or target is None:
            return
        try:
            mac = audio_connect.mac_from_device_id(target.device_id)
        except audio_connect.ConnectError:
            log.exception("Cannot reach %s", target.name)
            return
        log.info("Releasing %s for another device", target.name)
        if pause_media:
            self._media.pause()  # don't let the PC carry on out of its speakers
        self._handoff.hold(time.monotonic())
        threading.Thread(
            target=self._release_worker, args=(mac, target.name), name="podpop-release", daemon=True
        ).start()

    def _start_link_job(self, job, label: str) -> None:
        target = self._paired_airpods()
        if self._connecting or target is None:
            return
        try:
            mac = audio_connect.mac_from_device_id(target.device_id)
        except audio_connect.ConnectError:
            log.exception("Cannot reach %s", target.name)
            return
        log.info("%s %s", label, target.name)
        self._connecting, self._connect_failed = True, False
        self._connect_timeout.start()
        self._refresh()
        threading.Thread(
            target=self._link_worker, args=(job, mac, target.name), name="podpop-link", daemon=True
        ).start()

    # ------------------------------------------------------------ handlers

    def _on_advert(self, advert: Advert) -> None:
        result = self._tracker.feed(advert.report, advert.rssi)
        r = advert.report
        if r.lid_open and not result.accepted:
            self._log_ignored_lid(advert)
        log.debug(
            "advert %s %ddBm from=%s status=%02x L=%s%s R=%s%s accepted=%s",
            advert.address[-5:], advert.rssi, r.broadcaster.value, advert.payload[5],
            r.left.level, "e" if r.left_in_ear else "", r.right.level, "e" if r.right_in_ear else "",
            result.accepted,
        )
        if result.accepted:
            self._on_ears()
        if result.accepted and not self._connecting:
            in_ear = self._tracker.snapshot().in_ear
            if self._doctor.advert(in_ear=in_ear, audio_connected=bool(self._audio_connected)):
                self._auto_repair()
        if result.lid_opened:
            log.info("Case opened")
            if self._settings.auto_connect_on_case_open:
                self.connect_device()  # also cancels a hand-off: opening the case means "here"
            if self._settings.popup_on_case_open:
                self.show_popup()
        elif self._pending_popup.isActive() and self._tracker.snapshot().has_fresh_data:
            self.show_popup()
        if result.changed:
            if self._runtime.update(self._tracker.snapshot()):
                self._save_runtime()
            self._refresh()

    def _tick(self) -> None:
        now = time.monotonic()
        if now - self._last_tick > WAKE_GAP_S:
            log.info("PC woke up after %.0fs; restarting Bluetooth scanning", now - self._last_tick)
            self._ble.restart()
        self._last_tick = now
        self._refresh()

    def _log_ignored_lid(self, advert: Advert) -> None:
        # So a missed popup can be explained from the log.
        now = time.monotonic()
        if now - self._ignored_lid_logged < IGNORED_LID_LOG_S:
            return
        self._ignored_lid_logged = now
        if advert.rssi < self._settings.min_rssi:
            reason = f"weaker than the {self._settings.min_rssi} dBm signal threshold"
        else:
            reason = "doesn't look like the AirPods being shown"
        log.info("Ignored an open-case packet at %d dBm: %s", advert.rssi, reason)

    def _on_connection(self, event: ConnectionEvent) -> None:
        if self._name_filter.search(event.name):
            if not event.connected and self._handoff.holding(time.monotonic()):
                log.info("AirPods left this PC; hand-off done")
                self._handoff.end_hold()
            self._check_audio()  # Windows saw a link change; don't wait for the next poll

    def _on_scanner(self, state: ScannerState, detail: str) -> None:
        unavailable = state is ScannerState.UNAVAILABLE
        self._scanner_note = "Bluetooth unavailable — is it turned on?" if unavailable else None
        self._refresh()

    def _check_audio(self) -> None:
        target = self._paired_airpods()
        if target is None:
            connected = False
        else:
            try:
                connected = audio_connect.mac_from_device_id(target.device_id) in audio_connect.active_devices()
            except Exception:
                log.debug("Audio endpoint check failed; using Bluetooth link state", exc_info=True)
                connected = target.connected

        initial = self._audio_connected is None
        if connected == self._audio_connected:
            return
        self._audio_connected = connected
        log.info("AirPods audio %s%s", "connected" if connected else "disconnected", " (already)" if initial else "")
        if connected and not initial and not self._connecting and self._handoff.holding(time.monotonic()):
            log.info("Windows took the AirPods back during a hand-off; releasing them again")
            self.release_device(pause_media=False)
            self._refresh()
            return
        if not initial and not self._connecting and self._doctor.audio_changed(connected=connected):
            QTimer.singleShot(REPAIR_DELAY_MS, self._auto_repair)
        if connected:
            if self._connecting:
                self._finish_connect(failed=False)
                self.show_popup()  # restart the timer so "Connected" is seen
            elif not initial and self._settings.popup_on_connect:
                if self._tracker.snapshot().has_fresh_data:
                    self.show_popup()
                else:
                    self._pending_popup.start()
        else:
            self._pending_popup.stop()
        self._refresh()

    def _on_ears(self) -> None:
        snap = self._tracker.snapshot()
        ears = (snap.left.in_ear, snap.right.in_ear)
        if ears != self._last_ears:
            log.info("In ear: left=%s right=%s", *ears)
            self._last_ears = ears
        self._handle_ear(self._ear.update(*ears))

    def _handle_ear(self, action: EarAction) -> None:
        if self._ear.pending:
            self._ear_timer.start()
        else:
            self._ear_timer.stop()
        # Only control media when the AirPods are this PC's audio; otherwise
        # whatever is playing here isn't in your ears anyway.
        active = self._settings.auto_pause_on_removal and self._audio_connected
        if action is EarAction.PAUSE:
            if not active:
                self._ear.forget_pause()
                return
            log.info("AirPod taken out; pausing media")
            self._media.pause().add_done_callback(lambda f: self._bridge.media_paused.emit(bool(f.result())))
        elif action is EarAction.RESUME and active:
            log.info("AirPod back in; resuming media")
            self._media.resume()

    def _auto_repair(self) -> None:
        # Only re-open a link Windows already has; never pull the AirPods from another device.
        if self._settings.auto_fix_audio and self._audio_connected and not self._connecting:
            log.info("Back in range after being away; reconnecting audio in case it is stuck")
            self.repair_audio()

    def _check_away(self) -> None:
        idle = idle_seconds()
        if self._handoff.back(idle_s=idle):
            if not self._audio_connected:
                log.info("Back at the PC after a hand-off; offering to reconnect")
                self.show_popup()  # one click on Connect brings them back
            return
        if not self._settings.handoff_when_away or self._connecting:
            return
        wearing = self._tracker.snapshot().in_ear
        if self._handoff.due(idle_s=idle, connected=bool(self._audio_connected), wearing=wearing):
            self._media.is_playing().add_done_callback(lambda f: self._bridge.handoff_checked.emit(f.result()))

    def _on_handoff_checked(self, playing: bool) -> None:
        wearing = self._tracker.snapshot().in_ear
        if self._handoff.confirm(playing=playing, connected=bool(self._audio_connected), wearing=wearing):
            log.info("Away from the PC while wearing the AirPods; handing them to your other device")
            self.release_device()
        elif playing:
            log.info("Away from the PC, but media is playing on it; keeping the AirPods")

    def _release_worker(self, mac: str, device_name: str) -> None:  # runs on its own thread
        try:
            audio_connect.release(mac, device_name)
        except Exception as exc:
            log.warning("Could not release the AirPods: %s", exc)

    def _link_worker(self, job, mac: str, device_name: str) -> None:  # runs on its own thread
        try:
            job(mac, device_name)
            self._bridge.connect_done.emit("")
        except Exception as exc:
            log.warning("Bluetooth request failed: %s", exc)
            self._bridge.connect_done.emit(str(exc) or type(exc).__name__)

    def _on_connect_done(self, error: str) -> None:
        if not self._connecting:
            return
        if error:
            self._finish_connect(failed=True)
            return
        self._check_audio()
        if self._connecting and self._audio_connected:
            # A quick reconnect can finish before a poll ever saw the link drop.
            self._finish_connect(failed=False)
        # Otherwise the next audio check (or the timeout) finishes the job.

    def _finish_connect(self, *, failed: bool) -> None:
        self._connect_timeout.stop()
        self._connecting = False
        self._connect_failed = failed
        if failed:
            log.warning("AirPods did not connect")
        self._refresh()

    # ------------------------------------------------------------- helpers

    def _paired_airpods(self) -> ConnectionEvent | None:
        matches = [d for d in self._connections.paired() if self._name_filter.search(d.name)]
        matches.sort(key=lambda d: not d.connected)
        return matches[0] if matches else None

    def _action(self) -> Action:
        if self._audio_connected or self._paired_airpods() is None:
            return Action.HIDDEN
        if self._connecting:
            return Action.CONNECTING
        return Action.FAILED if self._connect_failed else Action.CONNECT

    def _view(self) -> DeviceView:
        target = self._paired_airpods()
        snapshot = self._tracker.snapshot()
        family = (snapshot.model or guess_from_name(target.name if target else "")).family
        minutes = self._runtime.minutes_left(snapshot, family)
        return build_view(snapshot, target.name if target else None, bool(self._audio_connected), minutes)

    def _load_runtime(self) -> None:
        try:
            self._runtime.load(json.loads(self._runtime_path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            log.warning("Ignoring unreadable battery profile %s", self._runtime_path)

    def _save_runtime(self) -> None:
        try:
            self._runtime_path.parent.mkdir(parents=True, exist_ok=True)
            self._runtime_path.write_text(json.dumps(self._runtime.to_dict()), encoding="utf-8")
        except OSError:
            log.exception("Could not save battery profile")

    def _refresh(self) -> None:
        view = self._view()
        action = self._action()
        self._tray.update(view, self._scanner_note)
        self._tray.set_link_actions(
            can_connect=action in (Action.CONNECT, Action.FAILED),
            can_repair=self._paired_airpods() is not None and not self._connecting,
            can_release=bool(self._audio_connected) and not self._connecting,
        )
        self._popup.set_action(action)
        self._popup.update_view(view)
        if self._settings.low_battery_alerts:
            for alert in self._alerts.update(self._tracker.snapshot()):
                side = "Left" if alert.part is Part.LEFT else "Right"
                self._tray.notify("AirPods battery low", f"{side} AirPod is at {alert.level}%.")

    def _apply_settings(self) -> None:
        self._tracker.min_rssi = self._settings.min_rssi
        if self._settings.low_battery_thresholds != self._alert_thresholds:
            self._alert_thresholds = self._settings.low_battery_thresholds
            self._alerts = LowBatteryMonitor(self._alert_thresholds)
        self._popup.follow_cursor = self._settings.popup_follows_mouse
        self._popup.intro_enabled = self._settings.popup_intro_animation
        self._apply_theme()
        self._handoff.away_s = self._settings.handoff_away_minutes * 60.0
        combos = {
            "show": self._settings.hotkey_show_popup,
            "connect": self._settings.hotkey_connect,
            "handoff": self._settings.hotkey_handoff,
        }
        if combos != self._hotkey_combos:
            self._hotkey_combos = combos
            failed = self._hotkeys.set_hotkeys(combos)
            if failed:
                self._tray.notify("Shortcut unavailable", f"{', '.join(failed)} is invalid or used by another app.")

    def _apply_theme(self) -> None:
        # Menus and the settings window follow the chosen theme too.
        # (Setting an unchanged scheme emits nothing, so this can't loop.)
        scheme = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(self._settings.theme)
        hints = QGuiApplication.styleHints()
        if scheme is None:
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(scheme)
        self._popup.set_theme(theme_for(self._settings.theme))

    def _on_hotkey(self, name: str) -> None:
        if name == "show":
            self.show_popup()
        elif name == "connect":
            self.repair_audio() if self._audio_connected else self.connect_device()
            self.show_popup()
        elif name == "handoff":
            self.release_device()

    def _save_settings(self) -> None:
        try:
            self._settings.save(self._settings_path)
        except OSError:
            log.exception("Could not save settings")
