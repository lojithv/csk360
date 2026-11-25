# SPDX-License-Identifier: GPL-3.0-or-later
"""Output: render presets, an automatic camera, subtitles and MP4 rendering.

Subtitles are written two ways: an .srt file next to the video, and (optionally)
burned in as text objects parented to the camera, shown only while their line
plays. Sequencer text strips are not used because any visual strip makes Blender
render the sequencer instead of the 3D scene.
"""

import math
import os

import bpy
from mathutils import Vector

from . import compiler

PRESETS = {
    "1080p": (1920, 1080), "720p": (1280, 720), "4k": (3840, 2160),
    "9:16": (1080, 1920), "vertical": (1080, 1920), "square": (1080, 1080),
}
ENGINES = {"eevee": "BLENDER_EEVEE", "workbench": "BLENDER_WORKBENCH"}
CAMERA_NAME = "CSK360 Camera"
SUB_COLLECTION = "CSK360 Subtitles"
SUB_PREFIX = "CSK360 Subtitle "


def set_output(scene, preset="1080p", fps=None, engine=None):
    if preset not in PRESETS:
        raise ValueError(f"Unknown size '{preset}'. Use one of: {', '.join(PRESETS)}.")
    scene.render.resolution_x, scene.render.resolution_y = PRESETS[preset]
    scene.render.resolution_percentage = 100
    if fps:
        scene.render.fps, scene.render.fps_base = int(fps), 1.0
    if engine:
        if engine.lower() not in ENGINES:
            raise ValueError(f"Unknown engine '{engine}'. Use eevee or workbench.")
        scene.render.engine = ENGINES[engine.lower()]
        if engine.lower() == "workbench":
            scene.display.shading.color_type = "MATERIAL"


def ensure_stage(scene):
    """A floor, a sun and a soft world colour when the scene has no lights yet."""
    if any(o.type == "LIGHT" for o in scene.objects):
        return False
    import bmesh
    if bpy.data.objects.get("CSK360 Floor") is None:
        mesh = bpy.data.meshes.new("CSK360 Floor")
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=15.0)
        bm.to_mesh(mesh)
        bm.free()
        mat = bpy.data.materials.new("CSK360 Floor")
        mat.diffuse_color = (0.55, 0.52, 0.48, 1)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.52, 0.48, 1)
        mesh.materials.append(mat)
        scene.collection.objects.link(bpy.data.objects.new("CSK360 Floor", mesh))
    sun = bpy.data.objects.new("CSK360 Sun", bpy.data.lights.new("CSK360 Sun", "SUN"))
    sun.data.energy = 3.0
    sun.data.angle = math.radians(8)
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("CSK360 World")
    scene.world.color = (0.45, 0.5, 0.58)
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.45, 0.5, 0.58, 1)
        bg.inputs["Strength"].default_value = 0.8
    return True


def ensure_camera(scene):
    """Use the scene camera, or add a front camera that frames the whole cast."""
    if scene.camera is not None:
        return scene.camera
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None:
        cam = bpy.data.objects.new(CAMERA_NAME, bpy.data.cameras.new(CAMERA_NAME))
        scene.collection.objects.link(cam)
    points = []
    for c in scene.csk360.cast:
        for _t, p, _y in compiler.root_keys(scene, c):
            points.append(p)
    if not points:
        points = [Vector((0, 0, 0))]
    lo = Vector((min(p.x for p in points), min(p.y for p in points), 0))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), 0))
    centre = (lo + hi) / 2
    lens = 35.0
    # Sensor fit AUTO: the longer side of the frame spans 36 mm.
    rx, ry = scene.render.resolution_x, max(scene.render.resolution_y, 1)
    sensor_x = 36.0 if rx >= ry else 36.0 * rx / ry
    sensor_y = 36.0 * ry / rx if rx >= ry else 36.0
    tan_h, tan_v = sensor_x / 2 / lens, sensor_y / 2 / lens
    half_width = (hi.x - lo.x) / 2 + 0.6       # cast spread plus room either side
    half_height = 1.1                          # feet to above the head, centred at 0.85 m
    nearest = centre.y - lo.y                  # the closest character is this much nearer
    dist = max(half_width / tan_h, half_height / tan_v) + nearest + 0.3
    target = Vector((centre.x, centre.y, 0.85))
    cam.data.lens = lens
    cam.location = target + Vector((0, -dist, 0.25))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    cam.matrix_world = cam.matrix_basis.copy()  # usable right away, before a depsgraph update
    return cam


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------

