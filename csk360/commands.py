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


CLIP_FIELDS = {"layer", "asset", "start", "duration", "loop_mode", "blend_in", "blend_out",
               "with_line", "match_line", "offset"}
MOVE_FIELDS = {"start", "speed", "walk_asset", "arrival_asset"}
LINE_FIELDS = {"text", "voice", "emotion", "start", "audio_path", "duration", "follows"}


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


LINE_GAP = 0.2  # seconds between a line and the one that follows it


def _reflow(scene):
    """Place lines that follow another line right after it. Returns cast ids that moved."""
    lines = {l.id: l for l in scene.csk360.lines}
    moved = []
    for _ in range(len(lines)):  # chains settle in at most len(lines) passes
        changed = False
        for line in lines.values():
            prev = lines.get(line.follows)
            if prev is None or prev is line:
                continue
            start = prev.start + prev.duration + LINE_GAP
            if abs(line.start - start) > 1e-6:
                line.start = start
                moved.append(line.cast_id)
                changed = True
        if not changed:
            break
    for clip in scene.csk360.clips:
        line = lines.get(clip.with_line)
        if line is None:
            continue
        duration = line.duration if clip.match_line and line.duration > 0 else clip.duration
        if abs(clip.start - line.start) > 1e-6 or abs(clip.duration - duration) > 1e-6:
            clip.start, clip.duration = line.start, duration
            moved.append(clip.cast_id)
    return moved


def _rebuild(scene, cast_ids=(), sounds=False):
    proj = scene.csk360
    warnings = []
    with batch(scene):
        if sounds:
            warnings += compiler.compile_dialogue(scene)
            moved = _reflow(scene)
            if moved:
                warnings = compiler.compile_dialogue(scene)
                cast_ids = list(cast_ids) + moved
        if len(proj.cast) > 1 and len(proj.lines) and cast_ids:
            # Listeners look at speakers, so one character's change can move another's head.
            cast_ids = list(cast_ids) + [c.id for c in proj.cast if c.auto_life]
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


def split_clip(scene, clip_id, at=None):
    """Split a clip in two at `at` seconds (default: the playhead). Returns the new clip's id.

    The second half continues the action where the first stopped, so playback looks the same."""
    clip = get_clip(scene, clip_id)
    at = playhead(scene) if at is None else at
    one_frame = 1.0 / compiler.fps(scene)
    end = clip.start + clip.duration
    if not (clip.start + one_frame <= at <= end - one_frame):
        raise CSKError("Put the playhead inside the clip to split it.")
    proj = scene.csk360
    with batch(scene):
        new = proj.clips.add()
        new.id = _new_id(proj, "clip")
        for k in ("cast_id", "layer", "asset", "loop_mode", "blend_out", "with_line", "match_line"):
            setattr(new, k, getattr(clip, k))
        new.start = at
        new.duration = end - at
        new.offset = clip.offset + (at - clip.start)
        new.blend_in = 0.0
        new.match_line = False
        clip.duration = at - clip.start
        clip.blend_out = 0.0
        if clip.with_line:
            clip.match_line = False
        proj.active_clip_index = len(proj.clips) - 1
        new_id = new.id
    _rebuild(scene, [clip.cast_id])
    return new_id


def clip_times(scene, cast_id=None):
    """Sorted start and end times of clips, moves and lines (one cast, or all)."""
    proj = scene.csk360
    times = set()
    for c in proj.clips:
        if cast_id in (None, c.cast_id):
            times.update((c.start, c.start + c.duration))
    for m in proj.moves:
        if cast_id in (None, m.cast_id):
            times.update((m.start, m.start + m.duration))
    for l in proj.lines:
        if cast_id in (None, l.cast_id):
            times.update((l.start, l.start + l.duration))
    return sorted(times)


def jump_to_clip(scene, direction=1, cast_id=None):
    """Move the playhead to the next (1) or previous (-1) clip boundary. Returns the time or None."""
    rate = compiler.fps(scene)
    now = playhead(scene)
    half = 0.5 / rate
    times = clip_times(scene, cast_id)
    pick = ([t for t in times if t > now + half][:1] if direction > 0
            else [t for t in times if t < now - half][-1:])
    if not pick:
        return None
    scene.frame_set(scene.frame_start + int(round(pick[0] * rate)))
    return pick[0]


