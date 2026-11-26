# SPDX-License-Identifier: GPL-3.0-or-later
"""Object labels, label detection and character abilities."""

import unittest

import bpy

from csk360 import commands, script, world

import helpers as h


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.maya = commands.add_starter_character(self.scene, "Maya", location=(2, 0, 0))
        self.floor = box("Floor", (10, 10, 0.02), (0, 0, -0.01))
        self.crate = box("Crate", (0.5, 0.5, 0.5), (1, 1, 0.25))         # 0.125 m3
        self.table = box("Table", (1.4, 0.8, 0.75), (-2, 1, 0.375))
        self.wall = box("Wall", (4, 0.2, 2.5), (0, 4, 1.25))
        self.cup = box("Cup", (0.08, 0.08, 0.1), (-2, 1, 0.8))

    def test_detect_guesses_from_size(self):
        done = world.detect(self.scene)
        self.assertNotIn("Leo", done)                       # characters are skipped
        self.assertTrue(done["Floor"]["walkable"])
        self.assertFalse(done["Floor"]["liftable"])
        crate = done["Crate"]
        self.assertTrue(crate["liftable"] and crate["jump_onto"] and crate["obstacle"])
        self.assertAlmostEqual(crate["weight"], 0.125 * world.DENSITY, delta=0.1)
        self.assertTrue(done["Table"]["jump_onto"])
        self.assertFalse(done["Table"]["liftable"])          # longer than a person can carry
        self.assertFalse(done["Wall"]["jump_onto"])          # too tall to stand on
        self.assertFalse(done["Wall"]["liftable"])
        self.assertTrue(done["Cup"]["liftable"])
        self.assertFalse(done["Cup"]["jump_onto"])           # too small to stand on
        self.assertEqual(done["Cup"]["source"], "AUTO")

    def test_detect_keeps_your_labels(self):
        world.label(self.crate, liftable=False, weight=500)
        world.detect(self.scene)
        self.assertFalse(world.get_label(self.crate)["liftable"])
        self.assertEqual(world.get_label(self.crate)["source"], "USER")
        world.detect(self.scene, overwrite=True)
        self.assertTrue(world.get_label(self.crate)["liftable"])

    def test_editing_a_detected_label_makes_it_yours(self):
        world.detect(self.scene)
        self.assertEqual(self.cup.csk360_label.source, "AUTO")
        self.cup.csk360_label.weight = 0.3          # as the panel does
        self.assertEqual(self.cup.csk360_label.source, "USER")

    def test_lifting_objects_people_and_teamwork(self):
        world.detect(self.scene)
        world.label(self.crate, liftable=True, weight=40)
        ok, why = world.can_lift(self.scene, self.leo, "Crate")
        self.assertFalse(ok)
        self.assertIn("40 kg", why)
        self.assertIn("15 kg short", why)
        ok, why = world.can_lift(self.scene, self.leo, "Crate", helpers=[self.maya])
        self.assertTrue(ok, why)
        self.assertIn("Leo and Maya", why)
        ok, why = world.can_lift(self.scene, self.leo, "Wall")
        self.assertFalse(ok)
        self.assertIn("not liftable", why)
        # People
        ok, _ = world.can_lift(self.scene, self.leo, self.maya)
        self.assertFalse(ok)
        world.set_abilities(self.scene, self.leo, strength=80)
        ok, why = world.can_lift(self.scene, self.leo, "Maya")
        self.assertTrue(ok, why)
        self.assertFalse(world.can_lift(self.scene, self.leo, self.leo)[0])

    def test_jumping_depends_on_jump_height(self):
        self.assertFalse(world.can_jump_onto(self.scene, self.leo, "Crate")[0])  # not labelled
        world.detect(self.scene)
        self.assertTrue(world.can_jump_onto(self.scene, self.leo, "Crate")[0])   # 0.5 m
        ok, why = world.can_jump_onto(self.scene, self.leo, "Table")               # 0.75 m
        self.assertFalse(ok)
        self.assertIn("0.75 m up", why)
        world.set_abilities(self.scene, self.leo, jump_height=0.8)
        self.assertTrue(world.can_jump_onto(self.scene, self.leo, "Table")[0])
        self.assertIn("not something to stand on", world.can_jump_onto(self.scene, self.leo, "Cup")[1])

    def test_bad_names_are_plain_errors(self):
        with self.assertRaises(commands.CSKError):
            world.label(self.crate, heavy=True)
        with self.assertRaises(commands.CSKError):
            world.set_abilities(self.scene, self.leo, flying=True)
        self.assertFalse(world.can_lift(self.scene, self.leo, "Nope")[0])

    def test_describe_lists_labels_and_abilities(self):
        world.label(self.crate, liftable=True, weight=9)
        d = commands.describe(self.scene)
        self.assertEqual(d["objects"]["Crate"]["weight"], 9)
        self.assertEqual(d["cast"][0]["abilities"]["strength"], 25.0)

    def test_scene_script_sets_abilities_and_labels(self):
        s = script.loads("""
cast:
  leo: {character: leo, strength: 60, jump: 0.9, weight: 70}
objects:
  Crate: {liftable: true, weight: 20}
timeline:
  - {at: 0, who: leo, do: wave}
""")
        script.build(self.scene, s, voices=False)
        leo = commands.cast_for_object(self.scene, bpy.data.objects["Leo"]).id
        self.assertEqual(world.abilities(self.scene, leo),
                         {"weight": 70.0, "strength": 60.0, "jump_height": 0.9})
        self.assertEqual(world.get_label("Crate")["weight"], 20)
        bad = script.loads("""
cast:
  leo: {character: leo, strength: lots}
objects:
  Crate: {liftabel: true}
timeline:
  - {at: 0, who: leo, do: wave}
""")
        errors, _ = script.validate(bad, self.scene)
        self.assertTrue(any("strength" in e for e in errors))
        self.assertTrue(any("liftabel" in e and "liftable" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
