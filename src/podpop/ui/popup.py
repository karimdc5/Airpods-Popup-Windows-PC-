"""The iPhone-style battery card that slides up from the bottom of the screen."""

from __future__ import annotations

import ctypes
import math
import sys
from enum import Enum

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..catalog import Family
from ..presenter import LOW_LEVEL, DeviceView, ItemView
from ..protocol import Part
from .artwork import case_led, paint_bud, paint_case, paint_headphones
from .intro import INTRO_MS, IntroOverlay
from .theme import Theme, font


# iPhone layout: both buds side by side on the left, the case on the right,
# a small battery icon and percentage under each.
BUD_W = 74
CASE_W = 150
HEADPHONES_W = 200
PAIR_GAP = 22  # between the buds and the case
ART_H = 112
PILL_W, PILL_H = 27.0, 12.5
BATTERY_Y = ART_H + 14
TILE_H = int(BATTERY_Y + PILL_H) + 6 + 18

CARD_MARGINS = (20, 16, 20, 20)
CARD_W = 2 * BUD_W + PAIR_GAP + CASE_W + CARD_MARGINS[0] + CARD_MARGINS[2]
_DISPLAY_ORDER = {Part.LEFT: 0, Part.RIGHT: 1, Part.CASE: 2, None: 0}
CARD_RADIUS = 28.0
SHADOW_MARGIN = 40
SCREEN_GAP = 18  # distance between card and the bottom of the work area
# The card rises this far while fading in. Kept under SCREEN_GAP so it never
# starts behind the taskbar, which can stay above us after a tray click.
ENTER_RISE = 14
EXIT_DROP = 10

ENTER_MS = 560
EXIT_MS = 220
FILL_MS = 900
FILL_STAGGER_MS = 90
HOVER_GRACE_MS = 2500
RESIZE_MS = 200


class Action(Enum):
    """State of the Connect button at the bottom of the card."""

    HIDDEN = None
    CONNECT = "Connect"
    CONNECTING = "Connecting…"
    FAILED = "Couldn’t connect · Try again"


