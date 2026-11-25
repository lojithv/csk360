# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose and action library.

For now the library is the file's Actions. Any non-generated action can be
used as a clip; actions marked with `mark()` carry metadata (kind, layer,
default duration, loop, stride, tags) used for defaults, filters and search.
Asset Browser integration comes later and will feed the same functions.
"""

import difflib

import bpy

META_KEY = "csk360"
GENERATED_PREFIX = "CSK360."

KINDS = ("pose", "action", "transition")

DEFAULT_META = {
    "kind": "action",      # pose | action | transition
    "layer": "BODY",       # BODY | GESTURE | FACE
    "loop": False,         # actions only: repeat to fill the clip
    "duration": 0.0,       # default clip length in seconds, 0 = natural length (2 s for poses)
    "stride": 0.0,         # metres per step for locomotion cycles (one cycle = two steps)
    "category": "",
    "tags": "",            # comma separated
    "favorite": False,     # shown in the pose pie menu (P)
}

# Picker category chips, as in Frameling.
CATEGORIES = ("Standing", "Gestures", "Sitting and kneeling", "Lying", "Motion keys")


def fps(scene=None):
    scene = scene or bpy.context.scene
    return scene.render.fps / scene.render.fps_base


def is_generated(action):
    return action.name.startswith(GENERATED_PREFIX)


def is_marked(action):
    return META_KEY in action.keys()


def meta(action):
    data = dict(DEFAULT_META)
    raw = action.get(META_KEY)
    if raw is not None:
        data.update(raw.to_dict() if hasattr(raw, "to_dict") else dict(raw))
    return data


def mark(action, **fields):
    """Mark an action as a library asset and set its metadata."""
    unknown = set(fields) - set(DEFAULT_META)
    if unknown:
        raise ValueError(f"Unknown asset fields: {', '.join(sorted(unknown))}")
    data = meta(action)
    data.update(fields)
    if data["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    action[META_KEY] = data
    action.use_fake_user = True
    return data


def resolve(asset_id):
    action = bpy.data.actions.get(asset_id)
    if action is None or is_generated(action):
        return None
    return action


def asset_ids(marked_only=False):
    return [a.name for a in bpy.data.actions
            if not is_generated(a) and (is_marked(a) or not marked_only)]


def suggest(asset_id):
    return difflib.get_close_matches(asset_id, asset_ids(), n=3, cutoff=0.5)


def info(action, scene=None):
    """Resolved clip defaults for an action."""
    m = meta(action)
    f0, f1 = action.frame_range
    length = max(f1 - f0, 1.0)
    rate = fps(scene)
    if m["kind"] == "pose":
        loop_mode = "HOLD"
    elif m["loop"]:
        loop_mode = "LOOP"
    else:
        loop_mode = "ONCE"
    duration = m["duration"] or (2.0 if m["kind"] == "pose" else length / rate)
    return {
        "id": action.name,
        "kind": m["kind"],
        "layer": m["layer"],
        "loop_mode": loop_mode,
        "duration": duration,
        "cycle_seconds": length / rate,
        "stride": m["stride"],
        "category": m["category"],
        "tags": [t.strip() for t in m["tags"].split(",") if t.strip()],
        "favorite": bool(m.get("favorite")),
    }


def default_walk():
    """First marked looping asset tagged 'walk', or ''."""
    for action in bpy.data.actions:
        if is_generated(action) or not is_marked(action):
            continue
        i = info(action)
        if i["loop_mode"] == "LOOP" and ("walk" in i["tags"] or action.name.lower().startswith("walk")):
            return action.name
    return ""


def favorites(limit=7):
    """Assets for the pose pie: favourites first, then the rest, by name."""
    items = search(marked_only=True)
    items.sort(key=lambda i: (not i["favorite"], i["id"]))
    return items[:limit]


def search(text="", layer=None, marked_only=True, category=None):
    """Library items matching all words of `text` in id, category or tags."""
    words = text.lower().split()
    out = []
    for name in asset_ids(marked_only=marked_only):
        i = info(bpy.data.actions[name])
        if layer and i["layer"] != layer:
            continue
        if category and i["category"] != category:
            continue
        hay = " ".join([name.lower(), i["category"].lower(), " ".join(i["tags"]).lower()])
        if not all(w in hay for w in words):
            continue
        out.append(i)
    return out
