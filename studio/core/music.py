"""Music presets for Media Remix.

A preset is a background track plus the settings that suit it (music
volume, cut-on-beat). Two sources:

* built-in tracks, synthesised locally with numpy on first use into
  assets/music/generated/ (no download, no licence to worry about: they are
  simple generative pieces, one per mood);
* the user's own files dropped into assets/music/ (mp3/wav/m4a/ogg/flac),
  optionally described in assets/music/library.toml:

      [[track]]
      file = "piano_memories.mp3"
      title = "Piano memories"
      mood = "nostalgic"        # nostalgic | cinematic | romantic | upbeat | energetic | calm
      volume = 0.3
      beat_sync = false

"Auto — match the look" picks the first track whose mood matches the look.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np

MOODS = ("nostalgic", "cinematic", "romantic", "upbeat", "energetic", "calm")

LOOK_MOOD = {
    "family_memory": "nostalgic", "vintage": "nostalgic", "cinematic": "cinematic", "black_white": "cinematic",
    "wedding": "romantic", "travel": "upbeat", "dynamic": "energetic", "clean": "calm",
}

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
SR = 44100
TRACK_SECONDS = 150.0


@dataclass(frozen=True)
class Track:
    key: str
    title: str
    mood: str
    path: Optional[str]        # None until a built-in track has been generated
    volume: float = 0.3
    beat_sync: bool = False
    builtin: bool = False
    bpm: float = 0.0
    attribution: str = ""      # credit line required by the track's licence (downloaded tracks)
    page_url: str = ""
    creator: str = ""
    sync: str = "bars"         # suggested way cuts follow this track (audio.SYNC_MODES)


# how cuts should follow the music, by mood: slow pieces cut on the bar,
# lively ones on the accents, rhythmic ones follow the energy too
MOOD_SYNC = {"nostalgic": "bars", "cinematic": "bars", "romantic": "bars", "calm": "bars",
             "upbeat": "accents", "energetic": "follow"}

# --------------------------------------------------------------- catalogue

BUILTIN: dict[str, dict] = {
    "gentle_piano": dict(title="Gentle piano", mood="nostalgic", volume=0.30, beat_sync=True, bpm=76,
                         key=60, progression=[(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")], style="arp"),
    "warm_strings": dict(title="Warm strings", mood="cinematic", volume=0.28, beat_sync=True, bpm=60,
                         key=62, progression=[(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")], style="pad"),
    "first_dance": dict(title="First dance", mood="romantic", volume=0.30, beat_sync=True, bpm=66,
                        key=65, progression=[(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")], style="waltz"),
    "sunny_strum": dict(title="Sunny strum", mood="upbeat", volume=0.32, beat_sync=True, bpm=112,
                        key=67, progression=[(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")], style="strum"),
    "soft_beat": dict(title="Soft beat", mood="energetic", volume=0.35, beat_sync=True, bpm=100,
                      key=57, progression=[(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")], style="beat"),
    "quiet_air": dict(title="Quiet air", mood="calm", volume=0.25, beat_sync=True, bpm=56,
                      key=64, progression=[(0, "maj"), (5, "maj"), (9, "min"), (7, "maj")], style="air"),
}


def _sync_for(meta: dict, mood: str) -> str:
    s = str(meta.get("sync") or "")
    return s if s in ("nudge", "beats", "bars", "accents", "follow") else MOOD_SYNC.get(mood, "bars")


def _generated_path(assets_dir: Path, key: str) -> Optional[Path]:
    gen = Path(assets_dir) / "generated"
    for ext in (".m4a", ".wav"):
        p = gen / f"{key}{ext}"
        if p.exists():
            return p
    return None


def library(assets_dir: Path) -> list[Track]:
    """Built-in presets first (in mood order), then the user's files."""
    assets_dir = Path(assets_dir)
    tracks: list[Track] = []
    for key, spec in BUILTIN.items():
        p = _generated_path(assets_dir, key)
        tracks.append(Track(key=key, title=spec["title"], mood=spec["mood"], path=str(p) if p else None,
                            volume=spec["volume"], beat_sync=spec["beat_sync"], builtin=True, bpm=spec["bpm"],
                            sync=MOOD_SYNC.get(spec["mood"], "bars")))

    meta: dict[str, dict] = {}
    toml_path = assets_dir / "library.toml"
    if toml_path.exists():
        try:
            import tomllib
            for t in tomllib.loads(toml_path.read_text(encoding="utf-8")).get("track", []):
                if t.get("file"):
                    meta[t["file"].lower()] = t
        except Exception:
            meta = {}

    if assets_dir.exists():
        for f in sorted(assets_dir.iterdir(), key=lambda p: p.name.lower()):
            if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
                continue
            m = meta.get(f.name.lower(), {})
            mood = m.get("mood", "nostalgic")
            tracks.append(Track(
                key=f"file:{f.name}", title=m.get("title", f.stem.replace("_", " ")),
                mood=mood if mood in MOODS else "nostalgic", path=str(f),
                volume=float(m.get("volume", 0.3)), beat_sync=bool(m.get("beat_sync", True)),
                attribution=str(m.get("attribution", "")), creator=str(m.get("creator", "")),
                sync=_sync_for(m, mood),
            ))

    # tracks fetched by core/music_online.py: audio file + JSON sidecar
    downloads = assets_dir / "downloads"
    if downloads.exists():
        for f in sorted(downloads.iterdir(), key=lambda p: p.name.lower()):
            if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
                continue
            side = f.with_suffix(".json")
            try:
                m = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
            except (OSError, json.JSONDecodeError):
                m = {}
            mood = m.get("mood", "nostalgic")
            tracks.append(Track(
                key=f"dl:{f.name}", title=m.get("title", f.stem), mood=mood if mood in MOODS else "nostalgic",
                path=str(f), volume=float(m.get("volume", 0.3)), beat_sync=bool(m.get("beat_sync", True)),
                attribution=str(m.get("attribution", "")), page_url=str(m.get("page_url", "")),
                creator=str(m.get("creator", "")), sync=_sync_for(m, mood),
            ))
    return tracks


