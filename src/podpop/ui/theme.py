"""Colors and fonts for light and dark mode, modelled on iOS system colors."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication

FONT_FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "Arial"]


@dataclass(frozen=True, slots=True)
class Theme:
    dark: bool
    card: QColor
    card_border: QColor
    card_glass: QColor  # tint over the blurred desktop behind the card
    shadow: QColor
    title: QColor
    subtitle: QColor
    ring_track: QColor
    ring_ok: QColor
    ring_low: QColor
    ring_warn: QColor
    button: QColor
    button_hover: QColor
    button_glyph: QColor
    accent: QColor
    art_light: QColor
    art_dark: QColor
    art_outline: QColor
    art_tip: QColor
    art_detail: QColor


DARK = Theme(
    dark=True,
    card=QColor(28, 28, 30, 246),
    card_border=QColor(255, 255, 255, 22),
    card_glass=QColor(28, 28, 30, 189),
    shadow=QColor(0, 0, 0, 150),
    title=QColor("#FFFFFF"),
    subtitle=QColor("#8E8E93"),
    ring_track=QColor(255, 255, 255, 36),
    ring_ok=QColor("#30D158"),
    ring_low=QColor("#FF453A"),
    ring_warn=QColor("#FFD60A"),
    button=QColor(255, 255, 255, 26),
    button_hover=QColor(255, 255, 255, 48),
    button_glyph=QColor("#AEAEB2"),
    accent=QColor("#0A84FF"),
    art_light=QColor("#FFFFFF"),
    art_dark=QColor("#D4D4DA"),
    art_outline=QColor(0, 0, 0, 0),  # rendered look: shading, not outlines
    art_tip=QColor("#C7C7CD"),
    art_detail=QColor("#2C2C2E"),
)

LIGHT = Theme(
    dark=False,
    card=QColor(255, 255, 255, 250),
    card_border=QColor(0, 0, 0, 18),
    card_glass=QColor(246, 246, 248, 205),
    shadow=QColor(0, 0, 0, 70),
    title=QColor("#000000"),
    subtitle=QColor("#6E6E73"),
    ring_track=QColor(0, 0, 0, 22),
    ring_ok=QColor("#34C759"),
    ring_low=QColor("#FF3B30"),
    ring_warn=QColor("#FFCC00"),
    button=QColor(0, 0, 0, 14),
    button_hover=QColor(0, 0, 0, 28),
    button_glyph=QColor("#6E6E73"),
    accent=QColor("#007AFF"),
    art_light=QColor("#FFFFFF"),
    art_dark=QColor("#DCDCE1"),
    art_outline=QColor(0, 0, 0, 0),
    art_tip=QColor("#D1D1D6"),
    art_detail=QColor("#3A3A3C"),
)


def system_theme() -> Theme:
    scheme = QGuiApplication.styleHints().colorScheme()
    return LIGHT if scheme == Qt.ColorScheme.Light else DARK


def theme_for(choice: str) -> Theme:
    """'dark' | 'light' | 'system'."""
    return {"dark": DARK, "light": LIGHT}.get(choice) or system_theme()


def font(pixel_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(round(pixel_size))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f
