# SPDX-License-Identifier: GPL-3.0-or-later
"""Supertonic 3 (Supertone Inc.) on ONNX Runtime, outside Blender.

Port of Frameling's Rust pipeline (MIT/Apache-2.0), which follows Supertone's
MIT sample code: text -> unicode ids -> duration predictor -> text encoder ->
flow-matching vector estimator -> vocoder -> 44.1 kHz mono.

The weights are under the BigScience OpenRAIL-M licence (use restrictions,
including disclosing generated speech as machine-generated). They are not
part of CSK360 and are installed separately with their LICENSE.
"""

import json
import math
import os
import unicodedata

import numpy as np

VOICES = ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")
LANGS = ("en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hr",
         "hu", "id", "it", "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi")
DEFAULT_STEPS = 10
BASE_SPEED = 1.05     # Supertonic's natural pace; CSK360 speed 1.0 maps to this
CHUNK_GAP_S = 0.25
MODEL_FILES = ("duration_predictor.onnx", "text_encoder.onnx", "vector_estimator.onnx",
               "vocoder.onnx", "tts.json", "unicode_indexer.json")


def is_model_dir(d):
    return all(os.path.isfile(os.path.join(d, "onnx", f)) for f in MODEL_FILES)


def installed_voices(d):
    return [v for v in VOICES if os.path.isfile(os.path.join(d, "voice_styles", v + ".json"))]


# --------------------------------------------------------------------- text

_REPLACE = [("–", "-"), ("‑", "-"), ("—", "-"), ("_", " "), ("“", '"'), ("”", '"'),
            ("‘", "'"), ("’", "'"), ("´", "'"), ("`", "'"), ("[", " "), ("]", " "),
            ("|", " "), ("/", " "), ("#", " "), ("→", " "), ("←", " "), ("@", " at "),
            ("e.g.,", "for example, "), ("i.e.,", "that is, ")]
_TIDY = [(" ,", ","), (" .", "."), (" !", "!"), (" ?", "?"), (" ;", ";"), (" :", ":"),
         (" '", "'"), ('""', '"'), ("''", "'")]
_ENDINGS = tuple(".!?;:,'\")]}…。」』】〉》›»>")
_ABBREV = {"Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.", "Ph.D.", "etc.", "e.g.", "i.e.",
           "vs.", "Inc.", "Ltd.", "Co.", "Corp.", "St.", "Ave.", "Blvd."}


def _is_emoji(c):
    o = ord(c)
    return 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x1F1E6 <= o <= 0x1F1FF


def preprocess(text, lang):
    t = "".join(c for c in unicodedata.normalize("NFKD", text) if not _is_emoji(c) and c not in "♥☆♡©\\")
    for a, b in _REPLACE + _TIDY:
        t = t.replace(a, b)
    t = " ".join(t.split())
    if not t.endswith(_ENDINGS):
        t += "."
    return f"<{lang}>{t}</{lang}>"


def _sentences(p):
    out, cur = [], ""
    for i, c in enumerate(p):
        cur += c
        nxt = p[i + 1] if i + 1 < len(p) else None
        if c in ".!?。！？" and (nxt is None or nxt.isspace()):
            words = cur.split()
            last = words[-1] if words else ""
            initial = len(last) == 2 and last[0].isascii() and last[0].isupper()
            if c != "." or not (last in _ABBREV or initial):
                out.append(cur.strip())
                cur = ""
    if cur.strip():
        out.append(cur.strip())
    return out


def chunk_text(text, max_len):
    chunks = []

    def push_long(s):
        cur = ""
        for w in s.split():
            if cur and len(cur) + 1 + len(w) > max_len:
                chunks.append(cur)
                cur = ""
            cur = f"{cur} {w}" if cur else w
        if cur:
            chunks.append(cur)

    for para in (p.strip() for p in text.replace("\r\n", "\n").split("\n\n")):
        if not para:
            continue
        cur = ""
        for s in _sentences(para.replace("\n", " ")):
            if not cur:
                cur = s
            elif len(cur) + 1 + len(s) <= max_len:
                cur += " " + s
            else:
                push_long(cur)
                cur = s
        if cur:
            push_long(cur)
    return chunks


# -------------------------------------------------------------------- noise

def _hash(parts):
    h = 0xCBF29CE484222325
    for p in parts:
        for b in list(p.encode("utf-8")) + [0xFF]:
            h ^= b
            h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _noise(seed, n):
    """Deterministic standard normals: same text + voice + speed -> same audio."""
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


# -------------------------------------------------------------------- model