def by_key(tracks: list[Track], key: str) -> Optional[Track]:
    return next((t for t in tracks if t.key == key), None)


def pick_for_look(look_key: str, tracks: list[Track]) -> Optional[Track]:
    mood = LOOK_MOOD.get(look_key, "nostalgic")
    return next((t for t in tracks if t.mood == mood), tracks[0] if tracks else None)


def ensure_track(track: Track, assets_dir: Path, progress: Optional[Callable[[float, str], None]] = None) -> Track:
    """Returns the track with a real path, synthesising a built-in one on
    first use (a few seconds, cached in assets/music/generated/)."""
    if track.path and Path(track.path).exists():
        return track
    if not track.builtin:
        raise FileNotFoundError(track.path or track.key)
    gen = Path(assets_dir) / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    wav = gen / f"{track.key}.wav"
    if progress:
        progress(0.1, f"Composing “{track.title}”")
    synthesize(track.key, wav)
    out = _encode_aac(wav)
    if progress:
        progress(1.0, f"“{track.title}” ready")
    return replace(track, path=str(out))


def _encode_aac(wav: Path) -> Path:
    m4a = wav.with_suffix(".m4a")
    try:
        proc = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "160k", str(m4a)],
                              capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode == 0 and m4a.exists() and m4a.stat().st_size > 1000:
            wav.unlink(missing_ok=True)
            return m4a
    except OSError:
        pass
    return wav


# ---------------------------------------------------------------- synthesis

def _midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def _chord_notes(root: int, kind: str) -> list[int]:
    return [root, root + (3 if kind == "min" else 4), root + 7]


