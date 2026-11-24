# SPDX-License-Identifier: GPL-3.0-or-later
"""Render a contact sheet of the starter character's library, for a quick visual check.

    blender -b --factory-startup -P tools/preview_starter.py -- out.png
"""

import os
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import csk360  # noqa: E402
from csk360 import commands  # noqa: E402

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(ROOT, "dist", "preview.png")
csk360.register()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 24
leo = commands.add_starter_character(scene, "Leo")
commands.add_clip(scene, leo, "walk", start=0, duration=1, blend_in=0)
commands.add_clip(scene, leo, "sit", start=1, duration=1, blend_in=0)
commands.add_clip(scene, leo, "wave", start=2, duration=1.5, blend_in=0)
commands.add_clip(scene, leo, "arms_crossed", start=3.5, duration=1.5, blend_in=0)
commands.add_line(scene, leo, "Ah", start=5, visemes=[(0, "D"), (0.5, "F"), (1.0, "X")], duration=1.0)

shots = [(1, "walk 1"), (7, "walk 7"), (13, "walk 13"), (37, "sit"),
         (58, "wave up"), (66, "wave"), (100, "arms crossed"), (121, "mouth D")]

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (2.4, -3.4, 1.3)
target = Vector((0, 0, 0.8))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 40
scene.camera = cam
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x = scene.render.resolution_y = 320
scene.render.image_settings.file_format = "PNG"
tmp = os.path.join(os.path.dirname(os.path.abspath(out)), "_frames")
os.makedirs(tmp, exist_ok=True)

tiles = []
for frame, label in shots:
    scene.frame_set(frame)
    path = os.path.join(tmp, f"{frame:04d}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    tiles.append(px)
    bpy.data.images.remove(img)
    print(f"rendered {label} (frame {frame})")

cols = 4
rows = (len(tiles) + cols - 1) // cols
h, w = tiles[0].shape[:2]
sheet = np.ones((rows * h, cols * w, 4), dtype=np.float32)
for i, t in enumerate(tiles):
    r, c = divmod(i, cols)
    sheet[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = t
img = bpy.data.images.new("sheet", cols * w, rows * h, alpha=True)
img.pixels = sheet.ravel()
img.filepath_raw = out
img.file_format = "PNG"
img.save()
print("saved", out)