class Model:
    def __init__(self, model_dir):
        import onnxruntime as ort

        self.dir = model_dir
        onnx = os.path.join(model_dir, "onnx")
        with open(os.path.join(onnx, "tts.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.sample_rate = int(cfg["ae"]["sample_rate"])
        self.base_chunk_size = int(cfg["ae"]["base_chunk_size"])
        self.chunk_compress = int(cfg["ttl"]["chunk_compress_factor"])
        self.latent_dim = int(cfg["ttl"]["latent_dim"])
        with open(os.path.join(onnx, "unicode_indexer.json"), encoding="utf-8") as f:
            idx = json.load(f)
        if isinstance(idx, dict):
            size = max(int(k) for k in idx) + 1
            arr = np.full(size, -1, dtype=np.int64)
            for k, v in idx.items():
                arr[int(k)] = v
            idx = arr
        self.indexer = np.asarray(idx, dtype=np.int64)

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = min(os.cpu_count() or 4, 8)
        prov = ["CPUExecutionProvider"]

        def load(name):
            return ort.InferenceSession(os.path.join(onnx, name), sess_options=opts, providers=prov)

        self.dp = load("duration_predictor.onnx")
        self.text_enc = load("text_encoder.onnx")
        self.vector_est = load("vector_estimator.onnx")
        self.vocoder = load("vocoder.onnx")
        self._styles = {}

    def _style(self, voice):
        if voice not in VOICES:
            raise ValueError(f"Unknown Supertonic voice '{voice}'. Voices: {', '.join(VOICES)}")
        if voice not in self._styles:
            with open(os.path.join(self.dir, "voice_styles", voice + ".json"), encoding="utf-8") as f:
                j = json.load(f)

            def tensor(v):
                return np.asarray(v["data"], dtype=np.float32).reshape(v["dims"])

            self._styles[voice] = (tensor(j["style_ttl"]), tensor(j["style_dp"]))
        return self._styles[voice]

    def synthesize(self, text, voice, lang="en", speed=1.0, steps=DEFAULT_STEPS):
        if lang not in LANGS:
            raise ValueError(f"Supertonic does not speak '{lang}'. It supports: {', '.join(LANGS)}")
        ttl, dp = self._style(voice)
        chunks = chunk_text(text, 120 if lang in ("ko", "ja") else 300)
        if not chunks:
            raise ValueError("Nothing to say: the line is empty.")
        seed = _hash([text, lang, voice, f"{speed:.3f}"])
        gap = np.zeros(int(CHUNK_GAP_S * self.sample_rate), dtype=np.float32)
        parts = []
        for i, c in enumerate(chunks):
            if i:
                parts.append(gap)
            parts.append(self._infer(preprocess(c, lang), ttl, dp, speed * BASE_SPEED,
                                     max(1, steps), seed + i))
        return np.concatenate(parts), self.sample_rate

    def _infer(self, text, ttl, dp, speed, steps, seed):
        cps = np.array([ord(c) for c in text], dtype=np.int64)
        ids = np.where(cps < len(self.indexer), self.indexer[np.minimum(cps, len(self.indexer) - 1)], -1)
        ids = ids.reshape(1, -1).astype(np.int64)
        n = ids.shape[1]
        mask = np.ones((1, 1, n), dtype=np.float32)

        dur = self.dp.run(["duration"], {"text_ids": ids, "style_dp": dp, "text_mask": mask})[0]
        duration = max(float(np.ravel(dur)[0]) / speed, 0.05)
        emb = self.text_enc.run(["text_emb"], {"text_ids": ids, "style_ttl": ttl, "text_mask": mask})[0]

        wav_len = int(duration * self.sample_rate)
        chunk = self.base_chunk_size * self.chunk_compress
        latent_len = max(1, math.ceil(wav_len / chunk))
        dim = self.latent_dim * self.chunk_compress
        xt = _noise(seed, dim * latent_len).reshape(1, dim, latent_len)
        latent_mask = np.ones((1, 1, latent_len), dtype=np.float32)
        total = np.array([steps], dtype=np.float32)
        for step in range(steps):
            xt = self.vector_est.run(["denoised_latent"], {
                "noisy_latent": xt, "text_emb": emb, "style_ttl": ttl, "latent_mask": latent_mask,
                "text_mask": mask, "current_step": np.array([step], dtype=np.float32),
                "total_step": total,
            })[0].astype(np.float32)
        wav = self.vocoder.run(["wav_tts"], {"latent": xt})[0]
        return np.ravel(wav)[:wav_len].astype(np.float32)
