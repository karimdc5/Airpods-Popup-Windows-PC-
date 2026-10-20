"""Turns a noisy stream of adverts into one stable view of *your* device.

Every pod broadcasts on its own, rotates its BLE address, and often only
knows its own battery, so a single advert is never the full picture. The
tracker keeps the last reading per part with a timestamp and decides which
nearby device is yours:

* adverts weaker than ``min_rssi`` are ignored (other people's AirPods);
* adverts are grouped by model, and the strongest group wins, with
  hysteresis so the display doesn't flicker between two nearby devices;
* within a group, adverts far weaker than the group's average are treated
  as a stranger with the same model and dropped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .catalog import DeviceModel, lookup
from .protocol import Part, ProximityReport

POD_FRESH_S = 90.0
CASE_FRESH_S = 15 * 60.0  # the case is only reported while a pod sits in it
CANDIDATE_TIMEOUT_S = 30.0
CANDIDATE_FORGET_S = 10 * 60.0
SWITCH_MARGIN_DB = 8.0
OUTLIER_DB = 25.0  # a bud held in your hand reads ~20 dB weaker than in your ear
RSSI_SMOOTHING = 0.3
# Pods in a closed case mostly stop broadcasting, so "open" after this much
# silence from the case counts as the lid being opened.
LID_QUIET_S = 15.0


@dataclass(frozen=True, slots=True)
class Component:
    level: int | None = None
    charging: bool = False
    in_ear: bool = False
    fresh: bool = False

    @property
    def known(self) -> bool:
        return self.level is not None


_EMPTY = Component()


@dataclass(frozen=True, slots=True)
class Snapshot:
    model: DeviceModel | None = None
    left: Component = _EMPTY
    right: Component = _EMPTY
    case: Component = _EMPTY
    rssi: float | None = field(default=None, compare=False)

    def component(self, part: Part) -> Component:
        match part:
            case Part.LEFT:
                return self.left
            case Part.RIGHT:
                return self.right
            case Part.CASE:
                return self.case

    @property
    def has_fresh_data(self) -> bool:
        return self.left.fresh or self.right.fresh or self.case.fresh

    @property
    def in_ear(self) -> bool:
        return self.left.in_ear or self.right.in_ear


@dataclass(frozen=True, slots=True)
class FeedResult:
    accepted: bool = False  # the advert came from the device being shown
    changed: bool = False  # the snapshot looks different
    lid_opened: bool = False  # the active device's case lid just went closed -> open


_IGNORED = FeedResult()


@dataclass(slots=True)
class _Reading:
    level: int
    charging: bool
    at: float


@dataclass(slots=True)
class _EarReading:
    in_ear: bool
    at: float


@dataclass(slots=True)
class _Candidate:
    model_id: int
    rssi: float
    last_seen: float
    readings: dict[Part, _Reading] = field(default_factory=dict)
    ears: dict[Part, _EarReading] = field(default_factory=dict)
    lid_open: bool | None = None
    lid_at: float = float("-inf")


class Tracker:
    def __init__(self, min_rssi: int = -75, clock: Callable[[], float] = time.monotonic) -> None:
        self.min_rssi = min_rssi
        self._clock = clock
        self._candidates: dict[int, _Candidate] = {}
        self._active: int | None = None

    def feed(self, report: ProximityReport, rssi: int) -> FeedResult:
        if rssi < self.min_rssi:
            return _IGNORED
        now = self._clock()
        before = self.snapshot()

        cand = self._candidates.get(report.model_id)
        if cand is None:
            cand = self._candidates[report.model_id] = _Candidate(report.model_id, float(rssi), now)
        elif now - cand.last_seen > CANDIDATE_TIMEOUT_S:
            cand.rssi = float(rssi)
        elif rssi < cand.rssi - OUTLIER_DB:
            return _IGNORED
        else:
            cand.rssi += RSSI_SMOOTHING * (rssi - cand.rssi)
        cand.last_seen = now

        for part in Part:
            battery = report.battery(part)
            if battery.level is not None:
                cand.readings[part] = _Reading(battery.level, battery.charging, now)
        for part, in_ear in ((Part.LEFT, report.left_in_ear), (Part.RIGHT, report.right_in_ear)):
            if in_ear is not None and report.battery(part).level is not None:
                cand.ears[part] = _EarReading(in_ear, now)

        lid_opened = False
        if report.lid_open is not None:
            was_open = cand.lid_open is True and now - cand.lid_at <= LID_QUIET_S
            lid_opened = report.lid_open and not was_open
            cand.lid_open, cand.lid_at = report.lid_open, now

        self._select(now)
        return FeedResult(
            accepted=self._active == cand.model_id,
            changed=self.snapshot() != before,
            lid_opened=lid_opened and self._active == cand.model_id,
        )

    def snapshot(self) -> Snapshot:
        cand = self._candidates.get(self._active) if self._active is not None else None
        if cand is None:
            return Snapshot()
        now = self._clock()
        return Snapshot(
            model=lookup(cand.model_id),
            left=_component(cand, Part.LEFT, now, POD_FRESH_S),
            right=_component(cand, Part.RIGHT, now, POD_FRESH_S),
            case=_component(cand, Part.CASE, now, CASE_FRESH_S),
            rssi=cand.rssi,
        )

    def _select(self, now: float) -> None:
        for model_id, cand in list(self._candidates.items()):
            if model_id != self._active and now - cand.last_seen > CANDIDATE_FORGET_S:
                del self._candidates[model_id]

        live = [c for c in self._candidates.values() if now - c.last_seen <= CANDIDATE_TIMEOUT_S]
        if not live:
            return  # keep showing the last device; its readings go stale on their own
        best = max(live, key=lambda c: c.rssi)
        current = self._candidates.get(self._active) if self._active is not None else None
        if (
            current is None
            or now - current.last_seen > CANDIDATE_TIMEOUT_S
            or best.rssi > current.rssi + SWITCH_MARGIN_DB
        ):
            self._active = best.model_id


def _component(cand: _Candidate, part: Part, now: float, fresh_for: float) -> Component:
    reading = cand.readings.get(part)
    if reading is None:
        return _EMPTY
    fresh = now - reading.at <= fresh_for
    ear = cand.ears.get(part)
    in_ear = ear is not None and ear.in_ear and now - ear.at <= fresh_for
    return Component(reading.level, reading.charging, in_ear, fresh)
