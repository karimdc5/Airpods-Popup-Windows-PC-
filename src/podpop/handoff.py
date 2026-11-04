"""Hands the AirPods to your phone when you step away from the PC.

AirPods let go of the PC by themselves when you close the case, but not
while you're wearing them: walk off with them in and the PC keeps the link,
so your iPhone can't take over. With hand-off:

* you're wearing the AirPods, they're this PC's audio, and nothing is playing
  on the PC;
* you haven't touched the keyboard or mouse for the away time (2 minutes by
  default);
* PodPop drops this PC's audio link, which frees the AirPods for your phone.

Windows reconnects paired headphones by itself as soon as they're free, and
as the last device they used it usually beats the phone to them. So for
``HOLD_S`` after a hand-off, the app lets go again whenever Windows grabs them
back on its own, until the phone has them (the PC's Bluetooth link drops) or
you connect them to the PC yourself.

When you're back (any keyboard or mouse input), the app shows the popup so
one click on Connect brings them back. It never takes them back on its own,
so it can't pull them off your phone in the middle of a call.

Pure logic; the app reads the idle time and does the Bluetooth work.
"""

from __future__ import annotations

AWAY_S = 120.0
HOLD_S = 120.0


class Handoff:
    def __init__(self, away_s: float = AWAY_S) -> None:
        self.away_s = away_s
        self._released = False
        self._kept = False  # checked this time away, but media was playing
        self._checking = False
        self._hold_until = float("-inf")

    def due(self, *, idle_s: float, connected: bool, wearing: bool) -> bool:
        """True means: you look away; check whether media is playing, then call confirm()."""
        if self._released or self._kept or self._checking:
            return False
        if idle_s >= self.away_s and connected and wearing:
            self._checking = True
            return True
        return False

    def confirm(self, *, playing: bool, connected: bool, wearing: bool) -> bool:
        """Call with the media check's result. True means: release the AirPods now."""
        self._checking = False
        if playing:
            self._kept = True  # don't cut off the music; look again after you're back
            return False
        if connected and wearing:
            self._released = True
            return True
        return False

    def hold(self, now: float) -> None:
        """Call after releasing them: start keeping Windows off them."""
        self._hold_until = now + HOLD_S

    def holding(self, now: float) -> bool:
        """True while Windows reconnecting by itself should be undone."""
        return now < self._hold_until

    def end_hold(self) -> None:
        """Call when the phone has them, or when you connect them to the PC yourself."""
        self._hold_until = float("-inf")

    def back(self, *, idle_s: float) -> bool:
        """Call regularly. True means: you're back after a hand-off; offer to reconnect."""
        if idle_s >= self.away_s:
            return False
        released = self._released
        self._released = self._kept = False
        return released
