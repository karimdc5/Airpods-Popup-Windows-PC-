"""Ear detection: turns noisy in-ear readings into pause/resume decisions.

Behaves like iOS: taking a bud out pauses; putting it back resumes, but only
if the pause was ours.

A new reading counts once it has stood for ``SETTLE_S`` without an advert
contradicting it, so a bud brushing your ear does nothing. AirPods advertise
only every ~1-5 s, so waiting for a *second* confirming advert would make
pausing slow and miss quick removals. Instead the app calls ``tick()``
frequently and the reading settles on time alone.

Pure logic with an injectable clock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

SETTLE_S = 0.8
RESUME_WITHIN_S = 10 * 60.0  # don't resume music paused long ago


class EarAction(Enum):
    NONE = "none"
    PAUSE = "pause"
    RESUME = "resume"


class EarDetector:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._worn: int | None = None  # settled number of buds in ears
        self._candidate: tuple[int, float] | None = None  # (count, first seen)
        self._paused: tuple[int, float] | None = None  # (buds worn before the pause, when)

    @property
    def pending(self) -> bool:
        """A reading is waiting to settle; keep calling tick()."""
        return self._candidate is not None

    def update(self, left_in_ear: bool, right_in_ear: bool) -> EarAction:
        """Feed the latest in-ear reading (call on every advert)."""
        count = int(left_in_ear) + int(right_in_ear)
        if self._worn is None:
            self._worn = count
        elif count == self._worn:
            self._candidate = None  # contradicted: it was a glitch
        elif self._candidate is None or self._candidate[0] != count:
            self._candidate = (count, self._clock())
        return self.tick()

    def tick(self) -> EarAction:
        """Settle a pending reading once it has stood long enough."""
        if self._candidate is None:
            return EarAction.NONE
        count, since = self._candidate
        now = self._clock()
        if now - since < SETTLE_S:
            return EarAction.NONE

        before, self._worn, self._candidate = self._worn, count, None
        if count < before:
            if self._paused is None:  # remember the fuller state to return to
                self._paused = (before, now)
                return EarAction.PAUSE
            return EarAction.NONE
        if self._paused is not None and count >= self._paused[0]:
            _, paused_at = self._paused
            self._paused = None
            if now - paused_at <= RESUME_WITHIN_S:
                return EarAction.RESUME
        return EarAction.NONE

    def forget_pause(self) -> None:
        """The pause didn't happen (nothing was playing) or no longer applies."""
        self._paused = None
