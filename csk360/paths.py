# SPDX-License-Identifier: GPL-3.0-or-later
"""Click-to-move picking and the walk paths drawn in the viewport.

`pick()` turns a viewport ray into a move target: the floor gives a point,
a prop gives the object (so the walk follows the prop if it moves, and uses
its "approach" child when it has one). `segments()` lists each character's
planned path. The draw handler shows the paths of the active character as
dashed lines with a ring at each destination.

Picking and geometry are plain functions so the headless tests can cover them;
only `_draw()` needs a GPU.
"""

import math

import bpy
from mathutils import Vector

from . import compiler

FLOOR_TOLERANCE = 0.1    # metres: a hit this close to the character's floor is "the floor"
FLOOR_NORMAL_Z = 0.7     # and faces up at least this much
MAX_PASSES = 16          # ray cast restarts past ignored objects
ARRIVAL_PROP = "csk360_arrival"   # custom property on a prop: action to play on arrival
LIFT = 0.02              # draw paths slightly above the floor

PATH_COLOR = (1.0, 0.55, 0.1, 0.9)
OTHER_COLOR = (1.0, 0.55, 0.1, 0.35)
PREVIEW_COLOR = (0.3, 0.8, 1.0, 0.9)

# Set by the click-to-move operator while it runs: {"cast_id", "from", "to"}.
preview = {}


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------

def hierarchy(obj):
    """The object and all of its descendants."""
    out = {obj}
    for child in obj.children_recursive:
        out.add(child)
    return out


def cast_objects(scene):
    """Every object that belongs to a cast member (rigs and their meshes)."""
    out = set()
    for c in scene.csk360.cast:
        if c.object is not None:
            out |= hierarchy(c.object)
    return out


def floor_height(cast):
    return cast.home[2]


def ray_hit(scene, depsgraph, origin, direction, ignore=(), accept=None):
    """First hit that is not in `ignore` (and passes `accept`): (location, normal, object)."""
    origin = Vector(origin)
    direction = Vector(direction).normalized()
    for _ in range(MAX_PASSES):
        ok, loc, normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction)
        if not ok:
            return None
        obj = getattr(obj, "original", obj)
        if obj not in ignore and (accept is None or accept(obj)):
            return loc, normal, obj
        origin = loc + direction * 1e-3
    return None


def floor_point(origin, direction, z):
    """Where the ray meets the horizontal plane at height z, or None."""
    origin = Vector(origin)
    direction = Vector(direction)
    if direction.z >= -1e-6:
        return None
    t = (z - origin.z) / direction.z
    if t <= 0.0:
        return None
    return origin + direction * t


def _standable(obj):
    lab = obj.csk360_label
    return lab.source == "NONE" or lab.jump_onto or lab.walkable


def pick(scene, depsgraph, cast, origin, direction, stand=False):
    """Move target under a viewport ray for `cast`.

    Returns {"point": Vector} for the floor, {"target": Object, "arrival": str}
    for a prop, or None when the ray misses everything and points at the sky.
    Characters (this one and the rest of the cast) are see-through. With stand=True
    (jumping), labelled objects you can't stand on are see-through too.
    """
    z = floor_height(cast)
    hit = ray_hit(scene, depsgraph, origin, direction, ignore=cast_objects(scene),
                  accept=_standable if stand else None)
    if hit is not None:
        loc, normal, obj = hit
        on_floor = normal.z >= FLOOR_NORMAL_Z and abs(loc.z - z) <= FLOOR_TOLERANCE
        if not on_floor:
            return {"target": obj, "arrival": str(obj.get(ARRIVAL_PROP, ""))}
        return {"point": Vector((loc.x, loc.y, z))}
    p = floor_point(origin, direction, z)
    return None if p is None else {"point": p}


def target_location(result, from_pos=None, z=None):
    """Location a pick result will walk to (for previews), at floor height z."""
    if result is None:
        return None
    if "point" in result:
        loc = result["point"].copy()
    else:
        loc = compiler.approach_point(result["target"], from_pos)
    if z is not None:
        loc.z = z
    return loc


# ---------------------------------------------------------------------------
# Path geometry
# ---------------------------------------------------------------------------

def segments(scene, cast):
    """[(move id, from, to)] in start order, at the character's floor height."""
    pos = Vector(cast.home)
    out = []
    moves = sorted((m for m in scene.csk360.moves if m.cast_id == cast.id), key=lambda m: m.start)
    for m in moves:
        target = compiler._move_target(m, pos)
        if target is None:
            continue
        target.z = pos.z
        out.append((m.id, pos.copy(), target.copy()))
        pos = target
    return out


def dashes(a, b, dash=0.15, gap=0.1):
    """Vertex pairs for a dashed line from a to b (flat list, two per dash)."""
    a, b = Vector(a), Vector(b)
    length = (b - a).length
    if length < 1e-6:
        return []
    d = (b - a) / length
    verts = []
    t = 0.0
    while t < length:
        verts.append(a + d * t)
        verts.append(a + d * min(t + dash, length))
        t += dash + gap
    return verts


def ring(center, radius=0.25, steps=24):
    """Vertex pairs for a flat circle around center."""
    c = Vector(center)
    pts = [c + Vector((math.cos(i / steps * math.tau) * radius,
                       math.sin(i / steps * math.tau) * radius, 0.0)) for i in range(steps)]
    verts = []
    for i in range(steps):
        verts.append(pts[i])
        verts.append(pts[(i + 1) % steps])
    return verts


def path_lines(scene, cast):
    """All line vertices for one character's planned path."""
    lift = Vector((0.0, 0.0, LIFT))
    verts = []
    for _id, a, b in segments(scene, cast):
        verts += dashes(a + lift, b + lift)
        verts += ring(b + lift)
    return verts


# ---------------------------------------------------------------------------
# Viewport drawing
# ---------------------------------------------------------------------------

_handle = None


def _batch(verts, color, width):
    import gpu
    from gpu_extras.batch import batch_for_shader
    if not verts:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": [tuple(v) for v in verts]})
    region = bpy.context.region
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw():
    import gpu
    context = bpy.context
    scene = context.scene
    proj = getattr(scene, "csk360", None)
    if proj is None or not proj.show_paths or (not len(proj.moves) and not preview):
        return
    from .commands import cast_for_object
    active = cast_for_object(scene, context.active_object)
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    for c in proj.cast:
        mine = active is not None and c.id == active.id
        _batch(path_lines(scene, c), PATH_COLOR if mine else OTHER_COLOR, 3.0 if mine else 1.5)
    if preview.get("to") is not None and preview.get("from") is not None:
        lift = Vector((0.0, 0.0, LIFT))
        a, b = preview["from"] + lift, preview["to"] + lift
        _batch(dashes(a, b) + ring(b, 0.3), PREVIEW_COLOR, 3.0)
    gpu.state.blend_set("NONE")


def register():
    global _handle
    if bpy.app.background or _handle is not None:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    preview.clear()
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
