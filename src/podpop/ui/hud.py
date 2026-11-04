"""Finds the HUD artwork the popup shows: a spin played once, then a still.

PodPop doesn't ship Apple's artwork. If you have some for personal use, put it
in ``%APPDATA%\\PodPop\\hud\\`` (or ``src/podpop/assets/hud/`` when running
from source; that folder is git-ignored), named after the model:

    airpodsPro_spin.webp    one full turn, played once when the card appears
    airpodsPro_still.png    shown for the rest of the card's life (optional:
                            without it the spin's last frame stays up)
    airpodsPro_case.png     the case beside the buds, used only for models
                            without PodPop's own 3D case render

The name comes from the model (catalog.DeviceModel.hud): ``airpods``,
``airpodsGen3``, ``airpodsGen4``, ``airpodsPro``, ``airpodsPro3``,
``airpodsMax``, ``beatssolo``, ``beatsstudio``; unknown models use
``airpodsGen4``. The spin must be an animated WebP or GIF with transparency:
Qt plays those, but shows only the first frame of an animated PNG, so
``scripts/import_hud.py`` converts a folder of ``*_spin.png`` APNGs for you.
Without a spin, the popup turns PodPop's own 3D model once.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..settings import config_dir

_PACKAGED = Path(__file__).resolve().parent.parent / "assets" / "hud"


def hud_dir() -> Path:
    return config_dir() / "hud"


def spin_for(name: str) -> Path | None:
    return _find(name, "_spin", (".webp", ".gif"))


def still_for(name: str) -> Path | None:
    return _find(name, "_still", (".png", ".webp"))


def case_for(name: str) -> Path | None:
    """Picture of the case for models without PodPop's 3D case render (the render wins)."""
    return _find(name, "_case", (".png", ".webp"))


def _find(name: str, suffix: str, extensions: tuple[str, ...]) -> Path | None:
    # PODPOP_NO_CLIP=1: show what a fresh install shows (README screenshots use this).
    if os.environ.get("PODPOP_NO_CLIP"):
        return None
    for folder in (hud_dir(), _PACKAGED):
        for ext in extensions:
            path = folder / f"{name}{suffix}{ext}"
            if path.is_file():
                return path
    return None
