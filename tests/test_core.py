# SPDX-License-Identifier: GPL-3.0-or-later
"""Core behaviour: model, compiler, commands, operators."""

import math
import os
import unittest

import bpy

from csk360 import commands, compiler, library
from csk360.commands import CSKError

import helpers as h


class Base(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene(fps=24)
        self.rig = h.make_rig(self.scene)
        # walk: 24-frame cycle (1 s), stride 0.35 m -> 0.7 m/s
        self.walk = h.make_action("walk", "root", {1: 0.0, 13: 0.1, 25: 0.0},
                                  kind="action", loop=True, stride=0.35, tags="walk, move")
        # wave: 12-frame one-shot, upper body
        self.wave = h.make_action("wave", "arm_L", {1: 0.0, 13: 1.0},
                                  kind="action", layer="GESTURE", tags="hello")
        # arms_up: a still pose
        self.pose = h.make_action("arms_up", "arm_L", {1: 0.5}, kind="pose")
        self.leo = commands.add_cast(self.scene, self.rig, name="Leo")

    def strips(self, track_name):
        return list(h.track(self.rig, track_name).strips)


class CastTests(Base):
    def test_add_cast_records_member(self):
        c = self.scene.csk360.cast[0]
        self.assertEqual(c.id, "leo")
        self.assertEqual(c.rig_type, "biped3d")
        self.assertEqual(c.object, self.rig)

    def test_same_object_twice_is_rejected(self):
        with self.assertRaises(CSKError):
            commands.add_cast(self.scene, self.rig)

    def test_ids_are_unique(self):
        other = h.make_rig(self.scene, name="Leo.001")
        self.assertEqual(commands.add_cast(self.scene, other, name="Leo"), "leo_2")

    def test_remove_cast_clears_everything(self):
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.add_move(self.scene, "leo", start=0, point=(2, 0, 0))
        commands.remove_cast(self.scene, "leo")
        proj = self.scene.csk360
        self.assertEqual((len(proj.cast), len(proj.clips), len(proj.moves)), (0, 0, 0))
        self.assertEqual(h.csk_tracks(self.rig), [])
        self.assertFalse(any(a.name.startswith("CSK360.") for a in bpy.data.actions))


class ClipTests(Base):
    def test_loop_clip_fills_duration(self):
        commands.add_clip(self.scene, "leo", "walk", start=1.0, duration=3.0)
        (s,) = self.strips("CSK360 Body")
        self.assertEqual(s.frame_start, 25)
        self.assertAlmostEqual(s.frame_end, 25 + 72)
        self.assertAlmostEqual(s.repeat, 3.0)
        # mid-cycle of the second repeat: frame 25+24+12 -> 0.1
        self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "root", 25 + 36), 0.1, places=4)

    def test_defaults_come_from_library(self):
        cid = commands.add_clip(self.scene, "leo", "wave", start=0)
        clip = commands.get_clip(self.scene, cid)
        self.assertEqual(clip.layer, "GESTURE")
        self.assertEqual(clip.loop_mode, "ONCE")
        self.assertAlmostEqual(clip.duration, 0.5)
        pose = commands.get_clip(self.scene, commands.add_clip(self.scene, "leo", "arms_up", start=3))
        self.assertEqual((pose.loop_mode, pose.duration), ("HOLD", 2.0))

    def test_clip_starts_at_playhead(self):
        self.scene.frame_set(49)
        cid = commands.add_clip(self.scene, "leo", "walk")
        self.assertAlmostEqual(commands.get_clip(self.scene, cid).start, 2.0)

    def test_once_clip_holds_last_pose_then_ends(self):
        commands.add_clip(self.scene, "leo", "wave", start=1.0, duration=2.0, blend_in=0)
        strips = self.strips("CSK360 Gesture")
        self.assertEqual(len(strips), 2)
        self.assertEqual(strips[0].frame_start, 25)
        self.assertAlmostEqual(strips[-1].frame_end, 25 + 48)
        self.assertEqual(strips[0].blend_type, "COMBINE")
        self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "arm_L", 31), 0.5, places=4)
        self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "arm_L", 65), 1.0, places=4)
        self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "arm_L", 80), 0.0, places=4)

    def test_once_clip_shorter_than_action_is_cut(self):
        commands.add_clip(self.scene, "leo", "wave", start=0, duration=0.25, blend_in=0)
        (s,) = self.strips("CSK360 Gesture")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 6)

    def test_pose_clip_holds(self):
        commands.add_clip(self.scene, "leo", "arms_up", start=0.5, duration=2.0, blend_in=0)
        (s,) = self.strips("CSK360 Body")
        self.assertEqual(s.frame_start, 13)
        self.assertAlmostEqual(s.frame_end, 13 + 48)
        for f in (13, 30, 60):
            self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "arm_L", f), 0.5, places=4)

    def test_long_pose_beyond_scale_limit(self):
        self.scene.frame_end = 30000
        commands.add_clip(self.scene, "leo", "arms_up", start=0, duration=60.0 * 10)
        (s,) = self.strips("CSK360 Body")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 24 * 600, places=2)

    def test_duration_shortcut_steps(self):
        cid = commands.add_clip(self.scene, "leo", "walk", start=0, duration=2.0)
        commands.change_clip_duration(self.scene, cid, 1.0)
        (s,) = self.strips("CSK360 Body")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 72)
        commands.change_clip_duration(self.scene, cid, -1.0 / 24)
        (s,) = self.strips("CSK360 Body")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 71)

    def test_duration_never_below_one_frame(self):
        cid = commands.add_clip(self.scene, "leo", "walk", start=0, duration=0.5)
        commands.change_clip_duration(self.scene, cid, -10)
        self.assertAlmostEqual(commands.get_clip(self.scene, cid).duration, 1 / 24)
        (s,) = self.strips("CSK360 Body")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 1)

    def test_overlapping_clips_get_a_second_track(self):
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=3)
        commands.add_clip(self.scene, "leo", "arms_up", start=1, duration=1, layer="BODY")
        commands.add_clip(self.scene, "leo", "walk", start=3, duration=1)
        self.assertEqual(len(self.strips("CSK360 Body")), 2)
        self.assertEqual(len(self.strips("CSK360 Body 2")), 1)

    def test_editing_a_property_recompiles(self):
        cid = commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.get_clip(self.scene, cid).start = 2.0  # as the UI would
        (s,) = self.strips("CSK360 Body")
        self.assertEqual(s.frame_start, 49)

    def test_unknown_asset_suggests_close_match(self):
        with self.assertRaises(CSKError) as ctx:
            commands.add_clip(self.scene, "leo", "wlak")
        self.assertIn("walk", str(ctx.exception))

    def test_missing_asset_is_a_warning_not_a_crash(self):
        cid = commands.add_clip(self.scene, "leo", "walk", start=0)
        bpy.data.actions.remove(self.walk)
        warnings = commands.rebuild(self.scene)
        self.assertTrue(any(cid in w for w in warnings))

    def test_manual_layer_is_never_touched(self):
        manual = h.make_action("manual_fix", "spine", {1: 0.3})
        self.rig.animation_data_create().action = manual
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.rebuild(self.scene)
        self.assertEqual(self.rig.animation_data.action, manual)
        self.assertAlmostEqual(h.bone_x(self.scene, self.rig, "spine", 10), 0.3, places=4)

    def test_users_own_tracks_survive(self):
        ad = self.rig.animation_data_create()
        mine = ad.nla_tracks.new()
        mine.name = "My track"
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.rebuild(self.scene)
        self.assertIn("My track", [t.name for t in ad.nla_tracks])

    def test_rebuild_is_idempotent(self):
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.add_move(self.scene, "leo", start=0, point=(2, 0, 0))
        commands.add_line(self.scene, "leo", "Hi", start=0, visemes=[(0, "A"), (0.3, "X")])
        before = (len(h.csk_tracks(self.rig)), len(bpy.data.actions))
        for _ in range(3):
            commands.rebuild(self.scene)
        self.assertEqual((len(h.csk_tracks(self.rig)), len(bpy.data.actions)), before)


