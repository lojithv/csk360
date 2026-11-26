# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene scripts: one text file that builds a whole scene.

Three input formats, all turned into the same plain dict:

* YAML in the design-doc shape (a built-in subset parser: Blender ships no PyYAML)::

    cast:
      leo:  {character: leo, voice: kokoro/am_michael}
      maya: {character: maya, voice: kokoro/af_heart}
    timeline:
      - {at: 0, who: maya, do: wave, for: 2}
      - {at: 0, who: leo, move_to: desk_chair, then: sit}
      - {at: 6, who: leo, say: "Morning! Did you see the numbers?", face: happy}
      - {after: prev, who: maya, say: "I did. We need to talk.", gesture: arms_crossed}
    output: {size: 1080p, fps: 24}

* JSON with the same structure.
* Frameling's screenplay text (``Maya (happy, wave): Hi Leo!``), so one screenplay
  works in both tools.

`validate()` returns problems without touching the scene; `build()` applies the
script through `commands`, exactly as the UI would.
"""

import difflib
import json
import os
import re

import bpy

from . import commands, library, world
from .commands import CSKError

EXPRESSIONS = ("neutral", "happy", "sad", "angry", "surprised", "thinking", "wink", "worried", "confused")
SIZES = {"1080p": (1920, 1080), "720p": (1280, 720), "4k": (3840, 2160),
         "9:16": (1080, 1920), "vertical": (1080, 1920), "square": (1080, 1080)}
ENTRY_KEYS = {"at", "after", "who", "do", "for", "move_to", "then", "say", "face", "gesture",
              "voice", "speed", "mode", "layer", "pick_up", "put_down", "helpers", "jump_onto"}


class ScriptError(CSKError):
    """The script has errors; `problems` lists every one."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("Script has errors:\n" + "\n".join(f"- {p}" for p in problems))


# ---------------------------------------------------------------------------
# YAML subset
# ---------------------------------------------------------------------------

def _strip_comment(line):
    out, quote = [], None
    for i, c in enumerate(line):
        if quote:
            if c == quote and line[i - 1] != "\\":
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


