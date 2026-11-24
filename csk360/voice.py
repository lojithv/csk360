# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender-side client for the CSK360 voice service.

Text-to-speech (Kokoro, Supertonic 3) and Rhubarb lip sync run in a separate
process with its own Python environment, so heavy dependencies never load
into Blender. That environment is created from Blender's own Python.

Everything lives in one folder (the "voice home"), shared by all Blender
versions: `~/.csk360` by default, or the CSK360_HOME environment variable.
"""

import hashlib
import json
import os
import subprocess
import sys
import threading

SERVICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_service", "service.py")
REQUIREMENTS = os.path.join(os.path.dirname(SERVICE), "requirements.txt")
DEFAULT_VOICE = "kokoro/af_heart"
ENGINES = ("kokoro", "supertonic", "rhubarb")

SUPERTONIC_TERMS = (
    "Supertonic 3 voices are licensed by Supertone Inc. under the BigScience OpenRAIL-M licence, "
    "not CSK360's GPL. By accepting you agree to its use restrictions, including: say clearly "
    "that generated speech is machine-generated, and do not impersonate a real person without "
    "their consent. Full text: <voice home>/models/supertonic/LICENSE."
)

_cached_voices = []


class VoiceError(Exception):
    """Plain-English voice setup or generation error."""


def home():
    return os.environ.get("CSK360_HOME") or os.path.join(os.path.expanduser("~"), ".csk360")


def venv_python(h=None):
    h = h or home()
    sub = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    return os.path.join(h, "venv", *sub)


def cache_path(text, voice_id, speed):
    key = hashlib.sha1(f"{voice_id}|{speed:.3f}|{text}".encode("utf-8")).hexdigest()[:16]
    return os.path.join(home(), "cache", key + ".wav"), key


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _service(args, on_line=None, timeout=None):
    py = venv_python()
    if not os.path.isfile(py):
        raise VoiceError("Voices are not installed yet. Press CSK360 > Voices > Install Voices.")
    cmd = [py, SERVICE, *args, "--home", home()]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", creationflags=_flags())
    out = []
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
        if on_line:
            on_line(obj)
    err = proc.stderr.read()
    proc.wait(timeout=timeout)
    if proc.returncode != 0:
        tail = err.strip().splitlines()[-1] if err.strip() else f"exit code {proc.returncode}"
        raise VoiceError(f"The voice service failed: {tail}")
    return out


def check():
    """What is installed. Never raises."""
    if not os.path.isfile(venv_python()):
        return {"venv": False, "runtime": False, "kokoro": False, "supertonic": False,
                "supertonic_terms_accepted": False, "rhubarb": False}
    try:
        st = _service(["check"])[-1]
    except (VoiceError, IndexError, OSError) as e:
        return {"venv": True, "error": str(e)}
    st["venv"] = True
    return st


_status_cache = None


def status(refresh=False):
    """Cached `check()` for drawing panels without spawning a process per redraw."""
    global _status_cache
    if refresh or _status_cache is None:
        _status_cache = check()
    return _status_cache


def setup(engines=ENGINES, supertonic_from=None, on_line=None):
    """Create the environment, install packages and download models (about 900 MB)."""
    h = home()
    os.makedirs(h, exist_ok=True)
    py = venv_python(h)
    if not os.path.isfile(py):
        if on_line:
            on_line({"progress": "Creating Python environment"})
        subprocess.run([sys.executable, "-m", "venv", os.path.join(h, "venv")], check=True,
                       creationflags=_flags())
    if on_line:
        on_line({"progress": "Installing onnxruntime and Kokoro packages"})
    r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", REQUIREMENTS],
                       capture_output=True, text=True, creationflags=_flags())
    if r.returncode != 0:
        raise VoiceError(f"Installing voice packages failed: {r.stderr.strip()[-300:]}")
    args = ["install", "--engines", ",".join(engines)]
    if supertonic_from:
        args += ["--supertonic-from", supertonic_from]
    return _service(args, on_line=on_line)[-1]["status"]


def accept_supertonic_terms():
    return _service(["accept-supertonic-terms"])[-1]


def voices(refresh=False):
    global _cached_voices
    if refresh or not _cached_voices:
        try:
            _cached_voices = _service(["voices"])[-1]["voices"]
        except (VoiceError, IndexError, OSError):
            _cached_voices = []
    return list(_cached_voices)


def speak(jobs, on_line=None):
    """Run jobs [{id, text, voice, speed, out}] and return results keyed by id."""
    if not jobs:
        return {}
    req = os.path.join(home(), "cache", f"request_{os.getpid()}_{threading.get_ident()}.json")
    os.makedirs(os.path.dirname(req), exist_ok=True)
    with open(req, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
    try:
        lines = _service(["speak", "--request", req], on_line=on_line)
    finally:
        try:
            os.remove(req)
        except OSError:
            pass
    return {r["id"]: r for r in lines if "id" in r}


class BackgroundJob:
    """Runs `speak` (or any callable) in a thread so Blender's UI stays responsive."""

    def __init__(self, fn, *args, **kwargs):
        self.result = None
        self.error = None
        self.messages = []
        self._thread = threading.Thread(target=self._run, args=(fn, args, kwargs), daemon=True)
        self._thread.start()

    def _run(self, fn, args, kwargs):
        try:
            self.result = fn(*args, on_line=self.messages.append, **kwargs)
        except Exception as e:  # surfaced to the user on the main thread
            self.error = e

    @property
    def done(self):
        return not self._thread.is_alive()

    def last_progress(self):
        for m in reversed(self.messages):
            if "progress" in m:
                pct = m.get("percent")
                return f"{m['progress']} {pct}%" if pct not in (None, -1) else m["progress"]
        return ""
