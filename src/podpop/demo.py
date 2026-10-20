"""Shows the popup with sample data, for design work without AirPods nearby."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .catalog import Family, lookup
from .presenter import build_view
from .state import Component, Snapshot
from .ui.popup import Action, PopupWindow
from .ui.theme import DARK, LIGHT, system_theme

_SAMPLE_MODELS = {
    Family.PRO: (0x2024, "My AirPods Pro"),
    Family.CLASSIC: (0x200F, "My AirPods"),
    Family.OPEN: (0x2019, "My AirPods 4"),
    Family.HEADPHONES: (0x200A, "My AirPods Max"),
}


def sample_snapshot(family: Family) -> Snapshot:
    model_id, _ = _SAMPLE_MODELS[family]
    return Snapshot(
        model=lookup(model_id),
        left=Component(100, charging=True, fresh=True),
        right=Component(60, in_ear=True, fresh=True),
        case=Component(70, fresh=True),
    )


def run(
    app: QApplication,
    family: Family,
    theme_name: str | None,
    screenshot: Path | None,
    nearby: bool = False,
    capture_ms: int = 2600,
) -> int:
    theme = {"dark": DARK, "light": LIGHT}.get(theme_name or "", system_theme())
    _, name = _SAMPLE_MODELS[family]
    popup = PopupWindow(theme)
    if nearby:  # AirPods around but connected elsewhere, e.g. to an iPhone
        popup.set_action(Action.CONNECT)
    popup.present(build_view(sample_snapshot(family), name, connected=not nearby), duration_s=0)

    if screenshot is not None:

        def capture() -> None:
            popup.grab().save(str(screenshot))
            app.quit()

        QTimer.singleShot(capture_ms, capture)
    else:
        popup.dismissed.connect(app.quit)
    return app.exec()