class ItemTile(QWidget):
    """Artwork + battery icon + percentage for one part (left, right, case…)."""

    def __init__(self, family: Family, part: Part | None, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        width = HEADPHONES_W if family is Family.HEADPHONES else CASE_W if part is Part.CASE else BUD_W
        self.setFixedSize(width, TILE_H)
        self.family = family
        self._theme = theme
        self._item: ItemView | None = None
        self._shown = 0.0
        self.art_visible = True  # hidden while the intro animation draws it instead

        self._anim = QVariantAnimation(self, duration=FILL_MS, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._delay = QTimer(self, singleShot=True)
        self._delay.timeout.connect(self._anim.start)

    @property
    def part(self) -> Part | None:
        return self._item.part if self._item else None

    @property
    def item(self) -> ItemView | None:
        return self._item

    def art_rect(self) -> QRectF:
        """Where this tile draws its artwork, in tile coordinates."""
        w = float(self.width())
        if self.family is Family.HEADPHONES:
            return QRectF((w - 120) / 2, 8, 120, ART_H - 12)
        if self.part is Part.CASE:
            return QRectF((w - 112) / 2, 24, 112, ART_H - 26)
        return QRectF(4, 6, w - 8, ART_H - 10)

    def art_opacity(self) -> float:
        item = self._item
        if item is None or item.level is None:
            return 0.38
        return 0.6 if item.stale else 1.0

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_item(self, item: ItemView, *, from_zero: bool = False, delay_ms: int = 0) -> None:
        self._item = item
        target = float(item.level or 0)
        if from_zero:
            self._shown = 0.0
        self._delay.stop()
        self._anim.stop()
        if math.isclose(target, self._shown):
            self.update()
            return
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(target)
        self._delay.start(delay_ms)
        self.update()

    def _on_anim(self, value: float) -> None:
        self._shown = float(value)
        self.update()

    def paintEvent(self, _event) -> None:
        item, theme = self._item, self._theme
        if item is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())

        known = item.level is not None
        if self.art_visible:
            p.setOpacity(self.art_opacity())
            paint_item_art(p, self.art_rect(), self.family, item, theme)

        p.setOpacity(0.6 if item.stale else 1.0)
        charging = item.charging and known
        bolt_w = 9.0 if charging else 0.0
        pill = QRectF((w - PILL_W - bolt_w) / 2, BATTERY_Y, PILL_W, PILL_H)
        low = known and item.level <= LOW_LEVEL and not item.charging
        _paint_battery(p, pill, self._shown / 100 if known else 0.0, theme, low)
        if charging:
            _paint_bolt(p, QPointF(pill.right() + 7.5, pill.center().y()), theme.title, 0.8)

        p.setPen(theme.title if known else theme.subtitle)
        p.setFont(font(12.5, QFont.Weight.DemiBold))
        text = f"{round(self._shown)}%" if known else "—"
        p.drawText(QRectF(0, pill.bottom() + 5, w, 18), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)
        p.end()


def paint_item_art(p: QPainter, rect: QRectF, family: Family, item: ItemView, theme: Theme, lid_open: float = 0.0) -> None:
    if family is Family.HEADPHONES:
        paint_headphones(p, rect, theme)
    elif item.part is Part.CASE:
        paint_case(p, rect, family, case_led(item.level, item.charging), theme, lid_open)
    else:
        paint_bud(p, rect, family, item.part is Part.LEFT, theme)


def _paint_battery(p: QPainter, body: QRectF, fraction: float, theme: Theme, low: bool) -> None:
    """The iOS status-bar battery: rounded body, a nub on the right, a fill bar."""
    p.save()
    p.setPen(QPen(theme.ring_track, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body, 3.6, 3.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.ring_track)
    p.drawRoundedRect(QRectF(body.right() + 1.2, body.center().y() - 2.4, 1.8, 4.8), 0.9, 0.9)
    if fraction > 0.005:
        inner = body.adjusted(2.0, 2.0, -2.0, -2.0)
        inner.setWidth(max(inner.width() * min(fraction, 1.0), 2.0))
        p.setBrush(theme.ring_low if low else theme.ring_ok)
        p.drawRoundedRect(inner, 1.8, 1.8)
    p.restore()


def _paint_bolt(p: QPainter, center: QPointF, color: QColor, scale: float = 1.0) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    bolt = QPainterPath()
    pts = [(1.2, -6.5), (-4.2, 1.0), (-0.4, 1.0), (-1.4, 6.5), (4.2, -1.2), (0.4, -1.2)]
    bolt.moveTo(center + QPointF(pts[0][0] * scale, pts[0][1] * scale))
    for x, y in pts[1:]:
        bolt.lineTo(center + QPointF(x * scale, y * scale))
    bolt.closeSubpath()
    p.setBrush(color)
    p.drawPath(bolt)
    p.restore()


class _CloseButton(QAbstractButton):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Close")

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.theme.button_hover if self.underMouse() else self.theme.button)
        p.drawEllipse(QRectF(self.rect()))
        pen = QPen(self.theme.button_glyph, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c, d = QPointF(self.width() / 2, self.height() / 2), 4.2
        p.drawLine(c + QPointF(-d, -d), c + QPointF(d, d))
        p.drawLine(c + QPointF(-d, d), c + QPointF(d, -d))
        p.end()


class _GearButton(QAbstractButton):
    """Small round settings button next to the close button."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Settings")

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.theme.button_hover if self.underMouse() else self.theme.button)
        p.drawEllipse(QRectF(self.rect()))
        c = QPointF(self.width() / 2, self.height() / 2)
        gear = QPainterPath()
        teeth, outer, inner = 8, 7.2, 5.4
        for i in range(teeth * 2):
            angle = math.pi * i / teeth
            r = outer if i % 2 == 0 else inner
            for da in (-0.17, 0.17):
                point = c + QPointF(math.cos(angle + da) * r, math.sin(angle + da) * r)
                gear.moveTo(point) if gear.elementCount() == 0 else gear.lineTo(point)
        gear.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(c, 2.4, 2.4)
        p.setBrush(self.theme.button_glyph)
        p.drawPath(gear.subtracted(hole))
        p.end()


class _ActionButton(QAbstractButton):
    """Full-width pill button, like the one on the iPhone popup."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.action = Action.HIDDEN
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def set_action(self, action: Action) -> None:
        self.action = action
        self.setVisible(action is not Action.HIDDEN)
        self.setEnabled(action is not Action.CONNECTING)
        self.update()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.theme.accent)
        if not self.isEnabled():
            color.setAlphaF(0.55)
        elif self.isDown():
            color = color.darker(120)
        elif self.underMouse():
            color = color.lighter(112)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font(15, QFont.Weight.DemiBold))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.action.value or "")
        p.end()


