"""The battery HUD: a frosted dark card near the top of the screen.

Top to bottom: the device name; the AirPods on the left (they turn once as
the card appears, then stay still) and the case on the right, like the iPhone
popup; under each, centred, its battery (a horizontal battery with the bolt
inside while charging, the percentage below; buds far apart get one each);
and the connection status. It sits just above the taskbar, fades in while rising 8 px, stays a
few seconds, and fades out the same way. There are no buttons; clicking the card connects the AirPods
when they're not connected, and otherwise just closes it.

Measurements follow the iOS HUD: 280 px wide, 26 px continuous corners,
rgba(28,28,30,.74) over the blurred, saturated desktop, a 1 px inner
hairline, and a soft 40 px shadow.
"""

from __future__ import annotations

import bisect
import ctypes
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from ..catalog import Family
from ..presenter import CRITICAL_LEVEL, LOW_LEVEL, DeviceView, ItemView
from ..protocol import Part
from . import hud, turntable
from .artwork import paint_headphones
from .theme import DARK, Theme

CARD_W = 280
CARD_RADIUS = 26.0
PADDING = (16, 20, 16, 18)  # left, top, right, bottom
TITLE_PX = 17
CLIP = 130  # the artwork's native size: drawn 1:1, never rescaled
CLIP_MARGIN = (4, 10)  # above; below, to the battery row
BOLT_PX = 9.0
BATTERY_W, BATTERY_H, BATTERY_R = 25.0, 12.0, 3.5
PERCENT_PX = 13
GROUP_W = 52
BUD_GROUP_GAP = 14  # between the L and R batteries when the buds are split
CASE_W = 104  # the case's column, right of the 130 px buds
ART_GAP = 14
SPLIT_AT = 10  # buds further apart than this (in %) get a battery each, like iOS
STATUS_PX = 12
STATUS_GAP = 12

SCREEN_GAP = 18  # between the card and the bottom of the work area
SHADOW_MARGIN = 40
ENTER_RISE = 8
FADE_MS = 180
# The card never leaves mid-spin: it waits for the turn to finish, then shows
# the still at least this long (and never less than the usual duration).
STILL_HOLD_MS = 1500
BLUR_DOWNSCALE = 24  # shrink, then smooth back up: a wide (~28 px) blur
SATURATION = 1.8

FONTS = ["SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Arial"]

BACKGROUND = QColor(28, 28, 30, 189)  # .74
SOLID = QColor(28, 28, 30)  # when there is no desktop snapshot (older Windows, demos)
HAIRLINE = QColor(255, 255, 255, 20)  # .08
SHADOW = QColor(0, 0, 0, 115)  # .45
TITLE = QColor(255, 255, 255, 250)  # .98
TRACK = QColor(255, 255, 255, 41)  # .16
OUTLINE = QColor(255, 255, 255, 110)
PERCENT = QColor(255, 255, 255, 230)  # .9
BOLT = QColor(255, 255, 255, 230)  # .9, white and monochrome
STATUS = QColor(255, 255, 255, 140)  # .55
GLYPH_COLOR = QColor(255, 255, 255, 140)  # .55
OK, WARN, LOW = QColor("#30D158"), QColor("#FFD60A"), QColor("#FF453A")



class Action(Enum):
    """What the link is doing; shown as the status line."""

    HIDDEN = "Connected"  # connected (or nothing to connect)
    CONNECT = "Not connected"
    CONNECTING = "Connectingâ€¦"
    FAILED = "Couldnâ€™t connect"


def battery_color(level: int | None, charging: bool) -> QColor:
    """Green while charging whatever the level; otherwise green above 20%, yellow at 11-20%, red at 10% and below."""
    if level is None or charging or level > LOW_LEVEL:
        return OK
    return LOW if level <= CRITICAL_LEVEL else WARN


@dataclass(frozen=True, slots=True)
class BatteryGroup:
    """One battery shown on the card: "pair", "left", "right", "case" or "headphones"."""

    kind: str
    level: int | None
    charging: bool


