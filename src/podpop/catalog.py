"""Apple and Beats audio products that broadcast Proximity Pairing adverts.

0x2024 is confirmed on real hardware. The other IDs come from community
reverse-engineering (OpenPods, AirPodsDesktop, furiousMAC).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Family(Enum):
    """Product shape; picks the artwork and whether there is a case."""

    PRO = "pro"  # short stem, silicone tips, landscape case
    CLASSIC = "classic"  # long stem, portrait case
    OPEN = "open"  # short stem, no tips, rounded case (AirPods 3/4)
    HEADPHONES = "headphones"  # single battery, no case

    @property
    def has_case(self) -> bool:
        return self is not Family.HEADPHONES


@dataclass(frozen=True, slots=True)
class DeviceModel:
    model_id: int | None
    name: str
    family: Family


def _m(model_id: int, name: str, family: Family) -> tuple[int, DeviceModel]:
    return model_id, DeviceModel(model_id, name, family)


_MODELS: dict[int, DeviceModel] = dict(
    [
        _m(0x2002, "AirPods", Family.CLASSIC),
        _m(0x200F, "AirPods (2nd generation)", Family.CLASSIC),
        _m(0x2013, "AirPods (3rd generation)", Family.OPEN),
        _m(0x2019, "AirPods 4", Family.OPEN),
        _m(0x201B, "AirPods 4 (ANC)", Family.OPEN),
        _m(0x200E, "AirPods Pro", Family.PRO),
        _m(0x2014, "AirPods Pro 2", Family.PRO),
        _m(0x2024, "AirPods Pro 2 (USB-C)", Family.PRO),
        _m(0x200A, "AirPods Max", Family.HEADPHONES),
        _m(0x201F, "AirPods Max (USB-C)", Family.HEADPHONES),
        _m(0x200B, "Powerbeats Pro", Family.PRO),
        _m(0x2011, "Beats Studio Buds", Family.PRO),
        _m(0x2016, "Beats Studio Buds +", Family.PRO),
        _m(0x2012, "Beats Fit Pro", Family.PRO),
        _m(0x2003, "Powerbeats³", Family.HEADPHONES),
        _m(0x200D, "Powerbeats⁴", Family.HEADPHONES),
        _m(0x2005, "BeatsX", Family.HEADPHONES),
        _m(0x2010, "Beats Flex", Family.HEADPHONES),
        _m(0x2006, "Beats Solo³", Family.HEADPHONES),
        _m(0x200C, "Beats Solo Pro", Family.HEADPHONES),
        _m(0x2009, "Beats Studio³", Family.HEADPHONES),
    ]
)

GENERIC_AIRPODS = DeviceModel(None, "AirPods", Family.PRO)


def lookup(model_id: int) -> DeviceModel:
    return _MODELS.get(model_id) or DeviceModel(model_id, "AirPods", Family.PRO)


_NAME_HINTS: tuple[tuple[re.Pattern[str], Family], ...] = (
    (re.compile(r"\bmax\b|solo|studio\s*\d|beats\s*x|flex", re.I), Family.HEADPHONES),
    (re.compile(r"\bpro\b|buds|fit", re.I), Family.PRO),
    (re.compile(r"airpods\s*[34]\b", re.I), Family.OPEN),
)


def guess_from_name(name: str) -> DeviceModel:
    """Best-effort model from a Windows device name, used before any advert arrives."""
    for pattern, family in _NAME_HINTS:
        if pattern.search(name):
            return DeviceModel(None, "AirPods", family)
    return GENERIC_AIRPODS
