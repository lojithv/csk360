# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice generation: job planning, applying results, and (when installed) the real service."""

import os
import sys
import tempfile
import unittest

import bpy

from csk360 import commands, voice
from csk360.commands import CSKError

import helpers as h

sys.path.insert(0, os.path.dirname(voice.SERVICE))
import supertonic_engine as st  # noqa: E402  (pure Python + numpy, safe to import in Blender)


class _TempHome(unittest.TestCase):
    def setUp(self):
        self._old_home = os.environ.get("CSK360_HOME")
        os.environ["CSK360_HOME"] = tempfile.mkdtemp(prefix="csk360_home_")
        self.scene = h.reset_scene()
        self.rig = h.make_rig(self.scene)
        self.leo = commands.add_cast(self.scene, self.rig, name="Leo", voice="supertonic/M1")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("CSK360_HOME", None)
        else:
            os.environ["CSK360_HOME"] = self._old_home


class VoiceJobTests(_TempHome):
    def test_jobs_only_for_lines_with_text(self):
        a = commands.add_line(self.scene, self.leo, "Hello there", start=0)
        commands.add_line(self.scene, self.leo, "   ", start=2)
        jobs = commands.voice_jobs(self.scene)
        self.assertEqual([j["id"] for j in jobs], [a])
        self.assertEqual(jobs[0]["voice"], "supertonic/M1")
        self.assertTrue(jobs[0]["out"].startswith(voice.home()))

    def test_line_voice_overrides_character(self):
        lid = commands.add_line(self.scene, self.leo, "Hi", start=0, voice="kokoro/am_michael")
        self.assertEqual(commands.voice_jobs(self.scene)[0]["voice"], "kokoro/am_michael")
        commands.get_cast(self.scene, self.leo).voice = ""
        commands.set_line(self.scene, lid, voice="")
        self.assertEqual(commands.voice_jobs(self.scene)[0]["voice"], voice.DEFAULT_VOICE)

    def test_bad_voice_id(self):
        commands.add_line(self.scene, self.leo, "Hi", start=0, voice="michael")
        with self.assertRaises(CSKError):
            commands.voice_jobs(self.scene)

    def test_applying_results_sets_audio_mouth_and_key(self):
        lid = commands.add_line(self.scene, self.leo, "Hi there", start=1.0)
        (job,) = commands.voice_jobs(self.scene)
        os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
        wav = h.write_wav(1.2, name=os.path.basename(job["out"]))
        os.replace(wav, job["out"])
        errors = commands.apply_voice_results(self.scene, {lid: {
            "id": lid, "ok": True, "wav": job["out"], "duration": 1.2,
            "visemes": [[0.0, "X"], [0.1, "B"], [0.5, "D"], [1.0, "X"]]}})
        self.assertEqual(errors, [])
        line = commands.get_line(self.scene, lid)
        self.assertEqual(line.audio_path, job["out"])
        self.assertAlmostEqual(line.duration, 1.2, places=1)
        self.assertEqual([v.shape for v in line.visemes], [0, 2, 4, 0])
        self.assertFalse(commands.line_needs_voice(self.scene, line))
        self.assertEqual(commands.voice_jobs(self.scene), [])
        self.assertEqual(h.prop_at(self.scene, self.rig, "mouth", 25 + 12), 4)  # D at 1.5 s
        self.assertIn("CSK360:" + lid, self.scene.sequence_editor.strips)
        # Editing the text makes only that line stale.
        commands.set_line(self.scene, lid, text="Hi there, friend")
        self.assertTrue(commands.line_needs_voice(self.scene, line))

    def test_failed_result_is_reported(self):
        lid = commands.add_line(self.scene, self.leo, "Hi", start=0)
        errors = commands.apply_voice_results(self.scene, {lid: {"id": lid, "ok": False, "error": "boom"}})
        self.assertEqual(errors, [f"{lid}: boom"])
        self.assertIn("boom", self.scene.csk360.last_report)

    def test_missing_environment_is_plain_english(self):
        commands.add_line(self.scene, self.leo, "Hi", start=0)
        with self.assertRaises(CSKError) as ctx:
            commands.generate_lines(self.scene)
        self.assertIn("Install Voices", str(ctx.exception))
        self.assertFalse(voice.check()["venv"])


class SupertonicTextTests(unittest.TestCase):
    """Same cases as Frameling's Rust tests, so both pipelines stay in step."""

    def test_preprocess(self):
        self.assertEqual(st.preprocess("Hello  “world” — hi", "en"), '<en>Hello "world" - hi.</en>')
        self.assertEqual(st.preprocess("Done!", "fr"), "<fr>Done!</fr>")

    def test_chunks_keep_titles_together(self):
        self.assertEqual(st.chunk_text("Dr. Smith is here. He said hi! Did you hear?", 25),
                         ["Dr. Smith is here.", "He said hi! Did you hear?"])

    def test_long_sentences_split_on_words(self):
        self.assertTrue(all(len(c) <= 50 for c in st.chunk_text("word " * 100, 50)))


_STATUS = {} if os.environ.get("CSK360_HOME") else voice.check()


def _ready(*keys):
    return all(_STATUS.get(k) for k in ("rhubarb",) + keys)


class RealVoiceTests(unittest.TestCase):
    """End to end with the real voice service and Rhubarb (skipped if not installed)."""

    def _run(self, voices):
        scene = h.reset_scene()
        leo = commands.add_starter_character(scene, "Leo", voice=voices[0])
        maya = commands.add_starter_character(scene, "Maya", location=(1, 0, 0), voice=voices[-1])
        a = commands.add_line(scene, leo, "Morning! Did you see the numbers?", start=0.5)
        b = commands.add_line(scene, maya, "I did. We need to talk.", after_previous=True)
        errors = commands.generate_lines(scene)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(commands.get_line(scene, b).start,
                                commands.get_line(scene, a).start + 0.5)
        for lid in (a, b):
            line = commands.get_line(scene, lid)
            self.assertTrue(os.path.isfile(line.audio_path))
            self.assertGreater(line.duration, 0.8)
            shapes = {v.shape for v in line.visemes}
            self.assertGreater(len(shapes), 2, f"{lid} mouth barely moves")
        # Cached: a second run does nothing.
        self.assertEqual(commands.voice_jobs(scene), [])

    @unittest.skipUnless(_ready("kokoro"), "Kokoro or Rhubarb not installed")
    def test_kokoro(self):
        self._run(["kokoro/am_michael", "kokoro/af_heart"])

    @unittest.skipUnless(_ready("supertonic", "supertonic_terms_accepted"),
                         "Supertonic not installed or its licence terms not accepted")
    def test_supertonic(self):
        self._run(["supertonic/M1", "supertonic/F1"])


if __name__ == "__main__":
    unittest.main()
