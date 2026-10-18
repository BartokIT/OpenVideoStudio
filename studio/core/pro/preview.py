"""Editor-side helpers over the pro engine: thumbnails for the media bin
and filmstrip, a low-res "edit timeline" that mirrors what the final
render will do, single frames at the playhead, and short clips around one
transition.

Everything here reuses the render path (prepare_assets, build_timeline,
Renderer, render_range), so what the editor shows is what gets rendered.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from . import looks as looks_mod
from .engine import Renderer, encoder_args, pick_encoder, prepare_assets, render_range
from .sources import _load_rgb
from .timeline import build_timeline, merge_options
from .transitions import LABELS as TRANSITION_LABELS

EDIT_W, EDIT_H = 960, 540
THUMB_W, THUMB_H = 320, 180
TIMELINE_EDIT = "timeline_edit.json"


# ------------------------------------------------------------- thumbnails

def _file_key(p: str) -> str:
    try:
        st = os.stat(p)
        return f"{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return "?"


def _photo_thumb(src: str, out: Path) -> None:
    img = _load_rgb(Path(src))
    ih, iw = img.shape[:2]
    s = max(THUMB_W / iw, THUMB_H / ih)
    w, h = max(int(iw * s), 1), max(int(ih * s), 1)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    x0, y0 = (w - THUMB_W) // 2, (h - THUMB_H) // 2
    img = img[y0:y0 + THUMB_H, x0:x0 + THUMB_W]
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    out.write_bytes(buf.tobytes())


def _video_thumb(src: str, out: Path) -> None:
    vf = (f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=increase,crop={THUMB_W}:{THUMB_H}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", src, "-frames:v", "1", "-vf", vf, "-q:v", "4", str(out)]
    proc = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not out.exists():
        # very short clips: fall back to the first frame
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-frames:v", "1", "-vf", vf, "-q:v", "4", str(out)]
        subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _placeholder_thumb(out: Path) -> None:
    img = np.full((THUMB_H, THUMB_W, 3), 60, np.uint8)
    cv2.line(img, (0, 0), (THUMB_W, THUMB_H), (120, 120, 120), 2)
    cv2.line(img, (0, THUMB_H), (THUMB_W, 0), (120, 120, 120), 2)
    cv2.imwrite(str(out), img)


def thumbnails(shots: list[dict], work_dir: Path, workers: int = 4,
               progress: Optional[Callable[[float, str], None]] = None) -> dict[str, str]:
    """One 320x180 JPEG per shot (every shot, enabled or not), cached by
    source size+mtime in work_dir/thumbs. Returns shot_id -> path."""
    thumb_dir = Path(work_dir) / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    index_path = thumb_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        index = {}

    out: dict[str, str] = {}
    todo = []
    for s in shots:
        key = _file_key(s["asset_path"])
        cached = index.get(s["asset_path"])
        if cached and cached.get("key") == key and Path(cached["thumb"]).exists():
            out[s["shot_id"]] = cached["thumb"]
        else:
            todo.append((s, key))

    def job(item):
        s, key = item
        dest = thumb_dir / f"{s['shot_id']}.jpg"
        try:
            if s["type"] == "video":
                _video_thumb(s["asset_path"], dest)
            else:
                _photo_thumb(s["asset_path"], dest)
            if not dest.exists():
                _placeholder_thumb(dest)
        except Exception:
            _placeholder_thumb(dest)
        return s, key, str(dest)

    done = 0
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
            for s, key, dest in ex.map(job, todo):
                done += 1
                out[s["shot_id"]] = dest
                index[s["asset_path"]] = {"key": key, "thumb": dest}
                if progress:
                    progress(done / len(todo), f"Thumbnails {done}/{len(todo)}")
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return out


# ------------------------------------------------- excluded media marker

# why a shot is out of the cut -> (badge colour BGR, caption text)
EXCLUDED_KINDS = {
    "manual": ((60, 60, 220), "removed by you"),
    "duplicate": ((40, 170, 235), "duplicate"),
    "budget": ((170, 140, 110), "over the target length"),
    "missing": ((60, 60, 60), "file missing"),
}


def excluded_kind(shot: dict) -> str:
    reason = str(shot.get("reason") or "")
    if "missing_file" in reason:
        return "missing"
    if "duplicate_suppressed" in reason:
        return "duplicate"
    if "budget_suppressed" in reason:
        return "budget"
    return "manual"


def excluded_thumb(thumb_path: str, kind: str = "manual") -> str:
    """A copy of the thumbnail marking a shot that is not in the film: a
    light grey veil (the photo stays readable), thin coloured bands top and
    bottom, and a small "not allowed" badge in the top-left corner
    (gr.Gallery can't overlay icons itself). The media bin crops 16:9
    thumbnails to a centred square, so "top-left" is measured from that
    square, not from the image edge, or the badge would be cropped away.
    Cached next to the thumbnail and rebuilt when the thumbnail changes."""
    src = Path(thumb_path)
    out = src.with_name(f"{src.stem}_off3_{kind}.jpg")
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return str(out)
        img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return thumb_path
    if img is None:
        return thumb_path
    color = EXCLUDED_KINDS.get(kind, EXCLUDED_KINDS["manual"])[0]
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    img = cv2.addWeighted(img, 0.6, gray, 0.4, 0)
    img = (img.astype(np.float32) * 0.78).astype(np.uint8)
    h, w = img.shape[:2]
    band = max(h // 45, 3)
    cv2.rectangle(img, (0, 0), (w - 1, band), color, -1)
    cv2.rectangle(img, (0, h - 1 - band), (w - 1, h - 1), color, -1)
    r = max(int(h * 0.09), 7)
    x0 = max((w - h) // 2, 0)            # left edge of the centred square the bin shows
    cx, cy = x0 + r + 7, band + r + 7
    cv2.circle(img, (cx, cy), r + 2, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)
    inner = int(r * 0.62)
    stroke = max(r // 4, 2)
    cv2.circle(img, (cx, cy), inner, (255, 255, 255), stroke, cv2.LINE_AA)
    d = int(inner * 0.72)
    cv2.line(img, (cx - d, cy + d), (cx + d, cy - d), (255, 255, 255), stroke, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return thumb_path
    out.write_bytes(buf.tobytes())
    return str(out)


# ---------------------------------------------------------- edit timeline

def build_edit_timeline(plan: dict, work_dir: Path, options: Optional[dict], cfg,
                        progress: Optional[Callable[[float, str], None]] = None) -> tuple[dict, Path]:
    """Prepares the enabled shots at 960x540 (cached per look/fit) and
    builds the same timeline the render will use, at edit resolution.
    Written to work_dir/timeline_edit.json so frames can be rendered from it."""
    opts = merge_options(options)
    look = looks_mod.get_look(opts["look"])
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    workers = int(getattr(cfg, "workers", 0) or max(2, min(6, (os.cpu_count() or 4) - 2)))
    say = progress or (lambda f, m: None)
    shots = [s for s in plan["shots"] if s.get("enabled")]
    prepared = prepare_assets(shots, work_dir, look, EDIT_W, EDIT_H, opts["photo_fit"], workers,
                              lambda f, m: say(f, m))
    tl = build_timeline(plan, prepared, opts, look, EDIT_W, EDIT_H, cfg.fps)
    tl_path = work_dir / TIMELINE_EDIT
    tl_path.write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    _RENDERERS.pop(str(tl_path), None)
    return tl, tl_path


def load_edit_timeline(work_dir: Path) -> Optional[dict]:
    p = Path(work_dir) / TIMELINE_EDIT
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- frames

_RENDERERS: dict[str, tuple[float, Renderer]] = {}


def _renderer(tl_path: Path) -> Renderer:
    """Keeps the Renderer (and its decoded photo canvases) alive between
    playhead moves; rebuilt when the timeline file changes."""
    key = str(tl_path)
    mtime = os.stat(tl_path).st_mtime
    cached = _RENDERERS.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    if cached:
        cached[1].close()
    tl = json.loads(Path(tl_path).read_text(encoding="utf-8"))
    r = Renderer(tl)
    _RENDERERS[key] = (mtime, r)
    return r


def frame_at(tl_path: Path, t: float) -> np.ndarray:
    r = _renderer(Path(tl_path))
    n = int(round(max(0.0, min(t, r.tl["total"] - 1e-3)) * r.fps))
    return r.frame(n)


def describe_time(tl: dict, t: float) -> dict:
    """What is on screen at t: shot index, the transition if t falls inside
    one, and the text overlays active at t."""
    shots, trans = tl["shots"], tl["transitions"]
    idx = next((i for i, s in enumerate(shots) if s["start"] <= t < s["end"]), len(shots) - 1)
    tr = next((k for k, x in enumerate(trans) if x["start"] <= t < x["end"]), None)
    texts = [o["kind"] for o in tl.get("overlays", []) if o["start"] <= t <= o["end"]]
    return {"shot": idx, "transition": tr, "texts": texts}


# --------------------------------------------------------- cut previews

def render_cut(tl: dict, tl_path: Path, k: int, out_path: Path, cfg, pad: float = 1.0) -> tuple[bool, str]:
    """Encodes the frames from pad seconds before transition k to pad
    seconds after it, so one cut can be judged in a couple of seconds."""
    tr = tl["transitions"][k]
    fps = tl["fps"]
    f0 = max(int((tr["start"] - pad) * fps), 0)
    f1 = min(int((tr["end"] + pad) * fps) + 1, tl["frames"])
    codec = pick_encoder(cfg.codec)
    enc = encoder_args(cfg, codec, fps)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tl_now = json.loads(Path(tl_path).read_text(encoding="utf-8"))
    return render_range(tl_now, f0, f1, out_path, enc)


def transition_label(name: str) -> str:
    return TRANSITION_LABELS.get(name, name or "")


# ------------------------------------------------------------ music track

def _with_rhythm(d: dict, beats: Optional[list[float]], rhythm: Optional[dict]) -> dict:
    if beats is not None:
        d["beats"] = beats
    r = rhythm or {}
    d["downbeats"] = r.get("downbeats", [])
    d["accents"] = [a[0] for a in r.get("accents", [])]
    d["tempo"] = r.get("tempo") or 0
    d["meter"] = r.get("meter") or 0
    return d


def bgm_analysis(path: Path, work_dir: Path, beats: Optional[list[float]] = None,
                 peak_seconds: float = 0.1, rhythm: Optional[dict] = None) -> Optional[dict]:
    """Waveform peaks (RMS per peak_seconds, 0..1) and beats of the music
    file, cached in work_dir by file size+mtime."""
    path = Path(path)
    if not path.exists():
        return None
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    key = _file_key(str(path))
    cache = work_dir / f"bgm_{hashlib.md5(f'{path}|{key}'.encode('utf-8')).hexdigest()[:10]}.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("key") == key and cached.get("path") == str(path):
            return _with_rhythm(cached, beats, rhythm)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        import librosa
        from audio import load_mono  # core/audio.py (ffmpeg decode: mp3/m4a/ogg/...)
        sr = 11025
        y, _ = load_mono(path, sr=sr, max_seconds=900)
        hop = max(int(peak_seconds * sr), 1)
        rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
        top = float(rms.max()) or 1.0
        peaks = [round(float(v / top), 2) for v in rms]
        duration = len(y) / sr
    except Exception:
        peaks, duration = [], 0.0
    out = {"path": str(path), "key": key, "name": path.name, "duration": round(duration, 2),
           "peak_seconds": peak_seconds, "peaks": peaks, "beats": beats or []}
    cache.write_text(json.dumps(out), encoding="utf-8")
    return _with_rhythm(out, beats, rhythm)


# --------------------------------------------------------- timeline view

# Where the editor (studio/server) serves local files from.
FILE_URL_PREFIX = "/files?path="


def file_url(path: str) -> str:
    """URL under which the front-end serves a file from an allowed path.
    Forward slashes and percent-encoding keep it safe inside CSS url("...")
    strings (a backslash there is an escape character) and query strings."""
    from urllib.parse import quote
    return FILE_URL_PREFIX + quote(str(path).replace("\\", "/"), safe="/:")


def _overlay_text(o: dict) -> str:
    parts = [l.get("text", "") for l in o.get("lines", []) if l.get("role", "text") != "rule" and l.get("text")]
    return " · ".join(parts)


def timeline_view(tl: dict, plan: dict, thumbs: dict, audio: Optional[dict] = None, playhead: float = 0.0,
                  selected: Optional[str] = None, snap: bool = True) -> dict:
    """Compact, UI-oriented view of the edit timeline for ui/timeline.js."""
    by_id = {s["shot_id"]: s for s in plan.get("shots", [])}
    chapter_names = {}
    for c in plan.get("chapters", []):
        raw = c.get("title", "")
        chapter_names[c["chapter_id"]] = raw.split("·", 1)[-1].strip() if "·" in raw else raw
    shots, chapters = [], []
    for i, s in enumerate(tl["shots"]):
        ps = by_id.get(s["shot_id"], {})
        name = (ps.get("relative_path") or Path(s["asset_path"]).name).rsplit("/", 1)[-1]
        thumb = thumbs.get(s["shot_id"])
        shots.append({
            "id": s["shot_id"], "index": i, "name": name, "type": s["type"],
            "start": round(s["start"], 3), "end": round(s["end"], 3), "duration": round(s["duration"], 2),
            "thumb": file_url(thumb) if thumb else None, "chapter": s.get("chapter_id"),
            "motion": s.get("motion") if s["type"] == "image" else None,
            "has_audio": bool(s.get("video", {}).get("has_audio")) if s["type"] == "video" else False,
            "caption": ps.get("title_text") or "",
        })
        if not chapters or chapters[-1]["id"] != s.get("chapter_id"):
            chapters.append({"id": s.get("chapter_id"), "name": chapter_names.get(s.get("chapter_id"), ""),
                             "start": round(s["start"], 3), "end": round(s["end"], 3)})
        else:
            chapters[-1]["end"] = round(s["end"], 3)
    transitions = []
    for k, tr in enumerate(tl["transitions"]):
        into = tl["shots"][tr["b"]]
        transitions.append({
            "index": k, "type": tr["type"], "label": transition_label(tr["type"]),
            "start": round(tr["start"], 3), "end": round(tr["end"], 3), "duration": round(tr["duration"], 3),
            "override": bool(by_id.get(into["shot_id"], {}).get("transition")), "into": into["shot_id"],
        })
    from .timeline import chapter_label

    raw_chapters = {c["chapter_id"]: c.get("title", "") for c in plan.get("chapters", [])}
    lang = (tl.get("options") or {}).get("language", "it")
    texts = []
    for o in tl.get("overlays", []):
        shot = tl["shots"][o["shot"]]
        override = (by_id.get(shot["shot_id"], {}).get("title_text") or "").strip()
        if o["kind"] == "chapter":
            # what the user edits is the title line only; the date line stays automatic
            edit = override or chapter_label(raw_chapters.get(shot.get("chapter_id"), ""), lang)[0]
        else:
            edit = override
        texts.append({"kind": o["kind"], "text": _overlay_text(o), "start": round(o["start"], 3),
                      "end": round(o["end"], 3), "shot": shot["shot_id"],
                      "editable": o["kind"] in ("caption", "chapter"), "edit_text": edit})
    return {
        "total": round(tl["total"], 3), "fps": tl["fps"], "playhead": round(float(playhead), 3),
        "selected": selected, "fade_in": tl.get("fade_in", 0), "fade_out": tl.get("fade_out", 0),
        "chapters": chapters, "shots": shots, "transitions": transitions, "texts": texts,
        "audio": ({k: audio.get(k) for k in ("name", "duration", "peak_seconds", "peaks", "beats", "downbeats",
                                             "accents", "tempo", "meter")} if audio else None),
        "snap": bool(snap),
        "music_sync": (tl.get("music") or {}).get("mode") if snap else None,
    }


def format_time(t: float) -> str:
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"
