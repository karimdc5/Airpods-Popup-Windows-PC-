"""Low-battery alerts that fire once per threshold, not on every advert."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .protocol import Part
from .state import Snapshot

REARM_MARGIN = 10  # a pod must climb this far above a threshold to alert on it again


@dataclass(frozen=True, slots=True)
class LowBatteryAlert:
    part: Part
    level: int


class LowBatteryMonitor:
    def __init__(self, thresholds: Sequence[int] = (20, 10)) -> None:
        self._thresholds = sorted(set(thresholds), reverse=True)
        self._fired: dict[Part, set[int]] = {Part.LEFT: set(), Part.RIGHT: set()}

    def update(self, snapshot: Snapshot) -> list[LowBatteryAlert]:
        alerts = []
        for part, fired in self._fired.items():
            pod = snapshot.component(part)
            if not pod.fresh or pod.level is None:
                continue
            if pod.charging:
                fired.clear()
                continue
            fired -= {t for t in fired if pod.level >= t + REARM_MARGIN}
            crossed = [t for t in self._thresholds if pod.level <= t and t not in fired]
            if crossed:
                fired.update(t for t in self._thresholds if pod.level <= t)
                alerts.append(LowBatteryAlert(part, pod.level))
        return alerts
