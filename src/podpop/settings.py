"""User settings, persisted as JSON in %APPDATA%\\PodPop."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)


def config_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME


def log_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME / "logs"


@dataclass(slots=True)
class Settings:
    popup_on_connect: bool = True
    popup_on_case_open: bool = True
    # Pull the AirPods over to this PC (e.g. from your iPhone) when the case opens.
    auto_connect_on_case_open: bool = True
    # Lock the PC while wearing them: free them for your phone; unlock: take them back.
    handoff_on_lock: bool = True
    # Reconnect by itself when you come back in range and the audio got stuck.
    auto_fix_audio: bool = True
    # Pause media when you take an AirPod out; resume when it goes back in.
    auto_pause_on_removal: bool = True
    # System-wide shortcuts; empty disables. Needs Ctrl, Alt or Win.
    hotkey_show_popup: str = "Ctrl+Alt+A"
    hotkey_connect: str = "Ctrl+Alt+C"  # connect, or fix stuck audio if already connected
    popup_duration_s: float = 7.0
    popup_follows_mouse: bool = False  # False: always on the primary monitor
    popup_intro_animation: bool = True  # case pulls back, opens, buds come out
    theme: str = "dark"  # "dark", "light" or "system" (follow Windows)
    low_battery_alerts: bool = True
    low_battery_thresholds: tuple[int, ...] = (20, 10)
    # Ignore adverts weaker than this (dBm); raise it if a neighbour's AirPods show up.
    min_rssi: int = -75
    # Bluetooth device names that count as "your AirPods" for connect events.
    device_name_pattern: str = r"AirPods|Beats|Powerbeats"

    @classmethod
    def load(cls, path: Path) -> Settings:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable settings %s: %s", path, exc)
            return cls()

        defaults = cls()
        values = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            default = getattr(defaults, f.name)
            value = raw[f.name]
            if isinstance(default, tuple) and isinstance(value, list):
                value = tuple(value)
            if type(value) is type(default) or (isinstance(default, float) and type(value) is int):
                values[f.name] = type(default)(value)
            else:
                log.warning("Ignoring setting %s=%r (expected %s)", f.name, value, type(default).__name__)
        return cls(**values)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
