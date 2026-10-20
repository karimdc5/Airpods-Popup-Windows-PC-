"""Estimates listening time left from battery level and how fast it drops.

AirPods report battery in 10 % steps. Until we have watched a bud drop a
step or two, we assume Apple's rated listening time; after that we use the
measured time per step (median of recent steps, so one odd reading doesn't
swing it). Measurements are kept per bud and survive restarts via
``to_dict``/``from_dict``.

Pure logic with an injectable clock.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .catalog import Family
from .protocol import Part
from .state import Snapshot

# Apple's rated listening time on a full charge (hours).
RATED_HOURS = {Family.PRO: 6.0, Family.CLASSIC: 5.0, Family.OPEN: 5.0, Family.HEADPHONES: 20.0}
MIN_STEP_S = 3 * 60.0  # faster "drops" are noise (e.g. a reading flicker)
MAX_STEP_S = 4 * 3600.0  # slower ones span a pause in listening; not a drain rate
KEEP_STEPS = 6


@dataclass(slots=True)
class _Pod:
    level: int | None = None
    last_drop_at: float | None = None  # when we saw it go down a step
    steps: list[float] = field(default_factory=list)  # seconds per 10 % step


class RuntimeEstimator:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._pods = {Part.LEFT: _Pod(), Part.RIGHT: _Pod()}

    def update(self, snapshot: Snapshot) -> bool:
        """Feed the latest state; True if a new drain measurement was learned."""
        now = self._clock()
        learned = False
        for part, pod in self._pods.items():
            c = snapshot.component(part)
            if not c.fresh or c.level is None:
                continue
            if c.charging or (pod.level is not None and c.level > pod.level):
                pod.last_drop_at = None  # charging restarts the clock
            elif pod.level is not None and c.level < pod.level:
                drops = (pod.level - c.level) // 10 or 1
                if pod.last_drop_at is not None:
                    per_step = (now - pod.last_drop_at) / drops
                    if MIN_STEP_S <= per_step <= MAX_STEP_S:
                        pod.steps = (pod.steps + [per_step])[-KEEP_STEPS:]
                        learned = True
                pod.last_drop_at = now
            pod.level = c.level
        return learned

    def minutes_left(self, snapshot: Snapshot, family: Family) -> int | None:
        """Listening time left for the emptier of the buds in use, or None."""
        now = self._clock()
        estimates = []
        for part, pod in self._pods.items():
            c = snapshot.component(part)
            if not c.fresh or c.level is None or c.charging:
                continue
            step = self._step_seconds(pod, family)
            steps_left = c.level / 10
            if pod.last_drop_at is not None:
                # Part of the current step is already used up.
                into_step = min(now - pod.last_drop_at, step * 0.9)
                steps_left = max(0.0, steps_left - into_step / step)
            estimates.append(steps_left * step / 60)
        return round(min(estimates)) if estimates else None

    def _step_seconds(self, pod: _Pod, family: Family) -> float:
        rated = RATED_HOURS.get(family, 5.0) * 3600 / 10
        if not pod.steps:
            return rated
        measured = statistics.median(pod.steps)
        if len(pod.steps) == 1:
            return (measured + rated) / 2  # one sample: don't trust it fully yet
        return measured

    def to_dict(self) -> dict[str, list[float]]:
        return {part.value: list(pod.steps) for part, pod in self._pods.items()}

    def load(self, data: dict) -> None:
        for part, pod in self._pods.items():
            steps = data.get(part.value, [])
            if isinstance(steps, list):
                pod.steps = [float(s) for s in steps if isinstance(s, (int, float)) and MIN_STEP_S <= s <= MAX_STEP_S][
                    -KEEP_STEPS:
                ]


def format_time_left(minutes: int | None) -> str | None:
    """53 -> 'About 55m left', 222 -> 'About 3h 40m left'."""
    if minutes is None:
        return None
    if minutes < 10:
        return "Less than 10m left"
    minutes = int(round(minutes / 5.0) * 5)  # the input is only accurate to ~10 %
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"About {mins}m left"
    return f"About {hours}h {mins:02d}m left" if mins else f"About {hours}h left"
