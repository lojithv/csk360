# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert Quaternius' RobotExpressive (CC0) into CSK360's starter robot asset.

    blender -b --factory-startup -P tools/make_robot.py -- RobotExpressive.glb csk360/assets/robot.blend

Source: three.js examples/models/gltf/RobotExpressive (model by Tomás Laulhé /
Quaternius, CC0 1.0; morph targets by Don McCurdy). The result is one mesh,
"csk360_robot", in CSK360's rest pose (arms down, facing -Y, feet at z=0,
HEIGHT tall), with one vertex group per CSK360 bone, and the joint positions
CSK360 builds its skeleton from stored on the mesh as "csk360_joints".
"""

import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
HEIGHT = 1.7
ARM_OUT = math.radians(12)       # arms hang this far out from vertical
ELBOW_BEND = math.radians(40)    # forearms bend forward this much at rest       # T-pose arms rotated down to CSK360's rest

# RobotExpressive bone -> CSK360 bone
BONE_MAP = {"Bone": "root", "Body": "hips", "Hips": "hips", "Abdomen": "spine", "Torso": "chest",
            "Neck": "neck", "Head": "head"}
for s in ("L", "R"):
    BONE_MAP.update({f"Shoulder.{s}": f"shoulder_{s}", f"UpperArm.{s}": f"upper_arm_{s}",
                     f"LowerArm.{s}": f"forearm_{s}", f"UpperLeg.{s}": f"thigh_{s}",
                     f"LowerLeg.{s}": f"shin_{s}", f"Foot.{s}": f"foot_{s}"})
    for f in ("Palm1", "Palm2", "Palm3", "Middle1", "Middle2", "Thumb", "Thumb2", "Index",
              "Index2", "Ring1", "Ring2"):
        BONE_MAP[f"{f}.{s}"] = f"hand_{s}"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src, bone_heuristic="TEMPERANCE")  # parts misplace with the default
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
# The bind pose is not usable (legs rely on IK the glTF bakes into its clips), so
# start from the first frame of the model's own Idle clip.
arm.animation_data.action = bpy.data.actions["Idle"]
bpy.context.scene.frame_set(int(bpy.data.actions["Idle"].frame_range[0]))
bpy.context.view_layer.update()
arm.animation_data.action = None    # keep the evaluated pose as it is now
for pb in arm.pose.bones:
    pb.matrix_basis = pb.matrix_basis.copy()
bpy.context.view_layer.update()
W = arm.matrix_world


def world_head(name):
    return W @ arm.pose.bones[name].head


def aim(bone, child, direction):
    """Rotate `bone` about its head (world space) so its head->child joint points along direction."""
    pb = arm.pose.bones[bone]
    h, c = world_head(bone), world_head(child)
    rot = (c - h).normalized().rotation_difference(Vector(direction).normalized()).to_matrix().to_4x4()
    m = Matrix.Translation(h) @ rot @ Matrix.Translation(-h)
    pb.matrix = W.inverted() @ m @ W @ pb.matrix
    bpy.context.view_layer.update()


# CSK360's rest pose: arms hanging straight down, slightly out from the body.
for side, sx in (("L", 1.0), ("R", -1.0)):
    down = (sx * math.sin(ARM_OUT), 0.0, -math.cos(ARM_OUT))
    aim(f"UpperArm.{side}", f"LowerArm.{side}", down)
    # The robot's forearms are long; a relaxed forward bend keeps the hands off the floor.
    fwd = (down[0], -math.sin(ELBOW_BEND), -math.cos(ELBOW_BEND))
    aim(f"LowerArm.{side}", f"Palm2.{side}", fwd)

dg = bpy.context.evaluated_depsgraph_get()
bm = bmesh.new()
deform = bm.verts.layers.deform.verify()
groups = sorted(set(BONE_MAP.values()))
gi = {g: i for i, g in enumerate(groups)}
mats = []

parts = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is not None]
torso_split = (world_head("Torso").z + world_head("Abdomen").z) / 2
for ob in parts:
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    me.transform(ev.matrix_world)
    base = len(bm.verts)
    slots = [sl.material for sl in ob.material_slots]   # originals, not evaluated copies
    for m in slots:
        if m not in mats:
            mats.append(m)
    mat_index = [mats.index(m) for m in slots]
    tmp = bmesh.new()
    tmp.from_mesh(me)
    for f in tmp.faces:
        f.material_index = mat_index[f.material_index]
    tmp.verts.index_update()
    # Weights: skinned parts map their groups; rigid parts follow their parent bone.
    weights = []
    for v in me.vertices:
        w = {}
        if ob.parent_type == "BONE":
            b = BONE_MAP.get(ob.parent_bone, "chest")
            if ob.name == "Torso":
                b = "chest" if v.co.z > torso_split else "spine"
            w[b] = 1.0
        else:
            for g in v.groups:
                name = BONE_MAP.get(ob.vertex_groups[g.group].name)
                if name and g.weight > 0:
                    w[name] = w.get(name, 0.0) + g.weight
        total = sum(w.values()) or 1.0
        weights.append({k: x / total for k, x in w.items()})
    tmp_mesh = bpy.data.meshes.new("tmp")
    tmp.to_mesh(tmp_mesh)
    tmp.free()
    bm.from_mesh(tmp_mesh)
    bm.verts.ensure_lookup_table()
    for i, w in enumerate(weights):
        bm.verts[base + i][deform].clear()   # drop the source model's own groups
        for k, x in w.items():
            bm.verts[base + i][deform][gi[k]] = x
    bpy.data.meshes.remove(tmp_mesh)
    ev.to_mesh_clear()

# Normalise: feet on the floor, centred, HEIGHT tall, facing -Y.
bm.verts.ensure_lookup_table()
lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
scale = HEIGHT / (hi.z - lo.z)
offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
face_y = -1.0   # glTF +Z forward imports as Blender -Y
norm = Matrix.Diagonal((scale, scale, scale, 1.0)) @ Matrix.Translation(-offset)
bmesh.ops.transform(bm, matrix=norm, verts=bm.verts)


def J(name, tail=False):
    pb = arm.pose.bones[name]
    p = W @ (pb.tail if tail else pb.head)
    return tuple(round(c, 4) for c in norm @ p)


joints = {"hips": J("UpperLeg.L")[2], "abdomen": J("Abdomen")[2], "torso": J("Torso")[2],
          "neck": J("Neck")[2], "head": J("Head")[2], "top": round((hi.z - lo.z) * scale, 4)}
for s in ("L",):
    joints.update({"shoulder": J(f"Shoulder.{s}"), "upper_arm": J(f"UpperArm.{s}"),
                   "forearm": J(f"LowerArm.{s}"), "hand": J(f"Palm2.{s}"),
                   "hand_tip": J(f"Middle2.{s}"), "thigh": J(f"UpperLeg.{s}"),
                   "shin": J(f"LowerLeg.{s}"), "foot": J(f"Foot.{s}")})

mesh = bpy.data.meshes.new("csk360_robot")
bm.to_mesh(mesh)
bm.free()
for m in mats:
    mesh.materials.append(m)
for p in mesh.polygons:
    p.use_smooth = False
mesh["csk360_joints"] = joints
mesh["csk360_groups"] = groups
mesh["csk360_source"] = ("RobotExpressive by Tomás Laulhé (Quaternius), CC0 1.0; "
                         "morph targets by Don McCurdy; via three.js examples")
mesh.use_fake_user = True
for m in mats:
    m.use_fake_user = True
print("JOINTS", joints)
print("SIZE", [round((hi[i] - lo[i]) * scale, 3) for i in range(3)], "verts", len(mesh.vertices))
bpy.data.libraries.write(dst, {mesh, *mats}, compress=True)
print("WROTE", dst)
