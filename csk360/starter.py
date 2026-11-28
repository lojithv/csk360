# SPDX-License-Identifier: GPL-3.0-or-later
"""Starter character (a robot) and starter library actions.

The body is Quaternius' RobotExpressive (CC0 1.0), bundled in assets/robot.blend
by tools/make_robot.py. CSK360 builds its own armature with the standard
`biped_toon` bone names at the robot's joints, adds a mouth grille with shape
keys driven by the rig's `mouth` control and blinking eye lenses, and gives
each new robot its own colour. Library actions are generated from code.

Characters face -Y (Blender's front view). Units are metres.
"""

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import library
from .model import MOUTH_SHAPES

RIG_TYPE = "biped_toon"   # the bone layout; the starter body is now a robot
MOUTH_PROP = "mouth"
BLINK_PROP = "blink"

ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "robot.blend")
ASSET_MESH = "csk360_robot"
# The starter robot is Quaternius' RobotExpressive (CC0 1.0), converted by tools/make_robot.py.
_SIDE_NAMES = ("shoulder", "upper_arm", "forearm", "hand", "thigh", "shin", "foot")
_CENTER_NAMES = ("root", "hips", "spine", "chest", "neck", "head")


def _asset_mesh():
    """The robot mesh template, appended from the bundled asset once per file."""
    me = bpy.data.meshes.get(ASSET_MESH)
    if me is None or me.library is not None:
        with bpy.data.libraries.load(ASSET, link=False) as (_src, dst):
            dst.meshes = [ASSET_MESH]
        me = dst.meshes[0]
        me.use_fake_user = True
        for m in me.materials:
            if m is not None:
                m.use_fake_user = True
                bsdf = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
                if bsdf is not None:   # viewport (Solid/Workbench) shows the same colour
                    m.diffuse_color = bsdf.inputs["Base Color"].default_value
    return me


def _joints():
    return _asset_mesh()["csk360_joints"].to_dict()


def bone_specs():
    """{bone: (head, tail, parent)} in the robot's rest pose. Left side is +X."""
    j = _joints()
    top = j["top"]
    specs = {
        "root": ((0, 0, 0), (0, 0.25, 0), None),
        "hips": ((0, 0, j["hips"]), (0, 0, j["abdomen"]), "root"),
        "spine": ((0, 0, j["abdomen"]), (0, 0, j["torso"]), "hips"),
        "chest": ((0, 0, j["torso"]), (0, 0, j["neck"]), "spine"),
        "neck": ((0, 0, j["neck"]), (0, 0, j["head"]), "chest"),
        "head": ((0, 0, j["head"]), (0, 0, top), "neck"),
    }
    sh = Vector(j["shoulder"])
    foot = Vector(j["foot"])
    side = {
        "shoulder": ((0.04, sh.y, sh.z), tuple(j["upper_arm"]), "chest"),
        "upper_arm": (tuple(j["upper_arm"]), tuple(j["forearm"]), "shoulder"),
        "forearm": (tuple(j["forearm"]), tuple(j["hand"]), "upper_arm"),
        "hand": (tuple(j["hand"]), tuple(j["hand_tip"]), "forearm"),
        "thigh": (tuple(j["thigh"]), tuple(j["shin"]), "hips"),
        "shin": (tuple(j["shin"]), tuple(j["foot"]), "thigh"),
        "foot": (tuple(j["foot"]), (foot.x, foot.y - 0.16, 0.0), "shin"),
    }
    for base, (head, tail, parent) in side.items():
        for s, sx in (("L", 1), ("R", -1)):
            h = (head[0] * sx, head[1], head[2])
            t = (tail[0] * sx, tail[1], tail[2])
            par = parent if parent in _CENTER_NAMES else f"{parent}_{s}"
            specs[f"{base}_{s}"] = (h, t, par)
    return specs


