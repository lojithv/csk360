# SPDX-License-Identifier: GPL-3.0-or-later
"""Compiler: turns the CSK360 model into Blender animation data.

All Blender writes for animation live here (design doc: "keep all Blender
writes inside the compiler"). Per cast member it owns:

* NLA tracks named "CSK360 <Layer>[ n]" on the character object
* generated actions named "CSK360.<cast id>.move" / ".mouth"
* sound strips named "CSK360:<line id>" in the sequencer

Everything else (the object's active action = the Manual layer, the user's
own NLA tracks, other strips) is never touched.

Uses the slotted-action API (Blender 4.4+).
"""

import math
import os

import bpy
from mathutils import Matrix, Vector

from . import library

TRACK_PREFIX = "CSK360 "
SOUND_PREFIX = "CSK360:"
LAYER_ORDER = ("MOVE", "BODY", "GESTURE", "FACE", "LIFE", "MOUTH")
TRACK_TITLES = {"MOVE": "Move", "BODY": "Body", "GESTURE": "Gesture", "FACE": "Face",
                "LIFE": "Life", "MOUTH": "Mouth"}
BLEND_TYPES = {"MOVE": "REPLACE", "BODY": "REPLACE", "GESTURE": "COMBINE",
               "FACE": "COMBINE", "LIFE": "COMBINE", "MOUTH": "REPLACE"}
MOUTH_PROP = "mouth"
TURN_SECONDS = 0.25
FALLBACK_WALK_SPEED = 1.2  # m/s when no stride is known
MAX_STRIP_FACTOR = 1000.0  # Blender's limit for NLA strip scale and repeat


def fps(scene):
    return scene.render.fps / scene.render.fps_base


def to_frame(scene, seconds):
    return scene.frame_start + seconds * fps(scene)


def generated_action_names(cast_id):
    base = library.GENERATED_PREFIX + cast_id
    return (base + ".move", base + ".mouth", base + ".life")


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------

def clear_cast(obj, cast_id):
    """Remove every NLA track and generated action CSK360 made for this cast."""
    if obj is not None and obj.animation_data is not None:
        tracks = obj.animation_data.nla_tracks
        for track in list(tracks):
            if track.name.startswith(TRACK_PREFIX):
                tracks.remove(track)
    for name in generated_action_names(cast_id):
        action = bpy.data.actions.get(name)
        if action is not None:
            bpy.data.actions.remove(action)


def clear_sounds(scene):
    sed = scene.sequence_editor
    if sed is None:
        return
    for strip in list(sed.strips):
        if strip.name.startswith(SOUND_PREFIX):
            sed.strips.remove(strip)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_generated_action(name, obj):
    """Create an empty action with one slot for `obj`; return (action, channelbag)."""
    old = bpy.data.actions.get(name)
    if old is not None:
        bpy.data.actions.remove(old)
    action = bpy.data.actions.new(name)
    slot = action.slots.new(id_type="OBJECT", name=obj.name)
    layer = action.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    return action, strip.channelbags.new(slot)


def _fcurve(channelbag, path, index=0):
    fc = channelbag.fcurves.find(path, index=index)
    return fc or channelbag.fcurves.new(path, index=index)


def _key(fc, frame, value, interpolation):
    kp = fc.keyframe_points.insert(frame, value, options={"FAST"})
    kp.interpolation = interpolation


def _ensure_slot(strip):
    if getattr(strip, "action_slot", True) is None and strip.action_suitable_slots:
        strip.action_slot = strip.action_suitable_slots[0]


def _set_length_factor(strip, factor):
    """Stretch a strip by `factor` using scale, then repeat past Blender's 1000x limit."""
    scale = min(factor, MAX_STRIP_FACTOR)
    strip.scale = scale
    if factor > scale:
        strip.repeat = factor / scale


def _clip_span(scene, start_s, duration_s):
    a = round(to_frame(scene, start_s))
    b = max(a + 1, round(to_frame(scene, start_s + duration_s)))
    return a, b


# ---------------------------------------------------------------------------
# Strip placement
# ---------------------------------------------------------------------------

