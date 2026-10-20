"""Watches paired Bluetooth Classic devices for connect/disconnect.

Uses a WinRT DeviceWatcher over association endpoints with the
``System.Devices.Aep.IsConnected`` property, which Windows updates live.
(``BluetoothDevice.GetDeviceSelectorFromConnectionStatus`` looks like the
obvious API but also matches paired devices that aren't connected.)

Callbacks arrive on a WinRT thread-pool thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_BLUETOOTH_CLASSIC = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
_AQS = (
    f'System.Devices.Aep.ProtocolId:="{_BLUETOOTH_CLASSIC}" AND '
    "System.Devices.Aep.IsPaired:=System.StructuredQueryType.Boolean#True"
)
_IS_CONNECTED = "System.Devices.Aep.IsConnected"


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    device_id: str
    name: str
    connected: bool
    initial: bool  # state found at startup rather than a live change


class ConnectionWatcher:
    def __init__(self, on_event: Callable[[ConnectionEvent], None]) -> None:
        self._on_event = on_event
        self._lock = threading.Lock()
        self._devices: dict[str, tuple[str, bool]] = {}
        self._enumerated = False
        self._watcher = None

    def start(self) -> None:
        from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind

        self._watcher = DeviceInformation.create_watcher_with_kind_aqs_filter_and_additional_properties(
            _AQS, [_IS_CONNECTED], DeviceInformationKind.ASSOCIATION_ENDPOINT
        )
        self._watcher.add_added(self._added)
        self._watcher.add_updated(self._updated)
        self._watcher.add_removed(self._removed)
        self._watcher.add_enumeration_completed(self._enumeration_completed)
        self._watcher.start()

    def stop(self) -> None:
        if self._watcher is None:
            return
        try:
            self._watcher.stop()
        except OSError:
            pass  # already stopped or aborted
        self._watcher = None

    def paired(self) -> list[ConnectionEvent]:
        """Every paired Bluetooth Classic device seen so far, connected or not."""
        with self._lock:
            return [ConnectionEvent(i, n, c, initial=True) for i, (n, c) in self._devices.items()]

    # Bluetooth AEP enumeration can take tens of seconds to "complete", so we
    # don't wait for it: devices found during enumeration report their state
    # as initial, and any later IsConnected change is a live event.

    def _added(self, _sender, info) -> None:
        connected = bool(_read_connected(info.properties))
        with self._lock:
            self._devices[info.id] = (info.name, connected)
            initial = not self._enumerated
        if connected:
            self._emit(ConnectionEvent(info.id, info.name, True, initial=initial))

    def _updated(self, _sender, update) -> None:
        connected = _read_connected(update.properties)
        if connected is None:
            return
        with self._lock:
            known = self._devices.get(update.id)
            if known is None or known[1] == connected:
                return
            name = known[0]
            self._devices[update.id] = (name, connected)
        self._emit(ConnectionEvent(update.id, name, connected, initial=False))

    def _removed(self, _sender, update) -> None:
        with self._lock:
            name, connected = self._devices.pop(update.id, ("", False))
        if connected:
            self._emit(ConnectionEvent(update.id, name, False, initial=False))

    def _enumeration_completed(self, _sender, _args) -> None:
        with self._lock:
            self._enumerated = True

    def _emit(self, event: ConnectionEvent) -> None:
        state = "connected" if event.connected else "disconnected"
        log.info("Bluetooth %s%s: %s", state, " (already)" if event.initial else "", event.name)
        try:
            self._on_event(event)
        except Exception:
            log.exception("connection handler failed")


def _read_connected(properties) -> bool | None:
    if not properties.has_key(_IS_CONNECTED):
        return None
    value = properties.lookup(_IS_CONNECTED)
    if value is None:
        return None
    from winrt.system import unbox_boolean

    return unbox_boolean(value)