def localize_audio(scene, blend_path=None, folder="csk360_audio"):
    """Copy generated voice files next to the .blend and point lines at the copies.

    Makes the project portable (the voice cache lives in the user's home folder).
    Returns the number of files copied."""
    import os
    import shutil
    blend_path = blend_path or bpy.data.filepath
    if not blend_path:
        return 0
    from . import voice
    cache = os.path.normcase(os.path.abspath(os.path.join(voice.home(), "cache")))
    dest_dir = os.path.join(os.path.dirname(os.path.abspath(blend_path)), folder)
    copied = 0
    changed = []
    with batch(scene):
        for line in scene.csk360.lines:
            if not line.audio_path:
                continue
            src = os.path.abspath(bpy.path.abspath(line.audio_path))
            if os.path.normcase(os.path.dirname(src)) != cache or not os.path.isfile(src):
                continue
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(src))
            if not os.path.isfile(dest):
                shutil.copyfile(src, dest)
                copied += 1
            line.audio_path = "//" + folder + "/" + os.path.basename(src)
            changed.append(line.cast_id)
    if changed:
        with batch(scene):
            compiler.compile_dialogue(scene, base_dir=os.path.dirname(os.path.abspath(blend_path)))
    return copied


def set_clip_with_line(scene, clip_id, line_id, match_duration=True):
    """Make a clip (e.g. a gesture) start with a dialogue line and follow it when it moves."""
    clip = get_clip(scene, clip_id)
    get_line(scene, line_id)
    with batch(scene):
        clip.with_line = line_id
        clip.match_line = match_duration
    _rebuild(scene, [clip.cast_id], sounds=True)


def remove_clip(scene, clip_id):
    proj = scene.csk360
    index, clip = _find(proj.clips, clip_id, "clip")
    cast_id = clip.cast_id
    with batch(scene):
        proj.clips.remove(index)
        _clamp_indices(proj)
    _rebuild(scene, [cast_id])


# ---------------------------------------------------------------------------
# Your own poses
# ---------------------------------------------------------------------------

LOWER_BODY_WORDS = ("root", "hips", "pelvis", "thigh", "shin", "calf", "leg", "foot", "toe")


def _is_lower_body(bone_name):
    n = bone_name.lower()
    return any(w in n for w in LOWER_BODY_WORDS)


def save_pose(scene, cast_id, name, category="", layer="AUTO", favorite=False, tags="",
              overwrite=False):
    """Save the character's current pose (as seen in the viewport) as a library pose.

    Only bones moved away from their rest pose are keyed. layer="AUTO" picks
    GESTURE when only the upper body moved (so it layers over walks and sits),
    else BODY. Returns the new asset id. Poses work on every character whose
    bones have the same names (all starter characters share them)."""
    import math

    cast = get_cast(scene, cast_id)
    obj = cast.object
    if obj is None or obj.type != "ARMATURE":
        raise CSKError(f"{cast.name} has no armature to take a pose from.")
    if not name or not name.strip():
        raise CSKError("Give the pose a name.")
    asset_id = _slug(name)
    existing = bpy.data.actions.get(asset_id)
    if existing is not None:
        if not overwrite:
            raise CSKError(f"A pose or action named '{asset_id}' already exists. "
                           "Choose another name or overwrite it.")
        bpy.data.actions.remove(existing)
    channels = []   # (data path, index, value)
    moved = set()
    eps = 1e-4
    for pb in obj.pose.bones:
        base = f'pose.bones["{pb.name}"]'
        for i, v in enumerate(pb.location):
            if abs(v) > eps:
                channels.append((base + ".location", i, v))
                moved.add(pb.name)
        if pb.rotation_mode == "QUATERNION":
            q = pb.rotation_quaternion
            if abs(q[0] - 1.0) > eps or any(abs(c) > eps for c in q[1:]):
                for i, v in enumerate(q):
                    channels.append((base + ".rotation_quaternion", i, v))
                moved.add(pb.name)
        elif pb.rotation_mode == "AXIS_ANGLE":
            aa = pb.rotation_axis_angle
            if abs(aa[0]) > eps:
                for i, v in enumerate(aa):
                    channels.append((base + ".rotation_axis_angle", i, v))
                moved.add(pb.name)
        else:
            for i, v in enumerate(pb.rotation_euler):
                if abs(math.remainder(v, math.tau)) > eps:
                    channels.append((base + ".rotation_euler", i, v))
                    moved.add(pb.name)
        for i, v in enumerate(pb.scale):
            if abs(v - 1.0) > eps:
                channels.append((base + ".scale", i, v))
                moved.add(pb.name)
    if not channels:
        raise CSKError(f"{cast.name} is in the rest pose. Pose the character first "
                       "(Pose Mode: rotate bones with R), then save.")
    if layer == "AUTO":
        layer = "BODY" if any(_is_lower_body(b) for b in moved) else "GESTURE"
    action = bpy.data.actions.new(asset_id)
    slot = action.slots.new(id_type="OBJECT", name="Character")
    cb = action.layers.new("Layer").strips.new(type="KEYFRAME").channelbags.new(slot)
    for path, index, value in channels:
        fc = cb.fcurves.new(path, index=index)
        fc.keyframe_points.insert(1, value)
    library.mark(action, kind="pose", layer=layer, duration=2.0, favorite=bool(favorite),
                 category=category or "My poses", tags=tags)
    return action.name