class MoveTests(Base):
    def test_walk_to_point_uses_stride(self):
        mid = commands.add_move(self.scene, "leo", start=0, point=(3.5, 0, 0))
        m = commands.get_move(self.scene, mid)
        self.assertEqual(m.walk_asset, "walk")
        self.assertAlmostEqual(m.duration, 5.0)  # 3.5 m / 0.7 m/s
        self.scene.frame_set(1 + 5 * 24 + 10)
        self.assertAlmostEqual(self.rig.location.x, 3.5, places=4)
        self.assertAlmostEqual(self.rig.rotation_euler.z, math.pi / 2, places=4)
        (s,) = self.strips("CSK360 Body")
        self.assertAlmostEqual(s.frame_end - s.frame_start, 120)
        self.assertAlmostEqual(s.repeat, 5.0)

    def test_halfway_position_and_explicit_speed(self):
        commands.add_move(self.scene, "leo", start=1.0, point=(0, -4, 0), speed=2.0)
        self.scene.frame_set(1 + 24 * 2)  # 1 s into a 2 s walk
        self.assertAlmostEqual(self.rig.location.y, -2.0, places=3)
        self.assertAlmostEqual(self.rig.rotation_euler.z, 0.0, places=4)

    def test_walk_to_object_approach_point_then_sit(self):
        h.make_action("sit", "root", {1: -0.4}, kind="pose", duration=3.0)
        chair = bpy.data.objects.new("chair", None)
        chair.location = (0, 4, 0)
        approach = bpy.data.objects.new("chair_approach", None)
        approach.parent = chair
        approach.location = (0, -1, 0)
        for o in (chair, approach):
            self.scene.collection.objects.link(o)
        self.scene.view_layers[0].update()
        mid = commands.add_move(self.scene, "leo", start=0, target="chair", arrival="sit")
        m = commands.get_move(self.scene, mid)
        self.assertAlmostEqual(m.duration, 3.0 / 0.7, places=4)
        names = [s.name for s in self.strips("CSK360 Body")]
        self.assertEqual(names, [f"{mid}.walk", f"{mid}.arrive"])
        self.scene.frame_set(200)
        self.assertAlmostEqual(self.rig.location.y, 3.0, places=4)

    def test_moves_chain_from_previous_end(self):
        commands.add_move(self.scene, "leo", start=0, point=(1.4, 0, 0))  # 2 s
        m2 = commands.add_move(self.scene, "leo", start=1.0, point=(1.4, 1.4, 0))
        commands.rebuild(self.scene)
        self.assertIn("delayed", self.scene.csk360.last_report)
        self.scene.frame_set(1 + 24 * 5)
        self.assertAlmostEqual(self.rig.location.y, 1.4, places=4)
        self.assertAlmostEqual(commands.get_move(self.scene, m2).duration, 2.0)


