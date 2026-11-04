"""Plays the pre-rendered 3D turntable: the buds and the case slowly spinning.

Like the iPhone popup, the pair of buds and the case each turn a full circle
every few seconds while the card is up. The frames are PodPop's own renders
(scripts/render_turntable.py), one sprite sheet per model and part, loaded
once and cross-faded between neighbouring angles so the motion stays smooth.
Models without frames (AirPods Max) keep the vector artwork.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ..catalog import Family
from ..protocol import Part

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "turntable"
FRAMES = 96  # must match scripts/render_turntable.py
COLS = 12
TURN_S = 6.0  # one full turn, like iOS
TICK_MS = 33
FADE_IN_S = 0.35

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


class TurntableOverlay(QWidget):
    """Draws the spinning buds over the two bud tiles and the case over its tile."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._tiles: list = []
        self._family: Family | None = None
        self._start = time.monotonic()
        self._timer = QTimer(self, interval=TICK_MS)
        self._timer.timeout.connect(self.update)
        self.hide()

    def set_tiles(self, family: Family, tiles: list) -> None:
        self._family, self._tiles = family, tiles
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    def clear(self) -> None:
        self._tiles = []
        self.stop()
        self.hide()

    def play(self) -> None:
        """Start from the front view, fading in."""
        self._start = time.monotonic()
        self.setGeometry(self.parentWidget().rect())
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, _event) -> None:
        if not self._tiles or self._family is None:
            return
        tiles = {t.part: t for t in self._tiles}
        elapsed = time.monotonic() - self._start
        position = (elapsed / TURN_S % 1.0) * FRAMES
        fade = min(1.0, elapsed / FADE_IN_S) if self._timer.isActive() else 1.0

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, case = tiles.get(Part.LEFT), tiles.get(Part.RIGHT), tiles.get(Part.CASE)
        if left is not None and right is not None:
            area = self._art_area(left).united(self._art_area(right))
            self._draw(p, frames(self._family, "buds"), area, position, fade * _dim(left, right))
        if case is not None:
            self._draw(p, frames(self._family, "case"), self._art_area(case), position, fade * _dim(case))
        p.end()

    def _art_area(self, tile) -> QRectF:
        rect = tile.turntable_rect()
        top_left = QPointF(tile.mapTo(self.parentWidget(), rect.topLeft().toPoint()))
        return QRectF(top_left, rect.size())

    @staticmethod
    def _draw(p: QPainter, sprites: list[QPixmap] | None, area: QRectF, position: float, opacity: float) -> None:
        if not sprites:
            return
        frame = sprites[0]
        ratio = min(area.width() / frame.width(), area.height() / frame.height())
        w, h = frame.width() * ratio, frame.height() * ratio
        target = QRectF(area.center().x() - w / 2, area.bottom() - h, w, h)
        i = int(position) % FRAMES
        blend = position - int(position)
        p.setOpacity(opacity)
        p.drawPixmap(target, sprites[i], QRectF(sprites[i].rect()))
        if blend > 0.02:  # cross-fade into the next angle
            p.setOpacity(opacity * blend)
            nxt = sprites[(i + 1) % FRAMES]
            p.drawPixmap(target, nxt, QRectF(nxt.rect()))


def _dim(*tiles) -> float:
    return max(t.art_opacity() for t in tiles)
