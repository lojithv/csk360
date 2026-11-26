# SPDX-License-Identifier: GPL-3.0-or-later
"""Objects that appear: copies of a template, made by characters."""

import unittest

import bpy

from csk360 import commands, world

import helpers as h


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


class SpawnTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.brick = box("Brick", (0.4, 0.2, 0.2), (5, 5, 0.1))
        world.label(self.brick, liftable=True, weight=3)

    def scale_at(self, ob, t):
        self.scene.frame_set(self.scene.frame_start + round(t * 24))
        return ob.matrix_world.to_scale().x

    def test_copy_pops_in_at_a_place(self):
        sid = commands.spawn(self.scene, "Brick", start=2.0, location=(1, 0, 0))
        ob = commands.get_spawn(self.scene, sid).object
        self.assertIsNot(ob, self.brick)
        self.assertEqual(ob.data, self.brick.data)                 # linked copy
        self.assertTrue(ob.csk360_label.liftable)
        self.assertAlmostEqual(self.scale_at(ob, 1.0), 0.0, places=4)
        self.assertAlmostEqual(self.scale_at(ob, 2.5), 0.4, places=3)
        self.assertAlmostEqual(ob.matrix_world.translation.z, 0.1, places=3)   # bottom on the floor
        self.assertAlmostEqual(self.scale_at(self.brick, 1.0), 0.4, places=3)  # template untouched

    def test_maker_makes_it_in_front_and_points(self):
        sid = commands.spawn(self.scene, "Brick", start=1.0, by=self.leo)
        ob = commands.get_spawn(self.scene, sid).object
        self.assertAlmostEqual(ob.matrix_world.translation.y, -commands.SPAWN_FORWARD, places=3)
        rig = commands.get_cast(self.scene, self.leo).object
        names = [s.name for t in rig.animation_data.nla_tracks for s in t.strips]
        self.assertIn(f"{sid}.make", names)

    def test_build_a_wall_and_carry_a_spawned_brick(self):
        ids = [commands.spawn(self.scene, "Brick", start=0.5 * i, location=(0.4 * i, 1, 0))
               for i in range(4)]
        self.assertEqual(len([o for o in self.scene.objects if o.name.startswith("Brick")]), 5)
        first = commands.get_spawn(self.scene, ids[0]).object
        cid = commands.pick_up(self.scene, self.leo, first, start=3.0)
        c = commands.get_carry(self.scene, cid)
        self.scene.frame_set(self.scene.frame_start + round((c.start + 0.2) * 24))
        self.assertGreater(first.matrix_world.translation.z, 0.6)   # in Leo's arms
        self.assertAlmostEqual(self.scale_at(first, 0.0), 0.0, places=4)   # still pops in first

    def test_removing_a_copy_deletes_it(self):
        sid = commands.spawn(self.scene, "Brick", start=1.0, location=(1, 0, 0), name="Spare")
        commands.remove_spawn(self.scene, sid)
        self.assertIsNone(bpy.data.objects.get("Spare"))
        self.assertIsNotNone(bpy.data.objects.get("Brick"))

    def test_script_spawn(self):
        from csk360 import script
        s = script.loads("""
cast:
  leo: {character: leo}
timeline:
  - {at: 0, spawn: Brick, place: [0, 2]}
  - {at: 1, who: leo, spawn: Brick}
  - {after: prev, who: leo, do: cheer}
""")
        report = script.build(self.scene, s, voices=False)
        self.assertEqual(len(report["spawns"]), 2)
        self.assertEqual(self.scene.csk360.spawns[1].by, "leo")


if __name__ == "__main__":
    unittest.main()