def _srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def subtitle_cues(scene):
    """[(start, end, speaker name, text)] for lines with text and a length."""
    names = {c.id: c.name for c in scene.csk360.cast}
    cues = [(l.start, l.start + l.duration, names.get(l.cast_id, l.cast_id), l.text.strip())
            for l in scene.csk360.lines if l.text.strip() and l.duration > 0]
    return sorted(cues)


def write_srt(scene, path, speaker_names=False):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, who, text) in enumerate(subtitle_cues(scene), 1):
            body = f"{who}: {text}" if speaker_names else text
            f.write(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{body}\n\n")
    return path


def clear_burned_subtitles():
    for o in [o for o in bpy.data.objects if o.name.startswith(SUB_PREFIX)]:
        data = o.data
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0:
            bpy.data.curves.remove(data)
    coll = bpy.data.collections.get(SUB_COLLECTION)
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)


def _subtitle_material(name="CSK360 Subtitle", colour=(1, 1, 1, 1)):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = colour
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = colour
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def burn_subtitles(scene):
    """Text objects on the camera, visible only while their line plays."""
    clear_burned_subtitles()
    cues = subtitle_cues(scene)
    if not cues:
        return 0
    cam = ensure_camera(scene)
    coll = bpy.data.collections.new(SUB_COLLECTION)
    scene.collection.children.link(coll)
    mat = _subtitle_material()
    rate = compiler.fps(scene)
    aspect = scene.render.resolution_y / max(scene.render.resolution_x, 1)
    # Place on a plane 1 m in front of the camera; frame width there = sensor/lens.
    width = 36.0 / cam.data.lens
    height = width * aspect
    shadow_mat = _subtitle_material("CSK360 Subtitle Shadow", (0, 0, 0, 1))
    size = height * 0.055
    for i, (a, b, _who, text) in enumerate(cues):
        f0 = scene.frame_start + int(round(a * rate))
        f1 = scene.frame_start + int(round(b * rate))
        # White text with a soft black copy just behind it, readable on any background.
        for suffix, m, offset in (("", mat, (0.0, 0.0, 0.0)),
                                  (" shadow", shadow_mat, (size * 0.06, -size * 0.06, -0.001))):
            name = f"{SUB_PREFIX}{i}{suffix}"
            curve = bpy.data.curves.new(name, "FONT")
            curve.body = text
            curve.align_x = "CENTER"
            curve.align_y = "BOTTOM"
            curve.size = size
            curve.text_boxes[0].width = width * 0.85
            curve.text_boxes[0].x = -width * 0.425
            curve.materials.append(m)
            obj = bpy.data.objects.new(name, curve)
            coll.objects.link(obj)
            obj.parent = cam
            obj.location = (offset[0], -height * 0.42 + offset[1], -1.0 + offset[2])
            for frame, hidden in ((scene.frame_start - 1, True), (f0, False), (f1, True)):
                obj.hide_render = hidden
                obj.hide_viewport = hidden
                obj.keyframe_insert("hide_render", frame=frame)
                obj.keyframe_insert("hide_viewport", frame=frame)
    return len(cues)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_video(scene, path, preset=None, engine=None, subtitles="srt", frames=None):
    """Render the scene to an MP4 (H.264 + AAC). subtitles: 'srt', 'burn', 'both' or 'none'."""
    path = os.path.abspath(bpy.path.abspath(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if preset:
        set_output(scene, preset, engine=engine)
    elif engine:
        set_output(scene, "1080p" if scene.render.resolution_x == 0 else _preset_of(scene), engine=engine)
    ensure_stage(scene)
    ensure_camera(scene)
    if subtitles in ("burn", "both"):
        burn_subtitles(scene)
    else:
        clear_burned_subtitles()
    if subtitles in ("srt", "both"):
        write_srt(scene, os.path.splitext(path)[0] + ".srt")
    im = scene.render.image_settings
    im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
    ff = scene.render.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    ff.constant_rate_factor = "MEDIUM"
    ff.audio_codec = "AAC"
    ff.audio_channels = "STEREO"
    scene.render.filepath = path
    old = (scene.frame_start, scene.frame_end)
    if frames:
        scene.frame_start, scene.frame_end = frames
    try:
        bpy.ops.render.render(animation=True, scene=scene.name)
    finally:
        scene.frame_start, scene.frame_end = old
    return path


def _preset_of(scene):
    size = (scene.render.resolution_x, scene.render.resolution_y)
    for name, s in PRESETS.items():
        if s == size:
            return name
    return "1080p"
