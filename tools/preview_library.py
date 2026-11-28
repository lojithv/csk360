# SPDX-License-Identifier: GPL-3.0-or-later
"""Render every starter library asset on its own starter character, in a grid.

    blender -b --factory-startup -P tools/preview_library.py -- out.png
"""

import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import csk360  # noqa: E402
from csk360 import commands, starter  # noqa: E402

out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(ROOT, "dist", "library.png")
csk360.register()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 24
RENDER_FRAME = 40
# Frame inside each action that shows it best.
SHOW = {"wave": 20, "shrug": 12, "clap": 5, "nod": 7, "shake_head": 6, "look_around": 20,
        "talk_hands": 13, "jump": 13, "run": 5, "walk": 7, "idle": 1}
names = list(starter.STARTER_ASSETS)
cols = 7
rows = math.ceil(len(names) / cols)
for i, name in enumerate(names):
    x, z = (i % cols) * 1.45, (rows - 1 - i // cols) * 2.2
    cid = commands.add_starter_character(scene, name.replace("_", " ").title(), location=(x, 0, z))
    c = commands.get_cast(scene, cid)
    c.auto_life = False
    c.object.rotation_euler.z = math.radians(-40)  # three-quarter view
    start = (RENDER_FRAME - SHOW.get(name, 10)) / 24
    commands.add_clip(scene, cid, name, start=start, duration=6, blend_in=0)
    txt = bpy.data.curves.new(name, "FONT")
    txt.body = name
    txt.size = 0.16
    txt.align_x = "CENTER"
    t = bpy.data.objects.new("label_" + name, txt)
    t.location = (x, -0.5, z - 0.25)
    t.rotation_euler = (math.radians(90), 0, 0)
    scene.collection.objects.link(t)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(cols * 1.45 + 0.4, rows * 2.2 * 1800 / 1100)
cam.location = ((cols - 1) * 1.45 / 2, -12, 0.85 + (rows - 1) * 1.1)
cam.rotation_euler = (math.radians(90), 0, 0)
world = bpy.data.worlds.new("w")
world.color = (0.55, 0.57, 0.62)
scene.world = world
scene.camera = cam
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x, scene.render.resolution_y = 1800, 1100
scene.frame_set(scene.frame_start + RENDER_FRAME)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("wrote", out)
