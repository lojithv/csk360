# SPDX-License-Identifier: GPL-3.0-or-later
"""Starter 3D toon character (`biped_toon`) and starter library actions.

Generated entirely from code so CSK360 is usable before any art exists:
one armature with the standard `biped_toon` bone names, one simple toon body
mesh weighted 100% per part (no weight painting), mouth shape keys driven by
the rig's `mouth` control, and a handful of library actions.

Characters face -Y (Blender's front view). Units are metres.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import library
from .model import MOUTH_SHAPES

RIG_TYPE = "biped_toon"
MOUTH_PROP = "mouth"

# name: (head, tail, parent). Left side is +X; right side is mirrored.
_CENTER_BONES = {
    "root": ((0, 0, 0), (0, 0.25, 0), None),
    "hips": ((0, 0, 0.72), (0, 0, 0.86), "root"),
    "spine": ((0, 0, 0.86), (0, 0, 1.0), "hips"),
    "chest": ((0, 0, 1.0), (0, 0, 1.15), "spine"),
    "neck": ((0, 0, 1.15), (0, 0, 1.22), "chest"),
    "head": ((0, 0, 1.22), (0, 0, 1.62), "neck"),
}
_SIDE_BONES = {
    "shoulder": ((0.04, 0, 1.12), (0.17, 0, 1.12), "chest"),
    "upper_arm": ((0.19, 0, 1.12), (0.21, 0, 0.90), "shoulder"),
    "forearm": ((0.21, 0, 0.90), (0.22, 0, 0.70), "upper_arm"),
    "hand": ((0.22, 0, 0.70), (0.22, 0, 0.62), "forearm"),
    "thigh": ((0.09, 0, 0.74), (0.09, 0, 0.41), "hips"),
    "shin": ((0.09, 0, 0.41), (0.09, 0, 0.08), "thigh"),
    "foot": ((0.09, 0, 0.08), (0.09, -0.14, 0.0), "shin"),
}


def _mirror(p):
    return (-p[0], p[1], p[2])


def bone_specs():
    specs = dict(_CENTER_BONES)
    for base, (head, tail, parent) in _SIDE_BONES.items():
        for side in ("L", "R"):
            h, t = (head, tail) if side == "L" else (_mirror(head), _mirror(tail))
            par = parent if parent in _CENTER_BONES else f"{parent}_{side}"
            specs[f"{base}_{side}"] = (h, t, par)
    return specs


BONES = tuple(bone_specs())
# Gestures may only key these (design doc: layer masking by convention).
UPPER_BODY = tuple(b for b in BONES if b in ("chest", "neck", "head")
                   or b.split("_")[0] in ("shoulder", "upper", "forearm", "hand"))

# Body parts: (bone, centre, radii, material)
_PARTS = [
    ("hips", (0, 0, 0.80), (0.15, 0.11, 0.10), "outfit_bottom"),
    ("spine", (0, 0, 1.00), (0.17, 0.12, 0.20), "outfit_top"),
    ("head", (0, 0, 1.42), (0.20, 0.19, 0.21), "skin"),
    ("head", (0.075, -0.17, 1.47), (0.03, 0.02, 0.04), "eye"),
    ("head", (-0.075, -0.17, 1.47), (0.03, 0.02, 0.04), "eye"),
]
for _side, _sx in (("L", 1), ("R", -1)):
    _PARTS += [
        (f"upper_arm_{_side}", (0.20 * _sx, 0, 1.01), (0.045, 0.045, 0.12), "outfit_top"),
        (f"forearm_{_side}", (0.215 * _sx, 0, 0.80), (0.04, 0.04, 0.11), "skin"),
        (f"hand_{_side}", (0.22 * _sx, 0, 0.65), (0.045, 0.04, 0.05), "skin"),
        (f"thigh_{_side}", (0.09 * _sx, 0, 0.58), (0.065, 0.065, 0.17), "outfit_bottom"),
        (f"shin_{_side}", (0.09 * _sx, 0, 0.25), (0.05, 0.05, 0.17), "outfit_bottom"),
        (f"foot_{_side}", (0.09 * _sx, -0.05, 0.035), (0.055, 0.1, 0.035), "shoes"),
    ]
_MOUTH = ("head", (0, -0.185, 1.34), (0.055, 0.02, 0.012), "mouth")

# Mouth shape per Rhubarb viseme: (width factor, height factor) over the rest mouth (X).
MOUTH_SCALES = {
    "A": (1.0, 0.4),   # M B P, closed
    "B": (1.1, 1.6),   # most consonants, slightly open
    "C": (1.15, 2.6),  # EH, AE, open
    "D": (1.25, 4.0),  # AA, wide open
    "E": (0.75, 2.8),  # AO, ER, rounded
    "F": (0.5, 1.6),   # UW, OW, W, puckered
    "G": (1.0, 0.8),   # F V
    "H": (1.0, 2.2),   # L
}

COLOURS = {
    "skin": (0.93, 0.72, 0.58, 1),
    "outfit_top": (0.20, 0.45, 0.85, 1),
    "outfit_bottom": (0.18, 0.18, 0.25, 1),
    "shoes": (0.35, 0.2, 0.1, 1),
    "eye": (0.03, 0.03, 0.03, 1),
    "mouth": (0.45, 0.08, 0.1, 1),
}


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------

def _material(name, colour):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = colour
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = colour
            bsdf.inputs["Roughness"].default_value = 0.8
    return mat


def _build_armature(name):
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    return rig, arm


def _add_edit_bones(arm):
    specs = bone_specs()
    for bname, (head, tail, _parent) in specs.items():
        eb = arm.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        eb.roll = 0.0
        eb.use_deform = bname != "root"
    for bname, (_h, _t, parent) in specs.items():
        if parent:
            eb = arm.edit_bones[bname]
            eb.parent = arm.edit_bones[parent]
            eb.use_connect = (Vector(eb.head) - Vector(arm.edit_bones[parent].tail)).length < 1e-6


def _build_body(name, rig):
    mesh = bpy.data.meshes.new(name + "_body")
    body = bpy.data.objects.new(name + "_body", mesh)
    mats = list(COLOURS)
    for m in mats:
        mesh.materials.append(_material(f"CSK360 {m}", COLOURS[m]))
    groups = {b: i for i, b in enumerate(BONES)}
    for b in BONES:
        body.vertex_groups.new(name=b)

    bm = bmesh.new()
    deform = bm.verts.layers.deform.verify()
    mouth_verts = []
    for part in _PARTS + [_MOUTH]:
        bone, centre, radii, mat = part
        matrix = Matrix.Translation(centre) @ Matrix.Diagonal((*radii, 1.0))
        res = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1.0, matrix=matrix)
        verts = res["verts"]
        for v in verts:
            v[deform][groups[bone]] = 1.0
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            f.material_index = mats.index(mat)
            f.smooth = True
        if part is _MOUTH:
            mouth_verts = verts
    bm.verts.index_update()
    mouth_idx = [v.index for v in mouth_verts]
    bm.to_mesh(mesh)
    bm.free()

    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    body.parent = rig

    # Mouth shape keys, driven by rig["mouth"] (0 = X rest, 1..8 = A..H).
    body.shape_key_add(name="Basis", from_mix=False)
    centre = Vector(_MOUTH[1])
    for i, shape in enumerate(MOUTH_SHAPES[1:], start=1):
        sx, sz = MOUTH_SCALES[shape]
        kb = body.shape_key_add(name=f"mouth_{shape}", from_mix=False)
        for vi in mouth_idx:
            co = mesh.vertices[vi].co - centre
            kb.data[vi].co = centre + Vector((co.x * sx, co.y, co.z * sz))
        fc = kb.driver_add("value")
        drv = fc.driver
        drv.type = "SCRIPTED"
        var = drv.variables.new()
        var.name = "m"
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = "OBJECT"
        var.targets[0].id = rig
        var.targets[0].data_path = f'["{MOUTH_PROP}"]'
        drv.expression = f"m == {i}"
    return body


def create_character(scene, name="Leo", location=(0.0, 0.0, 0.0), collection=None):
    """Build a starter biped_toon character. Returns the rig object."""
    if collection is None:
        collection = bpy.data.collections.new(f"CSK360 {name}")
        scene.collection.children.link(collection)
    rig, arm = _build_armature(name)
    collection.objects.link(rig)
    rig["csk360_rig"] = RIG_TYPE
    rig[MOUTH_PROP] = 0
    ui = rig.id_properties_ui(MOUTH_PROP)
    ui.update(min=0, max=len(MOUTH_SHAPES) - 1, description="Mouth shape: 0=X rest, 1..8 = A..H")

    # Edit bones need edit mode on an active object.
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_mode = bpy.context.mode
    if prev_mode != "OBJECT" and prev_active is not None:
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    _add_edit_bones(arm)
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    arm.display_type = "STICK"
    rig.show_in_front = True

    body = _build_body(name, rig)
    collection.objects.link(body)
    rig.location = location
    view_layer.objects.active = rig
    ensure_library()
    return rig


# ---------------------------------------------------------------------------
# Starter library
# ---------------------------------------------------------------------------

def _rot(path_bone):
    return f'pose.bones["{path_bone}"].rotation_euler'


def _loc(path_bone):
    return f'pose.bones["{path_bone}"].location'


def _action(name, channels, **meta):
    """channels: {(data_path, index): {frame: value}}; rotations in degrees."""
    action = bpy.data.actions.new(name)
    slot = action.slots.new(id_type="OBJECT", name="Character")
    strip = action.layers.new("Layer").strips.new(type="KEYFRAME")
    cb = strip.channelbags.new(slot)
    for (path, index), keys in channels.items():
        fc = cb.fcurves.new(path, index=index)
        is_rot = path.endswith("rotation_euler")
        for frame, value in keys.items():
            fc.keyframe_points.insert(frame, math.radians(value) if is_rot else value)
    library.mark(action, **meta)
    return action


def _walk():
    ch = {}
    for side, phase in (("L", 1), ("R", -1)):
        ch[(_rot(f"thigh_{side}"), 0)] = {1: -25 * phase, 13: 25 * phase, 25: -25 * phase}
        ch[(_rot(f"upper_arm_{side}"), 0)] = {1: 20 * phase, 13: -20 * phase, 25: 20 * phase}
    ch[(_rot("shin_L"), 0)] = {1: 5, 13: 5, 19: 45, 25: 5}
    ch[(_rot("shin_R"), 0)] = {1: 5, 7: 45, 13: 5, 25: 5}
    ch[(_loc("hips"), 1)] = {1: 0.0, 7: 0.03, 13: 0.0, 19: 0.03, 25: 0.0}
    return ch


def _idle():
    return {
        (_rot("chest"), 0): {1: 0, 25: 2.5, 49: 0},
        (_rot("head"), 2): {1: 0, 13: 4, 37: -4, 49: 0},
        (_rot("upper_arm_L"), 0): {1: 0, 25: -2, 49: 0},
        (_rot("upper_arm_R"), 0): {1: 0, 25: -2, 49: 0},
    }


def _wave():
    return {
        (_rot("upper_arm_R"), 0): {1: 0, 8: -160, 31: -160, 37: 0},
        (_rot("forearm_R"), 2): {1: 0, 8: 0, 12: 30, 16: -15, 20: 30, 24: -15, 28: 30, 31: 0},
    }


def _arms_crossed():
    return {
        (_rot("upper_arm_L"), 0): {1: -35},
        (_rot("upper_arm_L"), 2): {1: 20},   # Z+ swings the tail toward -X (inward for L)
        (_rot("forearm_L"), 0): {1: -95},
        (_rot("upper_arm_R"), 0): {1: -35},
        (_rot("upper_arm_R"), 2): {1: -20},
        (_rot("forearm_R"), 0): {1: -95},
    }


def _sit():
    return {
        (_loc("hips"), 1): {1: -0.30},
        (_rot("thigh_L"), 0): {1: -90},
        (_rot("thigh_R"), 0): {1: -90},
        (_rot("shin_L"), 0): {1: 90},
        (_rot("shin_R"), 0): {1: 90},
    }


STARTER_ASSETS = {
    "idle": (_idle, dict(kind="action", layer="BODY", loop=True, duration=4.0, favorite=True,
                         category="Standing", tags="idle, stand, wait")),
    "walk": (_walk, dict(kind="action", layer="BODY", loop=True, stride=0.35, favorite=True,
                         category="Motion keys", tags="walk, move")),
    "wave": (_wave, dict(kind="action", layer="GESTURE", category="Gestures", favorite=True,
                         tags="wave, hello, bye")),
    "arms_crossed": (_arms_crossed, dict(kind="pose", layer="GESTURE", duration=3.0, favorite=True,
                                         category="Gestures", tags="arms, cross, wait, annoyed")),
    "sit": (_sit, dict(kind="pose", layer="BODY", duration=3.0, favorite=True,
                       category="Sitting and kneeling", tags="sit, seat, chair")),
}


def ensure_library():
    """Create any missing starter actions. Existing ones (maybe user-edited) are kept."""
    made = []
    for name, (build, meta) in STARTER_ASSETS.items():
        if bpy.data.actions.get(name) is None:
            _action(name, build(), **meta)
            made.append(name)
    return made
