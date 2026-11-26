# SPDX-License-Identifier: GPL-3.0-or-later
"""Jumping onto and down from surfaces."""

import unittest

import bpy

from csk360 import commands, world
from csk360.commands import CSKError

import helpers as h


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


class JumpTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.rig = commands.get_cast(self.scene, self.leo).object
        box("Step", (0.8, 0.8, 0.4), (2.0, 0.0, 0.2))
        box("Wall", (0.8, 0.8, 1.4), (-2.0, 0.0, 0.7))
        world.detect(self.scene)

    def z_at(self, t):
        self.scene.frame_set(self.scene.frame_start + round(t * 24))
        return self.rig.matrix_world.translation.z

    def test_jump_onto_lands_on_top_after_an_arc(self):
        mid = commands.add_move(self.scene, self.leo, start=0, target="Step", jump=True)
        m = commands.get_move(self.scene, mid)
        end = m.start + m.duration
        self.assertAlmostEqual(self.z_at(end + 0.2), 0.4, places=3)
        hops = []
        for k in range(1, 12):
            self.z_at(end - k * 0.05)
            hops.append(self.rig.pose.bones["hips"].location.y)
        self.assertGreater(max(hops), 0.2)          # the jump action hops during the rise
        self.z_at(end + 0.2)
        x = self.rig.matrix_world.translation.x
        self.assertAlmostEqual(x, 2.0, places=2)                 # middle of the top
        clips = [s.name for t in self.rig.animation_data.nla_tracks for s in t.strips]
        self.assertTrue(any(n.endswith(".jump") for n in clips))

    def test_lands_beside_a_box_on_top(self):
        box("Parcel", (0.25, 0.25, 0.25), (2.0, 0.0, 0.525))   # sits on the step's centre
        mid = commands.add_move(self.scene, self.leo, start=0, target="Step", jump=True)
        m = commands.get_move(self.scene, mid)
        self.z_at(m.start + m.duration + 0.2)
        p = self.rig.matrix_world.translation
        self.assertAlmostEqual(p.z, 0.4, places=3)
        self.assertGreater((p.xy - bpy.data.objects["Parcel"].matrix_world.translation.xy).length, 0.25)

    def test_too_high_is_refused(self):
        with self.assertRaises(CSKError) as e:
            commands.add_move(self.scene, self.leo, start=0, target="Wall", jump=True)
        self.assertIn("1.40 m up", str(e.exception))

    def test_walking_off_jumps_down_to_the_floor(self):
        mid = commands.add_move(self.scene, self.leo, start=0, target="Step", jump=True)
        m = commands.get_move(self.scene, mid)
        down = commands.add_move(self.scene, self.leo, point=(4, 0, 0), after_previous=True)
        d = commands.get_move(self.scene, down)
        self.assertAlmostEqual(self.z_at(d.start + d.duration + 0.1), 0.0, places=3)
        self.assertAlmostEqual(self.rig.matrix_world.translation.x, 4.0, places=2)
        self.assertGreater(d.duration, 0.5)

    def test_script_jump_onto(self):
        from csk360 import script
        s = script.loads("""
cast:
  leo: {character: leo, jump: 0.6}
timeline:
  - {at: 0, who: leo, jump_onto: Step, then: cheer}
""")
        report = script.build(self.scene, s, voices=False)
        self.assertEqual(len(report["moves"]), 1)
        self.assertTrue(self.scene.csk360.moves[0].jump)


if __name__ == "__main__":
    unittest.main()
