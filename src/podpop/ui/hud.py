"""Finds the HUD clip the popup plays: a short loop of the AirPods turning.

PodPop doesn't ship Apple's clips. If you have one for personal use, put it in
``%APPDATA%\\PodPop\\hud\\`` (or ``src/podpop/assets/hud/`` when running from
source; that folder is git-ignored) named after the model:

    airpodsPro.mov / .mp4     AirPods Pro
    airpods.mov / .mp4        AirPods (1st/2nd generation)
    airpods3.mov / .mp4       AirPods 3 and 4
    airpodsMax.mov / .mp4     AirPods Max

Clips on a black background are blended in "screen" mode, so the black
disappears into the dark card; clips with transparency are drawn as they are.
Without a clip, the popup plays PodPop's own 3D turntable instead.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..catalog import Family
from ..settings import config_dir

_NAMES = {Family.PRO: "airpodsPro", Family.CLASSIC: "airpods", Family.OPEN: "airpods3", Family.HEADPHONES: "airpodsMax"}
_PACKAGED = Path(__file__).resolve().parent.parent / "assets" / "hud"


def clip_for(family: Family) -> Path | None:
    name = _NAMES.get(family)
    # PODPOP_NO_CLIP=1: show what a fresh install shows (README screenshots use this).
    if name is None or os.environ.get("PODPOP_NO_CLIP"):
        return None
    for folder in (config_dir() / "hud", _PACKAGED):
        for ext in (".mov", ".mp4", ".m4v", ".webm"):
            path = folder / f"{name}{ext}"
            if path.is_file():
                return path
    return None