def _place_clip(track, spec):
    """Create the strip(s) for one clip spec on `track`. Returns the strips."""
    action = spec["action"]
    a, b = spec["span"]
    dur = b - a
    f0, f1 = action.frame_range
    natural = max(f1 - f0, 1.0)
    mode = spec["loop_mode"]
    name = spec["name"]
    offset = int(spec.get("offset", 0))  # frames into the action (set by splitting a clip)
    strips = []

    if mode == "LOOP":
        t, remaining = a, dur
        o = offset % max(int(round(natural)), 1) if offset else 0
        if o:
            # Finish the cycle that was in progress, then loop normally.
            part = min(int(round(natural)) - o, remaining)
            s = track.strips.new(name, t, action)
            s.action_frame_start = f0 + o
            s.action_frame_end = f0 + o + part
            strips.append(s)
            t, remaining = t + part, remaining - part
        if remaining > 0:
            s = track.strips.new(name + (".loop" if strips else ""), t, action)
            s.repeat = min(remaining / natural, MAX_STRIP_FACTOR)
            strips.append(s)
    elif mode == "ONCE":
        played = max(math.floor(natural) - offset, 0)
        start = f0 + min(offset, math.floor(natural))
        if played:
            s = track.strips.new(name, a, action)
            if offset:
                s.action_frame_start = start
            if dur <= played:
                s.action_frame_end = start + dur
            elif start + played != f1:
                s.action_frame_end = start + played
            strips.append(s)
        if dur > played:
            last = start + played
            h = track.strips.new(name + (".hold" if strips else ""), a + played, action)
            h.action_frame_end = last + 1
            h.action_frame_start = last
            _set_length_factor(h, dur - played)
            strips.append(h)
    else:  # HOLD: a still pose taken from the first frame
        h = track.strips.new(name, a, action)
        h.action_frame_end = f0 + 1
        h.action_frame_start = f0
        _set_length_factor(h, dur)
        strips.append(h)

    for s in strips:
        _ensure_slot(s)
        s.blend_type = spec["blend_type"]
        s.extrapolation = "NOTHING"
        s.use_sync_length = False
    first, last_strip = strips[0], strips[-1]
    first.blend_in = min(spec["blend_in"], (first.frame_end - first.frame_start) * 0.5)
    last_strip.blend_out = min(spec["blend_out"], (last_strip.frame_end - last_strip.frame_start) * 0.5)
    return strips


def _assign_subtracks(specs):
    """Greedy interval packing: clips that overlap on one layer get extra tracks."""
    ends = []
    for spec in sorted(specs, key=lambda s: (s["span"][0], s["name"])):
        a = spec["span"][0]
        for i, end in enumerate(ends):
            if end <= a:
                spec["sub"] = i
                ends[i] = spec["span"][1]
                break
        else:
            spec["sub"] = len(ends)
            ends.append(spec["span"][1])
    return len(ends)


def _track_name(layer, sub):
    title = TRACK_PREFIX + TRACK_TITLES[layer]
    return title if sub == 0 else f"{title} {sub + 1}"


# ---------------------------------------------------------------------------
# Moves
# ---------------------------------------------------------------------------

STOP_GAP = 0.3  # metres between a character and the prop it walks up to


def approach_point(obj, from_pos):
    """Where to stop when walking to `obj` from `from_pos`.

    The object's "approach" child when it has one; otherwise the edge of its
    footprint (world bounding box in XY) facing the walker, plus STOP_GAP, so
    characters walk up to a crate instead of into it. Objects without size
    (empties) are walked to directly.
    """
    for child in obj.children:
        if "approach" in child.name.lower():
            return child.matrix_world.translation.copy()
    center = obj.matrix_world.translation.copy()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), 0.0))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), 0.0))
    if from_pos is None or (hi - lo).length < 0.01:
        return center
    d = Vector((from_pos.x - center.x, from_pos.y - center.y, 0.0))
    if d.length < 1e-6:
        return center
    d.normalize()
    # Distance from the centre to the footprint's edge along d (slab method).
    t = math.inf
    for axis in (0, 1):
        if abs(d[axis]) > 1e-9:
            edge = hi[axis] if d[axis] > 0 else lo[axis]
            t = min(t, (edge - center[axis]) / d[axis])
    if not math.isfinite(t) or t < 0.0:
        return center
    return center + d * (t + STOP_GAP)


def _move_target(move, from_pos=None):
    if move.target_kind == "OBJECT":
        obj = move.target_object
        if obj is None:
            return None
        return approach_point(obj, from_pos)
    return Vector(move.target_point)


def _walk_speed(scene, move):
    if move.speed > 0.0:
        return move.speed
    walk = library.resolve(move.walk_asset) if move.walk_asset else None
    if walk is not None:
        i = library.info(walk, scene)
        if i["stride"] > 0.0 and i["cycle_seconds"] > 0.0:
            return i["stride"] * 2.0 / i["cycle_seconds"]
    return FALLBACK_WALK_SPEED