def _pluck(freq: float, seconds: float, rng: np.random.Generator, bright: float = 1.0, amp: float = 1.0) -> np.ndarray:
    """Piano/guitar-like tone: harmonics with increasingly fast decay."""
    n = int(seconds * SR)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, np.float32)
    for k in range(1, 9):
        f = freq * k * (1 + 0.0004 * k * k)  # slight inharmonicity
        if f > SR / 2.2:
            break
        decay = 1.6 + 0.9 * k * bright
        out += (amp / k ** 1.2) * np.exp(-decay * t) * np.sin(2 * np.pi * f * t + rng.uniform(0, 0.4))
    attack = min(int(0.004 * SR), n)
    out[:attack] *= np.linspace(0, 1, attack, dtype=np.float32)
    return out


def _pad_chord(freqs: list[float], seconds: float, attack: float, release: float, amp: float = 1.0) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros(n, np.float32)
    for f in freqs:
        for det in (-0.25, 0.0, 0.25):  # detuned voices
            ff = f * 2 ** (det / 100)
            for k, w in ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.1)):
                out += amp * w / 3 * np.sin(2 * np.pi * ff * k * t)
    env = np.ones(n, np.float32)
    a = min(int(attack * SR), n)
    r = min(int(release * SR), n)
    env[:a] = np.linspace(0, 1, a, dtype=np.float32) ** 2
    env[n - r:] *= np.linspace(1, 0, r, dtype=np.float32) ** 2
    return out * env


def _kick(rng) -> np.ndarray:
    n = int(0.32 * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = 42 + 110 * np.exp(-t * 28)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)).astype(np.float32)


