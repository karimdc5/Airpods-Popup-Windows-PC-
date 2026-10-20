"""Decoder for Apple's Continuity "Proximity Pairing" BLE advertisement.

AirPods and Beats broadcast this message (inside Apple's manufacturer data,
company ID 0x004C) several times a second. It is what an iPhone reads to draw
its battery popup. The fields below are sent in the clear; the trailing 16
bytes are encrypted and ignored.

Offsets into the manufacturer payload (company ID already stripped):

    0     message type, 0x07
    1     remaining length
    2     prefix
    3-4   model ID, little-endian
    5     status    0x02 broadcasting pod in ear
                    0x04 both pods in case
                    0x08 other pod in ear
                    0x20 broadcasting pod is the LEFT one
                    0x40 broadcasting pod is in the case (seen on every
                         in-case packet, never from a worn bud)
    6     pods      low nibble: broadcasting pod battery, high: other pod
    7     power     low nibble: case battery
                    high nibble: 0x1 broadcasting pod charging,
                                 0x2 other pod charging, 0x4 case charging
    8     lid       0x08 closed, 0x07 open/close counter
    9     color

In-ear bits: a bud is always right about itself, but a bud sitting in the
case misreports the *other* bud (it says "not in ear" while you wear it), so
that half is only trusted from a bud that is out of the case.

Battery nibbles are 0-10 (x10 %); anything else means unknown, e.g. the other
pod is out of range of the broadcasting one, or no pod is in the case.

The layout agrees with AirPodsDesktop (Source/Core/AppleCP.h) and was checked
against real AirPods Pro 2 (USB-C) packets; see tests/test_protocol.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

APPLE_COMPANY_ID = 0x004C
PROXIMITY_PAIRING = 0x07

_MIN_PAYLOAD_LEN = 10
_MAX_LEVEL_NIBBLE = 10

_THIS_IN_EAR = 0x02
_BOTH_IN_CASE = 0x04
_OTHER_IN_EAR = 0x08
_BROADCASTER_IS_LEFT = 0x20
_BROADCASTER_IN_CASE = 0x40

_CHARGING_THIS = 0x1
_CHARGING_OTHER = 0x2
_CHARGING_CASE = 0x4

_LID_CLOSED = 0x08


class Part(Enum):
    LEFT = "left"
    RIGHT = "right"
    CASE = "case"


@dataclass(frozen=True, slots=True)
class Battery:
    level: int | None  # 0-100 in steps of 10, None when unknown
    charging: bool = False

    @property
    def known(self) -> bool:
        return self.level is not None


UNKNOWN_BATTERY = Battery(None)


@dataclass(frozen=True, slots=True)
class ProximityReport:
    model_id: int
    left: Battery
    right: Battery
    case: Battery
    # None: this advert can't tell (sent by the other bud while in the case).
    left_in_ear: bool | None
    right_in_ear: bool | None
    # Only a pod sitting in the case knows the lid state; None otherwise.
    lid_open: bool | None
    broadcaster: Part
    color: int

    def battery(self, part: Part) -> Battery:
        match part:
            case Part.LEFT:
                return self.left
            case Part.RIGHT:
                return self.right
            case Part.CASE:
                return self.case


def parse(payload: bytes) -> ProximityReport | None:
    """Decode Apple manufacturer data; returns None if it isn't Proximity Pairing."""
    if len(payload) < _MIN_PAYLOAD_LEN or payload[0] != PROXIMITY_PAIRING:
        return None

    status, pods, power, lid, color = payload[5:10]
    charging = power >> 4

    this_pod = _battery(pods & 0x0F, charging & _CHARGING_THIS)
    other_pod = _battery(pods >> 4, charging & _CHARGING_OTHER)
    in_case = this_pod.charging or bool(status & _BROADCASTER_IN_CASE)
    # "Both in case" (0x04) shows up even while the other bud is worn, so it
    # only vouches for the lid, never for ears.
    broadcaster_in_case = in_case or bool(status & _BOTH_IN_CASE)
    # A pod in the case often still sets its in-ear bit; it is not in your ear.
    this_in_ear = bool(status & _THIS_IN_EAR) and not in_case
    other_in_ear: bool | None = None
    if not in_case:
        other_in_ear = bool(status & _OTHER_IN_EAR) and not other_pod.charging

    if status & _BROADCASTER_IS_LEFT:
        broadcaster = Part.LEFT
        left, right, left_in_ear, right_in_ear = this_pod, other_pod, this_in_ear, other_in_ear
    else:
        broadcaster = Part.RIGHT
        left, right, left_in_ear, right_in_ear = other_pod, this_pod, other_in_ear, this_in_ear

    return ProximityReport(
        model_id=int.from_bytes(payload[3:5], "little"),
        left=left,
        right=right,
        case=_battery(power & 0x0F, charging & _CHARGING_CASE),
        left_in_ear=left_in_ear,
        right_in_ear=right_in_ear,
        lid_open=not lid & _LID_CLOSED if broadcaster_in_case else None,
        broadcaster=broadcaster,
        color=color,
    )


def _battery(nibble: int, charging: int) -> Battery:
    if nibble > _MAX_LEVEL_NIBBLE:
        return UNKNOWN_BATTERY
    return Battery(nibble * 10, bool(charging))
