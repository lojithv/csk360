# SPDX-License-Identifier: GPL-3.0-or-later
"""Picking up, carrying and putting down objects."""

import unittest

import bpy
from mathutils import Vector

from csk360 import commands, compiler, world
from csk360.commands import CSKError

import helpers as h


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


def at(scene, frame_seconds, ob):
    scene.frame_set(scene.frame_start + round(frame_seconds * 24))
    return ob.matrix_world.translation.copy()


class CarryTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.rig = commands.get_cast(self.scene, self.leo).object
        self.box = box("Box", (0.3, 0.3, 0.3), (2.0, 0.0, 0.15))
        self.table = box("Table", (0.8, 0.8, 0.7), (0.0, 2.5, 0.35))
        world.detect(self.scene)

    def test_too_heavy_is_refused_with_the_reason(self):
        world.label(self.box, liftable=True, weight=90)
        with self.assertRaises(CSKError) as e:
            commands.pick_up(self.scene, self.leo, "Box", start=0)
        self.assertIn("90 kg", str(e.exception))

    def test_walks_over_picks_up_carries_and_puts_down_in_front(self):
        cid = commands.pick_up(self.scene, self.leo, "Box", start=0)
        c = commands.get_carry(self.scene, cid)
        self.assertEqual(len(self.scene.csk360.moves), 1)         # walked over first
        m = self.scene.csk360.moves[0]
        self.assertAlmostEqual(c.start, m.start + m.duration, places=4)
        home = at(self.scene, 0, self.box)
        self.assertAlmostEqual((home - Vector((2, 0, 0.15))).length, 0, places=3)
        # After pick-up the box rides with Leo, in front of the chest.
        commands.add_move(self.scene, self.leo, point=(-1, -1, 0), after_previous=True)
        mid = self.scene.csk360.moves[1]
        t = mid.start + mid.duration
        p = at(self.scene, t + 0.1, self.box)
        leo = self.rig.matrix_world.translation
        self.assertLess((p.xy - leo.xy).length, 0.6)
        self.assertGreater(p.z, 0.7)
        # Put down in front: on the floor, near Leo.
        commands.put_down(self.scene, self.leo, start=t + 0.5)
        p = at(self.scene, t + 1.0, self.box)
        self.assertAlmostEqual(p.z, 0.15, places=2)
        self.assertLess((p.xy - self.rig.matrix_world.translation.xy).length, 0.8)
        # The carry gesture plays while carrying.
        self.assertTrue(any("carry" in s.name for t_ in self.rig.animation_data.nla_tracks
                            for s in t_.strips))

    def test_put_on_a_table_walks_there(self):
        commands.pick_up(self.scene, self.leo, "Box", start=0)
        end = max(m.start + m.duration for m in self.scene.csk360.moves)
        cid = commands.put_down(self.scene, self.leo, at="Table", start=end + 0.2)
        c = commands.get_carry(self.scene, cid)
        p = at(self.scene, c.end + 0.2, self.box)
        self.assertAlmostEqual(p.z, 0.7 + 0.15, places=2)
        self.assertAlmostEqual(p.x, 0.0, places=2)
        self.assertAlmostEqual(p.y, 2.5, places=2)

    def test_removing_the_carry_restores_the_object(self):
        cid = commands.pick_up(self.scene, self.leo, "Box", start=0, walk=False)
        commands.remove_carry(self.scene, cid)
        self.assertIsNone(self.box.get(compiler.HOME_PROP))
        self.assertEqual(len(self.box.constraints), 0)
        self.assertAlmostEqual((self.box.matrix_world.translation - Vector((2, 0, 0.15))).length, 0,
                               places=4)

    def test_put_down_needs_something_carried(self):
        with self.assertRaises(CSKError):
            commands.put_down(self.scene, self.leo, start=1)

    def test_cannot_pick_up_what_someone_else_holds(self):
        maya = commands.add_starter_character(self.scene, "Maya", location=(2.6, 0, 0))
        commands.pick_up(self.scene, self.leo, "Box", start=0, walk=False)
        with self.assertRaises(CSKError):
            commands.pick_up(self.scene, maya, "Box", start=1, walk=False)


class CarryScriptTests(unittest.TestCase):
    def test_script_pick_up_and_put_down(self):
        from csk360 import script
        scene = h.reset_scene()
        box("Box", (0.3, 0.3, 0.3), (1.5, 0.0, 0.15))
        box("Shelf", (0.6, 0.6, 0.5), (-1.5, 1.5, 0.25))
        s = script.loads("""
cast:
  leo: {character: leo}
objects:
  Box: {liftable: true, weight: 5}
  Shelf: {jump_onto: true, obstacle: true}
timeline:
  - {at: 0, who: leo, pick_up: Box}
  - {after: prev, who: leo, put_down: Shelf}
  - {after: prev, who: leo, do: cheer}
""")
        report = script.build(scene, s, voices=False)
        self.assertEqual(len(report["carries"]), 1)
        c = scene.csk360.carries[0]
        self.assertEqual((c.put_kind, c.put_object.name), ("OBJECT", "Shelf"))
        cheer = [k for k in scene.csk360.clips if k.asset == "cheer"][0]
        self.assertGreaterEqual(cheer.start, c.end)
        bad = script.loads("""
cast:
  leo: {character: leo}
objects:
  Box: {liftable: true, weight: 500}
timeline:
  - {at: 0, who: leo, pick_up: Box}
""")
        with self.assertRaises(script.ScriptError) as e:
            script.build(scene, bad, voices=False)
        self.assertIn("500 kg", str(e.exception))


if __name__ == "__main__":
    unittest.main()