BONES = _CENTER_NAMES + tuple(f"{b}_{s}" for b in _SIDE_NAMES for s in ("L", "R"))
# Gestures may only key these (design doc: layer masking by convention).
UPPER_BODY = tuple(b for b in BONES if b in ("chest", "neck", "head")
                   or b.split("_")[0] in ("shoulder", "upper", "forearm", "hand"))

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
MOUTH_RADII = (0.075, 0.02, 0.012)
MOUTH_COLOUR = (0.02, 0.02, 0.025, 1.0)

# Body colour per character (the robot's "Main" material); picked in turn.
PALETTE = [
    (0.59, 0.29, 0.04, 1.0),   # amber (the original)
    (0.08, 0.30, 0.65, 1.0),   # blue
    (0.10, 0.45, 0.22, 1.0),   # green
    (0.60, 0.10, 0.12, 1.0),   # red
    (0.40, 0.18, 0.55, 1.0),   # purple
    (0.55, 0.55, 0.58, 1.0),   # silver
]


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


def _body_material(index):
    """A copy of the robot's main material in the next palette colour."""
    colour = PALETTE[index % len(PALETTE)]
    name = f"CSK360 robot {index % len(PALETTE) + 1}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        base = next((m for m in _asset_mesh().materials if m and m.name.startswith("Main")), None)
        mat = base.copy() if base is not None else _material(name, colour)
        mat.name = name
        bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = colour
        mat.diffuse_color = colour
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


def _robot_count():
    return sum(1 for o in bpy.data.objects if o.get("csk360_rig") == RIG_TYPE)


def _build_body(name, rig):
    template = _asset_mesh()
    mesh = template.copy()
    mesh.name = name + "_body"
    for key in ("csk360_joints", "csk360_groups"):
        if key in mesh.keys():
            del mesh[key]
    mesh.use_fake_user = False
    body = bpy.data.objects.new(name + "_body", mesh)
    for g in template["csk360_groups"]:
        body.vertex_groups.new(name=g)
    for b in BONES:
        if b not in body.vertex_groups:
            body.vertex_groups.new(name=b)
    # This robot's colour.
    main = _body_material(_robot_count() - 1)
    for i, m in enumerate(mesh.materials):
        if m is not None and m.name.startswith("Main"):
            mesh.materials[i] = main

    # Mouth: a small dark grille on the face plate, below the eyes.
    j = _joints()
    head_z, top = j["head"], j["top"]
    black = {i for i, m in enumerate(mesh.materials) if m is not None and m.name.startswith("Black")}
    eye_top = head_z + 0.7 * (top - head_z)   # eye lenses; the brows sit above
    eye_verts = {"L": [], "R": []}
    for p in mesh.polygons:
        if p.material_index in black and p.center.z < eye_top:
            for vi in p.vertices:
                eye_verts["L" if mesh.vertices[vi].co.x > 0 else "R"].append(vi)
    mouth_z = head_z + 0.2 * (top - head_z)
    plate = [v.co.y for v in mesh.vertices
             if abs(v.co.x) < 0.08 and abs(v.co.z - mouth_z) < 0.04]
    front_y = min(plate) if plate else -0.35
    centre = Vector((0.0, front_y - MOUTH_RADII[1] * 0.3, mouth_z))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    deform = bm.verts.layers.deform.verify()
    head_group = body.vertex_groups["head"].index
    mouth_mat = len(mesh.materials)
    mesh.materials.append(_material("CSK360 robot mouth", MOUTH_COLOUR))
    res = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0,
                                    matrix=Matrix.Translation(centre) @
                                    Matrix.Diagonal((*MOUTH_RADII, 1.0)))
    for v in res["verts"]:
        v[deform][head_group] = 1.0
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mouth_mat
    bm.verts.index_update()
    mouth_idx = [v.index for v in res["verts"]]
    bm.to_mesh(mesh)
    bm.free()

    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    body.parent = rig

    # Mouth shape keys, driven by rig["mouth"] (0 = X rest, 1..8 = A..H).
    body.shape_key_add(name="Basis", from_mix=False)
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

    # Blink: the eye lenses squash shut, driven directly by rig["blink"] (0 open .. 1 closed).
    kb = body.shape_key_add(name="blink", from_mix=False)
    for idx in eye_verts.values():
        if not idx:
            continue
        c = sum((mesh.vertices[vi].co for vi in idx), Vector()) / len(idx)
        for vi in idx:
            co = mesh.vertices[vi].co - c
            kb.data[vi].co = c + Vector((co.x, co.y, co.z * 0.1))
    fc = kb.driver_add("value")
    drv = fc.driver
    drv.type = "AVERAGE"
    var = drv.variables.new()
    var.name = "b"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = rig
    var.targets[0].data_path = f'["{BLINK_PROP}"]'
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
    rig[BLINK_PROP] = 0.0
    rig.id_properties_ui(BLINK_PROP).update(min=0.0, max=1.0, description="Eyes: 0 open, 1 closed")

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


