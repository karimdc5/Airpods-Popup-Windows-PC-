"""PodPop's own 3D renders of the buds and case, one frame per angle of a turn.

The frames come from scripts/render_turntable.py, one sprite sheet per model
and part. The popup turns the buds once with them when there's no HUD spin,
and always draws the case from its front-on frame. Models without frames
(AirPods Max) keep the vector artwork.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtGui import QPixmap

from ..catalog import Family

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "turntable"
FRAMES = 96  # must match scripts/render_turntable.py
COLS = 12
TURN_S = 6.0  # one full turn, like iOS

_KEYS = {Family.PRO: "pro", Family.CLASSIC: "classic", Family.OPEN: "open"}
_cache: dict[tuple[str, str], list[QPixmap] | None] = {}


def frames(family: Family, kind: str) -> list[QPixmap] | None:
    """The turntable frames for ``kind`` ("buds" or "case"), or None if there are none."""
    key = _KEYS.get(family)
    if key is None:
        return None
    if (key, kind) not in _cache:
        sheet = QPixmap(str(ASSETS / f"{key}_{kind}.png"))
        if sheet.isNull():
            log.info("No turntable frames for %s %s; using the drawn artwork", key, kind)
            _cache[(key, kind)] = None
        else:
            rows = math.ceil(FRAMES / COLS)
            w, h = sheet.width() // COLS, sheet.height() // rows
            _cache[(key, kind)] = [sheet.copy((i % COLS) * w, (i // COLS) * h, w, h) for i in range(FRAMES)]
    return _cache[(key, kind)]


def available(family: Family) -> bool:
    return frames(family, "buds") is not None and frames(family, "case") is not None
