"""Renders the AirPods Pro model with Blender and packs it into the app's assets.

Runs scripts/render_model.py inside Blender, then turns its output into what
the popup loads from src/podpop/assets/model/:

    pro_intro.webp   the intro, played once as the popup appears (animated WebP)
    pro_buds.png     the buds, front-on, shown afterwards
    pro_case.png     the closed case, shown beside them
    pro_intro_end_buds.png / pro_intro_end_case.png
                     the intro's last frame split into buds and case, so the
                     popup can move each one to its place in the layout

Model: "AirPods Pro" by Jed Falcone, CC BY 4.0; see src/podpop/assets/model/CREDITS.md.

Usage:  .\.venv\Scripts\python scripts\make_model_assets.py BLENDER_EXE MODEL.glb
Needs Pillow (dev only) and Blender 4.2.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "podpop" / "assets" / "model"
FRAME_MS = 33  # 30 fps, as rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("blender", type=Path, help="path to blender.exe")
    parser.add_argument("model", type=Path, help="the AirPods Pro .glb from Sketchfab")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        render = Path(tmp)
        subprocess.run(
            [str(args.blender), "-b", "-P", str(ROOT / "scripts" / "render_model.py"), "--", str(args.model), str(render)],
            check=True,
        )
        OUT.mkdir(parents=True, exist_ok=True)
        frames = [Image.open(f).convert("RGBA") for f in sorted((render / "intro").glob("*.png"))]
        target = OUT / "pro_intro.webp"
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=1,
                       quality=92, method=6)
        print(f"{target.name}: {len(frames)} frames, {target.stat().st_size // 1024} KB")
        for name in ("buds", "case", "intro_end_buds", "intro_end_case"):
            shutil.copyfile(render / f"{name}.png", OUT / f"pro_{name}.png")
            print(f"pro_{name}.png")
        # Where each piece sits in the intro's last frame (alpha bounding box,
        # in frame pixels), so the popup can move it from there into the layout.
        layout = {"frame": list(frames[0].size)}
        for part in ("buds", "case"):
            box = Image.open(render / f"intro_end_{part}.png").getchannel("A").getbbox()
            layout[part] = [box[0], box[1], box[2] - box[0], box[3] - box[1]]
        (OUT / "pro_intro_end.json").write_text(json.dumps(layout), encoding="utf-8")
        print("pro_intro_end.json", layout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
