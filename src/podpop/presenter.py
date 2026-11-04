"""Pure mapping from tracker state to what the popup and tray display."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Family, guess_from_name
from .runtime import format_time_left
from .protocol import Part
from .state import Component, Snapshot

LOW_LEVEL = 20  # iOS turns the battery yellow at this level...
CRITICAL_LEVEL = 10  # ...and red at this one

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
    time_left: str | None = None  # e.g. "About 3h 40m left"
    hud: str = "airpodsGen4"  # which HUD artwork to show

    @property
    def lowest_pod_level(self) -> int | None:
        levels = [i.level for i in self.items if i.part is not Part.CASE and i.level is not None]
        return min(levels, default=None)

    def summary(self) -> str:
        parts = [f"{i.label} {_pct(i.level)}{' ⚡' if i.charging else ''}" for i in self.items]
        text = f"{self.title}\n" + " · ".join(parts)
        return f"{text}\n{self.time_left}" if self.time_left else text


def build_view(
    snapshot: Snapshot, device_name: str | None, connected: bool, minutes_left: int | None = None
) -> DeviceView:
    model = snapshot.model or guess_from_name(device_name or "")
    title = clean_device_name(device_name) if device_name else model.name

    # Like iOS: the device's name on top, its model underneath.
    time_left = format_time_left(minutes_left) if connected else None
    subtitle = model.name if snapshot.has_fresh_data or connected else "Searching…"
    if time_left:
        subtitle = f"{subtitle} · {time_left}"

    if model.family is Family.HEADPHONES:
        pod = snapshot.left if snapshot.left.known else snapshot.right
        items = (_item(None, "Battery", pod),)
    else:
        items = (
            _item(Part.LEFT, "Left", snapshot.left),
            _item(Part.CASE, "Case", snapshot.case),
            _item(Part.RIGHT, "Right", snapshot.right),
        )
    return DeviceView(title, subtitle, model.family, items, time_left, model.hud)


def _item(part: Part | None, label: str, c: Component) -> ItemView:
    return ItemView(part, label, c.level, c.charging, c.in_ear, stale=c.known and not c.fresh)


def _pct(level: int | None) -> str:
    return "—" if level is None else f"{level}%"