def _yaw_towards(delta, previous):
    # Characters face -Y at yaw 0 (Blender's front view).
    yaw = math.atan2(delta.x, -delta.y)
    turn = (yaw - previous + math.pi) % (2.0 * math.pi) - math.pi
    return previous + turn


def _compile_moves(scene, cast, moves, warnings):
    """Returns (move keys, virtual clip specs per layer)."""
    pos = Vector(cast.home)
    yaw = cast.home_yaw
    keys = [(0.0, pos.copy(), yaw)]
    virtual = {"BODY": [], "GESTURE": [], "FACE": []}
    t_free = 0.0
    for move in moves:
        target = _move_target(move, pos)
        if target is None:
            warnings.append(f"{move.id}: no target object")
            move.duration = 0.0
            continue
        target.z = pos.z
        delta = target - pos
        delta.z = 0.0
        dist = delta.length
        start = max(move.start, t_free)
        if start > move.start + 1e-6:
            warnings.append(f"{move.id}: starts during the previous move, delayed to {start:.2f}s")
        speed = _walk_speed(scene, move)
        dur = dist / speed if dist > 1e-4 else 0.0
        move.duration = dur
        if dur > 0.0:
            new_yaw = _yaw_towards(delta, yaw)
            turn = min(TURN_SECONDS, dur * 0.5)
            keys.append((start, pos.copy(), yaw))
            keys.append((start + turn, pos + delta * (turn / dur), new_yaw))
            keys.append((start + dur, target.copy(), new_yaw))
            if move.walk_asset:
                walk = library.resolve(move.walk_asset)
                if walk is None:
                    warnings.append(f"{move.id}: walk asset '{move.walk_asset}' not found")
                else:
                    virtual["BODY"].append({"name": f"{move.id}.walk", "action": walk,
                                            "start": start, "duration": dur, "loop_mode": "LOOP",
                                            "blend_in": 0.2, "blend_out": 0.0})
            pos, yaw = target, new_yaw
        if move.arrival_asset:
            act = library.resolve(move.arrival_asset)
            if act is None:
                warnings.append(f"{move.id}: arrival asset '{move.arrival_asset}' not found")
            else:
                i = library.info(act, scene)
                virtual[i["layer"]].append({"name": f"{move.id}.arrive", "action": act,
                                            "start": start + dur, "duration": i["duration"],
                                            "loop_mode": i["loop_mode"],
                                            "blend_in": 0.2, "blend_out": 0.0})
        t_free = start + dur
    return keys, virtual


def _build_move_track(scene, obj, cast, keys):
    action, cb = _new_generated_action(generated_action_names(cast.id)[0], obj)
    loc = [_fcurve(cb, "location", i) for i in range(3)]
    rot = _fcurve(cb, "rotation_euler", 2)
    for t, p, yaw in keys:
        f = to_frame(scene, t)
        for i in range(3):
            _key(loc[i], f, p[i], "LINEAR")
        _key(rot, f, yaw, "LINEAR")
    track = obj.animation_data.nla_tracks.new()
    track.name = _track_name("MOVE", 0)
    s = track.strips.new("move", int(round(action.frame_range[0])), action)
    _ensure_slot(s)
    s.blend_type = BLEND_TYPES["MOVE"]
    s.extrapolation = "HOLD"


# ---------------------------------------------------------------------------
# Mouth
# ---------------------------------------------------------------------------

def _build_mouth_track(scene, obj, cast, lines):
    keys = []
    for line in lines:
        for v in line.visemes:
            keys.append((line.start + v.time, v.shape))
        if line.duration > 0.0:
            keys.append((line.start + line.duration, 0))
    if not keys:
        return
    if MOUTH_PROP not in obj.keys():
        obj[MOUTH_PROP] = 0
    action, cb = _new_generated_action(generated_action_names(cast.id)[1], obj)
    fc = _fcurve(cb, f'["{MOUTH_PROP}"]')
    for t, shape in sorted(keys, key=lambda k: k[0]):
        _key(fc, to_frame(scene, t), float(shape), "CONSTANT")
    f0, f1 = action.frame_range
    a = math.floor(f0)
    track = obj.animation_data.nla_tracks.new()
    track.name = _track_name("MOUTH", 0)
    s = track.strips.new("mouth", a, action)
    s.action_frame_end = math.ceil(f1) + 1
    s.action_frame_start = a
    _ensure_slot(s)
    s.blend_type = BLEND_TYPES["MOUTH"]
    s.extrapolation = "NOTHING"


