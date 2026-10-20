"""Background BLE scanner that delivers decoded Proximity Pairing adverts.

Runs bleak on its own thread and asyncio loop so it never blocks the UI.
Callbacks are invoked on that thread; the caller is responsible for hopping
back to its own thread (the app does this through Qt signals).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .protocol import APPLE_COMPANY_ID, PROXIMITY_PAIRING, ProximityReport, parse

log = logging.getLogger(__name__)

RETRY_DELAY_S = 10.0
# Restart the scanner if it goes quiet; WinRT watchers can stop silently,
# e.g. after the radio is toggled or the PC wakes from sleep.
WATCHDOG_S = 120.0


@dataclass(frozen=True, slots=True)
class Advert:
    report: ProximityReport
    rssi: int
    address: str
    payload: bytes
    timestamp: float


class ScannerState(Enum):
    STARTING = "starting"
    SCANNING = "scanning"
    UNAVAILABLE = "unavailable"


class BleListener:
    def __init__(
        self,
        on_advert: Callable[[Advert], None],
        on_state: Callable[[ScannerState, str], None] = lambda state, detail: None,
    ) -> None:
        self._on_advert = on_advert
        self._on_state = on_state
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._last_advert = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="podpop-ble", daemon=True)
        self._thread.start()
        ready.wait()

    def stop(self) -> None:
        if self._thread is None or self._loop is None or self._stop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)
        self._thread = None

    def _run(self, ready: threading.Event) -> None:
        self._loop = asyncio.new_event_loop()
        self._stop = asyncio.Event()
        ready.set()
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    async def _main(self) -> None:
        from bleak import BleakScanner

        while not self._stop.is_set():
            self._on_state(ScannerState.STARTING, "")
            try:
                async with BleakScanner(detection_callback=self._handle):
                    log.info("BLE scanning started")
                    self._on_state(ScannerState.SCANNING, "")
                    self._last_advert = time.monotonic()
                    while not self._stop.is_set():
                        if await self._sleep(5.0):
                            return
                        if time.monotonic() - self._last_advert > WATCHDOG_S:
                            log.info("No Apple adverts for %.0fs, restarting scanner", WATCHDOG_S)
                            break
            except Exception as exc:  # bleak raises several types (BleakError, OSError, WinError…)
                log.warning("BLE scanner unavailable: %s", exc)
                self._on_state(ScannerState.UNAVAILABLE, str(exc) or type(exc).__name__)
                if await self._sleep(RETRY_DELAY_S):
                    return

    async def _sleep(self, seconds: float) -> bool:
        """Wait, waking early on stop. Returns True if stopping."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    def _handle(self, device, adv) -> None:
        payload = adv.manufacturer_data.get(APPLE_COMPANY_ID)
        if not payload or payload[0] != PROXIMITY_PAIRING:
            return
        self._last_advert = time.monotonic()
        report = parse(bytes(payload))
        if report is None:
            return
        try:
            self._on_advert(Advert(report, adv.rssi, device.address, bytes(payload), time.time()))
        except Exception:
            log.exception("advert handler failed")