class DialogueTests(Base):
    def test_line_adds_sound_and_mouth_keys(self):
        wav = h.write_wav(1.5)
        lid = commands.add_line(self.scene, "leo", "Morning!", start=2.0, audio_path=wav,
                                visemes=[(0.0, "A"), (0.5, "C"), (1.0, "X")])
        line = commands.get_line(self.scene, lid)
        self.assertAlmostEqual(line.duration, 1.5, places=1)
        strip = self.scene.sequence_editor.strips["CSK360:" + lid]
        self.assertEqual(strip.frame_start, 49)
        self.assertEqual(strip.channel, 1)
        self.assertEqual(h.prop_at(self.scene, self.rig, "mouth", 49), 1)   # A
        self.assertEqual(h.prop_at(self.scene, self.rig, "mouth", 62), 3)   # C at +0.5 s
        self.assertEqual(h.prop_at(self.scene, self.rig, "mouth", 74), 0)   # X at +1.0 s

    def test_moving_a_line_moves_voice_and_lips(self):
        wav = h.write_wav(1.0)
        lid = commands.add_line(self.scene, "leo", "Hi", start=0.0, audio_path=wav,
                                visemes=[(0.0, "B"), (0.5, "X")])
        commands.set_line(self.scene, lid, start=3.0)
        strip = self.scene.sequence_editor.strips["CSK360:" + lid]
        self.assertEqual(strip.frame_start, 73)
        self.assertEqual(len([s for s in self.scene.sequence_editor.strips
                              if s.name.startswith("CSK360:")]), 1)
        self.assertEqual(h.prop_at(self.scene, self.rig, "mouth", 73), 2)  # B

    def test_after_previous_line(self):
        commands.add_line(self.scene, "leo", "One", start=1.0, duration=2.0)
        lid = commands.add_line(self.scene, "leo", "Two", after_previous=True, duration=1.0)
        self.assertAlmostEqual(commands.get_line(self.scene, lid).start, 3.0)

    def test_missing_audio_warns(self):
        commands.add_line(self.scene, "leo", "Hi", start=0, audio_path="//nope.wav")
        self.assertIn("not found", self.scene.csk360.last_report)

    def test_bad_viseme_letter(self):
        with self.assertRaises(CSKError):
            commands.add_line(self.scene, "leo", "Hi", visemes=[(0, "Q")])