# ---------------------------------------------------------------------------
# Moves
# ---------------------------------------------------------------------------

def moves_end(scene, cast_id):
    """When the cast member's last move finishes (seconds), or None without moves."""
    ends = [m.start + m.duration for m in scene.csk360.moves if m.cast_id == cast_id]
    return max(ends) if ends else None


def add_move(scene, cast_id, start=None, point=None, target=None, speed=0.0,
             walk=None, arrival="", after_previous=False):
    """Walk to `point` (x, y, z) or to `target` (object or object name).
    `after_previous` starts when the character's last move ends (else at the playhead)."""
    get_cast(scene, cast_id)
    if after_previous and start is None:
        start = moves_end(scene, cast_id)
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
             visemes=None, voice="", emotion="neutral", duration=None, generate=False):
    """Add a dialogue line. `visemes` is [(seconds_from_line_start, 'A'..'H'|'X'), ...].

    With generate=True the line is voiced and lip-synced right away (blocking)."""
    get_cast(scene, cast_id)
    proj = scene.csk360
    follows = ""
    if start is None:
        if after_previous and len(proj.lines):
            last = max(proj.lines, key=lambda l: l.start + l.duration)
            follows = last.id
            start = last.start + last.duration + LINE_GAP
        else:
            start = playhead(scene)
    with batch(scene):
        line = proj.lines.add()
        line.id = _new_id(proj, "line")
        line.cast_id = cast_id
        line.follows = follows
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
    if generate:
        errors = generate_lines(scene, [line_id])
        if errors:
            raise CSKError("; ".join(errors))
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
# Voices (text-to-speech + lip sync, run by the separate voice service)
# ---------------------------------------------------------------------------

def line_voice(scene, line):
    """(voice id, speed) a line will be spoken with."""
    from . import voice
    cast = get_cast(scene, line.cast_id)
    return (line.voice or cast.voice or voice.DEFAULT_VOICE), cast.speed


def line_needs_voice(scene, line):
    from . import voice
    if not line.text.strip():
        return False
    v, speed = line_voice(scene, line)
    _path, key = voice.cache_path(line.text, v, speed)
    return line.audio_key != key or not line.audio_path


def voice_jobs(scene, line_ids=None, force=False):
    """Jobs for lines whose text, voice or speed changed since they were last voiced."""
    from . import voice
    jobs = []
    for line in scene.csk360.lines:
        if line_ids is not None and line.id not in line_ids:
            continue
        if not line.text.strip() or not (force or line_needs_voice(scene, line)):
            continue
        v, speed = line_voice(scene, line)
        if "/" not in v:
            raise CSKError(f"{line.id}: voice '{v}' should look like kokoro/af_heart or supertonic/M1.")
        out, _key = voice.cache_path(line.text, v, speed)
        jobs.append({"id": line.id, "text": line.text, "voice": v, "speed": speed, "out": out})
    return jobs


def apply_voice_results(scene, results):
    """Store generated audio and mouth shapes on their lines. Returns error messages."""
    import os
    errors, casts = [], []
    proj = scene.csk360
    with batch(scene):
        for line_id, r in results.items():
            try:
                line = get_line(scene, line_id)
            except CSKError:
                continue
            if not r.get("ok"):
                errors.append(f"{line_id}: {r.get('error', 'voice generation failed')}")
                continue
            line.audio_path = r["wav"]
            line.audio_key = os.path.splitext(os.path.basename(r["wav"]))[0]
            line.duration = r.get("duration", line.duration)
            _fill_visemes(line, r.get("visemes", []))
            casts.append(line.cast_id)
    warnings = _rebuild(scene, casts, sounds=True)
    proj.last_report = "; ".join(errors + warnings)
    return errors


def generate_lines(scene, line_ids=None, force=False):
    """Voice and lip-sync lines now (blocking). Returns error messages."""
    from . import voice
    jobs = voice_jobs(scene, line_ids, force)
    if not jobs:
        return []
    try:
        results = voice.speak(jobs)
    except voice.VoiceError as e:
        raise CSKError(str(e))
    return apply_voice_results(scene, results)


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
