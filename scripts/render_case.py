"""Renders case symbols (SVG) into the HUD folder as ``<name>_case.png``.

The symbols are Apple SF Symbols, as exported by
https://github.com/brendanballon/sfsymbols-svg. Apple's SF Symbols licence
doesn't allow redistributing them, so they are not in this repository: put
the SVGs you have in ``src/podpop/assets/symbols/`` (git-ignored) or pass
another folder. The PNGs it writes are git-ignored too, like the HUD clips.

Usage:  .\\.venv\\Scripts\\python scripts\\render_case.py [SVG_FOLDER] [--out DIR]
scripts/import_hud.py runs it as part of a normal import.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSizeF
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from podpop.ui.hud import hud_dir  # noqa: E402

SYMBOLS = ROOT / "src" / "podpop" / "assets" / "symbols"
HEIGHT = 260
TINT = QColor(255, 255, 255, 110)  # .55, like the rest of the card's secondary marks

# PodPop HUD name -> SF Symbol file. Spelled out because the two naming
# schemes diverge (gen numbers, ".pro", ".wireless"), so no string munging.
CASE_SYMBOLS: dict[str, str | None] = {
    "airpods": "airpods.chargingcase.svg",
    "airpodsGen3": "airpods.gen3.chargingcase.wireless.svg",
    "airpodsGen4": "airpods.chargingcase.wireless.svg",
    "airpodsPro": "airpods.pro.chargingcase.wireless.svg",
    "airpodsPro3": "airpods.pro.chargingcase.wireless.svg",  # same case shape as Pro 2
    "beatsstudio": "beats.studiobuds.chargingcase.svg",
    "airpodsMax": None,  # headphones: no case
    "beatssolo": None,  # headphones: no case
}


def render(source: Path, out: Path) -> list[Path]:
    """Render every mapped symbol found in ``source``; returns the PNGs written."""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (Qt needs one)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, symbol in CASE_SYMBOLS.items():
        if symbol is None:
            continue
        svg = source / symbol
        if not svg.is_file():
            print(f"{name}: {symbol} not found in {source}, skipped", flush=True)
            continue
        renderer = QSvgRenderer(str(svg))
        if not renderer.isValid():
            print(f"{name}: {symbol} isn't a valid SVG, skipped", flush=True)
            continue
        size = renderer.defaultSize()
        width = round(size.width() * HEIGHT / size.height())
        pixmap = QPixmap(width, HEIGHT)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(QPointF(0, 0), QSizeF(width, HEIGHT)))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), TINT)  # one flat tint, keeping the symbol's shape
        painter.end()
        target = out / f"{name}_case.png"
        pixmap.save(str(target))
        written.append(target)
        print(f"{name}: {symbol} -> {target.name} ({width}x{HEIGHT})", flush=True)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="?", default=SYMBOLS, help="folder with the SF Symbol SVGs")
    parser.add_argument("--out", type=Path, default=None, help="where to write (default: PodPop's HUD folder)")
    args = parser.parse_args()
    render(args.source, args.out or hud_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())


