"""Imports HUD artwork into PodPop's private folder (%APPDATA%\\PodPop\\hud).

Takes a folder of ``<name>_spin.png`` (animated PNG, played once),
``<name>_still.png`` (the pose afterwards) and ``<name>_case.png`` (the case
beside the buds). Qt can't animate APNG, so each spin is re-encoded as a
lossless animated WebP with the same frames, timing and transparency; stills
and cases are copied as they are. Then the case symbols are rendered (see
scripts/render_case.py) from ``--symbols``, by default
``src/podpop/assets/symbols``. With ``--fetch`` and no SVGs there yet, they're
downloaded first (scripts/fetch_symbols.py). Nothing goes into the repository.

Usage:  .\\.venv\\Scripts\\python scripts\\import_hud.py C:\\path\\to\\hud [--fetch] [--symbols DIR]
Needs Pillow (dev only).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from podpop.ui.hud import hud_dir  # noqa: E402

import fetch_symbols  # noqa: E402  (these two sit next to this script)
import render_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="folder with *_spin.png, *_still.png and *_case.png")
    parser.add_argument("--symbols", type=Path, default=render_case.SYMBOLS, help="folder with the case SVGs")
    parser.add_argument("--fetch", action="store_true", help="download the case SVGs first if the folder has none")
    args = parser.parse_args()
    out = hud_dir()
    out.mkdir(parents=True, exist_ok=True)

    for spin in sorted(args.source.glob("*_spin.png")):
        with Image.open(spin) as im:
            frames, durations = [], []
            for frame in ImageSequence.Iterator(im):
                frames.append(frame.convert("RGBA").copy())
                durations.append(round(frame.info.get("duration", 1000 / 60)))
        target = out / f"{spin.stem}.webp"
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                       lossless=True, method=4)
        print(f"{spin.name}: {len(frames)} frames, {sum(durations) / 1000:.1f} s -> {target.name}", flush=True)

    for still in sorted(args.source.glob("*_still.png")):
        shutil.copyfile(still, out / still.name)
        print(f"{still.name} -> copied", flush=True)

    for case in sorted(args.source.glob("*_case.png")):
        shutil.copyfile(case, out / case.name)
        print(f"{case.name} -> copied", flush=True)

    if args.fetch and not any(args.symbols.glob("*.svg")):
        if args.symbols.resolve() != render_case.SYMBOLS.resolve():
            print(f"--fetch downloads into {render_case.SYMBOLS}, not {args.symbols}", flush=True)
        if fetch_symbols.main() != 0:  # reports what failed; render whatever did arrive
            print("Some case symbols couldn't be downloaded; continuing with the rest", flush=True)

    if args.symbols.is_dir():
        render_case.render(args.symbols, out)
    else:
        print(f"No case symbols at {args.symbols}; skipped rendering cases", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
