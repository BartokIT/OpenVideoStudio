"""Narration voices for Create: the engines, their languages and voices,
installing the local ones, previews and voice samples.

* Edge TTS — Microsoft's online service (the default, nothing to install).
* Kokoro — local, Apache-2.0, 82M parameters: fast on CPU or GPU.
* Chatterbox — local, MIT, needs a GPU: the most expressive, and it can
  clone a voice from a short sample.

The local engines need PyTorch and pin libraries the editor doesn't use,
so they get their own environment (studio/voices/env, created here on
"Install") and run through providers/tts/local_worker.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from providers.tts import local_tts_provider as local

VOICES_DIR = local.VOICES_DIR
ENV_DIR = local.ENV_DIR
SAMPLES_DIR = VOICES_DIR / "samples"
INSTALLED = VOICES_DIR / "installed.json"
SAMPLE_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")

Progress = Optional[Callable[[float, str], None]]


def _c(value, label, hint="") -> dict:
    return {"value": value, "label": label, "hint": hint}


LANGUAGES = [_c("en", "English"), _c("it", "Italian"), _c("es", "Spanish"), _c("fr", "French"),
             _c("de", "German"), _c("pt", "Portuguese")]
LANGUAGE_NAMES = {c["value"]: c["label"] for c in LANGUAGES}

SAMPLE_TEXT = {
    "en": "In the quiet of dusk, a paper boat drifts down the rain-slicked street, carrying a message of hope.",
    "it": "Nel silenzio del tramonto, una barchetta di carta scivola lungo la strada bagnata, portando un messaggio di speranza.",
    "es": "En el silencio del atardecer, un barco de papel navega por la calle mojada, llevando un mensaje de esperanza.",
    "fr": "Dans le calme du crépuscule, un bateau de papier glisse dans la rue mouillée, porteur d'un message d'espoir.",
    "de": "In der Stille der Dämmerung treibt ein Papierboot die regennasse Straße hinab und trägt eine Botschaft der Hoffnung.",
    "pt": "No silêncio do entardecer, um barco de papel desliza pela rua molhada, levando uma mensagem de esperança.",
}

EDGE_VOICES = {
    "en": [_c("en-US-AriaNeural", "Aria (US, female)"), _c("en-US-JennyNeural", "Jenny (US, female)"),
           _c("en-US-GuyNeural", "Guy (US, male)"), _c("en-GB-SoniaNeural", "Sonia (UK, female)"),
           _c("en-GB-RyanNeural", "Ryan (UK, male)")],
    "it": [_c("it-IT-ElsaNeural", "Elsa (female)"), _c("it-IT-IsabellaNeural", "Isabella (female)"),
           _c("it-IT-DiegoNeural", "Diego (male)")],
    "es": [_c("es-ES-ElviraNeural", "Elvira (female)"), _c("es-ES-AlvaroNeural", "Álvaro (male)")],
    "fr": [_c("fr-FR-DeniseNeural", "Denise (female)"), _c("fr-FR-HenriNeural", "Henri (male)")],
    "de": [_c("de-DE-KatjaNeural", "Katja (female)"), _c("de-DE-ConradNeural", "Conrad (male)")],
    "pt": [_c("pt-BR-FranciscaNeural", "Francisca (BR, female)"), _c("pt-BR-AntonioNeural", "Antônio (BR, male)")],
}

KOKORO_VOICES = {
    "en": [_c("af_heart", "Heart (US, female)"), _c("af_bella", "Bella (US, female)"),
           _c("af_nicole", "Nicole (US, female, soft)"), _c("am_michael", "Michael (US, male)"),
           _c("am_fenrir", "Fenrir (US, male)"), _c("bf_emma", "Emma (UK, female)"),
           _c("bm_george", "George (UK, male)")],
    "it": [_c("if_sara", "Sara (female)"), _c("im_nicola", "Nicola (male)")],
    "es": [_c("ef_dora", "Dora (female)"), _c("em_alex", "Alex (male)")],
    "fr": [_c("ff_siwis", "Siwis (female)")],
    "pt": [_c("pf_dora", "Dora (BR, female)"), _c("pm_alex", "Alex (BR, male)")],
}

CHATTERBOX_LANGS = ["en", "it", "es", "fr", "de", "pt"]

TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"   # CUDA 12.8: RTX 20xx … 50xx
SPACY_EN = ("https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl")
# Chatterbox 0.1.7 pins torch 2.6, which has no kernels for RTX 50xx GPUs: it
# is installed without its pins, next to the current PyTorch (verified on
# an RTX 5080 with torch 2.11 + CUDA 12.8). gradio (its demo UI) is skipped.
CHATTERBOX_DEPS = ["librosa==0.11.0", "s3tokenizer", "transformers==5.2.0", "diffusers", "resemble-perth>=1.0.0",
                   "conformer==0.3.2", "safetensors>=0.5.3", "spacy-pkuseg", "pykakasi==2.3.0", "pyloudnorm",
                   "omegaconf"]

ENGINES = {
    "edge_tts": {"label": "Edge TTS", "kind": "online", "licence": "Microsoft service terms",
                 "hint": "Microsoft's online voices: free, nothing to install, the text is sent to Microsoft."},
    "kokoro": {"label": "Kokoro", "kind": "local", "licence": "Apache-2.0",
               "hint": "Local, small (82M) and fast, on CPU or GPU. Natural voices; no voice cloning.",
               "size": "≈ 3 GB with PyTorch"},
    "chatterbox": {"label": "Chatterbox", "kind": "local GPU", "licence": "MIT",
                   "hint": "Local on the GPU, the most expressive. Clones a voice from a 10–20 s sample. "
                           "Adds an inaudible watermark.",
                   "size": "≈ 6 GB with PyTorch and the model"},
}
DEFAULT = {"engine": "edge_tts", "language": "en"}


# ------------------------------------------------------------ catalog

def installed() -> dict:
    try:
        data = json.loads(INSTALLED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    ok = local.env_python().exists()
    return {k: bool(ok and data.get(k)) for k in ("kokoro", "chatterbox")}


def samples() -> list:
    if not SAMPLES_DIR.exists():
        return []
    return [_c(f"sample:{p.name}", f"My voice: {p.stem}") for p in sorted(SAMPLES_DIR.iterdir())
            if p.suffix.lower() in SAMPLE_EXTS]


def voices_for(engine: str, language: str) -> list:
    if engine == "edge_tts":
        return EDGE_VOICES.get(language, [])
    if engine == "kokoro":
        return KOKORO_VOICES.get(language, [])
    if engine == "chatterbox" and language in CHATTERBOX_LANGS:
        return [_c("default", "Default voice")] + samples()
    return []


def has_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


def catalog() -> dict:
    inst = installed()
    engines = []
    for key, e in ENGINES.items():
        engines.append({
            "value": key, **e, "installed": key == "edge_tts" or inst.get(key, False),
            "voices": {lang: voices_for(key, lang) for lang in LANGUAGE_NAMES if voices_for(key, lang)},
        })
    return {"engines": engines, "languages": LANGUAGES, "defaults": DEFAULT, "gpu": has_gpu(),
            "samples_dir": str(SAMPLES_DIR)}


def resolve(engine: Optional[str], language: Optional[str], voice: Optional[str]) -> tuple[str, str, Optional[str]]:
    """A valid (engine, language, voice): unknown values fall back to the
    language's first voice, then to Edge TTS in English."""
    language = language if language in LANGUAGE_NAMES else "en"
    engine = engine if engine in ENGINES else "edge_tts"
    options = voices_for(engine, language)
    if not options:
        engine, options = "edge_tts", voices_for("edge_tts", language)
    values = [v["value"] for v in options]
    return engine, language, voice if voice in values else values[0]


