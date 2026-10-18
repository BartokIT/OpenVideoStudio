"""Media Remix editing operations as plain functions.

This is the single place where the editor's behaviour lives (option
normalisation, music resolution, plan edits, timeline rebuilds, frames,
renders, projects). The editor (studio/server + studio/web) calls it
through a JSON API; it has no UI dependencies of its own.

Options are always the key-based dict stored in run_state.render_options
(see DEFAULT_OPTIONS), which is also what .ovsp.json project files keep.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2

import music as music_lib
import music_online
import pipeline
import project as project_lib
from pro import looks as pro_looks
from pro import preview as pro_preview
from pro import transitions as pro_transitions
from pro import typography as pro_typography
from pro.timeline import MOTION_LABELS, auto_chapter_text

STUDIO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = STUDIO_ROOT / "runs"
ASSETS_MUSIC = STUDIO_ROOT / "assets" / "music"
PROJECTS_DIR = STUDIO_ROOT / "projects"
CONFIG_PATH = STUDIO_ROOT / "config.toml"
TIMELINE_VIEW = "timeline_view.json"

Progress = Optional[Callable[[float, str], None]]


def configure(runs_root: Optional[Path] = None, assets_music: Optional[Path] = None,
              projects_dir: Optional[Path] = None) -> None:
    """Points the service at other folders (tests, portable installs)."""
    global RUNS_ROOT, ASSETS_MUSIC, PROJECTS_DIR
    if runs_root:
        RUNS_ROOT = Path(runs_root)
    if assets_music:
        ASSETS_MUSIC = Path(assets_music)
    if projects_dir:
        PROJECTS_DIR = Path(projects_dir)


# ------------------------------------------------------------- choices
# value/label pairs; "label" is the full wording (selects, tooltips),
# "short"/"hint" are for compact controls such as segmented buttons.

def _c(value, label, short=None, hint=None) -> dict:
    return {"value": value, "label": label, "short": short or label, "hint": hint or ""}


TRANSITION_MODES = [
    _c("auto", "Auto — varied, curated by style", "Auto", "The look's own palette, never the same twice in a row"),
    _c("mixed", "Mixed — every transition", "Mixed", "Any of the 20+ transitions"),
    _c("morph", "Face morph (where possible)", "Face morph", "Morph between portraits, the look's palette elsewhere"),
] + [_c(k, f"Favour: {lab}", lab, "Signature transition (~half of the cuts), the look's others for variety")
     for k, lab in sorted(pro_transitions.LABELS.items(), key=lambda kv: kv[1]) if k not in ("morph", "cut")]

FACEMORPH = [
    _c("auto", "Auto — between clear portraits", "Auto"),
    _c("always", "Always — whenever faces are found", "Always"),
    _c("off", "Off", "Off"),
]
ANIMS = [
    _c(None, "Auto (from style)", "Auto"), _c("fade_up", "Fade up"), _c("letters_rise", "Letters rise"),
    _c("tracking_in", "Cinematic tracking"), _c("blur_in", "Blur in"), _c("pop", "Word pop"),
    _c("typewriter", "Typewriter"), _c("wipe", "Wipe reveal"), _c("slide_right", "Slide in"),
]
FITS = [
    _c("auto", "Smart (blurred fill for portraits)", "Smart", "Crop landscape photos, show portraits whole over a blurred fill"),
    _c("crop", "Always crop to fill", "Crop"),
    _c("fit", "Always show whole photo", "Whole"),
]
RESOLUTIONS = [_c("720p", "720p"), _c("1080p", "1080p"), _c("4k", "4k", "4K")]
SORT_MODES = [
    _c("folder", "Folders (folder order, then filename)", "Folders"),
    _c("date", "Date (EXIF / file date)", "Date"),
]
MUSIC_SYNC = [
    _c("bars", "On the bars — calm, cuts on the first beat of a bar", "Bars", "Cuts on the first beat of a bar"),
    _c("beats", "On every beat — cuts on the nearest beat", "Beats", "Cuts on the nearest beat"),
    _c("accents", "On the accents — cuts on the strong hits", "Accents", "Cuts on the strong hits"),
    _c("follow", "Follow the music — accents, faster when it's loud", "Follow", "Accents, shorter shots when it's loud"),
    _c("nudge", "Light nudge — planned lengths, moved ≤0.6 s onto a beat", "Nudge", "Planned lengths, moved ≤0.6 s"),
]
FONTS = [_c(v, k) for k, v in pro_typography.FONT_CHOICES.items()]
MOTIONS = [_c("", "Auto (from style)", "Auto")] + [_c(k, lab) for k, lab in MOTION_LABELS.items()]
SHOT_TRANSITIONS = [_c("", "Auto (style)", "Auto"), _c("morph", pro_transitions.LABELS["morph"])] + [
    _c(k, lab) for k, lab in sorted(pro_transitions.LABELS.items(), key=lambda kv: kv[1]) if k != "morph"]


def values(choices: list) -> list:
    return [c["value"] for c in choices]


DEFAULT_OPTIONS = {
    "look": "family_memory", "title": "", "subtitle": "", "kicker": "", "closing_text": "",
    "chapter_titles": True, "captions": True, "font": None, "title_anim": None,
    "transition_mode": "auto", "transition_only": False, "transition_speed": 1.0, "facemorph": "auto",
    "beat_sync": True, "music_volume": 0.35, "resolution": "1080p", "photo_fit": "auto",
    "music_preset": None, "music_sync": "bars", "music_credit_on": True, "music_credit": "",
}


def default_target_duration() -> float:
    try:
        import tomllib
        return float(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                     .get("output", {}).get("target_duration_seconds", 180))
    except Exception:
        return 180.0


def catalog() -> dict:
    """Everything a front-end needs to build its controls."""
    looks = []
    for key, lk in pro_looks.LOOKS.items():
        looks.append({"value": key, "label": lk.label, "description": lk.description,
                      "mood": music_lib.LOOK_MOOD.get(key, ""), "letterbox": lk.letterbox,
                      "transitions": [pro_transitions.LABELS.get(t, t) for t in lk.transitions]})
    return {
        "looks": looks, "transition_modes": TRANSITION_MODES, "facemorph": FACEMORPH, "anims": ANIMS,
        "fits": FITS, "resolutions": RESOLUTIONS, "sort_modes": SORT_MODES, "music_sync": MUSIC_SYNC,
        "fonts": FONTS, "motions": MOTIONS, "shot_transitions": SHOT_TRANSITIONS,
        "moods": list(music_lib.MOODS),
        "online_sources": [{"value": s, "label": music_online.SOURCE_LABELS[s],
                            "available": s != "jamendo" or music_online.jamendo_available()}
                           for s in music_online.SOURCES],
        "default_options": dict(DEFAULT_OPTIONS), "default_target_duration": default_target_duration(),
    }


# ------------------------------------------------------------ options

def music_track(options: dict):
    """The preset Track behind the options, or None (none / custom file)."""
    key = options.get("music_preset")
    if not key or key == "custom":
        return None
    tracks = music_lib.library(ASSETS_MUSIC)
    if key == "auto":
        return music_lib.pick_for_look(options.get("look", ""), tracks)
    return music_lib.by_key(tracks, key)


def normalize_options(options: Optional[dict]) -> dict:
    """Fills defaults, drops unknown keys, clamps and validates values, and
    derives the music credit from the chosen preset."""
    o = dict(DEFAULT_OPTIONS)
    for k, v in (options or {}).items():
        if k in DEFAULT_OPTIONS:
            o[k] = v
    if o["look"] not in pro_looks.LOOKS:
        o["look"] = DEFAULT_OPTIONS["look"]
    for key, choices in (("transition_mode", TRANSITION_MODES), ("facemorph", FACEMORPH), ("photo_fit", FITS),
                         ("resolution", RESOLUTIONS), ("music_sync", MUSIC_SYNC)):
        if o[key] not in values(choices):
            o[key] = DEFAULT_OPTIONS[key]
    if o["font"] not in values(FONTS):
        o["font"] = None
    if o["title_anim"] not in values(ANIMS):
        o["title_anim"] = None
    for k in ("title", "subtitle", "kicker", "closing_text"):
        o[k] = str(o[k] or "").strip()
    for k in ("chapter_titles", "captions", "transition_only", "beat_sync", "music_credit_on"):
        o[k] = bool(o[k])
    try:
        o["transition_speed"] = round(min(max(float(o["transition_speed"]), 0.5), 2.0), 2)
    except (TypeError, ValueError):
        o["transition_speed"] = 1.0
    try:
        o["music_volume"] = round(min(max(float(o["music_volume"]), 0.0), 1.0), 2)
    except (TypeError, ValueError):
        o["music_volume"] = DEFAULT_OPTIONS["music_volume"]
    track = music_track(o) if o["music_credit_on"] else None
    o["music_credit"] = track.attribution if track and track.attribution else ""
    return o


def resolve_bgm(options: dict, custom_path: Optional[str] = None, progress: Progress = None) -> Optional[str]:
    """Path of the music to use: a preset (synthesised on first use), the
    custom file kept by an older run, or nothing."""
    if options.get("music_preset") == "custom":
        return custom_path if custom_path and Path(custom_path).exists() else None
    track = music_track(options)
    if track is None:
        return None
    try:
        return music_lib.ensure_track(track, ASSETS_MUSIC, progress).path
    except Exception:
        return None


# ---------------------------------------------------------------- plan

def transition_key(label) -> Optional[str]:
    t = str(label or "").strip().lower()
    if not t or t.startswith("auto"):
        return None
    aliases = {**{k: k for k in pro_transitions.LABELS}, **{v.lower(): k for k, v in pro_transitions.LABELS.items()}}
    return aliases.get(t) or aliases.get(t.replace(" ", "_"))


def load_plan(run_dir: Path) -> dict:
    return json.loads((Path(run_dir) / "plan.json").read_text(encoding="utf-8"))


def save_plan(run_dir: Path, plan: dict) -> None:
    plan["shots"].sort(key=lambda s: s["order"])
    for i, s in enumerate(plan["shots"]):
        s["order"] = i
    plan["total_planned_duration"] = round(sum(s["duration"] for s in plan["shots"] if s["enabled"]), 2)
    (Path(run_dir) / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def set_shot_text(plan: dict, shot: dict, text, options: dict) -> None:
    """"" on a shot that starts a chapter hides the chapter card (and any
    caption) there — an empty override would otherwise mean "automatic"
    and bring the folder name back. Typing exactly the automatic chapter
    title returns to automatic; anything else is an override."""
    text = (text or "").strip()
    auto = auto_chapter_text(plan, shot["shot_id"], options)
    if not text:
        shot["title_text"] = None
        shot["hide_text"] = bool(auto)
    elif auto and text == auto:
        shot["title_text"] = None
        shot["hide_text"] = False
    else:
        shot["title_text"] = text
        shot["hide_text"] = False


def move_before(plan: dict, shot_id: str, before_id: Optional[str]) -> bool:
    """Places shot_id right before before_id in plan order (None = after the
    last enabled shot). Returns False when nothing changes."""
    shots = sorted(plan["shots"], key=lambda s: s["order"])
    i = next((k for k, s in enumerate(shots) if s["shot_id"] == shot_id), None)
    if i is None:
        return False
    shot = shots.pop(i)
    if before_id:
        j = next((k for k, s in enumerate(shots) if s["shot_id"] == before_id), None)
        if j is None:
            shots.insert(i, shot)
            return False
    else:
        j = max((k for k, s in enumerate(shots) if s["enabled"]), default=-1) + 1
    shots.insert(j, shot)
    for k, s in enumerate(shots):
        s["order"] = k
    plan["shots"] = shots
    return j != i


def move_by(plan: dict, shot_id: str, delta: int) -> bool:
    """Moves a shot past its nearest neighbour in the same state (enabled
    shots move within the cut, skipping disabled ones)."""
    shots = sorted(plan["shots"], key=lambda s: s["order"])
    i = next((k for k, s in enumerate(shots) if s["shot_id"] == shot_id), None)
    if i is None:
        return False
    j = i + delta
    while 0 <= j < len(shots) and shots[j]["enabled"] != shots[i]["enabled"]:
        j += delta
    if not 0 <= j < len(shots):
        return False
    shot = shots.pop(i)
    shots.insert(j, shot)
    for k, s in enumerate(shots):
        s["order"] = k
    plan["shots"] = shots
    return True


# ---------------------------------------------------------------- runs

_LOCKS: dict = defaultdict(threading.RLock)
_FRAME_LOCK = threading.Lock()
RUN_ID_RE = re.compile(r"^run_[0-9A-Za-z_]+$")


@contextmanager
def run_lock(run_id: str):
    with _LOCKS[run_id]:
        yield


class ServiceError(Exception):
    """A user-facing error (bad input, missing run, failed stage)."""


def run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or ""):
        raise ServiceError("Invalid run id.")
    rd = RUNS_ROOT / run_id
    if not (rd / "run_state.json").exists():
        raise ServiceError("This run no longer exists.")
    return rd


def _work(rd: Path) -> Path:
    return Path(rd) / "render_work"


def _shot_name(s: dict) -> str:
    return (s.get("relative_path") or Path(s["asset_path"]).name).rsplit("/", 1)[-1]


def _shot_folder(s: dict) -> str:
    rel = s.get("relative_path") or ""
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _url(path) -> Optional[str]:
    return pro_preview.file_url(str(path)) if path else None


def _versioned(path: Path) -> str:
    """File URL with the modification time appended, so a re-render isn't
    served from the browser cache."""
    url = _url(path)
    return f"{url}{'&' if '?' in url else '?'}v={int(Path(path).stat().st_mtime)}"


def media_list(plan: dict, thumbs: dict) -> list:
    out = []
    for s in sorted(plan["shots"], key=lambda s: s["order"]):
        thumb = thumbs.get(s["shot_id"])
        item = {"id": s["shot_id"], "name": _shot_name(s), "folder": _shot_folder(s) or "(root)",
                "type": s["type"], "score": round(float(s.get("quality_score") or 0)), "enabled": bool(s["enabled"]),
                "duration": s["duration"], "thumb": _url(thumb), "excluded": None}
        if not s["enabled"]:
            kind = pro_preview.excluded_kind(s)
            item["excluded"] = {"kind": kind, "label": pro_preview.EXCLUDED_KINDS[kind][1]}
            if thumb:
                item["thumb"] = _url(pro_preview.excluded_thumb(thumb, kind))
        out.append(item)
    return out


def _shot_preview_time(tl: dict, idx: int) -> float:
    s = tl["shots"][idx]
    return s["start"] + s["t_in"] / 2 + min(1.0, s["duration"] * 0.3)


def _audio_url(path: Optional[str]) -> Optional[str]:
    if not path or not Path(path).exists():
        return None
    p = Path(path).resolve()
    for root in (ASSETS_MUSIC, RUNS_ROOT):
        try:
            p.relative_to(Path(root).resolve())
            return _url(p)
        except ValueError:
            continue
    return None


def rebuild(run_id: str, progress: Progress = None, t: Optional[float] = None,
            select: Optional[str] = None) -> dict:
    """Thumbnails, music analysis and the 540p edit timeline for a run;
    stores the compact timeline view the front-end draws."""
    rd = run_dir(run_id)
    with run_lock(run_id):
        state = pipeline.load_run_state(rd)
        res = pipeline.prepare_editor(rd, state, progress=progress)
        tl, thumbs = res["timeline"], res["thumbs"]
        plan = load_plan(rd)
        ids = [s["shot_id"] for s in tl["shots"]]
        if select and select in ids:
            t = _shot_preview_time(tl, ids.index(select))
        if t is None:
            t = _shot_preview_time(tl, 0) if tl["shots"] else 0.0
        t = min(max(float(t), 0.0), tl["total"])
        view = pro_preview.timeline_view(tl, plan, thumbs, res.get("audio"), t, select,
                                         snap=bool(state.render_options.get("beat_sync", True)))
        (_work(rd) / TIMELINE_VIEW).write_text(json.dumps(view), encoding="utf-8")
        return view


def _load_view(rd: Path) -> Optional[dict]:
    try:
        return json.loads((_work(rd) / TIMELINE_VIEW).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def editor_state(run_id: str, progress: Progress = None) -> dict:
    """Everything the editor shows for a run."""
    rd = run_dir(run_id)
    view = _load_view(rd) or rebuild(run_id, progress)
    state = pipeline.load_run_state(rd)
    plan = load_plan(rd)
    thumbs = pro_preview.thumbnails(plan["shots"], _work(rd))
    outputs = {}
    for name, f in (("preview", "preview.mp4"), ("final", "final.mp4")):
        p = rd / f
        if p.exists():
            outputs[name] = {"url": _versioned(p), "path": str(p),
                             "updated": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
    enabled = [s for s in plan["shots"] if s["enabled"]]
    return {
        "run_id": run_id, "source_folder": state.source_folder, "target_duration": state.target_duration_seconds,
        "sort_mode": state.sort_mode, "options": normalize_options(state.render_options),
        "music_preset": state.render_options.get("music_preset"),
        "bgm": state.bgm_path, "audio_url": _audio_url(state.bgm_path), "view": view,
        "media": media_list(plan, thumbs),
        "summary": {"shots": len(plan["shots"]), "in_film": len(enabled),
                    "duration": round(view["total"] if view else sum(s["duration"] for s in enabled), 2)},
        "stages": {k: v.get("status") for k, v in state.stages.items()},
        "outputs": outputs,
    }


def create_run(folder: str, target_duration: float, sort_mode: str, options: dict,
               progress: Progress = None) -> str:
    folder_p = Path(str(folder or "").strip().strip('"'))
    if not str(folder_p) or not folder_p.is_dir():
        raise ServiceError("Choose a folder that exists.")
    opts = normalize_options(options)
    say = progress or (lambda f, m: None)
    say(0.02, "Preparing music")
    bgm = resolve_bgm(opts)
    sort_mode = sort_mode if sort_mode in values(SORT_MODES) else "folder"
    try:
        target = min(max(float(target_duration), 10.0), 7200.0)
    except (TypeError, ValueError):
        target = default_target_duration()
    state = pipeline.new_run(RUNS_ROOT, folder_p, opts["look"], target, Path(bgm) if bgm else None, sort_mode)
    rd = pipeline.run_dir_for(RUNS_ROOT, state.run_id)
    say(0.05, "Scanning and scoring the media")
    state = pipeline.run_to_plan(rd, state)
    if state.stages["plan"]["status"] != "done":
        failed = next((k for k in ("scan", "score", "plan") if state.stages[k]["status"] == "failed"), "plan")
        err = state.stages[failed].get("error") or "failed"
        raise ServiceError(f"{failed} failed: {str(err).splitlines()[0]}")
    pipeline.set_render_options(rd, state, opts)
    rebuild(state.run_id, lambda f, m: say(0.35 + 0.65 * f, m))
    return state.run_id


def set_options(run_id: str, options: dict, progress: Progress = None, t: Optional[float] = None) -> dict:
    rd = run_dir(run_id)
    with run_lock(run_id):
        state = pipeline.load_run_state(rd)
        opts = normalize_options(options)
        bgm = resolve_bgm(opts, state.bgm_path, progress)
        view = _load_view(rd)
        if opts == normalize_options(state.render_options) and bgm == state.bgm_path and view:
            return view
        state.bgm_path = bgm
        pipeline.set_render_options(rd, state, opts)
        old = view or {}
        new = rebuild(run_id, progress, t=t if t is not None else old.get("playhead"))
        sel = old.get("selected")
        if sel and sel in [s["id"] for s in new["shots"]]:   # keep the selection across a restyle
            new["selected"] = sel
            (_work(rd) / TIMELINE_VIEW).write_text(json.dumps(new), encoding="utf-8")
        return new


EDIT_ACTIONS = ("update", "move", "move_by", "duration", "caption", "toggle", "enable")


def edit(run_id: str, action: str, shot_id: str, payload: Optional[dict] = None,
         progress: Progress = None) -> dict:
    """Applies one edit to the plan and rebuilds the timeline with the
    playhead on the edited shot. Returns the new timeline view."""
    p = payload or {}
    if action not in EDIT_ACTIONS:
        raise ServiceError(f"Unknown edit: {action}")
    rd = run_dir(run_id)
    with run_lock(run_id):
        plan = load_plan(rd)
        state = pipeline.load_run_state(rd)
        shot = next((s for s in plan["shots"] if s["shot_id"] == shot_id), None)
        if not shot:
            raise ServiceError("Shot not found.")
        if action == "update":
            if "enabled" in p:
                shot["enabled"] = bool(p["enabled"])
            if "duration" in p and p["duration"] not in (None, ""):
                d = round(min(max(float(p["duration"]), 0.5), 60.0), 2)
                if abs(d - float(shot["duration"])) >= 0.01:
                    shot["duration"], shot["duration_locked"] = d, True
            if "motion" in p:
                shot["motion"] = p["motion"] if p["motion"] in MOTION_LABELS else None
            if "transition" in p:
                shot["transition"] = transition_key(p["transition"])
            if "text" in p:
                set_shot_text(plan, shot, p["text"], state.render_options)
        elif action == "move":
            if not move_before(plan, shot_id, p.get("before") or None):
                return _load_view(rd) or rebuild(run_id, progress)
        elif action == "move_by":
            if not move_by(plan, shot_id, int(p.get("delta") or 0)):
                return _load_view(rd) or rebuild(run_id, progress)
        elif action == "duration":
            shot["duration"] = round(min(max(float(p.get("duration")), 0.5), 60.0), 2)
            shot["duration_locked"] = True
        elif action == "caption":
            set_shot_text(plan, shot, p.get("text"), state.render_options)
        elif action == "toggle":
            shot["enabled"] = not shot["enabled"]
        elif action == "enable":
            shot["enabled"] = bool(p.get("enabled", True))
        save_plan(rd, plan)
        for st in ("render", "audio"):   # the cut changed: earlier renders are stale
            state.stages[st] = {"status": "pending", "timestamp": None, "error": None, "qc": None}
        pipeline.save_run_state(rd, state)
        return rebuild(run_id, progress, select=shot_id if shot["enabled"] else None,
                       t=None if shot["enabled"] else (_load_view(rd) or {}).get("playhead"))


def set_view_cursor(run_id: str, playhead: Optional[float] = None, selected=...) -> dict:
    """Persists playhead / selection in the stored view (cheap, no rebuild)."""
    rd = run_dir(run_id)
    view = _load_view(rd)
    if not view:
        raise ServiceError("No timeline yet.")
    if playhead is not None:
        view["playhead"] = round(min(max(float(playhead), 0.0), view["total"]), 3)
    if selected is not ...:
        view["selected"] = selected
    (_work(rd) / TIMELINE_VIEW).write_text(json.dumps(view), encoding="utf-8")
    return {"playhead": view["playhead"], "selected": view["selected"]}


def shot_info(run_id: str, shot_id: str) -> dict:
    """Inspector data for one shot."""
    rd = run_dir(run_id)
    plan = load_plan(rd)
    shot = next((s for s in plan["shots"] if s["shot_id"] == shot_id), None)
    if not shot:
        raise ServiceError("Shot not found.")
    state = pipeline.load_run_state(rd)
    chapters = {c["chapter_id"]: c.get("title", "") for c in plan.get("chapters", [])}
    tl = pro_preview.load_edit_timeline(_work(rd)) or {"shots": [], "transitions": [], "overlays": []}
    idx = next((i for i, s in enumerate(tl["shots"]) if s["shot_id"] == shot_id), None)
    auto = auto_chapter_text(plan, shot_id, state.render_options)
    thumbs = pro_preview.thumbnails([shot], _work(rd))
    info = {
        "id": shot_id, "name": _shot_name(shot), "folder": _shot_folder(shot) or "(root)", "type": shot["type"],
        "score": round(float(shot.get("quality_score") or 0)), "chapter": chapters.get(shot.get("chapter_id"), ""),
        "enabled": bool(shot["enabled"]), "duration": float(shot["duration"]),
        "duration_locked": bool(shot.get("duration_locked")), "motion": shot.get("motion") or "",
        "transition": shot.get("transition") or "", "hide_text": bool(shot.get("hide_text")),
        "auto_title": auto, "text": "" if shot.get("hide_text") else (shot.get("title_text") or auto),
        "excluded": None if shot["enabled"] else pro_preview.EXCLUDED_KINDS[pro_preview.excluded_kind(shot)][1],
        "thumb": _url(thumbs.get(shot_id)), "timeline": None, "preview_t": None,
    }
    if idx is not None:
        s = tl["shots"][idx]
        tin = None
        if idx > 0:
            tr = tl["transitions"][idx - 1]
            tin = {"type": tr["type"], "label": pro_preview.transition_label(tr["type"]),
                   "duration": round(tr["duration"], 2), "chosen": bool(shot.get("transition"))}
        info["timeline"] = {"index": idx, "count": len(tl["shots"]), "start": round(s["start"], 2),
                            "end": round(s["end"], 2), "duration": round(s["duration"], 2),
                            "motion": s.get("motion"), "motion_label": MOTION_LABELS.get(s.get("motion"), ""),
                            "transition_in": tin,
                            "texts": [o["kind"] for o in tl.get("overlays", []) if o["shot"] == idx]}
        info["preview_t"] = round(_shot_preview_time(tl, idx), 3)
    return info


def frame_jpeg(run_id: str, t: float, quality: int = 86) -> tuple[bytes, dict]:
    """The exact frame at t from the edit timeline, as JPEG bytes, plus what
    is on screen (shot, transition, texts)."""
    rd = run_dir(run_id)
    tl_path = _work(rd) / pro_preview.TIMELINE_EDIT
    tl = pro_preview.load_edit_timeline(_work(rd))
    if not tl:
        raise ServiceError("No timeline yet.")
    t = min(max(float(t), 0.0), tl["total"])
    with _FRAME_LOCK:   # the cached Renderer is not thread-safe
        frame = pro_preview.frame_at(tl_path, t)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ServiceError("Could not encode the frame.")
    d = pro_preview.describe_time(tl, t)
    s = tl["shots"][d["shot"]]
    meta = {"t": round(t, 3), "total": tl["total"], "shot": d["shot"], "shot_id": s["shot_id"],
            "name": Path(s["asset_path"]).name,
            "transition": pro_preview.transition_label(tl["transitions"][d["transition"]]["type"])
            if d["transition"] is not None else "", "texts": d["texts"]}
    return buf.tobytes(), meta


# ------------------------------------------------------------- renders

def cut_preview(run_id: str, shot_id: str, progress: Progress = None) -> dict:
    rd = run_dir(run_id)
    tl = pro_preview.load_edit_timeline(_work(rd))
    if not tl:
        raise ServiceError("No timeline yet.")
    idx = next((i for i, s in enumerate(tl["shots"]) if s["shot_id"] == shot_id), None)
    if idx is None:
        raise ServiceError("This shot is not in the film.")
    if idx == 0:
        raise ServiceError("The first shot has no incoming transition.")
    k = idx - 1
    tr = tl["transitions"][k]
    if progress:
        progress(0.1, f"Rendering the cut: {pro_preview.transition_label(tr['type'])}")
    cfg = pipeline._render_cfg(pipeline.load_run_state(rd))
    out = _work(rd) / "cuts" / f"cut_{k:03d}.mp4"
    ok, err = pro_preview.render_cut(tl, _work(rd) / pro_preview.TIMELINE_EDIT, k, out, cfg)
    if not ok:
        raise ServiceError(f"Cut preview failed: {err[-300:]}")
    return {"url": _versioned(out),
            "label": f"{pro_preview.transition_label(tr['type'])} · {tr['duration']:.2f} s into shot {idx + 1}"}


def render_preview(run_id: str, progress: Progress = None) -> dict:
    rd = run_dir(run_id)
    with run_lock(run_id):
        state = pipeline.load_run_state(rd)
        out = pipeline.render_preview(rd, state, 15.0, progress=progress)
    if out is None:
        raise ServiceError("Preview failed — see the run's logs/render.log.")
    return {"url": _versioned(out), "path": str(out)}


def render_final(run_id: str, progress: Progress = None) -> dict:
    rd = run_dir(run_id)
    with run_lock(run_id):
        state = pipeline.load_run_state(rd)
        state = pipeline.set_render_options(rd, state, normalize_options(state.render_options))
        state = pipeline.approve_plan(rd, state)
        state = pipeline.run_after_review(rd, state, progress=progress)
    final = rd / "final.mp4"
    if state.stages["audio"]["status"] != "done" or not final.exists():
        st = "render" if state.stages["render"]["status"] != "done" else "audio"
        err = state.stages[st].get("error") or "failed"
        raise ServiceError(f"Render {st} failed: {str(err).splitlines()[0]}")
    qc = state.stages["render"].get("qc") or {}
    return {"url": _versioned(final), "path": str(final),
            "seconds": qc.get("elapsed_seconds"), "duration": qc.get("duration")}


def open_folder(run_id: str) -> None:
    subprocess.Popen(["explorer", str(run_dir(run_id))])


# ------------------------------------------------------------ projects

def list_projects() -> list:
    out = []
    for p in project_lib.list_projects(PROJECTS_DIR):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"name": d.get("name") or p.name, "path": str(p), "file": p.name,
                    "saved_at": d.get("saved_at", ""), "folder": d.get("source_folder", ""),
                    "shots": sum(1 for s in d.get("plan", {}).get("shots", []) if s.get("enabled"))})
    return out


def save_project(run_id: str, name: str) -> dict:
    rd = run_dir(run_id)
    state = pipeline.load_run_state(rd)
    name = (name or "").strip() or f"project_{run_id}"
    path = PROJECTS_DIR / f"{project_lib.slug(name)}{project_lib.SUFFIX}"
    project_lib.save_project(rd, state, path, name)
    return {"name": name, "path": str(path)}


def open_project(path: str, progress: Progress = None) -> dict:
    p = Path(path)
    if not p.exists():
        raise ServiceError("Project file not found.")
    try:
        rd, state, report = project_lib.load_project(p, RUNS_ROOT)
    except ValueError as e:
        raise ServiceError(str(e))
    rebuild(rd.name, progress)
    return {"run_id": rd.name, "name": report.get("name", ""), "missing": report.get("missing", []),
            "reused_run": report.get("reused_run", False)}


def recent_runs(limit: int = 8) -> list:
    out = []
    if not RUNS_ROOT.exists():
        return out
    runs = [d for d in RUNS_ROOT.iterdir() if d.is_dir() and RUN_ID_RE.match(d.name) and (d / "plan.json").exists()]
    for d in sorted(runs, key=lambda d: (d / "plan.json").stat().st_mtime, reverse=True)[:limit]:
        try:
            st = pipeline.load_run_state(d)
            plan = load_plan(d)
        except Exception:
            continue
        on = [s for s in plan["shots"] if s["enabled"]]
        out.append({"run_id": d.name, "folder": st.source_folder, "folder_name": Path(st.source_folder).name,
                    "look": st.render_options.get("look", st.style), "shots": len(on),
                    "duration": round(sum(s["duration"] for s in on), 1),
                    "updated": datetime.fromtimestamp((d / "plan.json").stat().st_mtime).isoformat(timespec="minutes"),
                    "folder_exists": Path(st.source_folder).exists()})
    return out


# --------------------------------------------------------------- music

def music_tracks() -> list:
    out = []
    for t in music_lib.library(ASSETS_MUSIC):
        out.append({"key": t.key, "title": t.title, "mood": t.mood, "builtin": t.builtin, "creator": t.creator,
                    "attribution": t.attribution, "volume": t.volume, "beat_sync": t.beat_sync, "sync": t.sync,
                    "downloaded": t.key.startswith("dl:"), "url": _audio_url(t.path) if t.path else None})
    return out


_SAFE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def save_uploaded_music(filename: str, data: bytes) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext not in music_lib.AUDIO_EXTS:
        raise ServiceError("Unsupported audio file (mp3, m4a, wav, ogg, flac).")
    if len(data) < 2048:
        raise ServiceError("The file is empty.")
    stem = _SAFE.sub("_", Path(filename).stem).strip(" ._") or "music"
    ASSETS_MUSIC.mkdir(parents=True, exist_ok=True)
    dest = ASSETS_MUSIC / f"{stem}{ext}"
    n = 1
    while dest.exists():
        n += 1
        dest = ASSETS_MUSIC / f"{stem}_{n}{ext}"
    dest.write_bytes(data)
    return {"key": f"file:{dest.name}", "title": stem.replace("_", " ")}


def search_music(query: str, source: str, mood: Optional[str]) -> list:
    try:
        res = music_online.search(query, source or "openverse", mood or None, 20)
    except (ValueError, RuntimeError) as e:
        raise ServiceError(str(e))
    except Exception as e:
        raise ServiceError(f"Search failed: {e}")
    return [{**music_online.asdict(t), "downloadable": t.downloadable, "no_derivatives": t.no_derivatives,
             "label": t.label()} for t in res]


def download_music(track: dict, progress: Progress = None) -> dict:
    fields = music_online.OnlineTrack.__dataclass_fields__
    try:
        t = music_online.OnlineTrack(**{k: track[k] for k in fields})
    except KeyError:
        raise ServiceError("Incomplete track data.")
    try:
        path = music_online.download(t, ASSETS_MUSIC / "downloads", progress)
    except PermissionError as e:
        raise ServiceError(str(e))
    except Exception as e:
        raise ServiceError(f"Download failed: {e}")
    return {"key": f"dl:{path.name}", "title": t.title, "attribution": t.attribution}


# --------------------------------------------------------- native dialogs

def _tk_dialog(fn):
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return fn(root) or ""
        finally:
            root.destroy()
    except Exception:
        return ""


def pick_folder() -> str:
    from tkinter import filedialog
    return _tk_dialog(lambda r: filedialog.askdirectory(parent=r, title="Choose the media folder"))


def pick_project_file() -> str:
    from tkinter import filedialog
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return _tk_dialog(lambda r: filedialog.askopenfilename(
        parent=r, initialdir=str(PROJECTS_DIR), title="Open an OpenVideoStudio project",
        filetypes=[("OpenVideoStudio project", f"*{project_lib.SUFFIX}"), ("All files", "*.*")]))


def disk_free_gb() -> float:
    try:
        return round(shutil.disk_usage(RUNS_ROOT if RUNS_ROOT.exists() else STUDIO_ROOT).free / 1e9, 1)
    except OSError:
        return 0.0
