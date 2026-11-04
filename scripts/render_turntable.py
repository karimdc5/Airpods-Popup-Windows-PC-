"""Renders the 3D turntable frames the popup plays (src/podpop/assets/turntable).

The AirPods and cases are modelled as signed distance fields (spheres,
ellipsoids, capsules and rounded boxes blended together) and ray-marched with
numpy under soft studio lighting, one frame per angle of a full turn. Output
is one sprite sheet per model and part, e.g. ``pro_buds.png``, ``pro_case.png``:
frames left to right, top to bottom, ``COLS`` per row.

Usage:  .\\.venv\\Scripts\\python scripts\\render_turntable.py [--preview]
Needs numpy and Pillow (dev only); the app just loads the PNGs.
"""

from __future__ import annotations

import argparse
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "podpop" / "assets" / "turntable"

FRAMES = 96  # one full turn
COLS = 12
SUPERSAMPLE = 2
STEPS = 110
EPS = 0.02

# Materials
WHITE, SILICONE, BLACK, METAL, MESH, LED_GREEN, HINGE, GROOVE = range(8)
ALBEDO = {
    WHITE: (0.93, 0.93, 0.94),
    SILICONE: (0.80, 0.80, 0.82),
    BLACK: (0.06, 0.06, 0.07),
    METAL: (0.55, 0.56, 0.58),
    MESH: (0.42, 0.42, 0.44),
    LED_GREEN: (0.25, 0.95, 0.45),
    HINGE: (0.62, 0.63, 0.65),
    GROOVE: (0.70, 0.70, 0.72),
}
GLOSS = {WHITE: 0.55, SILICONE: 0.12, BLACK: 0.7, METAL: 1.0, MESH: 0.2, LED_GREEN: 0.2, HINGE: 0.8, GROOVE: 0.4}


# --------------------------------------------------------------- SDF primitives


def length(v):
    return np.sqrt(np.sum(v * v, axis=-1))


def sd_ellipsoid(p, r):
    k0 = length(p / r)
    k1 = length(p / (r * r))
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sd_capsule(p, a, b, r):
    pa, ba = p - a, b - a
    h = np.clip(np.sum(pa * ba, axis=-1) / np.dot(ba, ba), 0.0, 1.0)
    return length(pa - ba * h[..., None]) - r


def sd_pebble(p, half, r_xy, r_z):
    """A box rounded by ``r_xy`` in its face and ``r_z`` toward the front and back."""
    hx, hy, hz = half[0] - r_z, half[1] - r_z, half[2] - r_z
    qx = np.abs(p[..., 0]) - (hx - (r_xy - r_z))
    qy = np.abs(p[..., 1]) - (hy - (r_xy - r_z))
    rr = r_xy - r_z
    d2 = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - rr
    dz = np.abs(p[..., 2]) - hz
    return np.sqrt(np.maximum(d2, 0) ** 2 + np.maximum(dz, 0) ** 2) + np.minimum(np.maximum(d2, dz), 0) - r_z


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def rot_y(p, angle):
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    return np.stack([c * x + s * z, y, -s * x + c * z], axis=-1)


# ----------------------------------------------------------------- the models


@dataclass(frozen=True)
class BudShape:
    head: tuple  # ellipsoid radii
    head_at: tuple
    stem_top: float
    stem_bottom: float
    stem_r: float
    tip: bool  # silicone ear tip (Pro)
    tip_dir: tuple = (0.5, -0.05, 0.86)


BUDS = {
    "pro": BudShape(head=(8.6, 9.4, 9.0), head_at=(2.0, 4.6, 1.2), stem_top=-1.0, stem_bottom=-25.0, stem_r=2.7, tip=True,
                    tip_dir=(0.72, -0.24, 0.65)),
    "classic": BudShape(head=(8.2, 8.6, 8.4), head_at=(1.6, 5.0, 0.8), stem_top=-1.0, stem_bottom=-32.0, stem_r=2.6, tip=False),
    "open": BudShape(head=(8.8, 9.2, 8.8), head_at=(1.8, 4.6, 1.0), stem_top=-1.0, stem_bottom=-21.0, stem_r=2.6, tip=False),
}

CASES = {  # half extents (x, y, z), face corner radius, edge radius, seam height from the top
    "pro": ((30.0, 22.5, 10.8), 15.5, 10.2, 12.0),
    "classic": ((22.0, 27.0, 10.6), 12.0, 10.0, 10.0),
    "open": ((25.0, 23.0, 10.6), 17.0, 10.0, 12.0),
}


