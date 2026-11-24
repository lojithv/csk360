# SPDX-License-Identifier: GPL-3.0-or-later
"""Command layer shared by the UI and by agents/scripts.

Every function takes a scene, edits the CSK360 model, and recompiles only
what changed. Operators are thin wrappers over these functions, so a script
calling `commands.add_clip(...)` gets exactly what the button does.

Times are in seconds from the scene's first frame.
"""

import contextlib
import re

import bpy

from . import compiler, library
from .model import MOUTH_SHAPES


class CSKError(Exception):
    """A user-facing error with a plain-English message."""


CLIP_FIELDS = {"layer", "asset", "start", "duration", "loop_mode", "blend_in", "blend_out"}
MOVE_FIELDS = {"start", "speed", "walk_asset", "arrival_asset"}
LINE_FIELDS = {"text", "voice", "emotion", "start", "audio_path", "duration"}


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def batch(scene):
    """Suspend automatic recompiles while editing several properties."""
    proj = scene.csk360
    previous = proj.suspend
    proj.suspend = True
    try:
        yield proj
    finally:
        proj.suspend = previous


def playhead(scene):
    return max(0.0, (scene.frame_current - scene.frame_start) / compiler.fps(scene))


def _new_id(proj, prefix):
    proj.next_id += 1
    return f"{prefix}{proj.next_id}"


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "character"


def _find(collection, item_id, kind):
    for i, item in enumerate(collection):
        if item.id == item_id:
            return i, item
    known = ", ".join(x.id for x in collection) or "none"
    raise CSKError(f"No {kind} with id '{item_id}'. Known: {known}")


def get_cast(scene, cast_id):
    return _find(scene.csk360.cast, cast_id, "cast member")[1]


def cast_for_object(scene, obj):
    if obj is None:
        return None
    for c in scene.csk360.cast:
        if c.object == obj:
            return c
    return None


def _resolve_asset(asset):
    action = library.resolve(asset)
    if action is None:
        hint = library.suggest(asset)
        extra = f" Did you mean: {', '.join(hint)}?" if hint else ""
        raise CSKError(f"No pose or action named '{asset}'.{extra}")
    return action


def _report(scene, warnings):
    scene.csk360.last_report = "; ".join(warnings)
    return warnings


def _rebuild(scene, cast_ids=(), sounds=False):
    proj = scene.csk360
    warnings = []
    with batch(scene):
        if sounds:
            warnings += compiler.compile_dialogue(scene)
        for cid in dict.fromkeys(cast_ids):
            for c in proj.cast:
                if c.id == cid:
                    warnings += compiler.compile_cast(scene, c)
    return _report(scene, warnings)


def rebuild(scene, cast_id=None):
    """Recompile one cast member, or everything when cast_id is None."""
    if cast_id is None:
        with batch(scene):
            return _report(scene, compiler.compile_all(scene))
    get_cast(scene, cast_id)
    return _rebuild(scene, [cast_id], sounds=True)


def on_item_changed(item):
    """Property update callback: recompile what the edited item affects."""
    scene = item.id_data
    if not isinstance(scene, bpy.types.Scene) or scene.csk360.suspend:
        return
    if hasattr(item, "cast_id"):
        cast_id = item.cast_id
    else:
        cast_id = getattr(item, "id", "")
    sounds = hasattr(item, "audio_path")
    if cast_id:
        _rebuild(scene, [cast_id], sounds=sounds)


# ---------------------------------------------------------------------------
# Cast
# ---------------------------------------------------------------------------

def add_cast(scene, obj, name=None, rig_type=None, voice=""):
    if obj is None:
        raise CSKError("Select a character object first.")
    existing = cast_for_object(scene, obj)
    if existing is not None:
        raise CSKError(f"'{obj.name}' is already in the cast as '{existing.id}'.")
    proj = scene.csk360
    taken = {c.id for c in proj.cast}
    base = _slug(name or obj.name)
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}_{n}", n + 1
    with batch(scene):
        c = proj.cast.add()
        c.id = cid
        c.name = name or obj.name
        c.object = obj
        c.rig_type = rig_type or ("biped3d" if obj.type == "ARMATURE" else "prop")
        c.voice = voice
        c.home = obj.location
        c.home_yaw = obj.rotation_euler.z
        proj.active_cast_index = len(proj.cast) - 1
    return cid


def add_starter_character(scene, name="Leo", location=(0.0, 0.0, 0.0), voice=""):
    """Build the starter 3D toon character, add the starter library and cast it."""
    from . import starter
    rig = starter.create_character(scene, name=name, location=location)
    return add_cast(scene, rig, name=name, rig_type="biped3d", voice=voice)


