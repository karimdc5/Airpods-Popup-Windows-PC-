"""Pure mapping from tracker state to what the popup and tray display."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Family, guess_from_name
from .protocol import Part
from .state import Component, Snapshot

LOW_LEVEL = 20  # iOS turns the battery ring red at this level

_NAME_SUFFIX = re.compile(r"\s+-\s+(Find My|Hands-Free.*|Stereo|Avrcp Transport)$", re.I)


def clean_device_name(name: str) -> str:
    """'karim’s AirPods Pro #2 - Find My' -> 'karim’s AirPods Pro #2'."""
    return _NAME_SUFFIX.sub("", name).strip()


@dataclass(frozen=True, slots=True)
class ItemView:
    part: Part | None  # None for single-battery devices (headphones)
    label: str
    level: int | None
    charging: bool = False
    in_ear: bool = False
    stale: bool = False


@dataclass(frozen=True, slots=True)
class DeviceView:
    title: str
    subtitle: str
    family: Family
    items: tuple[ItemView, ...]

    @property
    def lowest_pod_level(self) -> int | None:
        levels = [i.level for i in self.items if i.part is not Part.CASE and i.level is not None]
        return min(levels, default=None)

    def summary(self) -> str:
        parts = [f"{i.label} {_pct(i.level)}{' ⚡' if i.charging else ''}" for i in self.items]
        return f"{self.title}\n" + " · ".join(parts)


def build_view(snapshot: Snapshot, device_name: str | None, connected: bool) -> DeviceView:
    model = snapshot.model or guess_from_name(device_name or "")
    title = clean_device_name(device_name) if device_name else model.name

    status = "Connected" if connected else ("Nearby" if snapshot.has_fresh_data else "Searching…")
    subtitle = f"{model.name} · {status}" if model.name != title else status

    if model.family is Family.HEADPHONES:
        pod = snapshot.left if snapshot.left.known else snapshot.right
        items = (_item(None, "Battery", pod),)
    else:
        items = (
            _item(Part.LEFT, "Left", snapshot.left),
            _item(Part.CASE, "Case", snapshot.case),
            _item(Part.RIGHT, "Right", snapshot.right),
        )
    return DeviceView(title, subtitle, model.family, items)


def _item(part: Part | None, label: str, c: Component) -> ItemView:
    return ItemView(part, label, c.level, c.charging, c.in_ear, stale=c.known and not c.fresh)


def _pct(level: int | None) -> str:
    return "—" if level is None else f"{level}%"
