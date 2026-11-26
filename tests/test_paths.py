# SPDX-License-Identifier: GPL-3.0-or-later
"""Click-to-move picking, chained moves and path geometry."""

import unittest

import bpy
from mathutils import Vector

from csk360 import commands, compiler, paths

import helpers as h

DOWN = Vector((0.0, 0.0, -1.0))


def add_mesh(scene, name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


class PickTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.cast = commands.get_cast(self.scene, self.leo)
        # A thin floor whose top is at z = 0, and a 1 m crate at x = 2.
        self.floor = add_mesh(self.scene, "Floor", (10, 10, 0.1), (0, 0, -0.05))
        self.crate = add_mesh(self.scene, "Crate", (1, 1, 1), (2, 0, 0.5))
        self.dg = bpy.context.evaluated_depsgraph_get()

    def pick(self, x, y, z=5.0, direction=DOWN):
        return paths.pick(self.scene, self.dg, self.cast, Vector((x, y, z)), direction)

    def test_floor_gives_a_point_at_floor_height(self):
        r = self.pick(-1.5, 2.0)
        self.assertIn("point", r)
        self.assertAlmostEqual(r["point"].x, -1.5, places=4)
        self.assertAlmostEqual(r["point"].y, 2.0, places=4)
        self.assertAlmostEqual(r["point"].z, 0.0, places=4)

    def test_prop_gives_the_object_and_its_arrival(self):
        self.crate[paths.ARRIVAL_PROP] = "sit"
        r = self.pick(2.0, 0.0)
        self.assertIs(r["target"], self.crate)
        self.assertEqual(r["arrival"], "sit")

    def test_characters_are_see_through(self):
        # Straight down through Leo's head lands on the floor, not on Leo.
        r = self.pick(0.0, 0.0)
        self.assertIn("point", r)

    def test_empty_scene_uses_the_floor_plane(self):
        for ob in (self.floor, self.crate):
            bpy.data.objects.remove(ob)
        dg = bpy.context.evaluated_depsgraph_get()
        r = paths.pick(self.scene, dg, self.cast, Vector((0, -5, 3)), Vector((0.5, 1, -1)))
        self.assertAlmostEqual(r["point"].z, 0.0, places=4)
        self.assertAlmostEqual(r["point"].x, 1.5, places=4)
        self.assertAlmostEqual(r["point"].y, -2.0, places=4)

    def test_sky_gives_nothing(self):
        bpy.data.objects.remove(self.floor)
        dg = bpy.context.evaluated_depsgraph_get()
        r = paths.pick(self.scene, dg, self.cast, Vector((-5, 0, 1)), Vector((-1, 0, 0.2)))
        self.assertIsNone(r)

    def test_approach_child_sets_the_preview_spot(self):
        spot = bpy.data.objects.new("crate_approach", None)
        self.scene.collection.objects.link(spot)
        spot.parent = self.crate
        spot.matrix_world.translation = (2.0, -1.0, 0.0)
        bpy.context.view_layer.update()
        loc = paths.target_location({"target": self.crate, "arrival": ""})
        self.assertAlmostEqual(loc.y, -1.0, places=4)


class StopShortTests(unittest.TestCase):
    def test_walks_up_to_a_prop_instead_of_into_it(self):
        scene = h.reset_scene()
        leo = commands.add_starter_character(scene, "Leo")
        crate = add_mesh(scene, "Crate", (1, 1, 1), (3, 0, 0.5))
        m = commands.add_move(scene, leo, start=0, target=crate)
        rig = commands.get_cast(scene, leo).object
        scene.frame_set(scene.frame_start + int(commands.get_move(scene, m).duration * 24) + 2)
        # Crate's near face is at x = 2.5; Leo stops STOP_GAP before it.
        self.assertAlmostEqual(rig.matrix_world.translation.x, 2.5 - compiler.STOP_GAP, places=3)
        self.assertAlmostEqual(rig.matrix_world.translation.y, 0.0, places=3)

    def test_empties_are_walked_to_directly(self):
        scene = h.reset_scene()
        mark = bpy.data.objects.new("Mark", None)
        scene.collection.objects.link(mark)
        mark.location = (2, 1, 0)
        bpy.context.view_layer.update()
        p = compiler.approach_point(mark, Vector((0, 0, 0)))
        self.assertAlmostEqual((p - Vector((2, 1, 0))).length, 0.0, places=5)


class ChainAndGeometryTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.cast = commands.get_cast(self.scene, self.leo)

    def test_after_previous_chains_moves(self):
        a = commands.add_move(self.scene, self.leo, start=1.0, point=(2, 0, 0))
        b = commands.add_move(self.scene, self.leo, point=(2, 2, 0), after_previous=True)
        ma, mb = commands.get_move(self.scene, a), commands.get_move(self.scene, b)
        self.assertGreater(ma.duration, 0.0)
        self.assertAlmostEqual(mb.start, ma.start + ma.duration, places=5)
        self.assertEqual(self.scene.csk360.last_report, "")

    def test_first_chained_move_starts_at_the_playhead(self):
        self.scene.frame_set(self.scene.frame_start + 48)
        m = commands.add_move(self.scene, self.leo, point=(1, 0, 0), after_previous=True)
        self.assertAlmostEqual(commands.get_move(self.scene, m).start, 2.0, places=5)

    def test_segments_follow_the_moves_in_time_order(self):
        commands.add_move(self.scene, self.leo, start=5.0, point=(2, 2, 0))
        commands.add_move(self.scene, self.leo, start=0.0, point=(2, 0, 0))
        segs = paths.segments(self.scene, self.cast)
        self.assertEqual(len(segs), 2)
        self.assertEqual(tuple(segs[0][1]), (0.0, 0.0, 0.0))
        self.assertEqual(tuple(segs[0][2]), (2.0, 0.0, 0.0))
        self.assertEqual(tuple(segs[1][2]), (2.0, 2.0, 0.0))

    def test_dashes_and_ring(self):
        v = paths.dashes((0, 0, 0), (1, 0, 0), dash=0.15, gap=0.1)
        self.assertEqual(len(v) % 2, 0)
        self.assertEqual(len(v) // 2, 4)  # dashes start at 0, .25, .5, .75
        self.assertAlmostEqual(v[-1].x, 0.9, places=5)
        self.assertEqual(paths.dashes((1, 1, 0), (1, 1, 0)), [])
        r = paths.ring((0, 0, 0), radius=0.5, steps=8)
        self.assertEqual(len(r), 16)
        for p in r:
            self.assertAlmostEqual(p.length, 0.5, places=5)

    def test_path_lines_cover_every_move(self):
        commands.add_move(self.scene, self.leo, start=0.0, point=(2, 0, 0))
        self.assertGreater(len(paths.path_lines(self.scene, self.cast)), 0)


class OperatorTests(unittest.TestCase):
    def test_click_move_is_registered_and_needs_a_character(self):
        self.assertTrue(hasattr(bpy.types, "CSK360_OT_click_move"))
        h.reset_scene()
        # No 3D view and no character in background mode: poll fails, so M
        # would fall through to Blender's own binding.
        self.assertFalse(bpy.ops.csk360.click_move.poll())


if __name__ == "__main__":
    unittest.main()