def _hat(rng, seconds: float = 0.05, amp: float = 0.35) -> np.ndarray:
    n = int(seconds * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    noise = np.diff(noise, prepend=0.0)  # crude high-pass
    return amp * noise * np.exp(-np.arange(n, dtype=np.float32) / SR * 70)


def _reverb(x: np.ndarray, mix: float = 0.25) -> np.ndarray:
    from scipy.signal import lfilter

    wet = np.zeros_like(x)
    for delay_ms, g in ((29.7, 0.72), (37.1, 0.68), (41.1, 0.64), (53.3, 0.6)):
        d = int(delay_ms / 1000 * SR)
        a = np.zeros(d + 1, np.float32)
        a[0], a[-1] = 1.0, -g
        wet += lfilter([1.0], a, x).astype(np.float32)
    wet /= 4
    return (1 - mix) * x + mix * wet


def _add(buf: np.ndarray, sig: np.ndarray, at: float) -> None:
    i = int(at * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i]


def synthesize(key: str, out_wav: Path, seconds: float = TRACK_SECONDS, seed: int = 11) -> Path:
    """Writes a stereo 16-bit WAV for one of the BUILTIN presets."""
    from scipy.io import wavfile

    spec = BUILTIN[key]
    rng = np.random.default_rng(seed)
    bpm, root, prog, style = spec["bpm"], spec["key"], spec["progression"], spec["style"]
    beat = 60.0 / bpm
    beats_per_bar = 3 if style == "waltz" else 4
    bar = beat * beats_per_bar
    n = int(seconds * SR)
    mel = np.zeros(n, np.float32)
    pad = np.zeros(n, np.float32)
    drums = np.zeros(n, np.float32)
    bass = np.zeros(n, np.float32)

    t = 0.0
    bar_i = 0
    while t < seconds:
        deg, kind = prog[bar_i % len(prog)]
        chord = _chord_notes(root + deg, kind)
        freqs = [_midi(c) for c in chord]
        low = _midi(chord[0] - 12)

        if style in ("pad", "air", "waltz", "beat", "arp"):
            amp = {"pad": 0.22, "air": 0.16, "waltz": 0.12, "beat": 0.14, "arp": 0.10}[style]
            _add(pad, _pad_chord([f / 2 for f in freqs], bar * 1.05, attack=bar * 0.35, release=bar * 0.4, amp=amp), t)

        if style == "arp":
            pattern = [0, 1, 2, 1, 0, 2, 1, 2]
            for k, p in enumerate(pattern):
                if rng.random() < 0.08:
                    continue
                f = freqs[p] * (2 if k % 4 == 3 else 1)
                _add(mel, _pluck(f, 2.2, rng, bright=1.0, amp=0.35), t + k * beat / 2)
            _add(mel, _pluck(low, bar, rng, bright=0.5, amp=0.28), t)
        elif style == "waltz":
            _add(mel, _pluck(low, beat * 1.5, rng, bright=0.5, amp=0.34), t)
            for k in (1, 2):
                for f in freqs:
                    _add(mel, _pluck(f, beat, rng, bright=1.2, amp=0.16), t + k * beat + rng.uniform(0, 0.015))
            if bar_i % 2 == 1:
                _add(mel, _pluck(freqs[rng.integers(0, 3)] * 2, 1.6, rng, amp=0.2), t + beat * 2.5)
        elif style == "strum":
            for k in range(beats_per_bar * 2):
                if k in (0, 3, 4, 6):
                    down = k % 2 == 0
                    order = freqs if down else freqs[::-1]
                    for j, f in enumerate(order):
                        _add(mel, _pluck(f * (2 if not down else 1), 0.9, rng, bright=1.6, amp=0.2),
                             t + k * beat / 2 + j * 0.018)
                _add(drums, _hat(rng, 0.07, 0.12), t + k * beat / 2)
            _add(mel, _pluck(low, beat * 2, rng, bright=0.4, amp=0.26), t)
        elif style == "beat":
            for k in range(beats_per_bar):
                _add(drums, _kick(rng) * 0.9, t + k * beat)
                _add(drums, _hat(rng, 0.05, 0.3), t + k * beat + beat / 2)
                if k in (1, 3):
                    _add(drums, _hat(rng, 0.12, 0.22), t + k * beat)
            for k in range(beats_per_bar * 2):
                _add(bass, _pluck(low, beat * 0.6, rng, bright=0.3, amp=0.5 if k % 2 == 0 else 0.3), t + k * beat / 2)
            for k in (0, 3, 6):
                _add(mel, _pluck(freqs[(k // 3) % 3] * 2, 1.0, rng, amp=0.18), t + k * beat / 2)
        elif style == "pad":
            _add(bass, _pad_chord([low / 2], bar * 1.05, attack=bar * 0.4, release=bar * 0.4, amp=0.2), t)
            if bar_i % 4 == 3:
                _add(mel, _pluck(freqs[2] * 2, 3.0, rng, bright=0.8, amp=0.14), t + beat * 2)
        elif style == "air":
            if bar_i % 2 == 0:
                _add(mel, _pluck(freqs[rng.integers(0, 3)] * 2, 4.0, rng, bright=0.6, amp=0.16), t + beat * rng.integers(0, 3))

        t += bar
        bar_i += 1

    mix = mel + pad + drums + bass
    mix = _reverb(mix, mix=0.22 if style in ("beat", "strum") else 0.32)
    # gentle fade in/out at the loop points (mix_bgm loops the file)
    fade = int(1.5 * SR)
    mix[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / peak * 0.85
    # stereo: slight delay on the right channel for width
    d = int(0.011 * SR)
    right = np.concatenate([mix[:d] * 0, mix[:-d]])
    stereo = np.stack([0.85 * mix + 0.15 * right, 0.85 * right + 0.15 * mix], axis=1)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(out_wav), SR, (np.clip(stereo, -1, 1) * 32767).astype(np.int16))
    return out_wav


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate the built-in music presets")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "assets" / "music")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    for k in (args.only or BUILTIN):
        tr = ensure_track(by_key(library(args.out), k), args.out, lambda f, m: print(m))
        print(k, "->", tr.path)
