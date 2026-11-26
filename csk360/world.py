# SPDX-License-Identifier: GPL-3.0-or-later
"""The world characters live in: object labels, label detection and character abilities.

Labels say what characters can do with an object: walk on it, stand on it
(after a jump or climb), walk around it, lift it, and how heavy it is.
Abilities say what a character can do: how much it can lift and how high it
can jump. The checks return plain-English reasons, so scripts, the UI and
agents can explain why something can't happen.

    world.detect(scene)                       # guess labels for unlabelled objects
    world.label(obj, liftable=True, weight=12)
    ok, why = world.can_lift(scene, "leo", "Crate", helpers=["maya"])
    ok, why = world.can_jump_onto(scene, "leo", "Table")
"""

import bpy
from mathutils import Vector

LABEL_FIELDS = ("walkable", "jump_onto", "obstacle", "liftable", "weight")

# Detection rules (metres, kg). Guesses only; detected labels are marked as such.
FLOOR_MIN_AREA = 4.0        # a big flat thing at floor level is a floor
FLOOR_MAX_TOP = 0.05
SURFACE_MIN_AREA = 0.09     # at least 30 x 30 cm to stand on
SURFACE_MAX_TOP = 1.5       # higher tops are not "stand on" surfaces
LIFT_MAX_SIZE = 1.2         # longest side of something a person could carry
DENSITY = 150.0             # kg per m^3 of bounding box (furniture, boxes: mostly air)


class WorldError(Exception):
    pass


def _cmd():
    from . import commands
    return commands


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _obj(thing):
    if isinstance(thing, bpy.types.Object):
        return thing
    obj = bpy.data.objects.get(str(thing))
    if obj is None:
        raise _cmd().CSKError(f"No object named '{thing}'.")
    return obj


def get_label(obj):
    obj = _obj(obj)
    lab = obj.csk360_label
    out = {k: getattr(lab, k) for k in LABEL_FIELDS}
    out["weight"] = round(out["weight"], 2)
    out["source"] = lab.source
    return out


def label(obj, source="USER", **fields):
    """Set labels on an object. Unknown fields raise CSKError."""
    obj = _obj(obj)
    bad = set(fields) - set(LABEL_FIELDS)
    if bad:
        raise _cmd().CSKError(f"Unknown label(s): {', '.join(sorted(bad))}. "
                              f"Use: {', '.join(LABEL_FIELDS)}.")
    lab = obj.csk360_label
    for k, v in fields.items():
        setattr(lab, k, float(v) if k == "weight" else bool(v))
    lab.source = source
    return get_label(obj)


def clear_label(obj):
    obj = _obj(obj)
    lab = obj.csk360_label
    for k in LABEL_FIELDS:
        setattr(lab, k, 0.0 if k == "weight" else False)
    lab.source = "NONE"


def measure(obj):
    """World-space size of an object's bounding box."""
    obj = _obj(obj)
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector([min(c[i] for c in corners) for i in range(3)])
    hi = Vector([max(c[i] for c in corners) for i in range(3)])
    size = hi - lo
    return {"bottom": lo.z, "top": hi.z, "size": tuple(round(v, 4) for v in size),
            "area": size.x * size.y, "volume": size.x * size.y * size.z,
            "center": tuple((lo + hi) / 2)}


def guess(obj, floor_z=0.0):
    """Labels a person would probably give this object, from its size alone."""
    m = measure(obj)
    top = m["top"] - floor_z
    sx, sy, sz = m["size"]
    g = {k: False for k in LABEL_FIELDS}
    g["weight"] = 0.0
    if m["area"] >= FLOOR_MIN_AREA and top <= FLOOR_MAX_TOP:
        g["walkable"] = True
        return g
    g["obstacle"] = top > 0.15
    if m["area"] >= SURFACE_MIN_AREA and 0.15 < top <= SURFACE_MAX_TOP:
        g["jump_onto"] = True
    if max(sx, sy, sz) <= LIFT_MAX_SIZE:
        g["liftable"] = True
        g["weight"] = round(max(0.2, m["volume"] * DENSITY), 1)
    return g


def _skip(scene):
    from . import paths
    return paths.cast_objects(scene)


