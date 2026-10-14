"""Pro render orchestration.

1. prepare   graded photo canvases + faces/landmarks (parallel, cached)
2. timeline  cameras, transitions, text overlays -> timeline.json
3. frames    timeline split into chunks, each rendered by a separate
             worker process (python -m pro.worker) piping RGB frames into
             its own NVENC encoder
4. assemble  chunks stream-copied together, clip audio laid out on the
             timeline (with fades under transitions), muxed -> output.mp4
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import looks as looks_mod
from . import transitions as tr_mod
from . import typography as ty
from .sources import PhotoSource, VideoSource, prepare_photo, probe_video, write_cube_lut
from .timeline import build_timeline, merge_options

CORE_DIR = Path(__file__).resolve().parents[1]
_ENCODER_CACHE: dict = {}


# ------------------------------------------------------------- encoding

def pick_encoder(preferred: str) -> str:
    if preferred in _ENCODER_CACHE:
        return _ENCODER_CACHE[preferred]
    choice = "libx264"
    if "nvenc" in preferred:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2", "-frames:v", "2",
             "-c:v", preferred, "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0:
            choice = preferred
    elif preferred:
        choice = preferred
    _ENCODER_CACHE[preferred] = choice
    return choice


def encoder_args(cfg, codec: str, fps: int) -> list[str]:
    color = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    if "nvenc" in codec:
        v = ["-c:v", codec, "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", str(getattr(cfg, "cq", 19)),
             "-b:v", cfg.bitrate, "-maxrate", cfg.maxrate, "-bufsize", cfg.bufsize,
             "-spatial-aq", "1", "-temporal-aq", "1", "-bf", "3", "-g", str(fps * 2)]
    else:
        v = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-g", str(fps * 2)]
    return v + ["-pix_fmt", "yuv420p"] + color


# ------------------------------------------------------------- renderer

class Renderer:
    """Turns a timeline into frames. Every frame depends only on its time,
    so any frame range can be rendered independently."""

    def __init__(self, tl: dict):
        self.tl = tl
        self.W, self.H, self.fps = tl["width"], tl["height"], tl["fps"]
        self.look = looks_mod.get_look(tl["look"])
        self.shots = tl["shots"]
        self.trans = tl["transitions"]
        self.sources: dict[int, object] = {}
        self.overlays: dict[int, list] = {}
        for ov in tl["overlays"]:
            self.overlays.setdefault(ov["shot"], []).append(ty.overlay_from_dict(ov, self.look, self.W, self.H))
        self.ctx: dict[int, dict] = {}
        self.bar = looks_mod.letterbox_bars(self.W, self.H, self.look.letterbox)

    def _source(self, i: int):
        src = self.sources.get(i)
        if src is None:
            s = self.shots[i]
            src = PhotoSource(s, self.W, self.H) if s["type"] == "image" else VideoSource(s, self.W, self.H, self.fps)
            self.sources[i] = src
        return src

    def _release_before(self, t: float) -> None:
        for i in list(self.sources):
            if self.shots[i]["vis_end"] < t - 0.5:
                self.sources.pop(i).close()

    def shot_frame(self, i: int, t: float) -> np.ndarray:
        f = self._source(i).frame(t)
        f = looks_mod.apply_vignette(f, self.look.vignette)
        for ov in self.overlays.get(i, ()):
            if ov.active(t):
                if not ov._built:
                    ov.avoid = self._face_boxes(i, (ov.start + ov.end) / 2)
                f = ov.draw(f, t)
        return f

    def _face_boxes(self, i: int, t: float) -> list:
        s = self.shots[i]
        if s["type"] != "image":
            return []
        m = self._source(i).matrix(t)
        out = []
        for f in s["photo"].get("faces") or []:
            x0, y0 = m[0, 0] * f["x"] + m[0, 2], m[1, 1] * f["y"] + m[1, 2]
            out.append((x0, y0, x0 + m[0, 0] * f["w"], y0 + m[1, 1] * f["h"]))
        return out

    def frame(self, n: int) -> np.ndarray:
        t = n / self.fps
        self._release_before(t)
        active = [i for i, s in enumerate(self.shots) if s["vis_start"] <= t < s["vis_end"]]
        if not active:
            active = [len(self.shots) - 1] if t >= self.shots[-1]["start"] else [0]

        if len(active) >= 2:
            ia, ib = active[0], active[1]
            tr = self.trans[ia]
            p = (t - tr["start"]) / max(tr["duration"], 1e-3)
            ctx = self.ctx.setdefault(ia, {"seed": tr["seed"]})
            fa = self.shot_frame(ia, t)
            fb = self.shot_frame(ib, t)
            if tr["type"] == "morph":
                ctx["pts_a"] = self._source(ia).landmarks(t)
                ctx["pts_b"] = self._source(ib).landmarks(t)
                sa, sb = self._source(ia), self._source(ib)
                ea = sa.frame_points(t) if hasattr(sa, "frame_points") else None
                eb = sb.frame_points(t) if hasattr(sb, "frame_points") else None
                ctx["extra_a"], ctx["extra_b"] = (ea, eb) if ea is not None and eb is not None else (None, None)
            if tr["type"] == "circle_open":
                ctx["focus_b"] = self._source(ib).focus(t)
            out = tr_mod.apply(tr["type"], fa, fb, p, ctx)
        else:
            out = self.shot_frame(active[0], t)

        if not out.flags.writeable or not out.flags.c_contiguous:
            out = np.ascontiguousarray(out).copy()

        lk = self.look
        if lk.flicker or lk.dust or lk.gate_weave:
            out = looks_mod.apply_film_damage(out, lk, n, self.fps)
        out = looks_mod.apply_grain(out, lk.grain, n)
        out = looks_mod.apply_letterbox(out, self.bar)

        total = self.tl["total"]
        fi, fo = self.tl.get("fade_in", 0.8), self.tl.get("fade_out", 1.5)
        g = 1.0
        if fi > 0 and t < fi:
            g = ty.ease_in_out(t / fi)
        if fo > 0 and t > total - fo:
            g = min(g, ty.ease_in_out((total - t) / fo))
        if g < 0.999:
            out = (out.astype(np.float32) * g).astype(np.uint8)
        return out

    def close(self):
        for s in self.sources.values():
            s.close()
        self.sources.clear()


def render_range(tl: dict, f0: int, f1: int, out_path: Path, enc: list[str], progress_path: Optional[Path] = None) -> tuple[bool, str]:
    W, H, fps = tl["width"], tl["height"], tl["fps"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic", *enc, str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    r = Renderer(tl)
    try:
        for n in range(f0, f1):
            proc.stdin.write(r.frame(n).tobytes())
            if progress_path and (n - f0) % 10 == 0:
                progress_path.write_text(str(n - f0), encoding="ascii")
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    finally:
        r.close()
    if progress_path:
        progress_path.write_text(str(f1 - f0), encoding="ascii")
    return proc.returncode == 0, err[-3000:]


# ---------------------------------------------------------------- prepare

def _file_key(p: str) -> str:
    try:
        st = os.stat(p)
        return f"{p}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return p


def prepare_assets(shots: list[dict], work_dir: Path, look: looks_mod.Look, width: int, height: int,
                   fit: str, workers: int, progress: Optional[Callable] = None) -> dict:
    cache_dir = work_dir / f"canvas_{look.key}_{width}x{height}_{fit}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path = cache_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        index = {}

    lut = None
    if any(s["type"] == "video" for s in shots):
        lut = write_cube_lut(look.grade, work_dir / f"grade_{look.key}.cube")

    prepared: dict = {}
    todo = []
    for i, s in enumerate(shots):
        path = s["asset_path"]
        if not Path(path).exists():
            continue
        key = _file_key(path)
        if s["type"] == "image":
            cached = index.get(key)
            if cached and Path(cached["canvas"]).exists():
                prepared[s["shot_id"]] = cached
            else:
                todo.append((s, key, i))
        else:
            meta = probe_video(path)
            meta["lut"] = str(lut) if lut else None
            prepared[s["shot_id"]] = meta

    def job(item):
        s, key, i = item
        out = cache_dir / f"{s['shot_id']}.jpg"
        return s["shot_id"], key, prepare_photo(path_of(s), str(out), width, height, look.key, fit, i)

    def path_of(s):
        return s["asset_path"]

    # threads are enough: PIL/cv2/mediapipe release the GIL for the heavy parts
    done = 0
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as ex:
            for shot_id, key, meta in ex.map(_safe_job(job), todo):
                done += 1
                if meta is not None:
                    prepared[shot_id] = meta
                    index[key] = meta
                if progress:
                    progress(done / len(todo), f"Preparing photos {done}/{len(todo)}")
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return prepared


def _safe_job(fn):
    def run(item):
        try:
            return fn(item)
        except Exception as e:  # one unreadable photo must not kill the render
            return item[0]["shot_id"], item[1], None
    return run


# ------------------------------------------------------------------ audio

def build_audio(tl: dict, out_wav: Path, work_dir: Path, samplerate: int = 48000) -> tuple[bool, str]:
    total = tl["total"]
    inputs = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", f"anullsrc=channel_layout=stereo:sample_rate={samplerate}"]
    graph = []
    labels = ["[0:a]"]
    k = 1
    for s in tl["shots"]:
        if s["type"] != "video" or not s["video"].get("has_audio"):
            continue
        length = s["vis_end"] - s["vis_start"]
        inputs += ["-i", s["asset_path"]]
        fin = max(s["t_in"], 0.05)
        fout = max(s["t_out"], 0.05)
        delay = int(max(s["vis_start"], 0) * 1000)
        graph.append(
            f"[{k}:a]aformat=sample_rates={samplerate}:channel_layouts=stereo,atrim=0:{length:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fin:.3f},afade=t=out:st={max(length - fout, 0):.3f}:d={fout:.3f},"
            f"adelay={delay}|{delay}[c{k}]"
        )
        labels.append(f"[c{k}]")
        k += 1
    graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first[out]")
    gfile = work_dir / "audio_graph.txt"
    gfile.write_text(";\n".join(graph), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", str(gfile), "-map", "[out]",
           "-ar", str(samplerate), "-ac", "2", "-t", f"{total:.3f}", str(out_wav)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode == 0, proc.stderr[-3000:]


# ----------------------------------------------------------------- render

def render(plan: dict, work_dir: Path, output_path: Path, cfg, options: Optional[dict] = None,
           progress: Optional[Callable[[float, str], None]] = None, preview_seconds: Optional[float] = None) -> dict:
    """Renders plan to output_path. Returns a dict with status/steps."""
    t0 = time.time()
    opts = merge_options(options)
    look = looks_mod.get_look(opts["look"])
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    W, H, fps = cfg.width, cfg.height, cfg.fps
    W, H = W // 4 * 4, H // 4 * 4
    workers = int(getattr(cfg, "workers", 0) or max(2, min(6, (os.cpu_count() or 4) - 2)))
    say = progress or (lambda f, m: None)

    shots = [s for s in plan["shots"] if s.get("enabled")]
    if preview_seconds:
        acc, keep = 0.0, []
        for s in shots:
            keep.append(s)
            acc += s["duration"]
            if acc >= preview_seconds and len(keep) >= 3:
                break
        shots = keep
        plan = {**plan, "shots": keep}

    say(0.0, "Preparing photos")
    prepared = prepare_assets(shots, work_dir, look, W, H, opts["photo_fit"], workers,
                              lambda f, m: say(0.15 * f, m))
    tl = build_timeline(plan, prepared, opts, look, W, H, fps)
    tl_path = work_dir / ("timeline_preview.json" if preview_seconds else "timeline.json")
    tl_path.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")

    codec = pick_encoder(cfg.codec)
    enc = encoder_args(cfg, codec, fps)
    N = tl["frames"]
    chunk = max(fps * 3, math.ceil(N / (workers * 3)))
    ranges = [(f, min(f + chunk, N)) for f in range(0, N, chunk)]
    chunk_dir = work_dir / ("chunks_preview" if preview_seconds else "chunks")
    chunk_dir.mkdir(exist_ok=True)
    for old in chunk_dir.glob("*"):
        try:
            old.unlink()
        except OSError:
            pass
    enc_path = chunk_dir / "enc.json"
    enc_path.write_text(json.dumps(enc), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(CORE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["GLOG_minloglevel"] = "2"
    env["TF_CPP_MIN_LOG_LEVEL"] = "2"
    pending = list(enumerate(ranges))
    running: dict = {}
    failures = []
    outputs = [chunk_dir / f"c_{i:04d}.mp4" for i in range(len(ranges))]
    say(0.15, f"Rendering {N} frames with {workers} workers ({codec})")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    while pending or running:
        while pending and len(running) < workers:
            i, (f0, f1) = pending.pop(0)
            cmd = [sys.executable, "-m", "pro.worker", str(tl_path), str(f0), str(f1), str(outputs[i]), str(enc_path)]
            running[i] = (subprocess.Popen(cmd, cwd=str(CORE_DIR), env=env, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE, creationflags=creationflags), f0, f1)
        time.sleep(0.4)
        for i in list(running):
            proc, f0, f1 = running[i]
            if proc.poll() is not None:
                err = proc.stderr.read().decode("utf-8", "replace")
                if proc.returncode != 0 or not outputs[i].exists():
                    failures.append(f"chunk {i} [{f0}-{f1}] failed: {err[-2000:]}")
                del running[i]
        done_frames = 0
        for i, (f0, f1) in enumerate(ranges):
            pp = Path(str(outputs[i]) + ".progress")
            try:
                done_frames += int(pp.read_text(encoding="ascii") or 0)
            except (OSError, ValueError):
                pass
        el = time.time() - t0
        say(0.15 + 0.75 * done_frames / max(N, 1), f"Rendering frames {done_frames}/{N} · {el:.0f}s")
        if failures:
            for proc, _, _ in running.values():
                proc.kill()
            break

    steps = [{"shot_id": s["shot_id"], "status": "ok", "asset_path": s["asset_path"], "error": None}
             for s in tl["shots"]]
    if failures:
        return _result(plan, output_path, False, steps, "\n".join(failures), tl_path, t0)

    say(0.92, "Assembling")
    concat_txt = chunk_dir / "concat.txt"
    concat_txt.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in outputs), encoding="utf-8")
    video_only = work_dir / ("video_preview.mp4" if preview_seconds else "video_only.mp4")
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                           "-c", "copy", str(video_only)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return _result(plan, output_path, False, steps, proc.stderr[-3000:], tl_path, t0)

    wav = work_dir / ("audio_preview.wav" if preview_seconds else "timeline_audio.wav")
    ok, log = build_audio(tl, wav, work_dir, cfg.audio_samplerate)
    if not ok:
        return _result(plan, output_path, False, steps, log, tl_path, t0)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video_only), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", cfg.audio_codec, "-b:a", cfg.audio_bitrate, "-ar", str(cfg.audio_samplerate),
           "-shortest"]
    if cfg.faststart:
        cmd += ["-movflags", "+faststart"]
    proc = subprocess.run(cmd + [str(output_path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    say(1.0, "Done" if ok else "Mux failed")
    return _result(plan, output_path, ok, steps, None if ok else proc.stderr[-3000:], tl_path, t0,
                   extra={"frames": N, "duration": tl["total"], "encoder": codec, "workers": workers,
                          "transitions": [t["type"] for t in tl["transitions"]]})


def _result(plan, output_path, ok, steps, error, tl_path, t0, extra=None) -> dict:
    from datetime import datetime
    steps = list(steps) + [{"shot_id": "__final__", "output": str(output_path), "status": "ok" if ok else "failed",
                            "error": error}]
    out = {
        "rendered_at": datetime.now().isoformat(), "engine": "pro",
        "output_path": str(output_path) if ok else None, "timeline": str(tl_path),
        "shot_count": len([s for s in plan["shots"] if s.get("enabled")]),
        "succeeded": sum(1 for s in steps if s["status"] == "ok"),
        "failed": sum(1 for s in steps if s["status"] == "failed"),
        "status": "ok" if ok else "failed", "error": error,
        "elapsed_seconds": round(time.time() - t0, 1), "steps": steps,
    }
    if extra:
        out.update(extra)
    return out
