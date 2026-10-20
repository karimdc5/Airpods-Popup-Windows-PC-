"""Vector artwork of AirPods, cases and headphones, drawn with QPainter.

Everything is drawn in a fixed design box and scaled to the target rect,
so it stays crisp at any DPI and needs no image assets. Shapes are
parameterised by product family.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from ..catalog import Family
from .theme import Theme


class Led(Enum):
    OFF = ""
    GREEN = "#34D35A"
    AMBER = "#FFB020"


def case_led(level: int | None, charging: bool) -> Led:
    if level is None:
        return Led.OFF
    if charging:
        return Led.GREEN if level >= 100 else Led.AMBER
    return Led.GREEN if level >= 30 else Led.AMBER


@dataclass(frozen=True, slots=True)
class _BudShape:
    stem_length: float
    stem_width: float
    has_tip: bool
    mic_cap: bool


_BUDS = {
    Family.PRO: _BudShape(stem_length=78, stem_width=21, has_tip=True, mic_cap=True),
    Family.CLASSIC: _BudShape(stem_length=104, stem_width=19, has_tip=False, mic_cap=True),
    Family.OPEN: _BudShape(stem_length=74, stem_width=19, has_tip=False, mic_cap=False),
}

BUD_BOX = (100.0, 170.0)


@dataclass(frozen=True, slots=True)
class _CaseShape:
    box: tuple[float, float]
    body: QRectF
    radius: float
    seam_y: float
    led: QPointF


_CASES = {
    Family.PRO: _CaseShape((170, 132), QRectF(6, 6, 158, 116), 36, 42, QPointF(85, 84)),
    Family.CLASSIC: _CaseShape((124, 152), QRectF(10, 6, 104, 136), 30, 50, QPointF(62, 94)),
    Family.OPEN: _CaseShape((170, 132), QRectF(8, 8, 154, 112), 50, 44, QPointF(85, 86)),
}

HEADPHONES_BOX = (180.0, 172.0)


def paint_bud(p: QPainter, rect: QRectF, family: Family, left: bool, theme: Theme) -> None:
    shape = _BUDS.get(family, _BUDS[Family.PRO])
    p.save()
    _fit(p, rect, *BUD_BOX)
    if not left:
        p.translate(BUD_BOX[0], 0)
        p.scale(-1, 1)
    outline = _outline(theme)

    stem_bottom = 58 + shape.stem_length
    _ground_shadow(p, QPointF(34, stem_bottom + 6), 22, 4, theme)

    # Stem, tilted so the bottom leans outward.
    p.save()
    p.translate(44, 58)
    p.rotate(8)
    stem = QRectF(-shape.stem_width / 2, -10, shape.stem_width, shape.stem_length + 10)
    stem_path = QPainterPath()
    stem_path.addRoundedRect(stem, shape.stem_width / 2, shape.stem_width / 2)
    p.setPen(outline)
    p.setBrush(_vertical(stem, theme.art_light, theme.art_dark))
    p.drawPath(stem_path)
    if shape.mic_cap:
        p.save()
        p.setClipPath(stem_path)
        cap = QRectF(stem.left(), stem.bottom() - 11, stem.width(), 11)
        p.fillRect(cap, _vertical(cap, QColor("#C9CBD1"), QColor("#9EA1A8")))
        p.restore()
    p.restore()

    # Silicone ear tip, tucked behind the head.
    if shape.has_tip:
        p.save()
        p.translate(76, 40)
        p.rotate(-28)
        tip = QRectF(-17, -22, 34, 44)
        p.setPen(outline)
        p.setBrush(_vertical(tip, theme.art_tip.lighter(110), theme.art_tip.darker(112)))
        p.drawEllipse(tip)
        p.restore()

    # Head.
    head = QRectF(18, 14, 66, 62) if shape.has_tip else QRectF(18, 10, 66, 66)
    gradient = QLinearGradient(head.topLeft(), head.bottomRight())
    gradient.setColorAt(0, theme.art_light)
    gradient.setColorAt(1, theme.art_dark)
    p.setPen(outline)
    p.setBrush(QBrush(gradient))
    p.drawEllipse(head)

    detail = QColor(theme.art_detail)
    p.setPen(Qt.PenStyle.NoPen)
    if not shape.has_tip:  # speaker grille facing the ear
        detail.setAlpha(170)
        p.setBrush(detail)
        p.drawEllipse(QRectF(68, 28, 13, 22))
    detail.setAlpha(210)
    p.setBrush(detail)  # outward mic mesh
    p.save()
    p.translate(38, 30)
    p.rotate(-14)
    p.drawRoundedRect(QRectF(-8, -3, 16, 6), 3, 3)
    p.restore()

    _gloss(p, head, theme)
    p.restore()


def paint_case(
    p: QPainter, rect: QRectF, family: Family, led: Led, theme: Theme, lid_open: float = 0.0
) -> None:
    """Draw the case; ``lid_open`` 0..1 swings the lid up to reveal the inside."""
    shape = _CASES.get(family, _CASES[Family.PRO])
    p.save()
    _fit(p, rect, *shape.box)
    body = shape.body
    _ground_shadow(p, QPointF(body.center().x(), body.bottom() + 4), body.width() * 0.44, 6, theme)

    path = QPainterPath()
    path.addRoundedRect(body, shape.radius, shape.radius)
    lid_rect = QRectF(body.left(), body.top(), body.width(), shape.seam_y - body.top())
    base_rect = QRectF(body.left(), shape.seam_y, body.width(), body.bottom() - shape.seam_y)
    outline = _outline(theme)
    lid_open = max(0.0, min(1.0, lid_open))

    if lid_open <= 0.0:
        p.setPen(outline)
        p.setBrush(_vertical(body, theme.art_light, theme.art_dark))
        p.drawPath(path)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        seam = QPen(QColor(theme.art_outline.red(), theme.art_outline.green(), theme.art_outline.blue(), 55))
        seam.setCosmetic(True)
        seam.setWidthF(1.2)
        p.setPen(seam)
        p.drawLine(QPointF(body.left(), shape.seam_y), QPointF(body.right(), shape.seam_y))
        p.fillRect(lid_rect, _vertical(lid_rect, QColor(255, 255, 255, 150), QColor(255, 255, 255, 0)))
        p.restore()
    else:
        # Base: the body below the seam.
        base = QPainterPath()
        base.addRect(base_rect)
        base = path.intersected(base)
        p.setPen(outline)
        p.setBrush(_vertical(body, theme.art_light, theme.art_dark))
        p.drawPath(base)

        # Lid hinges at the back: its front edge lifts, exposing the inside back
        # wall between the lid and the rim.
        lift = 26.0 * lid_open
        back_wall = QRectF(body.left() + 10, shape.seam_y - lift, body.width() - 20, lift + 2)
        wall = QLinearGradient(back_wall.topLeft(), back_wall.bottomLeft())
        wall.setColorAt(0, QColor("#48484A"))
        wall.setColorAt(1, QColor("#1C1C1E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(wall))
        p.drawRect(back_wall)

        # The opening, seen slightly from above: a light rim around a dark well.
        well = _well_rect(shape, lid_open)
        p.setPen(outline)
        p.setBrush(theme.art_light)
        p.drawEllipse(well.adjusted(-3, -2, 3, 2))
        interior = QLinearGradient(well.topLeft(), well.bottomLeft())
        interior.setColorAt(0, QColor("#2C2C2E"))
        interior.setColorAt(1, QColor("#5A5A5E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(interior))
        p.drawEllipse(well)

        # Lid: swings up and back on its hinge, so from the front it rises and
        # foreshortens, showing its paler underside.
        lid = QPainterPath()
        lid.addRect(lid_rect)
        lid = path.intersected(lid)
        squash = 1.0 - 0.45 * lid_open  # tilting back foreshortens it
        p.save()
        p.translate(0, shape.seam_y - lift)
        p.scale(1.0, squash)
        p.translate(0, -shape.seam_y)
        p.setPen(outline)
        # Its underside comes into view: shade toward a soft grey so white buds read against it.
        underside = _mix(theme.art_dark, QColor("#9C9CA3"), lid_open)
        p.setBrush(_vertical(lid_rect, _mix(theme.art_light, underside, lid_open), underside))
        p.drawPath(lid)
        lining = QColor(theme.art_detail)
        lining.setAlpha(round(140 * lid_open))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lining)
        p.drawEllipse(QRectF(well.left(), shape.seam_y - 6, well.width(), 10))
        p.restore()

    if led is not Led.OFF:
        color = QColor(led.value)
        glow = QRadialGradient(shape.led, 11)
        color.setAlpha(110)
        glow.setColorAt(0, color)
        color.setAlpha(0)
        glow.setColorAt(1, color)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(shape.led, 11, 11)
        p.setBrush(QColor(led.value))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
    p.drawEllipse(shape.led, 3.4, 3.4)
    p.restore()


def case_well(rect: QRectF, family: Family) -> QRectF:
    """Where the opening of a fully open case is, in the coordinates of ``rect``."""
    shape = _CASES.get(family, _CASES[Family.PRO])
    scale, dx, dy = _fit_params(rect, *shape.box)
    well = _well_rect(shape, 1.0)
    return QRectF(dx + well.left() * scale, dy + well.top() * scale, well.width() * scale, well.height() * scale)


def case_body(rect: QRectF, family: Family) -> QRectF:
    """The case body (without shadow) in the coordinates of ``rect``."""
    shape = _CASES.get(family, _CASES[Family.PRO])
    scale, dx, dy = _fit_params(rect, *shape.box)
    b = shape.body
    return QRectF(dx + b.left() * scale, dy + b.top() * scale, b.width() * scale, b.height() * scale)


def _well_rect(shape: _CaseShape, lid_open: float) -> QRectF:
    body = shape.body
    half = 9.0 * lid_open
    return QRectF(body.left() + 10, shape.seam_y - half, body.width() - 20, 2 * half)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def paint_headphones(p: QPainter, rect: QRectF, theme: Theme) -> None:
    p.save()
    _fit(p, rect, *HEADPHONES_BOX)
    outline = _outline(theme)
    _ground_shadow(p, QPointF(90, 166), 74, 5, theme)

    band = QPainterPath(QPointF(34, 92))
    band.cubicTo(QPointF(34, 4), QPointF(146, 4), QPointF(146, 92))
    for width, color in ((15, theme.art_outline), (13, theme.art_tip), (7, theme.art_dark)):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(band)

    for x, cushion_x in ((12, 49), (118, 119)):
        cup = QRectF(x, 80, 50, 82)
        p.setPen(outline)
        p.setBrush(_vertical(cup, theme.art_light, theme.art_dark))
        p.drawRoundedRect(cup, 22, 22)
        _gloss(p, cup, theme)
        cushion = QColor(theme.art_detail)
        cushion.setAlpha(225)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cushion)
        p.drawRoundedRect(QRectF(cushion_x, 90, 12, 62), 6, 6)
    p.restore()


def _fit_params(rect: QRectF, width: float, height: float) -> tuple[float, float, float]:
    scale = min(rect.width() / width, rect.height() / height)
    return scale, rect.center().x() - width * scale / 2, rect.center().y() - height * scale / 2


def _fit(p: QPainter, rect: QRectF, width: float, height: float) -> None:
    scale, dx, dy = _fit_params(rect, width, height)
    p.translate(dx, dy)
    p.scale(scale, scale)


def _outline(theme: Theme) -> QPen:
    pen = QPen(theme.art_outline)
    pen.setCosmetic(True)
    pen.setWidthF(1.0)
    return pen


def _vertical(rect: QRectF, top: QColor, bottom: QColor) -> QBrush:
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0, top)
    gradient.setColorAt(1, bottom)
    return QBrush(gradient)


def _gloss(p: QPainter, shape: QRectF, theme: Theme) -> None:
    center = QPointF(shape.left() + shape.width() * 0.35, shape.top() + shape.height() * 0.28)
    gloss = QRadialGradient(center, shape.width() * 0.4)
    gloss.setColorAt(0, QColor(255, 255, 255, 190))
    gloss.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(gloss))
    p.drawEllipse(shape.adjusted(2, 2, -2, -2))


def _ground_shadow(p: QPainter, center: QPointF, rx: float, ry: float, theme: Theme) -> None:
    shadow = QRadialGradient(center, rx)
    shadow.setColorAt(0, QColor(0, 0, 0, 90 if theme.dark else 55))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    p.save()
    p.translate(center)
    p.scale(1, ry / rx)
    p.translate(-center)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(shadow))
    p.drawEllipse(center, rx, rx)
    p.restore()
