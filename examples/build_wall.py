# Example: Leo builds a brick wall (spawned bricks), Maya carries a box onto a step and jumps up.
# Run: OUT=/tmp blender -b --factory-startup -P examples/build_wall.py   (renders 4 frames to $OUT)

import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csk360; csk360.register()
from csk360 import commands, world, render
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; sc.render.fps = 24; sc.frame_end = 400
leo = commands.add_starter_character(sc, "Leo", location=(-0.6, -1.0, 0))
maya = commands.add_starter_character(sc, "Maya", location=(1.8, -1.2, 0))
bpy.ops.mesh.primitive_cube_add(size=1, location=(20, 20, 0.1)); b = bpy.context.active_object; b.name = "Brick"; b.scale = (0.4, 0.2, 0.2)
m = bpy.data.materials.new("brick"); m.diffuse_color = (0.65, 0.25, 0.15, 1); b.data.materials.append(m)
bpy.ops.mesh.primitive_cube_add(size=1, location=(2.6, 0.2, 0.2)); s = bpy.context.active_object; s.name = "Step"; s.scale = (0.7, 0.7, 0.4)
bpy.ops.mesh.primitive_cube_add(size=0.3, location=(1.2, -0.3, 0.15)); bx = bpy.context.active_object; bx.name = "Box"
mb = bpy.data.materials.new("box"); mb.diffuse_color = (0.8, 0.6, 0.3, 1); bx.data.materials.append(mb)
world.detect(sc)
world.label(b, liftable=True, weight=3)
t = 0.5
for row in range(3):
    for i in range(4):
        x = -1.0 + i * 0.42 + (0.21 if row % 2 else 0)
        commands.spawn(sc, "Brick", start=t, location=(x, 0.5, row * 0.2), by=leo)
        t += 0.45
commands.add_clip(sc, leo, "cheer", start=t + 0.3)
commands.pick_up(sc, maya, "Box", start=0.5)
e = max(mm.start + mm.duration for mm in sc.csk360.moves if mm.cast_id == maya)
commands.put_down(sc, maya, at="Step", start=e + 0.3)
c = sc.csk360.carries[0]
commands.add_move(sc, maya, start=c.end + 0.4, target="Step", jump=True, arrival="cheer")
print("report:", sc.csk360.last_report, "end", t)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.location = (2.2, -6.0, 2.4); cam.rotation_euler = (Vector((0.6, 0.0, 0.6)) - cam.location).to_track_quat("-Z","Y").to_euler()
cam.data.lens = 30; sc.camera = cam
render.ensure_stage(sc)
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = 960, 540
out = os.environ["OUT"]
for i, tt in enumerate([1.2, 3.0, 5.0, 6.8]):
    sc.frame_set(sc.frame_start + round(tt * 24))
    sc.render.filepath = os.path.join(out, f"build_{i}.png")
    bpy.ops.render.render(write_still=True)