def bud_sdf(p, shape: BudShape):
    """One left bud, ear side facing +x and +z. Returns (distance, material)."""
    head_c = np.array(shape.head_at)
    d_head = sd_ellipsoid(p - head_c, np.array(shape.head))
    d_stem = sd_capsule(p, np.array([0.0, shape.stem_top, 0.0]), np.array([0.0, shape.stem_bottom, 0.0]), shape.stem_r)
    d = smin(d_head, d_stem, 3.0)
    mat = np.full(d.shape, WHITE, dtype=np.int8)

    tip_dir = np.array(shape.tip_dir) / np.linalg.norm(shape.tip_dir)
    if shape.tip:
        nozzle_c = head_c + tip_dir * 7.2
        local = p - nozzle_c
        # Ellipsoid squashed along the nozzle axis.
        along = np.sum(local * tip_dir, axis=-1)
        across = local - along[..., None] * tip_dir
        d_tip = np.sqrt((along / 4.2) ** 2 + np.sum(across**2, axis=-1) / 6.8**2) * 5.0 - 5.0
        d = smin(d, d_tip, 1.0)
        on_tip = (d_tip < np.minimum(d_head, d_stem) + 0.2) & (d_tip < 1.0)
        mat = np.where(on_tip, SILICONE, mat)
        # The dark mesh in the middle of the tip.
        mesh = on_tip & (along > 3.2) & (np.sum(across**2, axis=-1) < 2.5**2)
        mat = np.where(mesh, MESH, mat)
    else:
        # Speaker grille on the ear side of the head.
        g = head_c + tip_dir * shape.head[0] * 0.92
        mat = np.where(length((p - g) / np.array([2.2, 3.6, 2.2])) < 1.0, MESH, mat)

    # Top vent: a small black oval on the front-top of the head.
    vent = head_c + np.array([-2.2, 7.4, 3.6])
    mat = np.where((d_head < d_stem) & (length((p - vent) / np.array([3.0, 1.6, 1.5])) < 1.0), BLACK, mat)
    # Back sensor: a long black oval on the back of the head, above the stem.
    sensor = head_c + np.array([-2.0, -0.5, -8.6])
    mat = np.where((d_head < d_stem) & (length((p - sensor) / np.array([1.5, 3.8, 1.6])) < 1.0), BLACK, mat)
    # Metal mic ring at the bottom of the stem.
    mat = np.where((p[..., 1] < shape.stem_bottom + 2.0) & (d_stem < d_head + 0.5), METAL, mat)
    return d, mat


def buds_sdf(p, family):
    shape = BUDS[family]
    gap = 14.0
    dl, ml = bud_sdf(p - np.array([-gap, 0.0, 0.0]), shape)
    mirrored = p * np.array([-1.0, 1.0, 1.0])
    dr, mr = bud_sdf(mirrored - np.array([-gap, 0.0, 0.0]), shape)
    d = np.minimum(dl, dr)
    return d, np.where(dl <= dr, ml, mr)


def case_sdf(p, family):
    half, r_xy, r_z, seam_from_top = CASES[family]
    d = sd_pebble(p, half, r_xy, r_z)
    mat = np.full(d.shape, WHITE, dtype=np.int8)
    seam_y = half[1] - seam_from_top
    mat = np.where(np.abs(p[..., 1] - seam_y) < 0.22, GROOVE, mat)
    front = p[..., 2] > 0
    # Status light on the front.
    led_y = -1.0 if family != "classic" else -4.0
    mat = np.where(front & (np.hypot(p[..., 0], p[..., 1] - led_y) < 0.8), LED_GREEN, mat)
    back = p[..., 2] < 0
    # Hinge on the back, across the seam.
    hinge = back & (np.abs(p[..., 0]) < half[0] * 0.33) & (np.abs(p[..., 1] - seam_y) < 2.6)
    mat = np.where(hinge, HINGE, mat)
    # Setup button ring on the back.
    ring = np.hypot(p[..., 0], p[..., 1] - (seam_y - 13.0))
    mat = np.where(back & (np.abs(ring - 3.0) < 0.22), GROOVE, mat)
    return d, mat


# ------------------------------------------------------------------- renderer