class _Flow:
    """Parser for flow values: {a: 1, b: [x, "y"]}, quoted strings, numbers, bare words."""

    def __init__(self, text, where):
        self.s, self.i, self.where = text, 0, where

    def fail(self, msg):
        raise ValueError(f"{self.where}: {msg} in: {self.s.strip()}")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def parse(self):
        v = self.value(stop="")
        self.ws()
        if self.i != len(self.s):
            self.fail("unexpected text after value")
        return v

    def value(self, stop):
        self.ws()
        if self.i >= len(self.s):
            return None
        c = self.s[self.i]
        if c == "{":
            return self.mapping()
        if c == "[":
            return self.sequence()
        if c in "\"'":
            return self.quoted()
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in stop:
            self.i += 1
        return _scalar(self.s[start:self.i].strip())

    def quoted(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\" and q == '"' and self.i + 1 < len(self.s):
                nxt = self.s[self.i + 1]
                out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                self.i += 2
                continue
            if c == q:
                if q == "'" and self.s[self.i + 1:self.i + 2] == "'":
                    out.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1
        self.fail("unclosed quote")

    def mapping(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.s[self.i:self.i + 1] == "}":
                self.i += 1
                return out
            key = self.quoted() if self.s[self.i:self.i + 1] in "\"'" else self._bare_key()
            self.ws()
            if self.s[self.i:self.i + 1] != ":":
                self.fail(f"expected ':' after '{key}'")
            self.i += 1
            out[str(key)] = self.value(stop=",}")
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c == ",":
                self.i += 1
            elif c != "}":
                self.fail("expected ',' or '}'")

    def _bare_key(self):
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ":,}":
            self.i += 1
        return self.s[start:self.i].strip()

    def sequence(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.s[self.i:self.i + 1] == "]":
                self.i += 1
                return out
            out.append(self.value(stop=",]"))
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c == ",":
                self.i += 1
            elif c != "]":
                self.fail("expected ',' or ']'")


def _scalar(t):
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if t in ("true", "True", "yes"):
        return True
    if t in ("false", "False", "no"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def parse_yaml(text):
    """Parse the block/flow YAML subset scene scripts use (mappings, lists, flow values)."""
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError(f"line {n}: use spaces, not tabs, for indentation")
        s = _strip_comment(raw)
        if s.strip() and s.strip() != "---":
            lines.append((n, len(s) - len(s.lstrip()), s.strip()))
    value, i = _block(lines, 0, lines[0][1] if lines else 0)
    if i != len(lines):
        raise ValueError(f"line {lines[i][0]}: unexpected indentation")
    return value


def _split_key(text, n):
    m = re.match(r'^("[^"]*"|\'[^\']*\'|[^:{}\[\],]+?)\s*:(\s+|$)(.*)$', text)
    if not m:
        return None
    key = m.group(1)
    if key[0] in "\"'":
        key = key[1:-1]
    return key.strip(), m.group(3)


def _block(lines, i, indent):
    if i >= len(lines):
        return None, i
    n, ind, text = lines[i]
    if text.startswith("- ") or text == "-":
        out = []
        while i < len(lines) and lines[i][1] == indent and (lines[i][2].startswith("- ") or lines[i][2] == "-"):
            n, ind, text = lines[i]
            rest = text[1:].strip()
            i += 1
            if not rest:
                if i < len(lines) and lines[i][1] > indent:
                    val, i = _block(lines, i, lines[i][1])
                else:
                    val = None
            elif _split_key(rest, n) and not rest.startswith(("{", "[", '"', "'")):
                # "- key: value" starts a mapping inside the list item
                sub = [(n, indent + 2, rest)]
                j = i
                while j < len(lines) and lines[j][1] > indent:
                    sub.append(lines[j])
                    j += 1
                val, _ = _block(sub, 0, indent + 2)
                i = j
            else:
                val = _Flow(rest, f"line {n}").parse()
            out.append(val)
        return out, i
    out = {}
    while i < len(lines) and lines[i][1] == indent:
        n, ind, text = lines[i]
        kv = _split_key(text, n)
        if kv is None:
            raise ValueError(f"line {n}: expected 'key: value', got: {text}")
        key, rest = kv
        i += 1
        if rest.strip():
            out[key] = _Flow(rest, f"line {n}").parse()
        elif i < len(lines) and lines[i][1] > indent:
            out[key], i = _block(lines, i, lines[i][1])
        else:
            out[key] = None
    return out, i


# ---------------------------------------------------------------------------
# Frameling screenplay
# ---------------------------------------------------------------------------

_LINE = re.compile(r"^(?P<who>[^:(\[>]+?)\s*(\((?P<tags>[^)]*)\))?\s*:\s*(?P<text>.+)$")


def parse_screenplay(text):
    """Frameling's screenplay format -> script dict (scenes play one after another)."""
    script = {"cast": {}, "timeline": [], "notes": []}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith(("title:", "style:")):
            key, _, val = line.partition(":")
            script[key.strip().lower()] = val.strip()
            continue
        if line.startswith("["):
            script["notes"].append(f"line {n}: scene '{line.strip('[]')}' (sets come later; ignored)")
            continue
        if line.startswith(">"):
            script["notes"].append(f"line {n}: caption ignored (subtitles come later)")
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"line {n}: expected 'Name (expression, action): text', got: {line}")
        name = m.group("who").strip()
        cid = commands._slug(name)
        script["cast"].setdefault(cid, {"character": name})
        entry = {"who": cid, "say": m.group("text").strip(), "after": "prev"}
        for tag in (t.strip().lower() for t in (m.group("tags") or "").split(",")):
            if not tag:
                continue
            if tag in EXPRESSIONS:
                entry["face"] = tag
            else:
                entry["gesture"] = tag
        script["timeline"].append(entry)
    return script


def load(path):
    with open(bpy.path.abspath(path), encoding="utf-8") as f:
        text = f.read()
    return loads(text, os.path.splitext(path)[1].lower())


def loads(text, kind=".yaml"):
    """Parse script text. kind: .json, .yaml/.yml, or .txt/.screenplay/.fountain."""
    try:
        if kind == ".json":
            data = json.loads(text)
        elif kind in (".txt", ".screenplay", ".fountain"):
            data = parse_screenplay(text)
        else:
            data = parse_yaml(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise ScriptError([f"Could not read the script: {e}"])
    if not isinstance(data, dict):
        raise ScriptError(["The script must be a mapping with 'cast' and 'timeline'."])
    return data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _suggest(name, options):
    hint = difflib.get_close_matches(str(name), list(options), n=3, cutoff=0.5)
    return f" Did you mean: {', '.join(hint)}?" if hint else ""


def _asset_ok(name, assets):
    return name in assets


def validate(script, scene=None):
    """Return (errors, warnings). Nothing in the scene is changed.

    Assets that the starter character provides count as available even before it is built.
    """
    from . import starter
    errors, warnings = [], list(script.get("notes", []))
    assets = set(library.asset_ids()) | set(starter.STARTER_ASSETS)
    cast = script.get("cast") or {}
    if not isinstance(cast, dict) or not cast:
        errors.append("'cast' must list at least one character, e.g. leo: {character: leo}.")
        cast = {}
    for cid, spec in cast.items():
        spec = spec if isinstance(spec, dict) else {}
        for k in ("weight", "strength", "jump"):
            if k in spec and not (isinstance(spec[k], (int, float)) and spec[k] >= 0):
                errors.append(f"cast {cid}: '{k}' must be a number (kg for weight and strength, "
                              "metres for jump).")
        v = spec.get("voice")
        if v and "/" not in str(v):
            errors.append(f"cast {cid}: voice '{v}' should look like kokoro/af_heart or supertonic/M1.")
    timeline = script.get("timeline") or []
    if not isinstance(timeline, list):
        errors.append("'timeline' must be a list of entries.")
        timeline = []
    for n, e in enumerate(timeline, 1):
        where = f"timeline #{n}"
        if not isinstance(e, dict):
            errors.append(f"{where}: each entry must be a mapping like {{at: 0, who: leo, do: wave}}.")
            continue
        unknown = set(e) - ENTRY_KEYS
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))}."
                          + _suggest(sorted(unknown)[0], ENTRY_KEYS))
        who = e.get("who")
        if who not in cast:
            errors.append(f"{where}: 'who: {who}' is not in the cast." + _suggest(who, cast))
        if "at" in e and not isinstance(e["at"], (int, float)):
            errors.append(f"{where}: 'at' must be seconds, e.g. at: 6.")
        if "after" in e and e["after"] != "prev":
            errors.append(f"{where}: only 'after: prev' is supported.")
        if not any(k in e for k in ("do", "move_to", "say", "gesture", "face", "pick_up", "put_down",
                                    "jump_onto")):
            errors.append(f"{where}: nothing to do; use do, move_to, say, gesture, face, "
                          "pick_up or put_down.")
        for key in ("pick_up", "put_down", "jump_onto"):
            t = e.get(key)
            if key in e and isinstance(t, str) and t != "front" and scene is not None \
                    and bpy.data.objects.get(t) is None:
                errors.append(f"{where}: no object named '{t}' to {key.replace('_', ' ')}."
                              + _suggest(t, [o.name for o in bpy.data.objects]))
        for key in ("do", "gesture", "then"):
            if key in e and not _asset_ok(e[key], assets):
                errors.append(f"{where}: no pose or action '{e[key]}'." + _suggest(e[key], assets))
        if "face" in e and not _asset_ok(e["face"], assets):
            warnings.append(f"{where}: no expression '{e['face']}' in the library yet; skipped.")
        if "move_to" in e:
            t = e["move_to"]
            if isinstance(t, list):
                if len(t) not in (2, 3) or not all(isinstance(x, (int, float)) for x in t):
                    errors.append(f"{where}: move_to point must be [x, y] or [x, y, z].")
            elif scene is not None and bpy.data.objects.get(str(t)) is None:
                errors.append(f"{where}: no object named '{t}' to walk to."
                              + _suggest(t, [o.name for o in bpy.data.objects]))
        if "for" in e and not (isinstance(e["for"], (int, float)) and e["for"] > 0):
            errors.append(f"{where}: 'for' must be a positive number of seconds.")
        if "mode" in e and e["mode"] not in ("LOOP", "ONCE", "HOLD", "loop", "once", "hold", "pose"):
            errors.append(f"{where}: mode must be loop, once or pose.")
    objects = script.get("objects") or {}
    if not isinstance(objects, dict):
        errors.append("'objects' must map object names to labels, e.g. Crate: {liftable: true, weight: 12}.")
        objects = {}
    from .world import LABEL_FIELDS
    for name, labels in objects.items():
        if scene is not None and bpy.data.objects.get(str(name)) is None:
            errors.append(f"objects: no object named '{name}'."
                          + _suggest(name, [o.name for o in bpy.data.objects]))
        if not isinstance(labels, dict):
            errors.append(f"objects {name}: give labels as a mapping, e.g. {{liftable: true}}.")
            continue
        bad = set(labels) - set(LABEL_FIELDS)
        if bad:
            errors.append(f"objects {name}: unknown label(s) {', '.join(sorted(bad))}."
                          + _suggest(sorted(bad)[0], LABEL_FIELDS))
    out = script.get("output") or {}
    if out.get("size") and str(out["size"]) not in SIZES:
        errors.append(f"output size '{out['size']}' unknown. Use one of: {', '.join(SIZES)}.")
    if script.get("set"):
        warnings.append(f"set '{script['set']}': sets come later; ignored.")
    if script.get("camera"):
        warnings.append(f"camera '{script['camera']}': the camera director comes later; ignored.")
    return errors, warnings


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _find_character(name):
    for o in bpy.data.objects:
        if o.name.lower() == str(name).lower() and o.type in ("ARMATURE", "MESH", "EMPTY"):
            return o
    return None


