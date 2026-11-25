# SPDX-License-Identifier: GPL-3.0-or-later
"""Output: presets, automatic camera, subtitles, MP4 render."""

import os
import unittest

import bpy
from mathutils import Vector

from csk360 import commands, render

import helpers as h


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        self.maya = commands.add_starter_character(self.scene, "Maya", location=(1.2, 0, 0))
        commands.add_line(self.scene, self.leo, "Morning!", start=0.5, duration=1.0)
        commands.add_line(self.scene, self.maya, "Hi, Leo.", after_previous=True, duration=0.8)

    def test_presets(self):
        render.set_output(self.scene, "9:16", fps=30, engine="workbench")
        r = self.scene.render
        self.assertEqual((r.resolution_x, r.resolution_y, r.fps), (1080, 1920, 30))
        self.assertEqual(r.engine, "BLENDER_WORKBENCH")
        with self.assertRaises(ValueError):
            render.set_output(self.scene, "8k")

    def test_auto_camera_frames_the_cast(self):
        cam = render.ensure_camera(self.scene)
        self.assertEqual(self.scene.camera, cam)
        self.assertAlmostEqual(cam.location.x, 0.6, places=3)
        self.assertLess(cam.location.y, -2.0)
        # Both characters are in front of the camera and inside its view.
        from bpy_extras.object_utils import world_to_camera_view
        for c in self.scene.csk360.cast:
            for z in (0.05, 1.6):  # feet and top of the head
                p = world_to_camera_view(self.scene, cam, c.object.location + Vector((0, 0, z)))
                self.assertTrue(0 < p.x < 1 and 0 < p.y < 1 and p.z > 0, f"{c.id} z={z}: {tuple(p)}")

    def test_srt(self):
        path = os.path.join(h.TMP, "subs.srt")
        render.write_srt(self.scene, path, speaker_names=True)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("1\n00:00:00,500 --> 00:00:01,500\nLeo: Morning!\n", text)
        self.assertIn("2\n00:00:01,700 --> 00:00:02,500\nMaya: Hi, Leo.\n", text)

    def test_burned_subtitles_show_only_during_their_line(self):
        self.assertEqual(render.burn_subtitles(self.scene), 2)
        sub = bpy.data.objects[render.SUB_PREFIX + "0"]
        visible = []
        for f in (1, 13, 30, 38, 50):  # line 1 is 0.5-1.5 s = frames 13-37
            self.scene.frame_set(f)
            visible.append(not sub.hide_render)
        self.assertEqual(visible, [False, True, True, False, False])
        self.assertEqual(sub.parent, self.scene.camera)
        render.burn_subtitles(self.scene)  # rebuilding replaces, never duplicates
        self.assertEqual(len([o for o in bpy.data.objects if o.name.startswith(render.SUB_PREFIX)]), 4)
        render.clear_burned_subtitles()
        self.assertFalse(any(o.name.startswith(render.SUB_PREFIX) for o in bpy.data.objects))

    def test_render_mp4(self):
        out = os.path.join(h.TMP, "clip.mp4")
        self.scene.render.resolution_percentage = 25
        path = render.render_video(self.scene, out, preset="720p", engine="workbench",
                                   subtitles="both", frames=(1, 12))
        self.scene.render.resolution_percentage = 25
        files = [f for f in os.listdir(h.TMP) if f.startswith("clip")]
        self.assertTrue(any(f.endswith(".mp4") and os.path.getsize(os.path.join(h.TMP, f)) > 1000
                            for f in files), files)
        self.assertTrue(os.path.isfile(os.path.join(h.TMP, "clip.srt")))
        self.assertEqual(path, os.path.abspath(out))


if __name__ == "__main__":
    unittest.main()
