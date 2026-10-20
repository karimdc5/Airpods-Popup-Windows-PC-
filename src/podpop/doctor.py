"""Decides when to repair the audio link after you walk away and come back.

Windows often re-links AirPods by itself when you come back in range, or
never notices they left, yet the audio stream stays stuck: it shows
"connected" with no sound until you disconnect and reconnect.

The doctor only acts when two things are both true:

* you were out of range while wearing them: no adverts for ``AWAY_S``
  while a bud was in your ear, and
* Windows already has the audio link up again.

It never connects on its own. If the AirPods moved to your iPhone, the PC
leaves them there; the popup's Connect button is for taking them back.

Pure logic with an injectable clock; the app performs the repair.
"""

from __future__ import annotations

import time
from collections.abc import Callable

AWAY_S = 45.0  # this long without adverts while wearing them means you left


class LinkDoctor:
    def __init__(self, away_s: float = AWAY_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._away_s = away_s
        self._clock = clock
        self._last_advert: float | None = None
        self._worn = False  # a bud was in your ear as of the last advert
        self._awaiting_link = False  # came back while Windows had no audio link yet

    def advert(self, *, in_ear: bool, audio_connected: bool) -> bool:
        """Call for every advert from your AirPods. True means: reconnect now."""
        returned = self._returned()
        self._last_advert, self._worn = self._clock(), in_ear
        if not returned:
            return False
        if audio_connected:
            return True
        self._awaiting_link = True  # fix it once Windows re-links by itself
        return False

    def audio_changed(self, *, connected: bool) -> bool:
        """Call when this PC's audio link goes up or down on its own. True means: reconnect now."""
        if not connected:
            return False
        if self._awaiting_link or self._returned():
            # Windows re-linked after you were away (possibly before we saw an advert).
            self._awaiting_link = False
            self._last_advert = self._clock()
            return True
        return False

    def _returned(self) -> bool:
        return self._worn and self._last_advert is not None and self._clock() - self._last_advert >= self._away_s