def voice_arg(voice: Optional[str]) -> Optional[str]:
    """What the engine receives: a sample id becomes the sample's path."""
    if voice and voice.startswith("sample:"):
        p = SAMPLES_DIR / Path(voice[7:]).name
        return str(p) if p.exists() else "default"
    return voice


# ------------------------------------------------------------ install

def _run(cmd: list, say: Callable[[float, str], None], lo: float, hi: float, label: str) -> None:
    say(lo, label)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=flags)
    tail = []
    n = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-12:]
        n += 1
        m = re.match(r"(Collecting|Downloading|Installing collected packages:)\s*(\S+)", line)
        if m:
            say(min(hi, lo + (hi - lo) * (1 - 1 / (1 + n / 40))), f"{label} — {m.group(2)[:60]}")
    if proc.wait() != 0:
        raise RuntimeError(f"{label} failed:\n" + "\n".join(tail[-6:]))


def install(engine: str, progress: Progress = None) -> dict:
    """Creates studio/voices/env if needed and installs the engine into it."""
    if engine not in ("kokoro", "chatterbox"):
        raise ValueError(f"{engine} has nothing to install")
    say = progress or (lambda f, m: None)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    py = local.env_python()
    if not py.exists():
        base = getattr(sys, "_base_executable", None) or sys.executable
        _run([base, "-m", "venv", ENV_DIR], say, 0.02, 0.05, "Creating the voices environment")
        _run([py, "-m", "pip", "install", "--upgrade", "pip"], say, 0.05, 0.08, "Updating pip")
    pip = [py, "-m", "pip", "install", "--disable-pip-version-check"]
    torch = [*pip, "torch", "torchaudio"] + (["--index-url", TORCH_CUDA_INDEX] if has_gpu() else [])
    _run(torch, say, 0.08, 0.55, "Installing PyTorch" + (" for your NVIDIA GPU" if has_gpu() else " (CPU)"))
    _run([*pip, "soundfile"], say, 0.55, 0.6, "Installing audio tools")
    if engine == "kokoro":
        _run([*pip, "kokoro==0.9.4", SPACY_EN], say, 0.6, 0.95, "Installing Kokoro")
    else:
        _run([*pip, "--no-deps", "chatterbox-tts==0.1.7"], say, 0.6, 0.65, "Installing Chatterbox")
        _run([*pip, *CHATTERBOX_DEPS], say, 0.65, 0.95, "Installing Chatterbox's libraries")
    try:
        data = json.loads(INSTALLED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[engine] = datetime.now().isoformat(timespec="seconds")
    INSTALLED.write_text(json.dumps(data, indent=2), encoding="utf-8")
    local.WORKER_PROCESS.stop()                 # a running worker would not see the new packages
    say(1.0, f"{ENGINES[engine]['label']} installed — the model downloads on first use")
    return catalog()


# ------------------------------------------------------------ preview / samples

def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s or "")[:40]


