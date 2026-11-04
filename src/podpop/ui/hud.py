"""Finds the HUD artwork the popup shows: a spin played once, then a still.

PodPop doesn't ship Apple's artwork. If you have some for personal use, put it
in ``%APPDATA%\\PodPop\\hud\\`` (or ``src/podpop/assets/hud/`` when running
from source; that folder is git-ignored), named after the model:

    airpodsPro_spin.webp    one full turn, played once when the card appears
    airpodsPro_still.png    shown for the rest of the card's life (optional:
                            without it the spin's last frame stays up)

Other models: ``airpods``, ``airpods3`` and ``airpodsMax`` in place of
``airpodsPro``. The spin must be an animated WebP or GIF with transparency:
Qt plays those, but shows only the first frame of an animated PNG, so convert
an APNG first. Without a spin, the popup turns PodPop's own 3D model once.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..catalog import Family
from ..settings import config_dir

_NAMES = {Family.PRO: "airpodsPro", Family.CLASSIC: "airpods", Family.OPEN: "airpods3", Family.HEADPHONES: "airpodsMax"}
_PACKAGED = Path(__file__).resolve().parent.parent / "assets" / "hud"


def spin_for(family: Family) -> Path | None:
    return _find(family, "_spin", (".webp", ".gif"))


def still_for(family: Family) -> Path | None:
    return _find(family, "_still", (".png", ".webp"))


def _find(family: Family, suffix: str, extensions: tuple[str, ...]) -> Path | None:
    name = _NAMES.get(family)
    # PODPOP_NO_CLIP=1: show what a fresh install shows (README screenshots use this).
    if name is None or os.environ.get("PODPOP_NO_CLIP"):
        return None
    for folder in (config_dir() / "hud", _PACKAGED):
        for ext in extensions:
            path = folder / f"{name}{suffix}{ext}"
            if path.is_file():
                return path
    return None
