# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures for the headless test suite."""

import math
import os
import struct
import tempfile
import wave

import bpy

from csk360 import library

TMP = tempfile.mkdtemp(prefix="csk360_tests_")


def reset_scene(fps=24):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = 500
    return scene


def make_rig(scene, name="Leo", location=(0.0, 0.0, 0.0)):
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    ob.location = location
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bones = (
        ("root", (0, 0, 0), (0, 0, 0.2), None),
        ("spine", (0, 0, 0.2), (0, 0, 1.0), "root"),
        ("arm_L", (0.2, 0, 1.0), (0.6, 0, 1.0), "spine"),
    )
    for bname, head, tail, parent in bones:
        eb = arm.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def make_action(name, bone, keys, slot_name="Leo", **meta):
    """Action keying `bone`.location.x with {frame: value}; marked as a library asset."""
    action = bpy.data.actions.new(name)
    slot = action.slots.new(id_type="OBJECT", name=slot_name)
    layer = action.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    cb = strip.channelbags.new(slot)
    fc = cb.fcurves.new(f'pose.bones["{bone}"].location', index=0)
    for frame, value in keys.items():
        kp = fc.keyframe_points.insert(frame, value)
        kp.interpolation = "LINEAR"
    library.mark(action, **meta)
    return action


def bone_x(scene, ob, bone, frame):
    scene.frame_set(frame)
    return ob.pose.bones[bone].location.x


def prop_at(scene, ob, prop, frame):
    scene.frame_set(frame)
    return ob[prop]


def write_wav(seconds, name="line.wav", rate=22050):
    path = os.path.join(TMP, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(int(seconds * rate)))
        w.writeframes(frames)
    return path


def csk_tracks(ob):
    if ob.animation_data is None:
        return []
    return [t for t in ob.animation_data.nla_tracks if t.name.startswith("CSK360 ")]


def track(ob, name):
    return ob.animation_data.nla_tracks.get(name)