class PersistenceTests(Base):
    def test_save_and_reload(self):
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        commands.add_line(self.scene, "leo", "Hi", start=0, visemes=[(0, "A")], duration=0.5)
        path = os.path.join(h.TMP, "roundtrip.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        scene = bpy.context.scene
        proj = scene.csk360
        self.assertEqual((len(proj.cast), len(proj.clips), len(proj.lines)), (1, 1, 1))
        self.assertEqual(proj.lines[0].visemes[0].shape, 1)
        self.assertEqual(library.meta(bpy.data.actions["walk"])["stride"], 0.35)
        rig = proj.cast[0].object
        self.assertIsNotNone(rig.animation_data.nla_tracks.get("CSK360 Body"))


class OperatorTests(Base):
    def test_operators_drive_the_same_commands(self):
        other = h.make_rig(self.scene, name="Maya")
        bpy.context.view_layer.objects.active = other
        self.assertEqual(bpy.ops.csk360.add_cast(), {"FINISHED"})
        self.assertEqual(bpy.ops.csk360.add_clip(asset="walk", duration=2.0), {"FINISHED"})
        clip = self.scene.csk360.clips[-1]
        self.assertEqual(clip.cast_id, "maya")
        bpy.ops.csk360.clip_duration(delta=1.0)
        self.assertAlmostEqual(clip.duration, 3.0)
        bpy.ops.csk360.clip_duration(delta=-1.0, by_frames=True)
        self.assertAlmostEqual(clip.duration, 3.0 - 1 / 24, places=5)
        self.scene.cursor.location = (1.4, 0, 0)
        self.assertEqual(bpy.ops.csk360.add_move(to="CURSOR"), {"FINISHED"})
        self.assertAlmostEqual(self.scene.csk360.moves[-1].duration, 2.0)
        self.assertEqual(bpy.ops.csk360.rebuild(), {"FINISHED"})
        self.assertEqual(bpy.ops.csk360.remove_clip(), {"FINISHED"})

    def test_operator_errors_are_plain_english(self):
        # In background mode Blender turns an ERROR report into a RuntimeError.
        with self.assertRaises(RuntimeError) as ctx:
            bpy.ops.csk360.add_clip(asset="nope")
        self.assertIn("No pose or action named 'nope'", str(ctx.exception))
        self.assertEqual(len(self.scene.csk360.clips), 0)


class AgentTests(Base):
    def test_describe_is_plain_data(self):
        import json
        commands.add_clip(self.scene, "leo", "walk", start=0, duration=2)
        data = commands.describe(self.scene)
        json.dumps(data)
        self.assertEqual(data["cast"][0]["id"], "leo")
        self.assertEqual({a["id"] for a in data["library"]} >= {"walk", "wave", "arms_up"}, True)


if __name__ == "__main__":
    unittest.main()