def _legs():
    """Leg measurements of the starter body (metres)."""
    j = _joints()
    thigh = Vector(j["thigh"]).z - Vector(j["shin"]).z
    shin = Vector(j["shin"]).z - Vector(j["foot"]).z
    back = max(v.co.y for v in _asset_mesh().vertices)   # furthest point behind
    return {"hips": j["thigh"][2], "thigh": thigh, "shin": shin, "ankle": j["foot"][2],
            "back": back, "length": thigh + shin}


def _sit():
    g = _legs()
    # Thighs level, shins down: feet back on the floor.
    drop = g["hips"] - g["shin"] - g["ankle"]
    return {
        (_loc("hips"), 1): {1: -drop},
        (_rot("thigh_L"), 0): {1: -90},
        (_rot("thigh_R"), 0): {1: -90},
        (_rot("shin_L"), 0): {1: 90},
        (_rot("shin_R"), 0): {1: 90},
    }


def _sym(base, axis, value_l, frames=None, mirror_sign=-1):
    """Same rotation on both sides; Y/Z rotations flip sign on the right side."""
    frames = frames or {1: None}
    out = {}
    for side, sign in (("L", 1), ("R", mirror_sign if axis in (1, 2) else 1)):
        out[(_rot(f"{base}_{side}"), axis)] = {f: (value_l if v is None else v) * sign
                                               for f, v in frames.items()}
    return out


def _point():
    return {
        (_rot("upper_arm_R"), 0): {1: -80},
        (_rot("forearm_R"), 0): {1: 38},    # straighten the robot's relaxed elbow
        (_rot("head"), 2): {1: -8},
    }


def _thinking():
    return {
        (_rot("upper_arm_R"), 0): {1: -45},
        (_rot("upper_arm_R"), 2): {1: -20},
        (_rot("forearm_R"), 0): {1: -150},
        (_rot("upper_arm_L"), 0): {1: -20},
        (_rot("upper_arm_L"), 2): {1: 25},
        (_rot("forearm_L"), 0): {1: -85},
        (_rot("head"), 0): {1: 8},
        (_rot("head"), 1): {1: 10},
    }


def _hands_on_hips():
    ch = _sym("upper_arm", 2, -40)
    ch.update(_sym("forearm", 2, 95))
    ch.update(_sym("forearm", 0, -10))
    return ch


def _cheer():
    ch = _sym("upper_arm", 0, -165)
    ch.update(_sym("upper_arm", 2, 25))   # arm raised: +Z on the left swings it outward
    ch.update(_sym("forearm", 0, -10))
    ch[(_rot("head"), 0)] = {1: -10}
    return ch


def _sad():
    return {
        (_rot("chest"), 0): {1: 12},
        (_rot("neck"), 0): {1: 10},
        (_rot("head"), 0): {1: 10},
        (_rot("upper_arm_L"), 0): {1: -8},
        (_rot("upper_arm_R"), 0): {1: -8},
    }