def set_home(scene, cast_id):
    """Use the character's current position as its start position."""
    c = get_cast(scene, cast_id)
    with batch(scene):
        c.home = c.object.location
        c.home_yaw = c.object.rotation_euler.z
    _rebuild(scene, [cast_id])


def remove_cast(scene, cast_id):
    proj = scene.csk360
    index, c = _find(proj.cast, cast_id, "cast member")
    with batch(scene):
        for coll in (proj.clips, proj.moves, proj.lines):
            for i in reversed(range(len(coll))):
                if coll[i].cast_id == cast_id:
                    coll.remove(i)
        compiler.clear_cast(c.object, cast_id)
        proj.cast.remove(index)
        proj.active_cast_index = min(proj.active_cast_index, max(len(proj.cast) - 1, 0))
        _clamp_indices(proj)
    _rebuild(scene, [], sounds=True)


def _clamp_indices(proj):
    proj.active_clip_index = min(proj.active_clip_index, max(len(proj.clips) - 1, 0))
    proj.active_move_index = min(proj.active_move_index, max(len(proj.moves) - 1, 0))
    proj.active_line_index = min(proj.active_line_index, max(len(proj.lines) - 1, 0))


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

def add_clip(scene, cast_id, asset, start=None, duration=None, layer=None,
             loop_mode=None, blend_in=None, blend_out=None):
    """Add a pose or action clip. Unset values come from the asset's metadata."""
    get_cast(scene, cast_id)
    action = _resolve_asset(asset)
    info = library.info(action, scene)
    proj = scene.csk360
    with batch(scene):
        clip = proj.clips.add()
        clip.id = _new_id(proj, "clip")
        clip.cast_id = cast_id
        clip.asset = action.name
        clip.layer = layer or info["layer"]
        clip.loop_mode = loop_mode or info["loop_mode"]
        clip.start = playhead(scene) if start is None else start
        clip.duration = info["duration"] if duration is None else duration
        if blend_in is not None:
            clip.blend_in = blend_in
        if blend_out is not None:
            clip.blend_out = blend_out
        proj.active_clip_index = len(proj.clips) - 1
        clip_id = clip.id
    _rebuild(scene, [cast_id])
    return clip_id


def get_clip(scene, clip_id):
    return _find(scene.csk360.clips, clip_id, "clip")[1]


def set_clip(scene, clip_id, **fields):
    bad = set(fields) - CLIP_FIELDS
    if bad:
        raise CSKError(f"Unknown clip fields: {', '.join(sorted(bad))}")
    clip = get_clip(scene, clip_id)
    if "asset" in fields:
        fields["asset"] = _resolve_asset(fields["asset"]).name
    with batch(scene):
        for k, v in fields.items():
            setattr(clip, k, v)
    _rebuild(scene, [clip.cast_id])


def change_clip_duration(scene, clip_id, delta_seconds):
    """Lengthen (positive) or shorten (negative) a clip; never below one frame."""
    clip = get_clip(scene, clip_id)
    one_frame = 1.0 / compiler.fps(scene)
    set_clip(scene, clip_id, duration=max(one_frame, clip.duration + delta_seconds))
    return clip.duration


def remove_clip(scene, clip_id):
    proj = scene.csk360
    index, clip = _find(proj.clips, clip_id, "clip")
    cast_id = clip.cast_id
    with batch(scene):
        proj.clips.remove(index)
        _clamp_indices(proj)
    _rebuild(scene, [cast_id])


# ---------------------------------------------------------------------------
# Moves
# ---------------------------------------------------------------------------

def add_move(scene, cast_id, start=None, point=None, target=None, speed=0.0,
             walk=None, arrival=""):
    """Walk to `point` (x, y, z) or to `target` (object or object name)."""
    get_cast(scene, cast_id)
    if (point is None) == (target is None):
        raise CSKError("Give either a point or a target object for the move.")
    if isinstance(target, str):
        obj = bpy.data.objects.get(target)
        if obj is None:
            raise CSKError(f"No object named '{target}'.")
        target = obj
    walk = library.default_walk() if walk is None else walk
    if walk:
        walk = _resolve_asset(walk).name
    if arrival:
        arrival = _resolve_asset(arrival).name
    proj = scene.csk360
    with batch(scene):
        m = proj.moves.add()
        m.id = _new_id(proj, "move")
        m.cast_id = cast_id
        m.start = playhead(scene) if start is None else start
        if target is not None:
            m.target_kind = "OBJECT"
            m.target_object = target
        else:
            m.target_kind = "POINT"
            m.target_point = point
        m.speed = speed
        m.walk_asset = walk
        m.arrival_asset = arrival
        proj.active_move_index = len(proj.moves) - 1
        move_id = m.id
    _rebuild(scene, [cast_id])
    return move_id


def get_move(scene, move_id):
    return _find(scene.csk360.moves, move_id, "move")[1]


