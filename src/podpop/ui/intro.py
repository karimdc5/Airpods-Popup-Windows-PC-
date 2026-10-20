"""Apple-style intro: a close-up of the case pulls back, it opens, the buds come out.

Drawn on a transparent overlay above the card while the tiles hide their own
artwork. The last frame matches the tiles exactly, so the hand-off is
invisible. Timeline (fractions of INTRO_MS):

    0.00-0.40  starts as a close-up of the case (cropped by the card) and the
               camera pulls back and up to frame it
    0.22-0.42  lid swings open while the camera settles
    0.40-0.60  buds rise up out of the case
    0.56-0.88  buds glide out to the left and right tiles; case shrinks into place
    0.82-0.98  lid closes
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..catalog import Family
from ..protocol import Part
from .artwork import case_well, paint_bud
from .theme import Theme

INTRO_MS = 1800

_EASE_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)
_EASE_IN_OUT = QEasingCurve(QEasingCurve.Type.InOutCubic)


def _seg(t: float, start: float, end: float) -> float:
    return min(1.0, max(0.0, (t - start) / (end - start)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _scaled(rect: QRectF, scale: float, center: QPointF) -> QRectF:
    w, h = rect.width() * scale, rect.height() * scale
    return QRectF(center.x() - w / 2, center.y() - h / 2, w, h)


def _lerp_rect(a: QRectF, b: QRectF, t: float) -> QRectF:
    return QRectF(
        _lerp(a.x(), b.x(), t), _lerp(a.y(), b.y(), t), _lerp(a.width(), b.width(), t), _lerp(a.height(), b.height(), t)
    )


class IntroOverlay(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self._tiles: list = []
        self._theme: Theme | None = None
        self._stage = QRectF()
        self._t = 0.0
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=INTRO_MS)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._finish)

    @property
    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def play(self, tiles: list, theme: Theme, stage: QRectF) -> None:
        """``stage``: the area (in the parent's coordinates) the camera shot is framed in."""
        self._tiles, self._theme, self._stage = tiles, theme, stage
        for tile in tiles:
            tile.art_visible = False
            tile.update()
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._t = 0.0
        self._anim.stop()
        self._anim.start()

    def stop(self) -> None:
        """End immediately, handing the artwork back to the tiles."""
        if self.running:
            self._anim.stop()
        self._finish()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def _on_value(self, value: float) -> None:
        self._t = float(value)
        self.update()

    def _finish(self) -> None:
        self.hide()
        for tile in self._tiles:
            tile.art_visible = True
            tile.update()
        self._tiles = []
        self.finished.emit()

    # ------------------------------------------------------------ drawing

    def _target(self, tile) -> QRectF:
        rect = tile.art_rect()
        top_left = QPointF(tile.mapTo(self.parentWidget(), rect.topLeft().toPoint()))
        return QRectF(top_left, rect.size())

    def paintEvent(self, _event) -> None:
        if not self._tiles or self._theme is None:
            return
        from .popup import paint_item_art  # popup imports this module

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t, theme = self._t, self._theme
        fade = _EASE_OUT.valueForProgress(_seg(t, 0.0, 0.10))
        tiles = {tile.part: tile for tile in self._tiles if tile.item is not None}
        family = self._tiles[0].family

        if family is Family.HEADPHONES or Part.CASE not in tiles:
            for tile in tiles.values():
                target = self._target(tile)
                scale = _lerp(1.35, 1.0, _EASE_OUT.valueForProgress(_seg(t, 0.0, 0.6)))
                p.setOpacity(fade * tile.art_opacity())
                paint_item_art(p, _scaled(target, scale, target.center()), family, tile.item, theme)
            p.end()
            return

        case_tile = tiles[Part.CASE]
        case_target = self._target(case_tile)
        pull_back = _EASE_IN_OUT.valueForProgress(_seg(t, 0.0, 0.40))
        lid = _EASE_IN_OUT.valueForProgress(_seg(t, 0.22, 0.42)) * (1 - _EASE_IN_OUT.valueForProgress(_seg(t, 0.82, 0.98)))
        rise = _EASE_OUT.valueForProgress(_seg(t, 0.40, 0.60))
        fly = _EASE_IN_OUT.valueForProgress(_seg(t, 0.56, 0.88))

        # Frame the shot: everything stays inside a rounded stage below the header.
        frame = QPainterPath()
        frame.addRoundedRect(self._stage, 20, 20)
        p.setClipPath(frame)
        # During the close-up the stage is the whole picture; the battery rings
        # beneath fade in as the camera pulls back.
        cover = 1.0 - _seg(t, 0.30, 0.46)
        if cover > 0:
            backdrop = theme.card
            p.setOpacity(cover)
            p.fillPath(frame, backdrop)
        # Camera: close on the case's front (LED side) at first, pulling back
        # and up until the whole case sits in the middle of the card.
        framed = QPointF(case_target.center().x(), case_target.center().y() - 2)
        close_up = QPointF(framed.x(), framed.y() - case_target.height() * 0.55)
        stage_center = QPointF(framed.x(), _lerp(close_up.y(), framed.y(), pull_back))
        case_scale = _lerp(_lerp(3.2, 1.22, pull_back), 1.0, fly)
        center = QPointF(_lerp(stage_center.x(), case_target.center().x(), fly), _lerp(stage_center.y(), case_target.center().y(), fly))
        case_rect = _scaled(case_target, case_scale, center)

        p.setOpacity(fade * case_tile.art_opacity())
        paint_item_art(p, case_rect, family, case_tile.item, theme, lid_open=lid)

        if rise <= 0.0:
            p.end()
            return
        well = case_well(case_rect, family)
        for part, side in ((Part.LEFT, -1), (Part.RIGHT, 1)):
            tile = tiles.get(part)
            if tile is None:
                continue
            target = self._target(tile)
            # Start: upright in the opening, sunk to the rim; rises until its
            # stem tip clears the rim, then glides to its tile.
            size = target.height() * _lerp(0.5, 0.62, rise) * case_scale / 1.22
            start_w = target.width() / target.height() * size
            sunk = _lerp(size * 0.8, -size * 0.12, rise)
            start = QRectF(
                well.center().x() + side * well.width() * 0.2 - start_w / 2,
                well.center().y() - size + sunk,
                start_w,
                size,
            )
            rect = _lerp_rect(start, target, fly)
            rect.translate(0, -math.sin(math.pi * fly) * 10)  # a gentle arc

            p.save()
            if fly < 0.2:
                # Hide the part still inside the case.
                clip = QRectF(0, 0, self.width(), well.center().y() + fly * 300)
                p.setClipRect(clip, Qt.ClipOperation.IntersectClip)
            p.setOpacity(fade * _lerp(1.0, tile.art_opacity(), fly))
            paint_bud(p, rect, family, part is Part.LEFT, theme)
            p.restore()
        p.end()
