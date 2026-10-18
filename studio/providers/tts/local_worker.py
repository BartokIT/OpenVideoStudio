"""Local TTS worker — runs inside the isolated voices environment
(studio/voices/env, created by core/voices.py), never in the editor's own
venv: Kokoro and Chatterbox need PyTorch and pin libraries the editor
doesn't use.

Protocol: one JSON request per line on stdin, one JSON reply per line on
stdout. Everything the libraries print goes to stderr so stdout stays a
clean channel. Models are loaded on first use and kept in memory until the
process exits (the editor stops it when idle, freeing the GPU).

    {"engine": "kokoro", "text": "...", "language": "it", "voice": "if_sara", "out": "C:/.../x.wav"}
    -> {"ok": true, "out": "...", "duration": 4.2}
    {"cmd": "ping"} -> {"ok": true, "engines": {"kokoro": true, "chatterbox": false}, "device": "cuda"}
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback

_reply = sys.stdout
sys.stdout = sys.stderr          # library chatter must not corrupt the reply channel

KOKORO_LANG = {"en": "a", "it": "i", "es": "e", "fr": "f", "pt": "p"}   # misaki language codes
SAMPLE_RATE = {"kokoro": 24000}
_models: dict = {}


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _kokoro(language: str, voice: str):
    from kokoro import KPipeline
    code = KOKORO_LANG.get(language, "a")
    if language == "en" and voice.startswith("b"):    # bf_/bm_ voices are British English
        code = "b"
    key = ("kokoro", code)
    if key not in _models:
        _models[key] = KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M", device=_device())
    return _models[key]


def _chatterbox():
    if "chatterbox" not in _models:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _models["chatterbox"] = ChatterboxMultilingualTTS.from_pretrained(device=_device())
    return _models["chatterbox"]


def synthesize(req: dict) -> dict:
    import numpy as np
    import soundfile as sf

    engine, text, language = req["engine"], req["text"].strip(), req.get("language") or "en"
    voice, out = req.get("voice") or "", req["out"]
    if engine == "kokoro":
        pipe = _kokoro(language, voice or "af_heart")
        parts = [a.numpy() if hasattr(a, "numpy") else np.asarray(a) for _, _, a in pipe(text, voice=voice or "af_heart")]
        audio, sr = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32), 24000
    elif engine == "chatterbox":
        model = _chatterbox()
        kwargs = {"language_id": language}
        if voice and voice != "default":
            kwargs["audio_prompt_path"] = voice            # a voice sample to clone
        if "exaggeration" in req:
            kwargs["exaggeration"] = float(req["exaggeration"])
        wav = model.generate(text, **kwargs)
        audio, sr = wav.squeeze(0).detach().cpu().numpy(), model.sr
    else:
        raise ValueError(f"Unknown engine {engine!r}")
    sf.write(out, audio, sr)
    return {"ok": True, "out": out, "duration": round(len(audio) / sr, 3)}


def ping() -> dict:
    engines = {"kokoro": importlib.util.find_spec("kokoro") is not None,
               "chatterbox": importlib.util.find_spec("chatterbox") is not None}
    return {"ok": True, "engines": engines, "device": _device()}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            res = ping() if req.get("cmd") == "ping" else synthesize(req)
        except Exception as e:  # reported to the editor, the worker keeps running
            traceback.print_exc()
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        _reply.write(json.dumps(res) + "\n")
        _reply.flush()


if __name__ == "__main__":
    main()