class _Card(QWidget):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.theme.card_border, 1))
        p.setBrush(self.theme.card)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS, CARD_RADIUS)
        p.end()


class PopupWindow(QWidget):
    dismissed = Signal()
    connect_clicked = Signal()
    settings_clicked = Signal()

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
        self._theme = theme
        self.follow_cursor = False  # True: open on the monitor under the mouse, else the primary one
        self.intro_enabled = True  # play the case-opening animation when the card appears
        self._view: DeviceView | None = None
        self._duration_ms = 0
        self._leaving = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        self._card = _Card(theme)
        self._card.setFixedWidth(CARD_W)
        outer.addWidget(self._card)
        self._shadow = QGraphicsDropShadowEffect(blurRadius=50, offset=QPointF(0, 12))
        self._card.setGraphicsEffect(self._shadow)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(*CARD_MARGINS)
        layout.setSpacing(10)

        # Title centred like iOS, settings on the left and close on the right.
        header = QHBoxLayout()
        header.setSpacing(8)
        self._gear = _GearButton(theme)
        self._gear.clicked.connect(self.settings_clicked)
        header.addWidget(self._gear, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._title = QLabel(alignment=Qt.AlignmentFlag.AlignHCenter)
        self._title.setFont(font(19, QFont.Weight.Bold))
        self._subtitle = QLabel(alignment=Qt.AlignmentFlag.AlignHCenter)
        self._subtitle.setFont(font(12))
        text.addSpacing(6)
        text.addWidget(self._title)
        text.addWidget(self._subtitle)
        header.addLayout(text, 1)
        self._close = _CloseButton(theme)
        self._close.clicked.connect(self.dismiss)
        header.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self._tiles_row = QHBoxLayout()
        self._tiles_row.setSpacing(0)
        layout.addLayout(self._tiles_row)
        self._tiles: list[ItemTile] = []

        self._action = _ActionButton(theme)
        self._action.clicked.connect(self.connect_clicked)
        layout.addSpacing(2)
        layout.addWidget(self._action)

        self._intro = IntroOverlay(self._card)

        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self.dismiss)
        self._anim: QParallelAnimationGroup | None = None
        self._apply_theme()

    # ----------------------------------------------------------------- API

    def present(self, view: DeviceView, duration_s: float) -> None:
        """Show (or refresh) the card; ``duration_s <= 0`` keeps it open until closed."""
        self._duration_ms = int(duration_s * 1000)
        entering = not self.isVisible() or self._leaving
        intro = entering and self.intro_enabled
        self._apply_view(view, from_zero=entering, fill_delay_ms=int(INTRO_MS * 0.7) if intro else 150)
        if entering:
            self._enter()
            if intro:
                self._card.layout().activate()
                stage = QRectF(self._tiles_row.geometry()).adjusted(0, -6, 0, 4)
                self._intro.play(self._tiles, self._theme, stage)
        self._restart_hide_timer(self._duration_ms)

    def update_view(self, view: DeviceView) -> None:
        if self.isVisible() and not self._leaving:
            self._apply_view(view, from_zero=False)

    def dismiss(self) -> None:
        if not self.isVisible() or self._leaving:
            return
        self._leaving = True
        self._hide_timer.stop()
        self._intro.stop()
        self._animate(
            self.pos() + QPoint(0, EXIT_DROP), 0.0, EXIT_MS, QEasingCurve.Type.InCubic, on_done=self._finish_dismiss
        )

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._apply_theme()

    def set_action(self, action: Action) -> None:
        if action is self._action.action:
            return
        self._action.set_action(action)
        self._reanchor()

    # ------------------------------------------------------------ internals

    def _apply_theme(self) -> None:
        t = self._theme
        self._card.theme = t
        self._close.theme = t
        self._gear.theme = t
        self._action.theme = t
        self._shadow.setColor(t.shadow)
        self._title.setStyleSheet(f"color: {t.title.name()}; background: transparent;")
        self._subtitle.setStyleSheet(f"color: {t.subtitle.name()}; background: transparent;")
        for tile in self._tiles:
            tile.set_theme(t)
        self._intro.set_theme(t)
        self._card.update()

    def _apply_view(self, view: DeviceView, *, from_zero: bool, fill_delay_ms: int = 150) -> None:
        self._view = view
        title_width = CARD_W - CARD_MARGINS[0] - CARD_MARGINS[2] - self._close.width() - self._gear.width() - 16
        self._title.setText(QFontMetrics(self._title.font()).elidedText(view.title, Qt.TextElideMode.ElideRight, title_width))
        self._title.setToolTip(view.title)
        self._subtitle.setText(view.subtitle)

        items = sorted(view.items, key=lambda i: _DISPLAY_ORDER[i.part])
        layout_key = [(view.family, i.part) for i in items]
        if layout_key != [(t.family, t.part) for t in self._tiles] or from_zero:
            self._intro.stop()  # it animates the old tiles
            self._rebuild_tiles(view.family, items)
        for index, (tile, item) in enumerate(zip(self._tiles, items)):
            delay = fill_delay_ms + index * FILL_STAGGER_MS if from_zero else 0
            tile.set_item(item, from_zero=from_zero, delay_ms=delay)
        self._reanchor()

    def _rebuild_tiles(self, family: Family, items: list[ItemView]) -> None:
        while self._tiles_row.count():
            child = self._tiles_row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._tiles = [ItemTile(family, item.part, self._theme) for item in items]
        self._tiles_row.addStretch(1)
        for tile in self._tiles:
            if tile.part is Part.CASE:
                self._tiles_row.addSpacing(PAIR_GAP)
            self._tiles_row.addWidget(tile)
            # A widget added to a visible window is shown only on a later event
            # loop pass; until then the layout measures the card without it.
            tile.show()
        self._tiles_row.addStretch(1)

    def _target_pos(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if self.follow_cursor:
            screen = QGuiApplication.screenAt(QCursor.pos()) or screen
        area = screen.availableGeometry()
        self.adjustSize()
        x = area.center().x() - self.width() // 2
        y = area.bottom() - self.height() + SHADOW_MARGIN - SCREEN_GAP
        return QPoint(x, y)

    def _reanchor(self) -> None:
        """Keep the card's bottom edge in place when its height changes."""
        old_height = self.height()
        self.adjustSize()
        if self.height() != old_height:
            self._retarget()

    def _retarget(self) -> None:
        if not self.isVisible() or self._leaving:
            return
        entering = self._anim is not None and self._anim.state() == QParallelAnimationGroup.State.Running
        if entering:
            self._enter()  # retarget the running entrance
        elif self.pos() != self._target_pos():
            self._animate(self._target_pos(), 1.0, RESIZE_MS, QEasingCurve.Type.OutCubic)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._retarget)  # re-check once the layout has settled

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Safety net: whatever changed the height, the card's bottom edge
        # must stay above the taskbar.
        if event.oldSize().isValid() and event.oldSize().height() != event.size().height():
            QTimer.singleShot(0, self._retarget)

    def _enter(self) -> None:
        self._leaving = False
        target = self._target_pos()
        if not self.isVisible():
            self.move(target + QPoint(0, ENTER_RISE))
            self.setWindowOpacity(0.0)
            self.show()
        self.raise_()
        _bring_to_front(self)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(0.9)
        self._animate(target, 1.0, ENTER_MS, curve)

    def _animate(self, pos: QPoint, opacity: float, ms: int, curve, on_done=None) -> None:
        if self._anim is not None:
            self._anim.stop()  # stop() doesn't emit finished, so no stale on_done runs
        group = QParallelAnimationGroup()  # owned by self._anim; freed when replaced
        move = QPropertyAnimation(self, b"pos", duration=ms, easingCurve=curve, endValue=pos)
        fade = QPropertyAnimation(
            self, b"windowOpacity", duration=min(ms, 280), easingCurve=QEasingCurve.Type.OutCubic, endValue=opacity
        )
        group.addAnimation(move)
        group.addAnimation(fade)
        if on_done is not None:
            group.finished.connect(on_done)
        self._anim = group
        group.start()

    def _finish_dismiss(self) -> None:
        self.hide()
        self._leaving = False
        self.dismissed.emit()

    def _restart_hide_timer(self, ms: int) -> None:
        self._hide_timer.stop()
        if ms > 0 and not self.underMouse():
            self._hide_timer.start(ms)

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()  # don't vanish while the user is looking at it
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._duration_ms > 0:
            self._restart_hide_timer(max(HOVER_GRACE_MS, self._hide_timer.remainingTime()))
        super().leaveEvent(event)


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
