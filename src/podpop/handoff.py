"""Hands the AirPods to your phone when you lock the PC, and takes them back on unlock.

AirPods let go of the PC by themselves when you close the case, but not
while you're wearing them: lock the PC and walk off, and the PC keeps the
link, so your iPhone can't take over. With hand-off:

* you lock the PC while wearing the AirPods and nothing is playing on it;
* after ``GRACE_S`` (so a quick lock/unlock does nothing) PodPop drops this
  PC's audio link, which frees the AirPods for your phone;
* you unlock while wearing them, and PodPop connects them back.

It never releases AirPods that are playing something from this PC (music
keeps going while the screen is locked), and it only takes back AirPods it
handed off itself.

Pure logic; the app watches the session and does the Bluetooth work.
"""

from __future__ import annotations

GRACE_S = 5.0


class Handoff:
    def __init__(self) -> None:
        self._locked = False
        self._released = False

    def lock(self, *, connected: bool, wearing: bool) -> bool:
        """Call when the session locks. True means: check again after ``GRACE_S``."""
        self._locked = True
        return connected and wearing

    def grace_over(self, *, connected: bool, wearing: bool, playing: bool) -> bool:
        """Call ``GRACE_S`` after a lock. True means: release the AirPods now."""
        if self._locked and connected and wearing and not playing:
            self._released = True
            return True
        return False

    def unlock(self, *, connected: bool, wearing: bool) -> bool:
        """Call when the session unlocks. True means: connect the AirPods back."""
        released = self._released
        self._locked = self._released = False
        return released and wearing and not connected