def set_move(scene, move_id, **fields):
    bad = set(fields) - MOVE_FIELDS - {"point", "target"}
    if bad:
        raise CSKError(f"Unknown move fields: {', '.join(sorted(bad))}")
    m = get_move(scene, move_id)
    with batch(scene):
        if "point" in fields:
            m.target_kind = "POINT"
            m.target_point = fields.pop("point")
        if "target" in fields:
            t = fields.pop("target")
            m.target_kind = "OBJECT"
            m.target_object = bpy.data.objects[t] if isinstance(t, str) else t
        for k, v in fields.items():
            setattr(m, k, v)
    _rebuild(scene, [m.cast_id])


def remove_move(scene, move_id):
    proj = scene.csk360
    index, m = _find(proj.moves, move_id, "move")
    cast_id = m.cast_id
    with batch(scene):
        proj.moves.remove(index)
        _clamp_indices(proj)
    _rebuild(scene, [cast_id])


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------

def _shape_index(shape):
    if isinstance(shape, str):
        try:
            return MOUTH_SHAPES.index(shape.upper())
        except ValueError:
            raise CSKError(f"Unknown mouth shape '{shape}'. Use one of {' '.join(MOUTH_SHAPES)}.")
    return int(shape)


def _fill_visemes(line, visemes):
    line.visemes.clear()
    for t, shape in visemes:
        v = line.visemes.add()
        v.time = t
        v.shape = _shape_index(shape)


def lines_end(scene, cast_id=None):
    ends = [l.start + l.duration for l in scene.csk360.lines
            if cast_id is None or l.cast_id == cast_id]
    return max(ends, default=0.0)


def add_line(scene, cast_id, text, start=None, after_previous=False, audio_path="",
             visemes=None, voice="", emotion="neutral", duration=None):
    """Add a dialogue line. `visemes` is [(seconds_from_line_start, 'A'..'H'|'X'), ...]."""
    get_cast(scene, cast_id)
    proj = scene.csk360
    if start is None:
        start = lines_end(scene) if after_previous else playhead(scene)
    with batch(scene):
        line = proj.lines.add()
        line.id = _new_id(proj, "line")
        line.cast_id = cast_id
        line.text = text
        line.voice = voice
        line.emotion = emotion
        line.start = start
        line.audio_path = audio_path
        if duration is not None:
            line.duration = duration
        elif visemes:
            line.duration = max(t for t, _ in visemes)
        if visemes:
            _fill_visemes(line, visemes)
        proj.active_line_index = len(proj.lines) - 1
        line_id = line.id
    _rebuild(scene, [cast_id], sounds=True)
    return line_id


def get_line(scene, line_id):
    return _find(scene.csk360.lines, line_id, "dialogue line")[1]


def set_line(scene, line_id, visemes=None, **fields):
    bad = set(fields) - LINE_FIELDS
    if bad:
        raise CSKError(f"Unknown line fields: {', '.join(sorted(bad))}")
    line = get_line(scene, line_id)
    with batch(scene):
        for k, v in fields.items():
            setattr(line, k, v)
        if visemes is not None:
            _fill_visemes(line, visemes)
    _rebuild(scene, [line.cast_id], sounds=True)


def remove_line(scene, line_id):
    proj = scene.csk360
    index, line = _find(proj.lines, line_id, "dialogue line")
    cast_id = line.cast_id
    with batch(scene):
        proj.lines.remove(index)
        _clamp_indices(proj)
    _rebuild(scene, [cast_id], sounds=True)


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------

def describe(scene):
    """Plain dict snapshot of the model, for agents and debugging."""
    proj = scene.csk360
    return {
        "fps": compiler.fps(scene),
        "cast": [{"id": c.id, "name": c.name, "object": c.object.name if c.object else None,
                  "rig_type": c.rig_type, "voice": c.voice} for c in proj.cast],
        "clips": [{"id": c.id, "who": c.cast_id, "asset": c.asset, "layer": c.layer,
                   "start": round(c.start, 4), "duration": round(c.duration, 4),
                   "mode": c.loop_mode} for c in proj.clips],
        "moves": [{"id": m.id, "who": m.cast_id, "start": round(m.start, 4),
                   "target": (m.target_object.name if m.target_kind == "OBJECT" and m.target_object
                              else [round(x, 4) for x in m.target_point]),
                   "duration": round(m.duration, 4), "walk": m.walk_asset,
                   "arrival": m.arrival_asset} for m in proj.moves],
        "lines": [{"id": l.id, "who": l.cast_id, "text": l.text, "start": round(l.start, 4),
                   "duration": round(l.duration, 4), "audio": l.audio_path,
                   "visemes": len(l.visemes)} for l in proj.lines],
        "library": library.search(marked_only=False),
        "warnings": proj.last_report,
    }