def _shrug():
    ch = _sym("upper_arm", 2, -12, {1: 0, 6: None, 20: None, 26: 0})
    ch.update(_sym("forearm", 0, -80, {1: 0, 6: None, 20: None, 26: 0}))
    ch.update(_sym("forearm", 2, -45, {1: 0, 6: None, 20: None, 26: 0}))
    ch[(_rot("head"), 1)] = {1: 0, 6: 10, 20: 10, 26: 0}
    return ch


def _clap():
    ch = _sym("upper_arm", 0, -45)
    ch.update(_sym("forearm", 0, -55))
    ch.update(_sym("upper_arm", 2, 18, {1: 0, 5: 18, 9: 0, 13: 18, 17: 0}))
    return ch


def _nod():
    return {(_rot("head"), 0): {1: 0, 7: 14, 13: 0, 19: 14, 25: 0}}


def _shake_head():
    return {(_rot("head"), 2): {1: 0, 6: 18, 12: -18, 18: 18, 24: -18, 30: 0}}


def _look_around():
    return {(_rot("head"), 2): {1: 0, 15: 40, 35: 40, 55: -40, 75: -40, 90: 0},
            (_rot("chest"), 2): {1: 0, 15: 8, 35: 8, 55: -8, 75: -8, 90: 0}}


def _talk_hands():
    ch = _sym("upper_arm", 0, -20)
    ch.update(_sym("forearm", 0, -70, {1: -70, 13: -55, 25: -70, 37: -60, 49: -70}))
    ch.update(_sym("forearm", 2, -20, {1: -10, 13: -30, 25: -10, 37: -25, 49: -10}))
    return ch


def _carry():
    ch = _sym("upper_arm", 0, -50)
    ch.update(_sym("upper_arm", 2, 12))
    ch.update(_sym("forearm", 0, -45))
    return ch


def _kneel():
    g = _legs()
    # Both knees on the floor, shins back.
    drop = g["hips"] - g["thigh"] - 0.04
    return {
        (_loc("hips"), 1): {1: -drop},
        (_rot("thigh_L"), 0): {1: -5},
        (_rot("thigh_R"), 0): {1: -5},
        (_rot("shin_L"), 0): {1: 95},
        (_rot("shin_R"), 0): {1: 95},
        (_rot("foot_L"), 0): {1: -40},
        (_rot("foot_R"), 0): {1: -40},
        (_rot("spine"), 0): {1: -5},
    }


def _lie_down():
    g = _legs()
    # Rotated onto the back, the furthest-back point rests on the floor.
    drop = g["hips"] - g["back"] - 0.01
    return {
        (_loc("hips"), 1): {1: -drop},
        (_rot("hips"), 0): {1: -90},
        (_rot("upper_arm_L"), 2): {1: -10},
        (_rot("upper_arm_R"), 2): {1: 10},
    }


def _jump():
    ch = {(_loc("hips"), 1): {1: 0, 6: -0.15, 11: 0.35, 15: 0.38, 20: 0, 24: -0.08, 28: 0}}
    ch.update(_sym("thigh", 0, -40, {1: 0, 6: -40, 11: -5, 15: -10, 20: -30, 24: -30, 28: 0}))
    ch.update(_sym("shin", 0, 70, {1: 0, 6: 70, 11: 10, 15: 20, 20: 50, 24: 50, 28: 0}))
    ch.update(_sym("upper_arm", 0, 30, {1: 0, 6: 30, 11: -150, 15: -150, 20: -20, 28: 0}))
    return ch


def _run():
    ch = {}
    for side, phase in (("L", 1), ("R", -1)):
        ch[(_rot(f"thigh_{side}"), 0)] = {1: -45 * phase, 9: 35 * phase, 17: -45 * phase}
        ch[(_rot(f"upper_arm_{side}"), 0)] = {1: 40 * phase, 9: -40 * phase, 17: 40 * phase}
        ch[(_rot(f"forearm_{side}"), 0)] = {1: -80, 17: -80}
    ch[(_rot("shin_L"), 0)] = {1: 20, 9: 20, 13: 90, 17: 20}
    ch[(_rot("shin_R"), 0)] = {1: 20, 5: 90, 9: 20, 17: 20}
    ch[(_rot("chest"), 0)] = {1: -10, 17: -10}
    ch[(_loc("hips"), 1)] = {1: 0.0, 5: 0.06, 9: 0.0, 13: 0.06, 17: 0.0}
    return ch