def render(kind: str, family: str, angle: float, size: tuple[int, int], scale: float) -> np.ndarray:
    """RGBA uint8 image of the model turned ``angle`` radians."""
    w, h = size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE
    sdf = (lambda q: buds_sdf(q, family)) if kind == "buds" else (lambda q: case_sdf(q, family))
    center_y = -6.0 if kind == "buds" else 0.0

    # Camera: slightly above, gentle perspective.
    elev = math.radians(8.0)
    dist = 260.0
    cam = np.array([0.0, center_y + dist * math.sin(elev), dist * math.cos(elev)])
    target = np.array([0.0, center_y, 0.0])
    fwd = (target - cam) / np.linalg.norm(target - cam)
    right = np.cross(fwd, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    xs = (np.arange(w) + 0.5 - w / 2) / scale / SUPERSAMPLE
    ys = (h / 2 - np.arange(h) - 0.5) / scale / SUPERSAMPLE
    gx, gy = np.meshgrid(xs, ys)
    focus = dist  # image plane through the target
    dirs = fwd * focus + right * gx[..., None] + up * gy[..., None]
    dirs /= length(dirs)[..., None]
    rays = dirs.reshape(-1, 3)
    origin = np.broadcast_to(cam, rays.shape)

    def scene(q):
        return sdf(rot_y(q, -angle))

    t = np.full(len(rays), dist - 60.0)
    hit = np.zeros(len(rays), bool)
    alive = np.ones(len(rays), bool)
    for _ in range(STEPS):
        idx = np.nonzero(alive)[0]
        if len(idx) == 0:
            break
        q = origin[idx] + rays[idx] * t[idx, None]
        d, _ = scene(q)
        t[idx] += d * 0.9
        done = d < EPS
        hit[idx[done]] = True
        far = t[idx] > dist + 80.0
        alive[idx[done | far]] = False

    rgb = np.ones((len(rays), 3))
    alpha = hit.astype(float)
    idx = np.nonzero(hit)[0]
    if len(idx):
        q = origin[idx] + rays[idx] * t[idx, None]
        _, mat = scene(q)
        e = 0.03
        n = np.stack(
            [scene(q + np.array(o))[0] - scene(q - np.array(o))[0] for o in ((e, 0, 0), (0, e, 0), (0, 0, e))], axis=-1
        )
        n /= np.maximum(length(n), 1e-9)[..., None]
        # Ambient occlusion: how open the space just outside the surface is.
        ao = np.ones(len(idx))
        for i, step in enumerate((0.6, 1.4, 2.6, 4.2)):
            ds, _ = scene(q + n * step)
            ao -= (step - ds) / step * 0.5 ** (i + 1) * 0.9
        ao = np.clip(ao, 0.0, 1.0)

        view = -rays[idx]
        albedo = np.array([ALBEDO[m] for m in range(8)])[mat]
        gloss = np.array([GLOSS[m] for m in range(8)])[mat]
        key = np.array([-0.45, 0.75, 0.55])
        key /= np.linalg.norm(key)
        fill = np.array([0.7, 0.15, 0.65])
        fill /= np.linalg.norm(fill)
        diffuse = 0.5 * np.clip(np.sum(n * key, -1), 0, 1) + 0.22 * np.clip(np.sum(n * fill, -1), 0, 1)
        sky = 0.52 + 0.14 * n[:, 1]  # bright studio dome above, soft grey bounce below
        light = (diffuse + sky) * (0.55 + 0.45 * ao)
        half = key + view
        half /= length(half)[..., None]
        spec = np.clip(np.sum(n * half, -1), 0, 1)
        fresnel = (1 - np.clip(np.sum(n * view, -1), 0, 1)) ** 4
        shine = gloss * (0.55 * spec**80 + 0.12 * spec**10) + gloss * 0.22 * fresnel * ao
        led = (mat == LED_GREEN)[:, None]
        color = albedo * light[:, None] + shine[:, None]
        color = np.where(led, np.array(ALBEDO[LED_GREEN]) * 1.15, color)
        rgb[idx] = np.clip(color, 0, 1) ** (1 / 1.15)

    img = np.concatenate([rgb, alpha[:, None]], axis=-1).reshape(h, w, 4)
    # Supersampled -> final size, premultiplied while averaging so edges stay clean.
    img[..., :3] *= img[..., 3:4]
    img = img.reshape(size[1], SUPERSAMPLE, size[0], SUPERSAMPLE, 4).mean(axis=(1, 3))
    a = img[..., 3:4]
    img[..., :3] = np.where(a > 0, img[..., :3] / np.maximum(a, 1e-6), 1.0)
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


SIZES = {"buds": ((220, 190), 3.6), "case": ((220, 170), 3.0)}
CLASSIC_SIZES = {"buds": ((220, 220), 3.4), "case": ((200, 200), 3.0)}


def _frame(args):
    kind, family, i = args
    (size, scale) = (CLASSIC_SIZES if family == "classic" else SIZES)[kind]
    angle = 2 * math.pi * i / FRAMES
    return i, render(kind, family, angle, size, scale)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="render 4 angles of the Pro only, to a scratch PNG")
    parser.add_argument("--families", default="pro,classic,open")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    if args.preview:
        tiles = [render(kind, "pro", math.radians(a), *SIZES[kind]) for kind in ("buds", "case") for a in (0, 50, 90, 180)]
        h = max(t.shape[0] for t in tiles)
        sheet = Image.new("RGBA", (sum(t.shape[1] for t in tiles[:4]), 2 * h), (255, 255, 255, 255))
        for k, tile in enumerate(tiles):
            im = Image.fromarray(tile, "RGBA")
            x = sum(t.shape[1] for t in tiles[(k // 4) * 4 : k])
            sheet.alpha_composite(im, (x, (k // 4) * h))
        sheet.save(args.out)
        print(f"Wrote {args.out}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as pool:  # each render holds a few hundred MB
        for family in args.families.split(","):
            for kind in ("buds", "case"):
                frames = [None] * FRAMES
                for i, img in pool.map(_frame, [(kind, family, i) for i in range(FRAMES)]):
                    frames[i] = img
                fh, fw = frames[0].shape[:2]
                rows = math.ceil(FRAMES / COLS)
                sheet = Image.new("RGBA", (fw * COLS, fh * rows), (0, 0, 0, 0))
                for i, img in enumerate(frames):
                    sheet.paste(Image.fromarray(img, "RGBA"), ((i % COLS) * fw, (i // COLS) * fh))
                path = args.out / f"{family}_{kind}.png"
                sheet.save(path, optimize=True)
                print(f"Wrote {path} ({path.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
