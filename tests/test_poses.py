# SPDX-License-Identifier: GPL-3.0-or-later
"""More starter poses, and saving your own poses to the library."""

import math
import unittest

import bpy

from csk360 import commands, library, starter
from csk360.commands import CSKError

import helpers as h


class StarterPoseTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.rig = commands.get_cast(self.scene, self.leo).object

    def test_at_least_twenty_assets_in_every_category(self):
        self.assertGreaterEqual(len(starter.STARTER_ASSETS), 20)
        cats = {m["category"] for _b, m in starter.STARTER_ASSETS.values()}
        self.assertTrue({"Standing", "Gestures", "Sitting and kneeling", "Lying",
                         "Motion keys"} <= cats)

    def test_every_asset_plays(self):
        for name in starter.STARTER_ASSETS:
            with self.subTest(asset=name):
                cid = commands.add_clip(self.scene, self.leo, name, start=0, duration=2, blend_in=0)
                self.scene.frame_set(13)
                moved = any(pb.rotation_euler.to_quaternion().angle > 0.05 or pb.location.length > 0.01
                            for pb in self.rig.pose.bones if pb.name != "root")
                self.assertTrue(moved, f"{name} does not move any bone at frame 13")
                commands.remove_clip(self.scene, cid)

    def test_jump_leaves_the_ground(self):
        commands.add_clip(self.scene, self.leo, "jump", start=0, blend_in=0)
        self.scene.frame_set(13)
        self.assertGreater(self.rig.pose.bones["hips"].location.y, 0.2)

    def test_run_is_faster_than_walk(self):
        run, walk = library.info(bpy.data.actions["run"]), library.info(bpy.data.actions["walk"])
        self.assertGreater(run["stride"] * 2 / run["cycle_seconds"],
                           walk["stride"] * 2 / walk["cycle_seconds"])


class SavePoseTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.rig = commands.get_cast(self.scene, self.leo).object
        commands.get_cast(self.scene, self.leo).auto_life = False
        self.scene.frame_set(1)

    def test_rest_pose_is_refused(self):
        with self.assertRaises(CSKError):
            commands.save_pose(self.scene, self.leo, "nothing")

    def test_upper_body_pose_becomes_a_gesture_and_works_on_others(self):
        self.rig.pose.bones["upper_arm_L"].rotation_euler.x = math.radians(-90)
        asset = commands.save_pose(self.scene, self.leo, "Salute Left", favorite=True)
        self.assertEqual(asset, "salute_left")
        m = library.meta(bpy.data.actions[asset])
        self.assertEqual((m["kind"], m["layer"], m["category"], m["favorite"]),
                         ("pose", "GESTURE", "My poses", True))
        bag = bpy.data.actions[asset].layers[0].strips[0].channelbags[0]
        self.assertEqual([fc.data_path for fc in bag.fcurves],
                         ['pose.bones["upper_arm_L"].rotation_euler'])
        self.assertIn(asset, [i["id"] for i in library.search("", category="My poses")])
        # Reuse on another character.
        maya = commands.add_starter_character(self.scene, "Maya", location=(2, 0, 0))
        commands.add_clip(self.scene, maya, asset, start=0, blend_in=0)
        rig = commands.get_cast(self.scene, maya).object
        self.scene.frame_set(5)
        self.assertAlmostEqual(rig.pose.bones["upper_arm_L"].rotation_euler.x, math.radians(-90),
                               places=2)

    def test_leg_pose_becomes_a_body_pose(self):
        self.rig.pose.bones["thigh_L"].rotation_euler.x = math.radians(-60)
        asset = commands.save_pose(self.scene, self.leo, "step up")
        self.assertEqual(library.meta(bpy.data.actions[asset])["layer"], "BODY")

    def test_name_clash_needs_overwrite(self):
        self.rig.pose.bones["head"].rotation_euler.z = 0.3
        commands.save_pose(self.scene, self.leo, "look")
        with self.assertRaises(CSKError):
            commands.save_pose(self.scene, self.leo, "look")
        self.rig.pose.bones["head"].rotation_euler.z = -0.3
        commands.save_pose(self.scene, self.leo, "look", overwrite=True)
        self.assertEqual(len([a for a in bpy.data.actions if a.name in ("look", "look.001")]), 1)
        with self.assertRaises(CSKError):
            commands.save_pose(self.scene, self.leo, "wave")  # starter asset names are taken

    def test_operator_is_registered(self):
        self.assertTrue(hasattr(bpy.types, "CSK360_OT_save_pose"))


if __name__ == "__main__":
    unittest.main()