STARTER_ASSETS = {
    # Standing and motion
    "idle": (_idle, dict(kind="action", layer="BODY", loop=True, duration=4.0,
                         category="Standing", tags="idle, stand, wait")),
    "walk": (_walk, dict(kind="action", layer="BODY", loop=True, stride=0.30,
                         category="Motion keys", tags="walk, move")),
    "run": (_run, dict(kind="action", layer="BODY", loop=True, stride=0.64,
                       category="Motion keys", tags="run, jog, hurry, move")),
    "jump": (_jump, dict(kind="action", layer="BODY", favorite=True,
                         category="Motion keys", tags="jump, hop, leap")),
    "sad": (_sad, dict(kind="pose", layer="GESTURE", duration=3.0,
                       category="Standing", tags="sad, down, slump, tired")),
    "hands_on_hips": (_hands_on_hips, dict(kind="pose", layer="GESTURE", duration=3.0,
                                           category="Standing", tags="hips, confident, waiting")),
    # Gestures
    "wave": (_wave, dict(kind="action", layer="GESTURE", category="Gestures", favorite=True,
                         tags="wave, hello, bye")),
    "point": (_point, dict(kind="pose", layer="GESTURE", duration=2.0, favorite=True,
                           category="Gestures", tags="point, there, look, show")),
    "thinking": (_thinking, dict(kind="pose", layer="GESTURE", duration=3.0, favorite=True,
                                 category="Gestures", tags="think, chin, hmm, wonder")),
    "cheer": (_cheer, dict(kind="pose", layer="GESTURE", duration=2.0, favorite=True,
                           category="Gestures", tags="cheer, celebrate, yay, win, arms up")),
    "arms_crossed": (_arms_crossed, dict(kind="pose", layer="GESTURE", duration=3.0, favorite=True,
                                         category="Gestures", tags="arms, cross, wait, annoyed")),
    "shrug": (_shrug, dict(kind="action", layer="GESTURE", category="Gestures",
                           tags="shrug, dunno, whatever")),
    "clap": (_clap, dict(kind="action", layer="GESTURE", loop=True, duration=2.0,
                         category="Gestures", tags="clap, applause, well done")),
    "nod": (_nod, dict(kind="action", layer="GESTURE", category="Gestures",
                       tags="nod, yes, agree")),
    "shake_head": (_shake_head, dict(kind="action", layer="GESTURE", category="Gestures",
                                     tags="shake, no, disagree")),
    "look_around": (_look_around, dict(kind="action", layer="GESTURE", category="Gestures",
                                       tags="look, search, around, lost")),
    "carry": (_carry, dict(kind="pose", layer="GESTURE", duration=2.0,
                           category="Gestures", tags="carry, hold, box, lift")),
    "talk_hands": (_talk_hands, dict(kind="action", layer="GESTURE", loop=True, duration=3.0,
                                     category="Gestures", tags="talk, explain, hands, speak")),
    # Sitting, kneeling, lying
    "sit": (_sit, dict(kind="pose", layer="BODY", duration=3.0, favorite=True,
                       category="Sitting and kneeling", tags="sit, seat, chair")),
    "kneel": (_kneel, dict(kind="pose", layer="BODY", duration=3.0,
                           category="Sitting and kneeling", tags="kneel, knee, propose, low")),
    "lie_down": (_lie_down, dict(kind="pose", layer="BODY", duration=3.0,
                                 category="Lying", tags="lie, sleep, rest, floor")),
}


def ensure_library():
    """Create any missing starter actions. Existing ones (maybe user-edited) are kept."""
    made = []
    for name, (build, meta) in STARTER_ASSETS.items():
        if bpy.data.actions.get(name) is None:
            _action(name, build(), **meta)
            made.append(name)
    return made