def preview(engine: str, language: str, voice: Optional[str], out_dir: Path, progress: Progress = None) -> Path:
    """Speaks the language's sample sentence with this voice (cached)."""
    engine, language, voice = resolve(engine, language, voice)
    say = progress or (lambda f, m: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{engine}_{language}_{_slug(voice)}.mp3"
    sample = SAMPLES_DIR / voice[7:] if voice and voice.startswith("sample:") else None
    if out.exists() and (not sample or not sample.exists() or out.stat().st_mtime > sample.stat().st_mtime):
        return out
    from providers.registry import get_provider
    if engine != "edge_tts" and not installed().get(engine):
        raise RuntimeError(f"{ENGINES[engine]['label']} isn't installed yet.")
    first = engine != "edge_tts" and engine not in local.WORKER_PROCESS._warm
    say(0.1, f"Loading {ENGINES[engine]['label']}" + (" (the first time it downloads the model)" if first else ""))
    res = get_provider("tts", engine).synthesize(SAMPLE_TEXT[language], voice=voice_arg(voice), language=language)
    shutil.move(str(res.audio_path), out)
    say(1.0, "Preview ready")
    return out


def save_sample(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SAMPLE_EXTS:
        raise ValueError(f"Use an audio file ({', '.join(SAMPLE_EXTS)}).")
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SAMPLES_DIR / f"{_slug(Path(filename).stem) or 'voice'}{ext}"
    dest.write_bytes(data)
    return f"sample:{dest.name}"


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)
