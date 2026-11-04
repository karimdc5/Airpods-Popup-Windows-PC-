"""The battery HUD: a frosted dark card near the top of the screen.

Top to bottom: the device name, the AirPods swaying gently (the front-facing
part of the clip, played back and forth, so the buds stay apart and mirrored),
a row of vertical battery capsules labelled L, C and R, and the connection
status. It sits just above the taskbar, fades in while rising 8 px, stays a
few seconds, and fades out the same way. There are no buttons; clicking the card connects the AirPods
when they're not connected, and otherwise just closes it.

Measurements follow the iOS HUD: 280 px wide, 26 px continuous corners,
rgba(28,28,30,.74) over the blurred, saturated desktop, a 1 px inner
hairline, and a soft 40 px shadow.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from collections.abc import Callable
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
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap
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
CLIP = 168
CLIP_MARGIN = (4, 2)  # above, below
LABEL_PX = 10
CAPSULE_W, CAPSULE_H, CAPSULE_R = 9.0, 34.0, 5.0
PERCENT_PX = 11
COLUMN_GAP = 22
STATUS_PX = 12
STATUS_GAP = 12

SCREEN_GAP = 18  # between the card and the bottom of the work area
SHADOW_MARGIN = 40
ENTER_RISE = 8
FADE_MS = 180
BLUR_DOWNSCALE = 24  # shrink, then smooth back up: a wide (~28 px) blur
SATURATION = 1.8

FONTS = ["SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Arial"]

BACKGROUND = QColor(28, 28, 30, 189)  # .74
SOLID = QColor(28, 28, 30)  # when there is no desktop snapshot (older Windows, demos)
HAIRLINE = QColor(255, 255, 255, 20)  # .08
SHADOW = QColor(0, 0, 0, 115)  # .45
TITLE = QColor(255, 255, 255, 250)  # .98
TRACK = QColor(255, 255, 255, 41)  # .16
PERCENT = QColor(255, 255, 255, 217)  # .85
STATUS = QColor(255, 255, 255, 140)  # .55
LABEL = QColor(255, 255, 255, 140)  # .55
OK, WARN, LOW = QColor("#30D158"), QColor("#FFD60A"), QColor("#FF453A")

_COLUMN_ORDER = {Part.LEFT: 0, Part.CASE: 1, Part.RIGHT: 2, None: 0}
_LABELS = {Part.LEFT: "L", Part.CASE: "C", Part.RIGHT: "R"}

# The clip turns the pair as one piece, so from the side one bud hides the
# other. Only its front-facing start is used, swung back and forth.
SWAY_END_US = 900_000  # the first 0.9 s of the clip
SWAY_PERIOD_S = 4.0  # there and back
SWAY_DEG = 28.0  # the fallback turntable's swing either side of front-on
FRAME_PX = 2 * CLIP  # decoded frames are kept at 2x for high-DPI screens


class Action(Enum):
    """What the link is doing; shown as the status line."""

    HIDDEN = "Connected"  # connected (or nothing to connect)
    CONNECT = "Not connected"
    CONNECTING = "Connecting…"
    FAILED = "Couldn’t connect"


def battery_color(level: int | None, charging: bool) -> QColor:
    """Green above 20%, yellow at 11-20%, red at 10% and below (green while charging)."""
    if level is None or charging or level > LOW_LEVEL:
        return OK
    return LOW if level <= CRITICAL_LEVEL else WARN


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


class _Clip:
    """The front-facing start of the AirPods clip, decoded once by Qt Multimedia.

    The frames are kept in memory and played back and forth (see ``frame_at``)
    instead of looping the whole turn.
    """

    def __init__(self, on_frame: Callable[[], None]) -> None:
        self._on_frame = on_frame
        self.frames: list[QImage] = []
        self.path = None
        self.screen_blend = True  # black background: blend in screen mode
        self._player = None

    def load(self, path) -> None:
        if path == self.path:
            return
        if self._player is not None:
            self._player.stop()
        self.path, self.frames = path, []
        if path is None:
            return
        from PySide6.QtMultimedia import QMediaPlayer, QVideoSink  # only needed with a clip

        if self._player is None:
            self._player = QMediaPlayer()  # no audio output: muted
            self._sink = QVideoSink()
            self._player.setVideoSink(self._sink)
            self._sink.videoFrameChanged.connect(self._frame)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()  # decode the front segment now, off screen

    def frame_at(self, seconds: float) -> QImage | None:
        """Ease from the first frame to the last of the segment and back."""
        if not self.frames:
            return None
        phase = (1 - math.cos(2 * math.pi * seconds / SWAY_PERIOD_S)) / 2
        return self.frames[round(phase * (len(self.frames) - 1))]

    def _frame(self, video_frame) -> None:
        image = video_frame.toImage()
        if image.isNull() or self._player is None:
            return
        start = video_frame.startTime()  # microseconds, or -1 if unknown
        if (start >= 0 and start > SWAY_END_US) or len(self.frames) > 120:
            self._player.stop()  # we have the front-facing part
            return
        if not self.frames:  # decide once per clip whether it carries transparency
            self.screen_blend = image.pixelColor(0, 0).alpha() == 255
        smooth = Qt.TransformationMode.SmoothTransformation
        self.frames.append(image.scaled(FRAME_PX, FRAME_PX, Qt.AspectRatioMode.KeepAspectRatio, smooth))
        self._on_frame()


class _Card(QWidget):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(CARD_W, self.content_height())
        self.view: DeviceView | None = None
        self.status = Action.HIDDEN.value
        self.backdrop: QPixmap | None = None
        self.animate = True
        self._started = time.monotonic()
        self._clip = _Clip(self.update)
        self._tick = QTimer(self, interval=33)  # drives the sway
        self._tick.timeout.connect(self.update)

    @staticmethod
    def content_height() -> int:
        return round(PADDING[1] + TITLE_PX + 5 + CLIP_MARGIN[0] + CLIP + CLIP_MARGIN[1] + _battery_row_h()
                     + STATUS_GAP + STATUS_PX + 3 + PADDING[3])

    def set_view(self, view: DeviceView) -> None:
        if self.view is None or self.view.family is not view.family:
            self._clip.load(hud.clip_for(view.family))
        self.view = view
        self.update()

    def start(self) -> None:
        self._started = time.monotonic()
        if self.animate:
            self._tick.start()

    def stop(self) -> None:
        self._tick.stop()

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

        # The card is always opaque inside its shape: the blurred desktop, or the
        # solid fallback. A clip blended in screen mode needs that, or its black
        # background would show as a darker square on a see-through card.
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

        self._paint_clip(p, QRectF((w - CLIP) / 2, y, CLIP, CLIP))
        y += CLIP + CLIP_MARGIN[1]

        items = sorted(self.view.items, key=lambda i: _COLUMN_ORDER[i.part])
        column_w = 30.0  # wide enough for "100%"
        row_w = len(items) * column_w + (len(items) - 1) * COLUMN_GAP
        x = (w - row_w) / 2
        for item in items:
            self._paint_column(p, x + column_w / 2, y, item, self.view.family)
            x += column_w + COLUMN_GAP
        y += _battery_row_h() + STATUS_GAP

        p.setFont(_font(STATUS_PX, QFont.Weight.Normal))
        p.setPen(STATUS)
        p.drawText(QRectF(0, y, w, STATUS_PX + 4), Qt.AlignmentFlag.AlignCenter, self.status)
        p.end()

    def _paint_clip(self, p: QPainter, box: QRectF) -> None:
        elapsed = time.monotonic() - self._started if self.animate else 0.0
        frame = self._clip.frame_at(elapsed)
        if frame is not None:
            p.save()
            if self._clip.screen_blend:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.drawImage(_fit(box, frame.width(), frame.height()), frame)
            p.restore()
            return
        if self._clip.path is not None:
            return  # still decoding the first frames; never flash the fallback over a real clip
        sprites = turntable.frames(self.view.family, "buds")
        if sprites:
            # Swing either side of front-on, like the clip.
            angle = SWAY_DEG * math.sin(2 * math.pi * elapsed / SWAY_PERIOD_S)
            sprite = sprites[round(angle / 360 * turntable.FRAMES) % turntable.FRAMES]
            p.drawPixmap(_fit(box, sprite.width(), sprite.height()), sprite, QRectF(sprite.rect()))
        elif self.view.family is Family.HEADPHONES:
            paint_headphones(p, box.adjusted(18, 22, -18, -22), DARK)

    def _paint_column(self, p: QPainter, cx: float, top: float, item: ItemView, family: Family) -> None:
        p.setFont(_font(LABEL_PX, QFont.Weight.DemiBold))
        p.setPen(LABEL)
        p.drawText(QRectF(cx - 15, top, 30, LABEL_PX + 3), Qt.AlignmentFlag.AlignCenter, _LABELS.get(item.part, ""))

        capsule = QRectF(cx - CAPSULE_W / 2, top + LABEL_PX + 3 + 6, CAPSULE_W, CAPSULE_H)
        path = QPainterPath()
        path.addRoundedRect(capsule, CAPSULE_R, CAPSULE_R)
        p.fillPath(path, TRACK)
        known = item.level is not None
        if known and item.level > 0:
            fill_h = CAPSULE_H * min(item.level, 100) / 100
            p.save()
            p.setClipPath(path)
            fill = QRectF(capsule.left(), capsule.bottom() - fill_h, CAPSULE_W, fill_h)  # anchored at the bottom
            p.fillRect(fill, battery_color(item.level, item.charging))
            p.restore()

        p.setFont(_font(PERCENT_PX, QFont.Weight.Medium))
        p.setPen(PERCENT)
        text = f"{item.level}%" if known else "—"
        p.drawText(QRectF(cx - 30, capsule.bottom() + 5, 60, PERCENT_PX + 4), Qt.AlignmentFlag.AlignCenter, text)


def _battery_row_h() -> float:
    return LABEL_PX + 3 + 6 + CAPSULE_H + 5 + PERCENT_PX + 3


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
        outer.addWidget(self._card)
        self._card.setGraphicsEffect(QGraphicsDropShadowEffect(blurRadius=40, offset=QPointF(0, 12), color=SHADOW))

        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self.dismiss)

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
