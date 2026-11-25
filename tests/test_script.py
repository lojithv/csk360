# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene scripts: YAML subset, JSON, Frameling screenplay, validation, build and the CLI."""

import json
import os
import subprocess
import sys
import unittest

import bpy

from csk360 import commands, script
from csk360.script import ScriptError

import helpers as h

DOC_EXAMPLE = """\
set: office_small
cast:
  leo:  {character: leo, voice: kokoro/am_michael}
  maya: {character: maya, voice: kokoro/af_heart}
timeline:
  - {at: 0, who: maya, do: wave, for: 2}
  - {at: 0, who: leo, move_to: desk_chair, then: sit}
  - {at: 6, who: leo, say: "Morning! Did you see the numbers?", face: happy}
  - {after: prev, who: maya, say: "I did. We need to talk.", face: worried, gesture: arms_crossed}
camera: auto_two_shot
output: {size: 1080p, fps: 24}
"""


class YamlTests(unittest.TestCase):
    def test_doc_example_parses(self):
        d = script.parse_yaml(DOC_EXAMPLE)
        self.assertEqual(d["cast"]["leo"], {"character": "leo", "voice": "kokoro/am_michael"})
        self.assertEqual(d["timeline"][2]["say"], "Morning! Did you see the numbers?")
        self.assertEqual(d["timeline"][0], {"at": 0, "who": "maya", "do": "wave", "for": 2})
        self.assertEqual(d["output"], {"size": "1080p", "fps": 24})

    def test_block_lists_comments_and_quotes(self):
        d = script.parse_yaml(
            "# a comment\n"
            "cast:\n"
            "  leo:\n"
            "    character: Leo   # trailing comment\n"
            "timeline:\n"
            "  - at: 1.5\n"
            "    who: leo\n"
            "    say: 'It''s #1, really: yes'\n"
            "  - {at: 3, who: leo, move_to: [1, -2]}\n")
        self.assertEqual(d["cast"]["leo"]["character"], "Leo")
        self.assertEqual(d["timeline"][0], {"at": 1.5, "who": "leo", "say": "It's #1, really: yes"})
        self.assertEqual(d["timeline"][1]["move_to"], [1, -2])

    def test_bad_yaml_is_a_script_error(self):
        with self.assertRaises(ScriptError) as ctx:
            script.loads("timeline:\n  - {at: 0, who: leo\n")
        self.assertIn("Could not read", str(ctx.exception))


