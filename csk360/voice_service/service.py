# SPDX-License-Identifier: GPL-3.0-or-later
"""CSK360 voice service. Runs OUTSIDE Blender, in its own venv.

    python service.py check   --home H
    python service.py install --home H [--engines kokoro,supertonic,rhubarb] [--supertonic-from DIR]
    python service.py voices  --home H
    python service.py speak   --home H --request jobs.json

`speak` reads a JSON list of jobs
    {"id", "text", "voice": "kokoro/af_heart" | "supertonic/M1[@de]", "speed", "out"}
writes `out` (16-bit WAV) plus `out`.json, and prints one JSON result per job:
    {"id", "ok", "wav", "duration", "visemes": [[seconds, "A".."H"|"X"], ...], "error"}
Progress and logs go to stderr. Every stdout line is JSON.

Layout under --home:
    venv/                        created by the Blender side with Blender's Python
    models/kokoro/               kokoro-v1.0.onnx, voices-v1.0.bin
    models/supertonic/           Supertonic 3 (onnx/, voice_styles/, LICENSE, NOTICE.txt)
    rhubarb/                     Rhubarb Lip Sync (rhubarb.exe + res/)
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
SUPERTONIC_REV = "724fb5abbf5502583fb520898d45929e62f02c0b"
SUPERTONIC_URL = f"https://huggingface.co/Supertone/supertonic-3/resolve/{SUPERTONIC_REV}/"
SUPERTONIC_FILES = ("onnx/tts.json", "onnx/unicode_indexer.json", "onnx/duration_predictor.onnx",
                    "onnx/text_encoder.onnx", "onnx/vector_estimator.onnx", "onnx/vocoder.onnx", "LICENSE")
RHUBARB_VERSION = "1.14.0"
RHUBARB_URL = (f"https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v{RHUBARB_VERSION}/"
               f"Rhubarb-Lip-Sync-{RHUBARB_VERSION}-Windows.zip")
SUPERTONIC_ACCEPTED = "ACCEPTED_TERMS"

KOKORO_LANGS = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi", "i": "it",
                "j": "ja", "p": "pt-br", "z": "cmn"}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj), flush=True)


def paths(home):
    return {
        "kokoro": os.path.join(home, "models", "kokoro"),
        "supertonic": os.path.join(home, "models", "supertonic"),
        "rhubarb": os.path.join(home, "rhubarb"),
    }


def rhubarb_exe(home):
    root = paths(home)["rhubarb"]
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower() in ("rhubarb.exe", "rhubarb"):
                return os.path.join(dirpath, f)
    return None


def status(home):
    from supertonic_engine import installed_voices, is_model_dir
    p = paths(home)
    st = p["supertonic"]
    try:
        import onnxruntime  # noqa: F401
        runtime = True
    except ImportError:
        runtime = False
    try:
        import kokoro_onnx  # noqa: F401
        kokoro_pkg = True
    except ImportError:
        kokoro_pkg = False
    return {
        "runtime": runtime,
        "kokoro": kokoro_pkg and all(os.path.isfile(os.path.join(p["kokoro"], f)) for f in KOKORO_FILES),
        "supertonic": is_model_dir(st) and bool(installed_voices(st)),
        "supertonic_terms_accepted": os.path.isfile(os.path.join(st, SUPERTONIC_ACCEPTED)),
        "rhubarb": rhubarb_exe(home) is not None,
    }


# ------------------------------------------------------------------ install

def download(url, dest):
    if os.path.isfile(dest):
        log(f"cached {os.path.basename(dest)}")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    log(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "csk360-voice-service"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
            done += len(block)
            pct = int(done * 100 / total) if total else -1
            if pct != last and pct % 10 == 0:
                log(f"  {os.path.basename(dest)} {pct}%")
                emit({"progress": os.path.basename(dest), "percent": pct})
                last = pct
    os.replace(part, dest)
    return dest


def install(home, engines, supertonic_from=None):
    p = paths(home)
    if "kokoro" in engines:
        for f in KOKORO_FILES:
            download(KOKORO_URL + f, os.path.join(p["kokoro"], f))
    if "supertonic" in engines:
        st = p["supertonic"]
        for rel in SUPERTONIC_FILES + tuple(f"voice_styles/{v}.json" for v in
                                            ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")):
            dest = os.path.join(st, *rel.split("/"))
            src = os.path.join(supertonic_from, *rel.split("/")) if supertonic_from else None
            if src and os.path.isfile(src) and not os.path.isfile(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                log(f"copying {rel}")
                shutil.copyfile(src, dest)
            else:
                download(SUPERTONIC_URL + rel, dest)
        with open(os.path.join(st, "NOTICE.txt"), "w", encoding="utf-8") as f:
            f.write("Supertonic 3 text-to-speech model\nCopyright (c) 2026 Supertone Inc.\n"
                    f"Source: https://huggingface.co/Supertone/supertonic-3 (revision {SUPERTONIC_REV})\n\n"
                    "These files are licensed under the BigScience OpenRAIL-M License (see LICENSE),\n"
                    "not under CSK360's GPL. Using these voices means agreeing to the use restrictions\n"
                    "in paragraph 5 and Attachment A, including: disclose that generated speech is\n"
                    "machine-generated, and do not impersonate a real person without consent.\n"
                    "The files are unmodified.\n")
    if "rhubarb" in engines and rhubarb_exe(home) is None:
        tmp = tempfile.mkdtemp(prefix="csk360_rhubarb_")
        z = download(RHUBARB_URL, os.path.join(tmp, "rhubarb.zip"))
        with zipfile.ZipFile(z) as zf:
            zf.extractall(p["rhubarb"])
        shutil.rmtree(tmp, ignore_errors=True)
    return status(home)


# -------------------------------------------------------------------- voices

def list_voices(home):
    st = status(home)
    out = []
    if st["kokoro"]:
        import numpy as np
        with np.load(os.path.join(paths(home)["kokoro"], "voices-v1.0.bin")) as data:
            names = sorted(data.files)
        out += [f"kokoro/{n}" for n in names]
    if st["supertonic"]:
        from supertonic_engine import installed_voices
        out += [f"supertonic/{v}" for v in installed_voices(paths(home)["supertonic"])]
    return out


def parse_voice(voice_id):
    """'kokoro/af_heart' -> ('kokoro', 'af_heart', None); 'supertonic/M1@de' -> (..., 'de')."""
    if "/" not in voice_id:
        raise ValueError(f"Voice '{voice_id}' should look like kokoro/af_heart or supertonic/M1.")
    engine, rest = voice_id.split("/", 1)
    name, _, lang = rest.partition("@")
    if engine not in ("kokoro", "supertonic"):
        raise ValueError(f"Unknown voice engine '{engine}'. Use kokoro or supertonic.")
    return engine, name, lang or None


# --------------------------------------------------------------------- speak

class Engines:
    def __init__(self, home):
        self.home = home
        self._kokoro = None
        self._supertonic = None

    def kokoro(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            d = paths(self.home)["kokoro"]
            self._kokoro = Kokoro(os.path.join(d, KOKORO_FILES[0]), os.path.join(d, KOKORO_FILES[1]))
        return self._kokoro

    def supertonic(self):
        if self._supertonic is None:
            d = paths(self.home)["supertonic"]
            if not os.path.isfile(os.path.join(d, SUPERTONIC_ACCEPTED)):
                raise RuntimeError("Supertonic voices need you to accept their licence terms first "
                                   "(CSK360 > Voices > Accept Supertonic Terms).")
            from supertonic_engine import Model
            self._supertonic = Model(d)
        return self._supertonic

    def speak(self, text, voice_id, speed):
        engine, name, lang = parse_voice(voice_id)
        if engine == "kokoro":
            k_lang = lang or KOKORO_LANGS.get(name[:1], "en-us")
            samples, rate = self.kokoro().create(text, voice=name, speed=speed, lang=k_lang)
            return samples, rate, (k_lang.startswith("en"))
        samples, rate = self.supertonic().synthesize(text, name, lang=lang or "en", speed=speed)
        return samples, rate, (lang or "en") == "en"


def write_wav(path, samples, rate):
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def lipsync(home, wav, text, english=True):
    exe = rhubarb_exe(home)
    if exe is None:
        raise RuntimeError("Rhubarb Lip Sync is not installed.")
    with tempfile.TemporaryDirectory(prefix="csk360_lip_") as tmp:
        dialog = os.path.join(tmp, "dialog.txt")
        out = os.path.join(tmp, "cues.json")
        with open(dialog, "w", encoding="utf-8") as f:
            f.write(text)
        cmd = [exe, "-f", "json", "-o", out, "-r", "pocketSphinx" if english else "phonetic",
               "--dialogFile", dialog, wav]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
        if r.returncode != 0:
            raise RuntimeError(f"Rhubarb failed: {(r.stderr or r.stdout).strip()[-300:]}")
        with open(out, encoding="utf-8") as f:
            cues = json.load(f)["mouthCues"]
    return [[round(c["start"], 3), c["value"]] for c in cues]


def speak(home, jobs):
    engines = Engines(home)
    for job in jobs:
        res = {"id": job.get("id"), "ok": False}
        try:
            out = job["out"]
            meta = out + ".json"
            if os.path.isfile(out) and os.path.isfile(meta):
                with open(meta, encoding="utf-8") as f:
                    res.update(json.load(f))
                res["cached"] = True
            else:
                log(f"speaking {job.get('id')}: {job['voice']}")
                samples, rate, english = engines.speak(job["text"], job["voice"], float(job.get("speed", 1.0)))
                write_wav(out, samples, rate)
                visemes = lipsync(home, out, job["text"], english)
                data = {"wav": out, "duration": round(len(samples) / rate, 4), "visemes": visemes}
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                res.update(data)
            res["ok"] = True
        except Exception as e:  # report per line, keep going
            res["error"] = f"{type(e).__name__}: {e}"
        emit(res)


def cache_key(text, voice, speed):
    return hashlib.sha1(f"{voice}|{speed:.3f}|{text}".encode("utf-8")).hexdigest()[:16]


def main(argv=None):
    ap = argparse.ArgumentParser(description="CSK360 voice service")
    ap.add_argument("command", choices=["check", "install", "voices", "speak", "accept-supertonic-terms"])
    ap.add_argument("--home", required=True)
    ap.add_argument("--engines", default="kokoro,supertonic,rhubarb")
    ap.add_argument("--supertonic-from")
    ap.add_argument("--request")
    a = ap.parse_args(argv)
    if a.command == "check":
        emit(status(a.home))
    elif a.command == "install":
        emit({"status": install(a.home, set(a.engines.split(",")), a.supertonic_from)})
    elif a.command == "voices":
        emit({"voices": list_voices(a.home)})
    elif a.command == "accept-supertonic-terms":
        d = paths(a.home)["supertonic"]
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SUPERTONIC_ACCEPTED), "w", encoding="utf-8") as f:
            f.write("The user accepted the BigScience OpenRAIL-M use restrictions for Supertonic 3.\n")
        emit(status(a.home))
    elif a.command == "speak":
        with open(a.request, encoding="utf-8") as f:
            speak(a.home, json.load(f))


if __name__ == "__main__":
    main()
