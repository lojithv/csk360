# SPDX-License-Identifier: GPL-3.0-or-later
"""Clip editing: split, jump between clips, voice files copied next to the .blend."""

import os
import unittest

import bpy

from csk360 import commands, voice
from csk360.commands import CSKError

import helpers as h


class EditingBase(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene(fps=24)
        self.rig = h.make_rig(self.scene)
        h.make_action("walk", "root", {1: 0.0, 7: 0.3, 13: 0.1, 19: -0.2, 25: 0.0},
                      kind="action", loop=True)
        h.make_action("wave", "arm_L", {1: 0.0, 13: 1.0}, kind="action")
        self.leo = commands.add_cast(self.scene, self.rig, name="Leo")

    def curve(self, bone, frames):
        return [round(h.bone_x(self.scene, self.rig, bone, f), 4) for f in frames]


class SplitTests(EditingBase):
    def assert_split_is_invisible(self, asset, bone, start, duration, cut):
        cid = commands.add_clip(self.scene, self.leo, asset, start=start, duration=duration,
                                blend_in=0, blend_out=0)
        frames = range(1, int((start + duration) * 24) + 4)
        before = self.curve(bone, frames)
        new = commands.split_clip(self.scene, cid, at=cut)
        a, b = commands.get_clip(self.scene, cid), commands.get_clip(self.scene, new)
        self.assertAlmostEqual(a.duration, cut - start, places=5)
        self.assertAlmostEqual(b.start, cut, places=5)
        self.assertAlmostEqual(b.start + b.duration, start + duration, places=5)
        self.assertEqual(self.curve(bone, frames), before)

    def test_split_loop_mid_cycle(self):
        self.assert_split_is_invisible("walk", "root", 0.5, 3.0, 1.75)

    def test_split_once_then_hold(self):
        self.assert_split_is_invisible("wave", "arm_L", 0.0, 2.0, 0.25)

    def test_split_once_in_hold(self):
        self.assert_split_is_invisible("wave", "arm_L", 0.0, 2.0, 1.5)

    def test_split_outside_clip(self):
        cid = commands.add_clip(self.scene, self.leo, "walk", start=1, duration=1)
        with self.assertRaises(CSKError):
            commands.split_clip(self.scene, cid, at=3.0)

    def test_split_operator_uses_playhead(self):
        commands.add_clip(self.scene, self.leo, "walk", start=0, duration=2)
        self.scene.frame_set(25)
        bpy.context.view_layer.objects.active = self.rig
        self.assertEqual(bpy.ops.csk360.split_clip(), {"FINISHED"})
        self.assertEqual(len(self.scene.csk360.clips), 2)


class JumpTests(EditingBase):
    def test_jump_between_boundaries(self):
        commands.add_clip(self.scene, self.leo, "walk", start=1, duration=2)
        commands.add_line(self.scene, self.leo, "Hi", start=4, duration=1)
        self.scene.frame_set(1)
        stops = []
        while (t := commands.jump_to_clip(self.scene, 1, self.leo)) is not None:
            stops.append(t)
        self.assertEqual(stops, [1.0, 3.0, 4.0, 5.0])
        self.assertEqual(commands.jump_to_clip(self.scene, -1, self.leo), 4.0)
        self.assertEqual(self.scene.frame_current, 1 + 4 * 24)

    def test_jump_operator(self):
        commands.add_clip(self.scene, self.leo, "walk", start=1, duration=2)
        self.scene.frame_set(1)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.csk360.jump_clip(direction="NEXT")
        self.assertEqual(self.scene.frame_current, 25)


class LocalizeAudioTests(EditingBase):
    def setUp(self):
        super().setUp()
        self._old = os.environ.get("CSK360_HOME")
        os.environ["CSK360_HOME"] = os.path.join(h.TMP, "voicehome")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CSK360_HOME", None)
        else:
            os.environ["CSK360_HOME"] = self._old

    def test_saving_copies_voice_files_next_to_the_blend(self):
        cache = os.path.join(voice.home(), "cache")
        os.makedirs(cache, exist_ok=True)
        src = os.path.join(cache, "abc123.wav")
        os.replace(h.write_wav(1.0, name="abc123.wav"), src)
        lid = commands.add_line(self.scene, self.leo, "Hi", start=0, audio_path=src)
        blend = os.path.join(h.TMP, "project", "scene.blend")
        os.makedirs(os.path.dirname(blend), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        line = commands.get_line(bpy.context.scene, lid)
        self.assertEqual(line.audio_path, "//csk360_audio/abc123.wav")
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(blend), "csk360_audio", "abc123.wav")))
        bpy.ops.wm.open_mainfile(filepath=blend)
        scene = bpy.context.scene
        strip = scene.sequence_editor.strips["CSK360:" + lid]
        self.assertTrue(os.path.isfile(bpy.path.abspath(strip.sound.filepath)))
        commands.rebuild(scene)
        self.assertEqual(scene.csk360.last_report, "")


if __name__ == "__main__":
    unittest.main()