# ---------------------------------------------------------------------------
# Life: blinks, idle fill, listeners look at the speaker
# ---------------------------------------------------------------------------

BLINK_PROP = "blink"
HEAD_BONE = "head"
MAX_LOOK = math.radians(60)


def scene_seconds(scene):
    return max((scene.frame_end - scene.frame_start) / fps(scene), 0.0)


def root_keys(scene, cast):
    """(time, position, yaw) keys of the character's root over time."""
    moves = sorted((m for m in scene.csk360.moves if m.cast_id == cast.id), key=lambda m: m.start)
    if not moves:
        return [(0.0, Vector(cast.home), cast.home_yaw)]
    keys, _virtual = _compile_moves(scene, cast, moves, [])
    return keys


def pose_at(keys, t):
    """Linear interpolation of root keys at time t -> (position, yaw)."""
    if t <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for (t0, p0, y0), (t1, p1, y1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            f = 0.0 if t1 - t0 < 1e-9 else (t - t0) / (t1 - t0)
            return p0.lerp(p1, f), y0 + (y1 - y0) * f
    return keys[-1][1], keys[-1][2]


def _idle_specs(scene, cast, body_specs):
    """Fill gaps (over 0.5 s) between Body clips with the idle loop, up to the scene end."""
    idle = library.resolve(cast.idle_asset or "idle")
    if idle is None:
        return []
    covered = sorted((s["start"], s["start"] + s["duration"]) for s in body_specs)
    gaps, t = [], 0.0
    for a, b in covered:
        if a - t > 0.5:
            gaps.append((t, a))
        t = max(t, b)
    end = scene_seconds(scene)
    if end - t > 0.5:
        gaps.append((t, end))
    return [{"name": f"idle.{i}", "action": idle, "start": a, "duration": b - a,
             "loop_mode": "LOOP", "blend_in": 0.3, "blend_out": 0.0}
            for i, (a, b) in enumerate(gaps)]


def _blink_keys(scene, cast):
    import random
    rng = random.Random(cast.id)  # same blinks every rebuild
    end = scene_seconds(scene)
    frame = 1.0 / fps(scene)
    keys, t = [], rng.uniform(0.8, 2.5)
    while t < end:
        t0 = round(t / frame) * frame  # on whole frames, so the closed eye is actually rendered
        keys += [(t0, 0.0), (t0 + frame, 1.0), (t0 + 2 * frame, 1.0), (t0 + 4 * frame, 0.0)]
        t += rng.uniform(2.0, 5.0)
    return keys


def _look_keys(scene, cast, root):
    """Head yaw keys: turn toward whoever else is speaking."""
    proj = scene.csk360
    others = {c.id: c for c in proj.cast if c.id != cast.id}
    paths = {}
    segments = []  # (start, end, head angle)
    lines = sorted((l for l in proj.lines if l.cast_id in others and l.duration > 0), key=lambda l: l.start)
    for line in lines:
        speaker = others[line.cast_id]
        if speaker.id not in paths:
            paths[speaker.id] = root_keys(scene, speaker)
        mid = line.start + line.duration * 0.5
        me, my_yaw = pose_at(root, mid)
        them, _ = pose_at(paths[speaker.id], mid)
        d = them - me
        d.z = 0.0
        if d.length < 1e-3:
            continue
        d.rotate(Matrix.Rotation(-my_yaw, 3, "Z"))  # into the character's own frame
        angle = max(-MAX_LOOK, min(MAX_LOOK, math.atan2(d.x, -d.y)))
        segments.append((line.start, line.start + line.duration, angle))

    keys, current = [], 0.0

    def add(t, v):
        if not keys or t > keys[-1][0] + 1e-4:
            keys.append((t, v))

    for i, (a, b, angle) in enumerate(segments):
        add(max(a - 0.2, 0.0), current)
        add(a + 0.15, angle)
        add(b, angle)
        nxt = segments[i + 1][0] if i + 1 < len(segments) else None
        if nxt is None or nxt > b + 0.6:
            add(b + 0.4, 0.0)
            current = 0.0
        else:
            current = angle
    return keys


def _build_life_track(scene, obj, cast):
    if not cast.auto_life:
        return
    blink = _blink_keys(scene, cast) if BLINK_PROP in obj.keys() else []
    has_head = obj.type == "ARMATURE" and obj.pose and HEAD_BONE in obj.pose.bones
    look = _look_keys(scene, cast, root_keys(scene, cast)) if has_head else []
    if not blink and not look:
        return
    action, cb = _new_generated_action(generated_action_names(cast.id)[2], obj)
    if blink:
        fc = _fcurve(cb, f'["{BLINK_PROP}"]')
        for t, v in blink:
            _key(fc, to_frame(scene, t), v, "LINEAR")
    if look:
        pb = obj.pose.bones[HEAD_BONE]
        index = 1  # bone-local Y = vertical axis for an upright head
        if pb.rotation_mode in ("QUATERNION", "AXIS_ANGLE"):
            look = []  # only Euler heads for now
        fc = _fcurve(cb, f'pose.bones["{HEAD_BONE}"].rotation_euler', index)
        for t, v in look:
            _key(fc, to_frame(scene, t), v, "BEZIER")
    f0, f1 = action.frame_range
    a = math.floor(f0)
    track = obj.animation_data.nla_tracks.new()
    track.name = _track_name("LIFE", 0)
    s = track.strips.new("life", a, action)
    s.action_frame_end = math.ceil(f1) + 1
    s.action_frame_start = a
    _ensure_slot(s)
    s.blend_type = BLEND_TYPES["LIFE"]
    s.extrapolation = "NOTHING"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def compile_cast(scene, cast):
    """Rebuild every generated track for one cast member. Returns warnings."""
    warnings = []
    proj = scene.csk360
    obj = cast.object
    clear_cast(obj, cast.id)
    if obj is None:
        return [f"{cast.name}: no character object"]
    obj.animation_data_create()

    moves = sorted((m for m in proj.moves if m.cast_id == cast.id), key=lambda m: m.start)
    virtual = {"BODY": [], "GESTURE": [], "FACE": []}
    if moves:
        keys, virtual = _compile_moves(scene, cast, moves, warnings)
        _build_move_track(scene, obj, cast, keys)

    for layer in ("BODY", "GESTURE", "FACE"):
        specs = []
        for clip in proj.clips:
            if clip.cast_id != cast.id or clip.layer != layer:
                continue
            action = library.resolve(clip.asset)
            if action is None:
                warnings.append(f"{clip.id}: asset '{clip.asset}' not found")
                continue
            specs.append({"name": clip.id, "action": action, "start": clip.start,
                          "duration": clip.duration, "loop_mode": clip.loop_mode,
                          "blend_in": clip.blend_in, "blend_out": clip.blend_out,
                          "offset": round(clip.offset * fps(scene))})
        specs.extend(virtual[layer])
        if layer == "BODY" and cast.auto_life:
            specs.extend(_idle_specs(scene, cast, specs))
        if not specs:
            continue
        rate = fps(scene)
        for spec in specs:
            spec["span"] = _clip_span(scene, spec["start"], spec["duration"])
            spec["blend_in"] *= rate
            spec["blend_out"] *= rate
            spec["blend_type"] = BLEND_TYPES[layer]
        n = _assign_subtracks(specs)
        tracks = []
        for sub in range(n):
            track = obj.animation_data.nla_tracks.new()
            track.name = _track_name(layer, sub)
            tracks.append(track)
        for spec in sorted(specs, key=lambda s: s["span"][0]):
            _place_clip(tracks[spec["sub"]], spec)

    _build_life_track(scene, obj, cast)
    lines = sorted((l for l in proj.lines if l.cast_id == cast.id), key=lambda l: l.start)
    _build_mouth_track(scene, obj, cast, lines)
    return warnings


def compile_dialogue(scene, base_dir=None):
    """Rebuild all CSK360 sound strips and update line durations. Returns warnings.

    `base_dir` resolves "//" paths when the .blend is about to be saved somewhere new."""
    warnings = []
    proj = scene.csk360
    clear_sounds(scene)
    lines = [l for l in proj.lines if l.audio_path]
    if not lines:
        return warnings
    sed = scene.sequence_editor_create()
    channel_of = {c.id: i + 1 for i, c in enumerate(proj.cast)}
    rate = fps(scene)
    for line in lines:
        path = (bpy.path.abspath(line.audio_path, start=base_dir) if base_dir
                else bpy.path.abspath(line.audio_path))
        if not os.path.isfile(path):
            warnings.append(f"{line.id}: audio file not found: {line.audio_path}")
            continue
        channel = min(channel_of.get(line.cast_id, 1), 128)
        strip = sed.strips.new_sound(SOUND_PREFIX + line.id, path, channel,
                                     int(round(to_frame(scene, line.start))))
        line.duration = strip.frame_final_duration / rate
    return warnings


def compile_all(scene):
    warnings = compile_dialogue(scene)
    for cast in scene.csk360.cast:
        warnings += compile_cast(scene, cast)
    return warnings