def battery_groups(view: DeviceView) -> list[BatteryGroup]:
    """Like iOS: one battery for the AirPods and one for the case.

    The buds share a battery (the lower of the two) while their levels are
    within ``SPLIT_AT``; further apart, each gets its own. The pair counts as
    charging only if every bud with a reading is charging, and the case's
    charging never makes the buds look charged.
    """
    parts = {i.part: i for i in view.items}
    if view.family is Family.HEADPHONES or None in parts:
        item = next(iter(view.items))
        return [BatteryGroup("headphones", item.level, is_charging(item))]
    buds = [parts[p] for p in (Part.LEFT, Part.RIGHT) if p in parts]
    known = [b for b in buds if b.level is not None]
    groups: list[BatteryGroup] = []
    if len(known) == 2 and abs(known[0].level - known[1].level) > SPLIT_AT:
        groups += [BatteryGroup(b.part.value, b.level, is_charging(b)) for b in known]
    else:
        level = min((b.level for b in known), default=None)
        groups.append(BatteryGroup("pair", level, bool(known) and all(is_charging(b) for b in known)))
    case = parts.get(Part.CASE)
    if case is not None:
        groups.append(BatteryGroup("case", case.level, is_charging(case)))
    return groups


def is_charging(item: ItemView) -> bool:
    """Per column: a bud only charges in the case, never in an ear, whatever the case is doing."""
    if item.level is None:
        return False
    return item.charging and not (item.part in (Part.LEFT, Part.RIGHT) and item.in_ear)


