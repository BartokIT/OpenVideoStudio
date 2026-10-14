"""BGM mixing with fades and beat-aligned shot durations.

The amix filter_complex pattern (original vol 1.0, BGM vol 0.25, amix
duration=first dropout_transition=3, BGM looped via -stream_loop -1,
video stream copied not re-encoded) is carried over from an earlier
private prototype of this mixing logic.

New for V1 (not present in that earlier prototype): fade-in/out on the BGM
track, and librosa beat detection used to nudge shot durations so cuts
land near a beat. Ducking (sidechain compression of the music under the
original/narration track) and EBU R128 loudness normalisation are on by
default; [audio] duck / loudnorm in config.toml turn them off.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import librosa


@dataclass
class AudioConfig:
    original_volume: float = 1.0
    bgm_volume: float = 0.25
    fade_seconds: float = 2.0
    amix_dropout_transition: float = 3.0
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    duck: bool = True
    loudnorm: bool = True

    @classmethod
    def from_toml(cls, path: Path) -> "AudioConfig":
        import tomllib
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        a = data.get("audio", {})
        enc = data.get("encode", {})
        return cls(
            original_volume=a.get("original_volume", 1.0), bgm_volume=a.get("bgm_volume", 0.25),
            fade_seconds=a.get("fade_seconds", 2.0), amix_dropout_transition=a.get("amix_dropout_transition", 3.0),
            audio_codec=enc.get("audio_codec", "aac"), audio_bitrate=enc.get("audio_bitrate", "192k"),
            duck=a.get("duck", True), loudnorm=a.get("loudnorm", True),
        )


def _run(cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    return ok, (proc.stderr[-4000:] if not ok else "")


def _video_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def load_mono(path: Path, sr: int = 22050, max_seconds: float = 900.0):
    """Decodes any audio file ffmpeg understands (mp3, m4a, ogg, flac, wav…)
    to a float32 mono numpy array at sr. librosa/soundfile alone cannot
    open m4a/aac, which is what the built-in presets are encoded as."""
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-t", f"{max_seconds:.1f}", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode == 0 and len(proc.stdout) >= 4 * sr // 10:
        return np.frombuffer(proc.stdout, dtype=np.float32).copy(), sr
    y, sr2 = librosa.load(str(path), sr=sr, mono=True, duration=max_seconds)
    return y, sr2


def detect_beats(bgm_path: Path) -> list[float]:
    y, sr = load_mono(Path(bgm_path), sr=22050)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    return [round(float(t), 3) for t in beat_times]


RHYTHM_VERSION = 3


def analyze_rhythm(path: Path, sr: int = 22050) -> dict:
    """Musical structure used to cut to the music:

    tempo / beat      BPM and seconds per beat
    beats             every beat (s)
    meter, downbeats  3 or 4 beats per bar and the first beat of each bar,
                      picked as the beat phase with the strongest onsets
    accents           strong hits (onsets in the top part of the onset
                      strength), with a 0..1 strength, snapped to a beat
                      when they are within 80 ms of one
    energy            loudness curve, 0..1, one value every energy_step s
    duration          length of the file (the mix loops it)
    """
    import numpy as np

    y, sr = load_mono(Path(path), sr=sr)
    duration = len(y) / sr
    hop = 512
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop)
    beat_frames = np.asarray(beat_frames, dtype=int)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    tempo = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 0.0
    beat = float(np.median(np.diff(beats))) if len(beats) >= 2 else (60.0 / tempo if tempo else 0.5)

    def strength_at(frames):
        out = []
        for f in frames:
            a, b = max(int(f) - 2, 0), min(int(f) + 3, len(oenv))
            out.append(float(oenv[a:b].max()) if b > a else 0.0)
        return np.asarray(out, dtype=np.float32)

    # Busy accompaniments (arpeggios, strumming eighths) make the tracker lock
    # to double time: above 135 BPM keep every other beat, on the stronger phase.
    if tempo > 135 and len(beat_frames) >= 8:
        bstr = strength_at(beat_frames)
        ph = 0 if bstr[0::2].mean() >= bstr[1::2].mean() else 1
        beat_frames = beat_frames[ph::2]
        beats = beats[ph::2]
        tempo /= 2
        beat *= 2

    meter, phase = 4, 0
    if len(beats) >= 8:
        bstr = strength_at(beat_frames)
        base = float(bstr.mean()) + 1e-9
        best = -1.0
        for m in (4, 3):
            for p in range(m):
                sel = bstr[p::m]
                if len(sel) < 2:
                    continue
                score = float(sel.mean()) / base * (0.97 if m == 3 else 1.0)
                if score > best:
                    best, meter, phase = score, m, p
    downbeats = beats[phase::meter] if len(beats) else beats

    onset_frames = librosa.onset.onset_detect(onset_envelope=oenv, sr=sr, hop_length=hop, units="frames")
    accents: list[list[float]] = []
    if len(onset_frames):
        # an accent is a hit clearly above the track's typical onset: strength
        # 0 at the 60th percentile, 1 at the 98th; roughly the top quarter survives
        ostr = oenv[onset_frames]
        p60, p98 = float(np.percentile(ostr, 60)), float(np.percentile(ostr, 98))
        span = max(p98 - p60, 1e-6)
        times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
        for t, s in zip(times, ostr):
            s = min(max((float(s) - p60) / span, 0.0), 1.0)
            if s < 0.35:
                continue
            if len(beats):
                k = int(np.argmin(np.abs(beats - t)))
                if abs(beats[k] - t) <= 0.08:
                    t = beats[k]
            accents.append([round(float(t), 3), round(s, 2)])
        dedup: dict = {}
        for t, s in accents:
            dedup[t] = max(s, dedup.get(t, 0.0))
        accents = [[t, s] for t, s in sorted(dedup.items())]

    step = 0.5
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    per = max(int(step * sr / hop), 1)
    blocks = [float(rms[i:i + per].mean()) for i in range(0, len(rms), per)] or [0.0]
    arr = np.asarray(blocks, dtype=np.float32)
    lo, hi = float(np.percentile(arr, 5)), float(np.percentile(arr, 95))
    norm = np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1)
    if len(norm) >= 5:  # ~2 s smoothing so the pacing breathes instead of jittering
        norm = np.convolve(norm, np.ones(5) / 5, mode="same")

    return {
        "version": RHYTHM_VERSION, "tempo": round(tempo, 2), "beat": round(beat, 4), "meter": int(meter),
        "beats": [round(float(t), 3) for t in beats],
        "downbeats": [round(float(t), 3) for t in downbeats],
        "accents": accents, "energy": [round(float(v), 3) for v in norm], "energy_step": step,
        "duration": round(duration, 3),
    }


SYNC_MODES = ("nudge", "beats", "bars", "accents", "follow")


def _loop_times(times, period: float, until: float) -> list:
    """The mix loops the music file: repeat its event times every period."""
    if not times:
        return []
    if not period or period <= 0:
        return [t for t in times if t <= until]
    out, k = [], 0
    while k * period <= until:
        for t in times:
            v = t + k * period
            if v > until:
                break
            out.append(round(v, 3))
        k += 1
    return out


def align_plan_to_music(plan: dict, rhythm: dict, mode: str = "bars",
                        min_holds: Optional[dict] = None) -> dict:
    """Moves every cut onto the music. Unlike align_plan_to_beats (kept as
    the gentle "nudge" mode) the music decides where cuts go:

    beats    each cut on the beat nearest to the planned length
    bars     cuts on the first beat of a bar (falls back to a beat)
    accents  cuts prefer strong hits, even a beat or two away
    follow   like accents, and shot lengths follow the music's energy:
             loud passages cut faster, quiet ones linger

    Video clips are never stretched past their source; min_holds (shot_id
    -> seconds, for shots carrying titles) are respected so the timeline
    builder never has to lengthen a shot afterwards and push the following
    cuts off the beat. Shots with "duration_locked" (set by the user) keep
    their length, rounded to the nearest beat. Returns a new plan."""
    import bisect

    mode = mode if mode in SYNC_MODES else "bars"
    beats = rhythm.get("beats") or []
    if mode == "nudge":
        return align_plan_to_beats(plan, beats)
    if len(beats) < 4:
        return plan
    beat = float(rhythm.get("beat") or (beats[-1] - beats[0]) / max(len(beats) - 1, 1))
    min_holds = min_holds or {}
    shots = [dict(s) for s in plan["shots"]]
    enabled = [s for s in shots if s.get("enabled")]
    if not enabled:
        return plan
    until = sum(float(s["duration"]) for s in enabled) * 1.7 + 30.0
    period = float(rhythm.get("duration") or 0.0)
    beat_g = _loop_times(beats, period, until)
    down_g = set(_loop_times(rhythm.get("downbeats") or [], period, until))
    acc_g: dict = {}
    raw_acc = rhythm.get("accents") or []
    for t, s in zip(_loop_times([a[0] for a in raw_acc], period, until),
                    [a[1] for a in raw_acc] * (int(until // period) + 2 if period else 1)):
        acc_g[t] = max(s, acc_g.get(t, 0.0))
    energy = rhythm.get("energy") or []
    estep = float(rhythm.get("energy_step") or 0.5)

    def energy_at(t: float) -> float:
        if not energy:
            return 0.5
        if period:
            t = t % period
        return float(energy[min(int(t / estep), len(energy) - 1)])

    # candidate cut points and how attractive each one is
    cands: dict = {}
    if mode == "beats":
        for t in beat_g:
            cands[t] = 0.3 if t in down_g else 0.0
    elif mode == "bars":
        # only downbeats; plain beats are a fallback used when no bar line
        # falls inside the allowed window (see the loop below)
        for t in beat_g:
            cands[t] = 0.3 * acc_g.get(t, 0.0) if t in down_g else None
    else:  # accents / follow
        for t in beat_g:
            cands[t] = (0.25 if t in down_g else 0.0) + 1.2 * acc_g.get(t, 0.0)
        for t, s in acc_g.items():
            cands.setdefault(t, 1.2 * s)
    times = sorted(cands)

    t = 0.0
    for i, s in enumerate(enabled):
        d0 = float(s["duration"])
        is_video = s.get("type") == "video"
        locked = bool(s.get("duration_locked"))
        d = d0
        if mode == "follow" and not locked and not is_video:
            d = d0 * (1.4 - 0.8 * energy_at(t + d0 / 2))   # quiet 1.4x … loud 0.6x
        min_d = max(float(min_holds.get(s["shot_id"], 0.0)), 1.0 if is_video else 1.2, 0.6 * beat)
        if is_video:
            min_d = min(min_d, d0)
        target = t + max(d, min_d)
        lo = t + min_d
        hi = t + d0 if is_video else t + max(d * 1.6, d + 2 * beat, min_d + 2 * beat)
        chapter_end = i + 1 < len(enabled) and enabled[i + 1].get("chapter_id") != s.get("chapter_id")
        window = times[bisect.bisect_left(times, lo - 1e-6):bisect.bisect_right(times, hi + 1e-6)]
        if locked:
            pool = [(c, 0.0) for c in window]
        else:
            pool = [(c, cands[c]) for c in window if cands[c] is not None]
            if not pool:  # bars mode with no bar line in reach: fall back to beats
                pool = [(c, 0.0) for c in window]
        best, best_cost = None, float("inf")
        for c, w in pool:
            if chapter_end and not locked and c in down_g:
                w += 1.2   # a new chapter starts on a bar line
            cost = abs(c - target) / beat - w
            if cost < best_cost:
                best, best_cost = c, cost
        if best is None:
            best = min(target, t + d0) if is_video else target
        s["duration"] = round(best - t, 3)
        s["reason"] = (s.get("reason") or "") + f"+music_{mode}"
        t = best

    new_plan = dict(plan)
    new_plan["shots"] = shots
    new_plan["total_planned_duration"] = round(sum(s["duration"] for s in shots if s.get("enabled")), 2)
    new_plan["beat_aligned"] = True
    new_plan["music"] = {"mode": mode, "beat": round(beat, 4), "tempo": rhythm.get("tempo"),
                         "meter": rhythm.get("meter")}
    return new_plan


def align_plan_to_beats(plan: dict, beat_times: list[float], max_shift: float = 0.6) -> dict:
    """Nudges enabled shots' durations (bounded by max_shift seconds) so the
    cumulative cut points land as close as possible to a detected beat.
    Returns a new plan dict; does not mutate the input."""
    if not beat_times:
        return plan

    shots = [dict(s) for s in plan["shots"]]
    enabled = [s for s in shots if s["enabled"]]

    cursor = 0.0
    for shot in enabled:
        boundary = cursor + shot["duration"]
        nearest = min(beat_times, key=lambda b: abs(b - boundary))
        shift = nearest - boundary
        if abs(shift) <= max_shift:
            shot["duration"] = round(max(shot["duration"] + shift, 0.5), 2)
            shot["reason"] = shot.get("reason", "") + "+beat_aligned"
        cursor += shot["duration"]

    new_plan = dict(plan)
    new_plan["shots"] = shots
    new_plan["total_planned_duration"] = round(sum(s["duration"] for s in shots if s["enabled"]), 2)
    new_plan["beat_aligned"] = True
    return new_plan


def mix_bgm(video_path: Path, bgm_path: Optional[Path], out_path: Path, cfg: Optional[AudioConfig] = None) -> tuple[bool, str]:
    cfg = cfg or AudioConfig()
    video_path, out_path = Path(video_path), Path(out_path)

    if not bgm_path:
        # No BGM selected: just copy through so pipeline.py always has a
        # final.mp4 regardless of whether this stage does real work.
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(out_path)]
        return _run(cmd)

    bgm_path = Path(bgm_path)
    duration = _video_duration(video_path)
    fade_out_start = max(duration - cfg.fade_seconds, 0)

    bgm_chain = (
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={cfg.bgm_volume},"
        f"afade=t=in:st=0:d={cfg.fade_seconds},afade=t=out:st={fade_out_start}:d={cfg.fade_seconds}"
    )
    if cfg.duck:
        # Ducking: the music dips automatically under speech / clip sound
        # (sidechain on the original track) and comes back in between.
        filter_complex = (
            f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={cfg.original_volume},asplit=2[a0][sc];"
            f"{bgm_chain}[a1];"
            f"[a1][sc]sidechaincompress=threshold=0.02:ratio=8:attack=60:release=900[a1d];"
            f"[a0][a1d]amix=inputs=2:duration=first:dropout_transition={cfg.amix_dropout_transition}:normalize=0"
        )
    else:
        filter_complex = (
            f"[0:a]volume={cfg.original_volume}[a0];{bgm_chain}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition={cfg.amix_dropout_transition}:normalize=0"
        )
    if cfg.loudnorm:
        # streaming-platform loudness so every export plays at a consistent level
        filter_complex += ",loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    filter_complex += "[a]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(bgm_path),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", cfg.audio_codec, "-b:a", cfg.audio_bitrate,
        "-shortest",
        str(out_path),
    ]
    return _run(cmd)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mix BGM into a rendered video, with fades")
    parser.add_argument("video", type=Path)
    parser.add_argument("--bgm", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("final.mp4"))
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config.toml")
    args = parser.parse_args()

    cfg = AudioConfig.from_toml(args.config) if args.config.exists() else AudioConfig()
    ok, log = mix_bgm(args.video, args.bgm, args.out, cfg)
    print("OK" if ok else f"FAILED\n{log}")
