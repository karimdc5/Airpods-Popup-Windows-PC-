"""Renders the AirPods Pro model's artwork with Blender: the intro and the stills.

Model: "AirPods Pro" by Jed Falcone (https://sketchfab.com/3d-models/airpods-pro-3f84ddc3d87a4ec0a5e5f379abfecd9c),
licensed CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Rendered here
with our own camera, lighting and framing.

Writes, on transparent backgrounds:
    intro/0001.png ...   the model's own animation (the lid opens, the buds come out)
    intro_end_buds.png   its last frame, buds only (same camera)
    intro_end_case.png   its last frame, case only
    buds.png             the buds on their own, front-on, after they came out
    case.png             the closed case, front-on

Run inside Blender (portable is fine), after "--":
    blender -b -P scripts/render_model.py -- airpods_pro.glb OUT_DIR [--preview]
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUT = Path(argv[0]), Path(argv[1])
PREVIEW = "--preview" in argv
OUT.mkdir(parents=True, exist_ok=True)

INTRO_SIZE = (496, 260)  # 2x the popup's art row (248 x 130)
STILL_HEIGHT = 260  # 2x the 130 px art height
FPS = 30
# The model's animation (24 fps, 148 frames) is a loop: the lid opens (13-37),
# the buds rise out (37-67), hold, then everything goes back. The intro uses
# the way out only, ending once the buds are clear of the case.
INTRO_START = 10  # the lid starts moving at 13; skip most of the still lead-in
INTRO_END = 49
BUDS_OUT = 67  # pose for the buds still: fully out, facing front
ELEVATION_DEG = 20

# ------------------------------------------------------------------ scene

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(GLB))
scene = bpy.context.scene

action_end = 0.0
for obj in bpy.data.objects:
    if obj.animation_data and obj.animation_data.action:
        action_end = max(action_end, obj.animation_data.action.frame_range[1])
scene.render.fps = 24  # the importer keys at 24 fps; we resample when writing
scene.frame_start, scene.frame_end = 1, max(2, round(action_end))


def find(name):
    return next(o for o in bpy.data.objects if o.name == name)


case_root, buds_root = find("Case_1"), find("Airpods")


def meshes_under(root):
    out = [root] if root.type == "MESH" else []
    for child in root.children_recursive:
        if child.type == "MESH":
            out.append(child)
    return out


def bbox(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


# Render settings: Eevee, transparent film, soft studio look.
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "AgX"  # rolls highlights off instead of clipping to flat white
scene.view_settings.look = "AgX - Medium High Contrast"
scene.eevee.taa_render_samples = 16 if PREVIEW else 64
scene.eevee.use_shadows = True

world = bpy.data.worlds.new("Studio")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
bg.inputs["Strength"].default_value = 0.55  # soft even fill; the lights do the shaping


def light(name, kind, energy, location, size=1.0):
    data = bpy.data.lights.new(name, kind)
    data.energy = energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    obj.rotation_euler = (Vector((0, 0, 0)) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(obj)
    return obj


camera_data = bpy.data.cameras.new("Camera")
camera_data.type = "ORTHO"
camera = bpy.data.objects.new("Camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera


def aim(center: Vector, extent: Vector, size: tuple[int, int], margin: float = 1.08):
    """Front view (from -Y, a little above), framing a box of ``extent`` around ``center``."""
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    elevation = math.radians(ELEVATION_DEG)
    distance = 10 * max(extent)
    camera.location = center + Vector((0, -math.cos(elevation), math.sin(elevation))) * distance
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    aspect = size[0] / size[1]
    camera_data.ortho_scale = margin * max(extent.x, extent.z * aspect)
    camera_data.clip_end = distance * 3


def setup_lights(center: Vector, extent: Vector):
    for obj in [o for o in bpy.data.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(obj)
    r = max(extent) * 3
    watts = 26 * r * r  # constant brightness at the subject whatever its size
    light("Key", "AREA", watts, center + Vector((-r, -r, r * 1.1)), size=r * 0.8)
    light("Fill", "AREA", watts * 0.35, center + Vector((r, -r * 0.8, r * 0.2)), size=r)
    light("Rim", "AREA", watts * 0.5, center + Vector((0, r, r * 0.8)), size=r * 0.6)


def show(objs_visible):
    keep = set(objs_visible)
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in keep


def render_to(path: Path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


case_meshes, bud_meshes = meshes_under(case_root), meshes_under(buds_root)
all_meshes = case_meshes + bud_meshes

# --- the intro: frame everything the way out covers (closed case to buds out)
lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
for f in range(INTRO_START, INTRO_END + 1, 4):
    scene.frame_set(f)
    flo, fhi = bbox(all_meshes)
    lo, hi = Vector(map(min, lo, flo)), Vector(map(max, hi, fhi))
center, extent = (lo + hi) / 2, hi - lo
aim(center, extent, INTRO_SIZE)
setup_lights(center, extent)
show(all_meshes)
total = INTRO_END - INTRO_START
count = 6 if PREVIEW else round(total / 24 * FPS) + 1
for i in range(count):
    frame = INTRO_START + total * i / max(count - 1, 1)
    scene.frame_set(int(frame), subframe=frame - int(frame))
    render_to(OUT / "intro" / f"{i + 1:04d}.png")

# --- the intro's last moment as two layers, same camera: the popup moves them
# from here to their places in the layout (buds left, case right)
scene.frame_set(INTRO_END)
show(bud_meshes)
render_to(OUT / "intro_end_buds.png")
show(case_meshes)
render_to(OUT / "intro_end_case.png")

# --- the buds alone, as they end up after coming out
scene.frame_set(BUDS_OUT)
show(bud_meshes)
lo, hi = bbox(bud_meshes)
center, extent = (lo + hi) / 2, hi - lo
aim(center, extent, (round(STILL_HEIGHT * max(extent.x / extent.z, 0.6)), STILL_HEIGHT), margin=1.04)
setup_lights(center, extent)
render_to(OUT / "buds.png")

# --- the closed case alone
scene.frame_set(scene.frame_start)
show(case_meshes)
lo, hi = bbox(case_meshes)
center, extent = (lo + hi) / 2, hi - lo
aim(center, extent, (round(STILL_HEIGHT * extent.x / extent.z), STILL_HEIGHT), margin=1.04)
setup_lights(center, extent)
render_to(OUT / "case.png")
print("done", count, "intro frames")