def _font(px: float, weight: QFont.Weight, tracking: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(FONTS)
    f.setPixelSize(round(px))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return f


def squircle(rect: QRectF, radius: float) -> QPainterPath:
    """A rounded rect with continuous (superellipse) corners, like iOS, not circular arcs."""
    reach = min(radius * 1.528, rect.width() / 2, rect.height() / 2)  # how far each corner's curve runs
    n = 4.6  # superellipse exponent; 2 would be a quarter circle
    steps = 16
    # Corner centres, clockwise from top-right, with the direction of their outer edges.
    corners = (
        (rect.right() - reach, rect.top() + reach, 1, -1),
        (rect.right() - reach, rect.bottom() - reach, 1, 1),
        (rect.left() + reach, rect.bottom() - reach, -1, 1),
        (rect.left() + reach, rect.top() + reach, -1, -1),
    )
    path = QPainterPath()
    for k, (cx, cy, sx, sy) in enumerate(corners):
        for i in range(steps + 1):
            t = (i / steps) * math.pi / 2
            a, b = (math.sin(t), math.cos(t)) if k % 2 == 0 else (math.cos(t), math.sin(t))
            x = cx + sx * reach * a ** (2 / n)
            y = cy + sy * reach * b ** (2 / n)
            if k == 0 and i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    return path


class _Spin:
    """The AirPods artwork: one turn when the card appears, then motionless.

    The spin (animated WebP/GIF) is decoded once by Qt's image reader, the
    same decoder QMovie uses, and played on a precise timer: QMovie schedules
    frames with Windows' 15.6 ms coarse timer, which stretched a 33 ms frame
    to ~47 ms and a 6 s turn to almost 9 s. On the last frame it stops and the
    still takes over (or the last frame stays, if there's no still). It never
    loops.
    """

    def __init__(self, on_change: Callable[[], None], on_done: Callable[[], None]) -> None:
        self._on_change = on_change
        self._on_done = on_done
        self.frames: list[QPixmap] = []
        self._ends: list[float] = []  # when each frame ends, in seconds from the start
        self.still: QPixmap | None = None
        self.done = True
        self._index = 0
        self._started = 0.0
        self._key = None
        self._timer = QTimer(interval=8, timerType=Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)

    def load(self, spin, still) -> None:
        if (spin, still) == self._key:
            return
        self._key = (spin, still)
        self._timer.stop()
        self.frames, self._ends, self.done = [], [], True
        if spin is not None:
            reader = QImageReader(str(spin))
            elapsed = 0.0
            while True:
                image = reader.read()
                if image.isNull():
                    break
                self.frames.append(QPixmap.fromImage(image))
                elapsed += max(reader.nextImageDelay(), 1) / 1000.0
                self._ends.append(elapsed)
        self.still = QPixmap(str(still)) if still is not None else None
        if self.still is not None and self.still.isNull():
            self.still = None

    @property
    def available(self) -> bool:
        return bool(self.frames) or self.still is not None

    def play(self) -> None:
        self._index = 0
        if not self.frames:
            self.done = True
            return
        self.done = False
        self._started = time.monotonic()
        self._timer.start()

    def hold(self) -> None:
        """Skip the spin: show the final pose right away."""
        self._timer.stop()
        self.done = True
        self._index = max(0, len(self.frames) - 1)

    def pixmap(self) -> QPixmap | None:
        if self.done and self.still is not None:
            return self.still
        if self.frames:
            return self.frames[self._index]
        return None

    def _advance(self) -> None:
        elapsed = time.monotonic() - self._started
        index = bisect.bisect_right(self._ends, elapsed)
        if index >= len(self.frames):
            self._timer.stop()  # one turn, never a loop
            self.done = True
            self._index = len(self.frames) - 1
            self._on_change()
            self._on_done()
            return
        if index != self._index:
            self._index = index
            self._on_change()


class _Card(QWidget):
    clicked = Signal()
    spin_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(CARD_W, self.content_height())
        self.view: DeviceView | None = None
        self.status = Action.HIDDEN.value
        self.backdrop: QPixmap | None = None
        self.animate = True
        self._started = time.monotonic()
        self._spin = _Spin(self.update, self.spin_finished.emit)
        self._case_art: QPixmap | None = None
        self._tick = QTimer(self, interval=33)  # drives the fallback model's single turn
        self._tick.timeout.connect(self._fallback_tick)

    @staticmethod
    def content_height() -> int:
        return round(PADDING[1] + TITLE_PX + 5 + CLIP_MARGIN[0] + CLIP + CLIP_MARGIN[1] + _battery_row_h()
                     + STATUS_GAP + STATUS_PX + 3 + PADDING[3])

    def set_view(self, view: DeviceView) -> None:
        if self.view is None or self.view.hud != view.hud:
            self._spin.load(hud.spin_for(view.hud), hud.still_for(view.hud))
            case = hud.case_for(view.hud)
            self._case_art = QPixmap(str(case)) if case is not None else None
        self.view = view
        self.update()

    def start(self) -> None:
        self._started = time.monotonic()
        if not self.animate:
            self._spin.hold()
        elif self._spin.available:
            self._spin.play()
        else:
            self._tick.start()

    def stop(self) -> None:
        self._tick.stop()
        self._spin.hold()

    @property
    def spinning(self) -> bool:
        return not self._spin.done or self._tick.isActive()

    def _fallback_tick(self) -> None:
        if time.monotonic() - self._started >= turntable.TURN_S:
            self._tick.stop()  # one turn, then still
            self.spin_finished.emit()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    # ------------------------------------------------------------ painting

    def paintEvent(self, _event) -> None:
        if self.view is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w = float(self.width())
        shape = squircle(QRectF(self.rect()), CARD_RADIUS)

        # Inside its shape the card is always opaque: the blurred desktop, or the
        # solid fallback when there's no snapshot.
        p.setClipPath(shape)
        if self.backdrop is not None:
            p.drawPixmap(QRectF(self.rect()), self.backdrop, QRectF(self.backdrop.rect()))
        else:
            p.fillPath(shape, SOLID)
        p.fillPath(shape, BACKGROUND)
        p.setClipping(False)
        p.setPen(QPen(HAIRLINE, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(squircle(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS - 0.5))

        y = float(PADDING[1])
        title_font = _font(TITLE_PX, QFont.Weight.DemiBold, -0.2)
        inner = w - PADDING[0] - PADDING[2]
        title = QFontMetrics(title_font).elidedText(self.view.title, Qt.TextElideMode.ElideRight, int(inner))
        p.setFont(title_font)
        p.setPen(TITLE)
        p.drawText(QRectF(PADDING[0], y, inner, TITLE_PX + 5), Qt.AlignmentFlag.AlignCenter, title)
        y += TITLE_PX + 5 + CLIP_MARGIN[0]

        groups = battery_groups(self.view)
        case_group = next((g for g in groups if g.kind == "case"), None)
        bud_groups = [g for g in groups if g.kind != "case"]
        if case_group is not None:  # buds left, case right, the pair centred on the card
            row_w = CLIP + ART_GAP + CASE_W
            buds_box = QRectF((w - row_w) / 2, y, CLIP, CLIP)
            case_box = QRectF(buds_box.right() + ART_GAP, y, CASE_W, CLIP)
            self._paint_clip(p, buds_box)
            self._paint_case(p, case_box)
        else:
            buds_box = QRectF((w - CLIP) / 2, y, CLIP, CLIP)
            self._paint_clip(p, buds_box)
        y += CLIP + CLIP_MARGIN[1]

        # Each battery centred under its own artwork.
        span = len(bud_groups) * GROUP_W + (len(bud_groups) - 1) * BUD_GROUP_GAP
        x = buds_box.center().x() - span / 2
        for group in bud_groups:
            self._paint_group(p, x + GROUP_W / 2, y, group)
            x += GROUP_W + BUD_GROUP_GAP
        if case_group is not None:
            self._paint_group(p, case_box.center().x(), y, case_group)
        y += _battery_row_h() + STATUS_GAP

        p.setFont(_font(STATUS_PX, QFont.Weight.Normal))
        p.setPen(STATUS)
        p.drawText(QRectF(0, y, w, STATUS_PX + 4), Qt.AlignmentFlag.AlignCenter, self.status)
        p.end()

    def _paint_clip(self, p: QPainter, box: QRectF) -> None:
        if self._spin.available:
            pixmap = self._spin.pixmap()
            if pixmap is not None and not pixmap.isNull():
                p.drawPixmap(_fit(box, pixmap.width(), pixmap.height()), pixmap, QRectF(pixmap.rect()))
            return
        sprites = turntable.frames(self.view.family, "buds")
        if sprites:
            # One turn as the card appears, then front-on and still.
            elapsed = time.monotonic() - self._started if self.animate else turntable.TURN_S
            turn = min(elapsed / turntable.TURN_S, 1.0)
            sprite = sprites[round(turn * turntable.FRAMES) % turntable.FRAMES]
            p.drawPixmap(_fit(box, sprite.width(), sprite.height()), sprite, QRectF(sprite.rect()))
        elif self.view.family is Family.HEADPHONES:
            paint_headphones(p, box.adjusted(18, 22, -18, -22), DARK)

    def _paint_case(self, p: QPainter, box: QRectF) -> None:
        """The case beside the buds: your ``<name>_case.png`` if there is one, else PodPop's own, front-on."""
        sprites = turntable.frames(self.view.family, "case")
        image = sprites[0] if sprites else self._case_art
        if image is None or image.isNull():
            return
        # Bottom-aligned with the buds, a little narrower than its column so it sits like iOS.
        scale = min((box.width() - 6) / image.width(), (box.height() * 0.5) / image.height())
        w, h = image.width() * scale, image.height() * scale
        target = QRectF(box.center().x() - w / 2, box.bottom() - h - box.height() * 0.04, w, h)
        p.drawPixmap(target, image, QRectF(image.rect()))

    def _paint_group(self, p: QPainter, cx: float, top: float, group: BatteryGroup) -> None:
        battery = QRectF(cx - BATTERY_W / 2, top, BATTERY_W, BATTERY_H)
        if group.kind in ("left", "right"):  # split buds: say which is which, just left of the battery
            _paint_side_label(p, QRectF(battery.left() - 14, battery.top() - 2, 11, BATTERY_H + 4), group.kind)
        _paint_battery(p, battery, group.level, group.charging)

        p.setFont(_font(PERCENT_PX, QFont.Weight.Medium))
        p.setPen(PERCENT)
        text = f"{group.level} %" if group.level is not None else "â€”"
        p.drawText(QRectF(cx - GROUP_W / 2, battery.bottom() + 5, GROUP_W, PERCENT_PX + 4), Qt.AlignmentFlag.AlignCenter, text)


def _paint_battery(p: QPainter, body: QRectF, level: int | None, charging: bool) -> None:
    """The iOS battery: outlined body with a nub, filled from the left, a white bolt inside while charging."""
    p.save()
    outline = QPainterPath()
    outline.addRoundedRect(body, BATTERY_R, BATTERY_R)
    p.fillPath(outline, TRACK)
    p.strokePath(outline, QPen(OUTLINE, 1.0))
    nub = QRectF(body.right() + 1.0, body.center().y() - 2.2, 1.8, 4.4)
    p.fillPath(_rounded(nub, 0.9), OUTLINE)
    if level is not None and level > 0:
        inner = body.adjusted(2.0, 2.0, -2.0, -2.0)
        inner.setWidth(max(inner.width() * min(level, 100) / 100, 2.0))
        p.fillPath(_rounded(inner, BATTERY_R - 1.8), battery_color(level, charging))
    if charging and level is not None:
        h = BOLT_PX
        _paint_bolt(p, QRectF(body.center().x() - h * 0.31, body.center().y() - h / 2, h * 0.62, h))
    p.restore()


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _paint_side_label(p: QPainter, r: QRectF, kind: str) -> None:
    p.save()
    p.setFont(_font(10, QFont.Weight.DemiBold))
    p.setPen(GLYPH_COLOR)
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "L" if kind == "left" else "R")
    p.restore()


def _battery_row_h() -> float:
    return BATTERY_H + 5 + PERCENT_PX + 4


def _paint_bolt(p: QPainter, r: QRectF) -> None:
    """A small white lightning bolt filling ``r``."""
    pts = [(0.62, 0.0), (0.0, 0.58), (0.42, 0.58), (0.3, 1.0), (1.0, 0.38), (0.56, 0.38), (0.72, 0.0)]
    bolt = QPainterPath(QPointF(r.left() + pts[0][0] * r.width(), r.top() + pts[0][1] * r.height()))
    for x, y in pts[1:]:
        bolt.lineTo(r.left() + x * r.width(), r.top() + y * r.height())
    bolt.closeSubpath()
    p.strokePath(bolt, QPen(QColor(0, 0, 0, 90), 1.0))
    p.fillPath(bolt, BOLT)


def _fit(box: QRectF, w: int, h: int) -> QRectF:
    """object-fit: contain."""
    scale = min(box.width() / w, box.height() / h)
    fw, fh = w * scale, h * scale
    return QRectF(box.center().x() - fw / 2, box.center().y() - fh / 2, fw, fh)


class PopupWindow(QWidget):
    dismissed = Signal()
    connect_clicked = Signal()

    def __init__(self, theme: Theme) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.follow_cursor = False  # True: open on the monitor under the mouse, else the primary one
        # What the glass shows: by default a snapshot of the desktop behind the card.
        # Demos and screenshots pass their own so no real desktop ends up in an image.
        self.backdrop_source: Callable[[QRect], QPixmap | None] | None = None
        self._action = Action.HIDDEN
        self._leaving = False
        self._anim: QParallelAnimationGroup | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        self._card = _Card()
        self._card.clicked.connect(self._on_click)
        self._card.spin_finished.connect(self._on_spin_finished)
        outer.addWidget(self._card)
        self._card.setGraphicsEffect(QGraphicsDropShadowEffect(blurRadius=40, offset=QPointF(0, 12), color=SHADOW))

        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._on_hide_timer)
        self._dismiss_after_spin = False

    # ----------------------------------------------------------------- API

    @property
    def intro_enabled(self) -> bool:
        return self._card.animate

    @intro_enabled.setter
    def intro_enabled(self, value: bool) -> None:
        self._card.animate = value  # play the AirPods clip, or hold its first frame

    def present(self, view: DeviceView, duration_s: float) -> None:
        """Show (or refresh) the card; ``duration_s <= 0`` keeps it until clicked."""
        self._card.set_view(view)
        self._dismiss_after_spin = False
        if not self.isVisible() or self._leaving:
            self._enter()
        ms = int(duration_s * 1000)
        if ms > 0:
            self._hide_timer.start(ms)
        else:
            self._hide_timer.stop()

    def update_view(self, view: DeviceView) -> None:
        if self.isVisible() and not self._leaving:
            self._card.set_view(view)

    def dismiss(self) -> None:
        if not self.isVisible() or self._leaving:
            return
        self._leaving = True
        self._hide_timer.stop()
        self._animate(self.pos() + QPoint(0, ENTER_RISE), 0.0, QEasingCurve.Type.InCubic, on_done=self._finish_dismiss)

    def set_theme(self, theme: Theme) -> None:
        pass  # the HUD is always the dark material, like iOS

    def set_action(self, action: Action) -> None:
        self._action = action
        self._card.status = action.value
        self._card.update()

    # ------------------------------------------------------------ internals

    def _on_hide_timer(self) -> None:
        if self._card.spinning:
            self._dismiss_after_spin = True  # leave once the turn is done
        else:
            self.dismiss()

    def _on_spin_finished(self) -> None:
        if self._leaving or not self.isVisible():
            return
        if self._dismiss_after_spin or (self._hide_timer.isActive() and self._hide_timer.remainingTime() < STILL_HOLD_MS):
            self._dismiss_after_spin = False
            self._hide_timer.start(STILL_HOLD_MS)

    def _on_click(self) -> None:
        if self._action in (Action.CONNECT, Action.FAILED):
            self.connect_clicked.emit()
        else:
            self.dismiss()

    def _target_pos(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if self.follow_cursor:
            screen = QGuiApplication.screenAt(QCursor.pos()) or screen
        area = screen.availableGeometry()
        self.adjustSize()
        y = area.bottom() - self.height() + SHADOW_MARGIN - SCREEN_GAP
        return QPoint(area.center().x() - self.width() // 2, y)

    def _enter(self) -> None:
        self._leaving = False
        target = self._target_pos()
        if not self.isVisible():
            self._card.backdrop = self._grab_backdrop(target)
            self.move(target + QPoint(0, ENTER_RISE))
            self.setWindowOpacity(0.0)
            self.show()
        self.raise_()
        _bring_to_front(self)
        self._card.start()
        self._animate(target, 1.0, QEasingCurve.Type.OutCubic)

    def _grab_backdrop(self, target: QPoint) -> QPixmap | None:
        """The desktop where the card will rest, blurred and saturated (we're not on screen yet)."""
        card = QRect(target + QPoint(SHADOW_MARGIN, SHADOW_MARGIN), self._card.size())
        if self.backdrop_source is not None:
            shot = self.backdrop_source(card)
        else:
            screen = QGuiApplication.screenAt(card.center()) or QGuiApplication.primaryScreen()
            local = card.translated(-screen.geometry().topLeft())
            shot = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())
        if shot is None or shot.isNull():
            return None
        smooth = Qt.TransformationMode.SmoothTransformation
        small = shot.toImage().convertToFormat(QImage.Format.Format_RGB32).scaled(
            max(1, shot.width() // BLUR_DOWNSCALE), max(1, shot.height() // BLUR_DOWNSCALE),
            Qt.AspectRatioMode.IgnoreAspectRatio, smooth,
        )
        _saturate(small, SATURATION)
        # Back up in a couple of smooth steps: close to a gaussian blur.
        mid = small.scaled(small.width() * 4, small.height() * 4, Qt.AspectRatioMode.IgnoreAspectRatio, smooth)
        return QPixmap.fromImage(mid)

    def _animate(self, pos: QPoint, opacity: float, curve, on_done=None) -> None:
        if self._anim is not None:
            self._anim.stop()  # stop() doesn't emit finished, so no stale on_done runs
        group = QParallelAnimationGroup()
        group.addAnimation(QPropertyAnimation(self, b"pos", duration=FADE_MS, easingCurve=curve, endValue=pos))
        group.addAnimation(QPropertyAnimation(self, b"windowOpacity", duration=FADE_MS, easingCurve=curve, endValue=opacity))
        if on_done is not None:
            group.finished.connect(on_done)
        self._anim = group
        group.start()

    def _finish_dismiss(self) -> None:
        self.hide()
        self._card.stop()
        self._leaving = False
        self.dismissed.emit()


def _saturate(image: QImage, amount: float) -> None:
    """In place; the image is tiny (the blur shrank it), so per-pixel is cheap."""
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            r, g, b = c.redF(), c.greenF(), c.blueF()
            grey = 0.2126 * r + 0.7152 * g + 0.0722 * b
            image.setPixelColor(x, y, QColor.fromRgbF(*(min(1.0, max(0.0, grey + (v - grey) * amount)) for v in (r, g, b))))


_HWND_TOPMOST = -1
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


def _bring_to_front(window: QWidget) -> None:
    """Put the window at the top of the always-on-top band without taking focus.

    Qt's raise_() doesn't lift a non-activating window above the taskbar
    once the taskbar has been clicked (it is topmost too, and more recent).
    """
    if sys.platform != "win32":
        return
    ctypes.windll.user32.SetWindowPos(
        int(window.winId()), _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
    )