class ScreenplayTests(unittest.TestCase):
    def test_frameling_screenplay(self):
        d = script.loads("Title: Coffee break\n[office]\nMaya (happy, wave): Hi Leo!\n"
                         "Leo (surprised): Oh, hi Maya!\n> Meanwhile...\n", ".txt")
        self.assertEqual(set(d["cast"]), {"maya", "leo"})
        self.assertEqual(d["timeline"][0], {"who": "maya", "say": "Hi Leo!", "after": "prev",
                                            "face": "happy", "gesture": "wave"})
        self.assertEqual(d["timeline"][1]["face"], "surprised")
        self.assertEqual(len(d["notes"]), 2)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()

    def test_doc_example_errors_until_the_chair_exists(self):
        errors, warnings = script.validate(script.parse_yaml(DOC_EXAMPLE), self.scene)
        self.assertEqual(len(errors), 1)
        self.assertIn("desk_chair", errors[0])
        self.assertTrue(any("happy" in w for w in warnings))
        self.assertTrue(any("camera" in w for w in warnings))
        chair = bpy.data.objects.new("desk_chair", None)
        self.scene.collection.objects.link(chair)
        errors, _ = script.validate(script.parse_yaml(DOC_EXAMPLE), self.scene)
        self.assertEqual(errors, [])

    def test_errors_have_suggestions(self):
        d = {"cast": {"leo": {"voice": "michael"}},
             "timeline": [{"at": 0, "who": "loe", "do": "wavee"},
                          {"at": "soon", "who": "leo", "sya": "hi"}],
             "output": {"size": "8k"}}
        errors, _ = script.validate(d, self.scene)
        text = "\n".join(errors)
        self.assertIn("Did you mean: leo", text)
        self.assertIn("Did you mean: wave", text)
        self.assertIn("Did you mean: say", text)
        self.assertIn("kokoro/af_heart", text)
        self.assertIn("'at' must be seconds", text)
        self.assertIn("output size", text)

    def test_build_refuses_invalid_scripts(self):
        with self.assertRaises(ScriptError):
            script.build(self.scene, {"cast": {}, "timeline": []}, voices=False)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        chair = bpy.data.objects.new("desk_chair", None)
        chair.location = (0, 3, 0)
        self.scene.collection.objects.link(chair)

    def test_build_doc_example(self):
        report = script.build(self.scene, script.parse_yaml(DOC_EXAMPLE), voices=False)
        proj = self.scene.csk360
        self.assertEqual(set(report["cast"]), {"leo", "maya"})
        self.assertEqual(len(proj.moves), 1)
        self.assertEqual(len(proj.lines), 2)
        self.assertEqual(proj.cast[0].voice, "kokoro/am_michael")
        self.assertEqual((self.scene.render.resolution_x, self.scene.render.resolution_y), (1920, 1080))
        wave = next(c for c in proj.clips if c.asset == "wave")
        self.assertEqual((wave.start, wave.duration), (0.0, 2.0))
        first, second = proj.lines
        self.assertEqual(first.start, 6.0)
        self.assertEqual(second.follows, first.id)
        arms = next(c for c in proj.clips if c.asset == "arms_crossed")
        self.assertEqual(arms.with_line, second.id)
        # Once the first line has a length (as voicing gives it), the reply and its gesture follow.
        commands.set_line(self.scene, first.id, duration=2.0)
        self.assertAlmostEqual(second.start, 8.2, places=5)
        self.assertAlmostEqual(arms.start, 8.2, places=5)
        commands.set_line(self.scene, second.id, duration=1.5)
        self.assertAlmostEqual(arms.duration, 1.5, places=5)
        self.assertGreater(self.scene.frame_end, 24 * 8)

    def test_rebuilding_replaces_the_previous_build(self):
        data = script.parse_yaml(DOC_EXAMPLE)
        script.build(self.scene, data, voices=False)
        script.build(self.scene, data, voices=False)
        proj = self.scene.csk360
        self.assertEqual((len(proj.cast), len(proj.lines)), (2, 2))
        self.assertEqual(len([o for o in bpy.data.objects if o.type == "ARMATURE"]), 2)

    def test_json_and_point_moves(self):
        data = script.loads(json.dumps({
            "cast": {"leo": {}},
            "timeline": [{"at": 0, "who": "leo", "move_to": [1.4, 0]},
                         {"after": "prev", "who": "leo", "do": "arms_crossed"}]}), ".json")
        script.build(self.scene, data, voices=False)
        clip = self.scene.csk360.clips[0]
        self.assertAlmostEqual(clip.start, 2.0, places=4)  # 1.4 m at the walk's 0.7 m/s


class CliTests(unittest.TestCase):
    def test_cli_validate_and_build(self):
        cli = os.path.join(os.path.dirname(script.__file__), "csk360_build.py")
        path = os.path.join(h.TMP, "scene.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("cast:\n  leo: {character: leo}\ntimeline:\n  - {at: 0, who: leo, do: wave}\n"
                    "  - {at: 1, who: leo, say: Hello there}\n")
        out = os.path.join(h.TMP, "built.blend")
        r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "-P", cli, "--",
                            path, "--no-voices", "--save", out, "--json"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-1500:])
        report = json.loads(r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1])
        self.assertEqual(report["cast"], {"leo": "leo"})
        self.assertTrue(os.path.isfile(out))

        bad = os.path.join(h.TMP, "bad.yaml")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("cast:\n  leo: {}\ntimeline:\n  - {at: 0, who: leo, do: wavee}\n")
        r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "-P", cli, "--",
                            bad, "--validate"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Did you mean: wave", r.stdout)


if __name__ == "__main__":
    unittest.main()