def _mode(value):
    if value is None:
        return None
    v = str(value).upper()
    return "HOLD" if v == "POSE" else v


def build(scene, script, voices=True, clear=True):
    """Apply a script to the scene. Returns a report dict; raises ScriptError on errors."""
    from . import starter
    errors, warnings = validate(script, scene)
    if errors:
        raise ScriptError(errors)
    if clear:
        for cid in [c.id for c in scene.csk360.cast]:
            commands.remove_cast(scene, cid)
    starter.ensure_library()
    out = script.get("output") or {}
    if out.get("fps"):
        scene.render.fps, scene.render.fps_base = int(out["fps"]), 1.0
    if out.get("size"):
        scene.render.resolution_x, scene.render.resolution_y = SIZES[str(out["size"])]
        scene.render.resolution_percentage = 100

    ids = {}
    spacing = 0
    for cid, spec in (script.get("cast") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        name = spec.get("character") or cid
        obj = _find_character(name)
        if obj is None:
            title = str(name).replace("_", " ").title().replace(" ", "")
            obj = starter.create_character(scene, name=title, location=(spacing * 1.2, 0.0, 0.0))
            spacing += 1
            warnings.append(f"cast {cid}: no object named '{name}', added a starter character.")
        prior = commands.cast_for_object(scene, obj)
        if prior is not None:
            ids[cid] = prior.id
        else:
            ids[cid] = commands.add_cast(scene, obj, name=str(name), voice=spec.get("voice", ""))
        if spec.get("voice"):
            commands.get_cast(scene, ids[cid]).voice = spec["voice"]
        if spec.get("speed"):
            commands.get_cast(scene, ids[cid]).speed = float(spec["speed"])
        abil = {k2: spec[k1] for k1, k2 in (("weight", "weight"), ("strength", "strength"),
                                             ("jump", "jump_height")) if k1 in spec}
        if abil:
            world.set_abilities(scene, ids[cid], **abil)

    for name, labels in (script.get("objects") or {}).items():
        world.label(str(name), **labels)

    prev_end = 0.0
    made = {"clips": [], "moves": [], "lines": []}
    for e in script.get("timeline") or []:
        who = ids[e["who"]]
        start = float(e["at"]) if "at" in e else (None if "say" in e else prev_end)
        end = start or 0.0
        if "move_to" in e:
            t = e["move_to"]
            kw = {"point": tuple(list(t) + [0.0] * (3 - len(t)))} if isinstance(t, list) else {"target": str(t)}
            mid = commands.add_move(scene, who, start=start or 0.0, arrival=e.get("then", ""), **kw)
            m = commands.get_move(scene, mid)
            made["moves"].append(mid)
            end = m.start + m.duration
        if "do" in e:
            cid = commands.add_clip(scene, who, e["do"], start=start or 0.0, duration=e.get("for"),
                                    loop_mode=_mode(e.get("mode")),
                                    layer=str(e["layer"]).upper() if e.get("layer") else None)
            made["clips"].append(cid)
            c = commands.get_clip(scene, cid)
            end = max(end, c.start + c.duration)
        if "jump_onto" in e:
            try:
                mid = commands.add_move(scene, who, start=start or end, target=str(e["jump_onto"]),
                                        jump=True, arrival=e.get("then", ""))
            except CSKError as err:
                raise ScriptError([f"timeline entry for {e['who']}: {err}"])
            m = commands.get_move(scene, mid)
            made["moves"].append(mid)
            end = m.start + m.duration
        if "pick_up" in e:
            try:
                kid = commands.pick_up(scene, who, str(e["pick_up"]), start=start or end,
                                       helpers=[ids[h] for h in e.get("helpers", []) if h in ids])
            except CSKError as err:
                raise ScriptError([f"timeline entry for {e['who']}: {err}"])
            made.setdefault("carries", []).append(kid)
            end = commands.get_carry(scene, kid).start + 0.3
        if "put_down" in e:
            t = e["put_down"]
            at = None if t in (None, "front", True) else (list(t) if isinstance(t, list) else str(t))
            try:
                kid = commands.put_down(scene, who, at=at, start=start or end)
            except CSKError as err:
                raise ScriptError([f"timeline entry for {e['who']}: {err}"])
            end = commands.get_carry(scene, kid).end + 0.3
        line_id = None
        if "say" in e:
            line_id = commands.add_line(scene, who, str(e["say"]), start=start,
                                        after_previous=start is None, voice=e.get("voice", ""))
            made["lines"].append(line_id)
            line = commands.get_line(scene, line_id)
            end = max(end, line.start + line.duration)
        for key, layer in (("gesture", "GESTURE"), ("face", "FACE")):
            if key not in e or library.resolve(e[key]) is None:
                continue
            ref = commands.get_line(scene, line_id) if line_id else None
            cid = commands.add_clip(scene, who, e[key], start=ref.start if ref else (start or 0.0),
                                    duration=e.get("for"), layer=layer)
            if ref is not None:
                commands.set_clip_with_line(scene, cid, line_id, match_duration="for" not in e)
            made["clips"].append(cid)
        prev_end = end

    report = {"cast": ids, **made, "warnings": warnings, "voice_errors": []}
    if voices and made["lines"]:
        report["voice_errors"] = commands.generate_lines(scene, made["lines"])
    commands.rebuild(scene)
    last = max([l.start + l.duration for l in scene.csk360.lines] +
               [c.start + c.duration for c in scene.csk360.clips] +
               [m.start + m.duration for m in scene.csk360.moves] + [prev_end, 1.0])
    scene.frame_end = scene.frame_start + int(round((last + 0.5) * commands.compiler.fps(scene)))
    return report