def detect(scene, overwrite=False):
    """Guess labels for every unlabelled mesh (or all of them with overwrite).

    Objects you labelled yourself are never changed unless overwrite is True.
    Returns {object name: labels} for what was set."""
    skip = _skip(scene)
    done = {}
    for obj in scene.objects:
        if obj.type != "MESH" or obj in skip:
            continue
        if obj.csk360_label.source == "USER" and not overwrite:
            continue
        if obj.csk360_label.source == "AUTO" and not overwrite:
            continue
        g = guess(obj)
        label(obj, source="AUTO", **g)
        done[obj.name] = get_label(obj)
    return done


def labelled(scene, **match):
    """Objects whose labels match, e.g. labelled(scene, liftable=True)."""
    out = []
    for obj in scene.objects:
        if obj.csk360_label.source == "NONE":
            continue
        lab = get_label(obj)
        if all(lab.get(k) == v for k, v in match.items()):
            out.append(obj.name)
    return out


# ---------------------------------------------------------------------------
# Abilities
# ---------------------------------------------------------------------------

ABILITY_FIELDS = ("weight", "strength", "jump_height")


def set_abilities(scene, cast_id, **fields):
    bad = set(fields) - set(ABILITY_FIELDS)
    if bad:
        raise _cmd().CSKError(f"Unknown ability: {', '.join(sorted(bad))}. "
                              f"Use: {', '.join(ABILITY_FIELDS)}.")
    c = _cmd().get_cast(scene, cast_id)
    for k, v in fields.items():
        setattr(c, k, float(v))
    return abilities(scene, cast_id)


def abilities(scene, cast_id):
    c = _cmd().get_cast(scene, cast_id)
    return {k: round(getattr(c, k), 3) for k in ABILITY_FIELDS}


def _cast_by_ref(scene, ref):
    """A cast member from its id, name or object, else None."""
    proj = scene.csk360
    for c in proj.cast:
        if ref in (c.id, c.name) or (c.object is not None and (ref is c.object or ref == c.object.name)):
            return c
    return None


def _weight_of(scene, thing):
    """(kg, display name, is_person) for an object or a cast member."""
    person = _cast_by_ref(scene, thing)
    if person is not None:
        return person.weight, person.name, True
    obj = _obj(thing)
    lab = obj.csk360_label
    if lab.source == "NONE":
        raise _cmd().CSKError(f"'{obj.name}' has no labels yet. Label it (CSK360 > Objects) "
                              "or press Detect Labels.")
    if not lab.liftable:
        raise _cmd().CSKError(f"'{obj.name}' is not liftable.")
    if lab.weight <= 0.0:
        raise _cmd().CSKError(f"'{obj.name}' has no weight set.")
    return lab.weight, obj.name, False


def can_lift(scene, cast_id, thing, helpers=()):
    """(ok, reason). `thing` is an object, an object name or a cast member (a person).
    Helpers add their strength (lifting together)."""
    commands = _cmd()
    c = commands.get_cast(scene, cast_id)
    try:
        kg, name, is_person = _weight_of(scene, thing)
    except commands.CSKError as e:
        return False, str(e)
    if is_person and name == c.name:
        return False, f"{c.name} can't lift themself."
    team = [c] + [commands.get_cast(scene, h) for h in helpers]
    total = sum(m.strength for m in team)
    who = c.name if len(team) == 1 else " and ".join(m.name for m in team)
    if total >= kg:
        return True, f"{who} can lift {name} ({kg:g} kg; can lift {total:g} kg)."
    short = kg - total
    hint = " Add helpers or raise their strength." if not is_person else ""
    return False, (f"{who} can't lift {name}: it weighs {kg:g} kg and "
                   f"{'they' if len(team) > 1 else c.name} can lift {total:g} kg "
                   f"({short:g} kg short).{hint}")


def can_jump_onto(scene, cast_id, obj):
    """(ok, reason) for jumping or climbing onto an object's top."""
    commands = _cmd()
    c = commands.get_cast(scene, cast_id)
    try:
        obj = _obj(obj)
    except commands.CSKError as e:
        return False, str(e)
    lab = obj.csk360_label
    if lab.source == "NONE":
        return False, f"'{obj.name}' has no labels yet. Label it or press Detect Labels."
    if not lab.jump_onto:
        return False, f"'{obj.name}' is not something to stand on."
    rise = measure(obj)["top"] - c.home[2]
    if rise > c.jump_height + 1e-6:
        return False, (f"{c.name} can't jump onto {obj.name}: its top is {rise:.2f} m up and "
                       f"{c.name} jumps {c.jump_height:.2f} m.")
    return True, f"{c.name} can jump onto {obj.name} ({rise:.2f} m up)."
