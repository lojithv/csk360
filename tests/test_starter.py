# SPDX-License-Identifier: GPL-3.0-or-later
"""Starter 3D toon character and starter library."""

import unittest

import bpy

from csk360 import commands, library, starter

import helpers as h


class StarterTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene(fps=24)
        self.leo = commands.add_starter_character(self.scene, "Leo", location=(1.0, 2.0, 0.0))
        self.rig = commands.get_cast(self.scene, self.leo).object

    def body(self):
        return next(o for o in self.rig.children if o.type == "MESH")

    def mouth_values(self, frame):
        self.scene.frame_set(frame)
        body = self.body().evaluated_get(bpy.context.evaluated_depsgraph_get())
        keys = body.data.shape_keys.key_blocks
        return {k.name: k.value for k in keys if k.name.startswith("mouth_")}

    def test_rig_has_standard_bones(self):
        self.assertEqual(set(self.rig.data.bones.keys()), set(starter.BONES))
        self.assertEqual(self.rig["csk360_rig"], "biped_toon")
        self.assertEqual(tuple(self.rig.location), (1.0, 2.0, 0.0))
        self.assertEqual(commands.get_cast(self.scene, self.leo).home[:], (1.0, 2.0, 0.0))

    def test_body_is_weighted_and_deforms(self):
        body = self.body()
        self.assertEqual(body.modifiers[0].object, self.rig)
        self.assertTrue(all(len(v.groups) == 1 for v in body.data.vertices))

    def test_mouth_shape_keys_follow_mouth_control(self):
        body = self.body()
        names = [k.name for k in body.data.shape_keys.key_blocks]
        self.assertEqual(names, ["Basis"] + [f"mouth_{s}" for s in "ABCDEFGH"])
        for fc in body.data.shape_keys.animation_data.drivers:
            self.assertTrue(fc.driver.is_simple_expression, fc.data_path)
        commands.add_line(self.scene, self.leo, "Ah", start=1.0,
                          visemes=[(0.0, "D"), (0.5, "F"), (1.0, "X")])
        self.assertEqual(self.mouth_values(25 + 1)["mouth_D"], 1.0)
        values = self.mouth_values(25 + 13)
        self.assertEqual(values["mouth_F"], 1.0)
        self.assertEqual(values["mouth_D"], 0.0)
        self.assertEqual(sum(self.mouth_values(25 + 30).values()), 0.0)

    def test_starter_library(self):
        self.assertEqual(set(library.asset_ids(marked_only=True)), set(starter.STARTER_ASSETS))
        walk = library.info(bpy.data.actions["walk"])
        self.assertEqual((walk["loop_mode"], walk["stride"]), ("LOOP", 0.35))
        self.assertEqual(library.default_walk(), "walk")

    def test_picker_search_and_pie_favourites(self):
        ids = lambda items: [i["id"] for i in items]  # noqa: E731
        self.assertEqual(ids(library.search("hello")), ["wave"])
        self.assertEqual(ids(library.search("sit chair")), ["sit"])
        self.assertEqual(ids(library.search("", category="Gestures")), ["arms_crossed", "wave"])
        self.assertEqual(library.search("chair", category="Gestures"), [])
        self.assertEqual(set(ids(library.favorites())), set(starter.STARTER_ASSETS))
        self.assertTrue(hasattr(bpy.types, "CSK360_MT_pose_pie"))
        self.assertTrue(hasattr(bpy.ops.csk360, "pose_picker"))

    def test_gestures_only_key_upper_body(self):
        for name, (_build, meta) in starter.STARTER_ASSETS.items():
            if meta["layer"] != "GESTURE":
                continue
            action = bpy.data.actions[name]
            bag = action.layers[0].strips[0].channelbags[0]
            for fc in bag.fcurves:
                bone = fc.data_path.split('"')[1]
                self.assertIn(bone, starter.UPPER_BODY, f"{name} keys {bone}")

    def test_second_character_reuses_library_and_actions_play(self):
        maya = commands.add_starter_character(self.scene, "Maya", location=(-1, 0, 0))
        self.assertEqual(len([a for a in bpy.data.actions if a.name in starter.STARTER_ASSETS]),
                         len(starter.STARTER_ASSETS))
        commands.add_clip(self.scene, maya, "wave", start=0, blend_in=0)
        rig = commands.get_cast(self.scene, maya).object
        self.scene.frame_set(20)
        self.assertLess(rig.pose.bones["upper_arm_R"].rotation_euler.x, -2.0)
        self.assertAlmostEqual(self.rig.pose.bones["upper_arm_R"].rotation_euler.x, 0.0)

    def test_walk_move_with_starter_walk(self):
        mid = commands.add_move(self.scene, self.leo, start=0, point=(1.0, -0.8, 0.0))
        self.assertAlmostEqual(commands.get_move(self.scene, mid).duration, 2.8 / 0.7 / 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
