"""Records the popup's opening animation to docs/images/demo.gif for the README.

Usage:  .\\.venv\\Scripts\\python scripts\\make_demo_gif.py [--theme dark|light]
Needs Pillow (pip install pillow); the app itself doesn't.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QBuffer, QIODevice, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from podpop.catalog import Family  # noqa: E402
from podpop.demo import _SAMPLE_MODELS, sample_snapshot  # noqa: E402
from podpop.presenter import build_view  # noqa: E402
from podpop.ui.popup import PopupWindow  # noqa: E402
from podpop.ui.theme import DARK, LIGHT  # noqa: E402

FRAME_MS = 40  # 25 fps
RECORD_MS = 3600  # the slide-in, the case opening and the battery rings
HOLD_MS = 2200  # pause on the finished card before the GIF loops
PAD = 36
BACKDROP = ((38, 44, 92), (112, 58, 120))  # top-left -> bottom-right, readable on light and dark pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "images" / "demo.gif")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    popup = PopupWindow(DARK if args.theme == "dark" else LIGHT)
    _, name = _SAMPLE_MODELS[Family.PRO]
    frames: list[Image.Image] = []

    def grab() -> None:
        frames.append(_to_pil(popup.grab().toImage()))
        if len(frames) * FRAME_MS >= RECORD_MS:
            timer.stop()
            app.quit()

    timer = QTimer(interval=FRAME_MS)
    timer.timeout.connect(grab)
    popup.present(build_view(sample_snapshot(Family.PRO), name, connected=True), duration_s=0)
    timer.start()
    app.exec()

    backdrop = _backdrop(frames[0].size)
    scenes = [_compose(backdrop, f) for f in frames]
    durations = [FRAME_MS] * (len(scenes) - 1) + [HOLD_MS]
    scenes[0].save(
        args.out, save_all=True, append_images=scenes[1:], duration=durations, loop=0, optimize=True, disposal=1
    )
    print(f"Wrote {args.out} ({len(scenes)} frames, {args.out.stat().st_size // 1024} KB)")
    return 0


def _to_pil(image) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    from io import BytesIO

    return Image.open(BytesIO(bytes(buffer.data()))).convert("RGBA")


def _backdrop(size: tuple[int, int]) -> Image.Image:
    w, h = size[0] + 2 * PAD, size[1] + 2 * PAD
    (r0, g0, b0), (r1, g1, b1) = BACKDROP
    base = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(base)
    for y in range(h):  # diagonal-ish gradient: blend by row, then soften
        t = y / max(h - 1, 1)
        draw.line([(0, y), (w, y)], fill=(int(r0 + (r1 - r0) * t), int(g0 + (g1 - g0) * t), int(b0 + (b1 - b0) * t)))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([w * 0.55, -h * 0.3, w * 1.3, h * 0.6], fill=(70, 120, 200))
    return Image.blend(base, glow.filter(ImageFilter.GaussianBlur(60)), 0.35).convert("RGBA")


def _compose(backdrop: Image.Image, frame: Image.Image) -> Image.Image:
    scene = backdrop.copy()
    scene.alpha_composite(frame, (PAD, PAD))
    return scene.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)


if __name__ == "__main__":
    raise SystemExit(main())
