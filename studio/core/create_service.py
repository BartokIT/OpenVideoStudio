"""AI Creation (prompt -> script -> storyboard -> review -> keyframes ->
clips -> narration -> subtitles -> final video) as plain functions for the
editor's API.

The review gate is unchanged: nothing generates on the GPU until
approve_and_generate() is called, which marks the storyboard reviewed and
then runs the stages that each re-check it (creative/pipeline.py).
ComfyUI is started on demand when a generation needs it and isn't running.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

STUDIO_ROOT = Path(__file__).resolve().parents[1]
if str(STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_ROOT))

import creative.pipeline as cp  # noqa: E402
import studio_service as svc  # noqa: E402
from studio_service import ServiceError, run_lock  # noqa: E402

CREATE_ID_RE = re.compile(r"^create_[0-9A-Za-z_]+$")
COMFY_URL = "http://127.0.0.1:8188"

ASPECTS = [
    svc._c("9:16", "9:16 vertical", "9:16", "448×768 — validated end-to-end on a 6 GB GPU"),
    svc._c("16:9", "16:9 landscape", "16:9", "768×448 — same pixel budget, not separately validated"),
    svc._c("1:1", "1:1 square", "1:1", "608×608 — not separately validated"),
]
LANGUAGES = [svc._c("en", "English", "EN"), svc._c("zh", "Chinese", "中文")]
GEN_STAGES = ["keyframes", "clips", "narration", "subtitles", "edit"]
STAGE_LABELS = {"script": "Script", "storyboard": "Storyboard", "keyframes": "Keyframes", "clips": "Video clips",
                "narration": "Narration", "subtitles": "Subtitles", "edit": "Final edit"}
# share of the progress bar each generation stage takes (keyframes and clips dominate)
STAGE_WEIGHTS = {"keyframes": 0.35, "clips": 0.45, "narration": 0.08, "subtitles": 0.02, "edit": 0.10}
EDITABLE = ("image_prompt", "video_motion_prompt", "narration_text", "duration_seconds")


def _config() -> dict:
    try:
        import tomllib
        return tomllib.loads(svc.CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def configured_ollama_model() -> str:
    """config.toml's [providers].ollama_model ("configurable here on purpose
    — never hardcode it")."""
    return _config().get("providers", {}).get("ollama_model", "qwen3:8b")


def _ollama_server() -> str:
    return _config().get("providers", {}).get("ollama_server", "http://127.0.0.1:11434")


def catalog() -> dict:
    c = _config().get("creative", {})
    return {
        "aspects": ASPECTS, "languages": LANGUAGES,
        "defaults": {"duration": 15.0, "aspect": c.get("aspect_ratio", "9:16"),
                     "style": c.get("default_style", "cinematic sci-fi"), "language": c.get("default_language", "en")},
        "llm_model": configured_ollama_model(), "stage_labels": STAGE_LABELS,
    }


# ------------------------------------------------------------ services

def _reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def services_status() -> dict:
    portable = comfy_portable_dir()
    return {"ollama": _reachable(f"{_ollama_server()}/api/tags"), "ollama_server": _ollama_server(),
            "comfyui": _reachable(f"{COMFY_URL}/system_stats"),
            "comfyui_startable": bool(portable), "comfyui_dir": str(portable) if portable else ""}


def comfy_portable_dir() -> Optional[Path]:
    """The ComfyUI portable folder (the one with python_embeded/), from
    COMFYUI_PORTABLE or derived from COMFYUI_ROOT (…/ComfyUI)."""
    candidates = []
    if os.environ.get("COMFYUI_PORTABLE"):
        candidates.append(Path(os.environ["COMFYUI_PORTABLE"]))
    if os.environ.get("COMFYUI_ROOT"):
        candidates.append(Path(os.environ["COMFYUI_ROOT"]).parent)
    for c in candidates:
        if (c / "python_embeded" / "python.exe").exists() and (c / "ComfyUI" / "main.py").exists():
            return c
    return None


def ensure_comfyui(progress=None, timeout: float = 240.0) -> None:
    """Starts ComfyUI in its own window when it isn't running (it is only
    needed for keyframes and clips)."""
    if _reachable(f"{COMFY_URL}/system_stats"):
        return
    portable = comfy_portable_dir()
    if not portable:
        raise ServiceError("ComfyUI isn't running and can't be started automatically: set COMFYUI_ROOT "
                           "(…\\ComfyUI_windows_portable\\ComfyUI) in studio/.env, or start ComfyUI yourself.")
    if progress:
        progress(0.01, "Starting ComfyUI…")
    subprocess.Popen([str(portable / "python_embeded" / "python.exe"), "-s", "ComfyUI\\main.py",
                      "--windows-standalone-build"], cwd=str(portable),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _reachable(f"{COMFY_URL}/system_stats"):
            return
        if progress:
            progress(0.01, f"Starting ComfyUI… {int(time.time() - t0)} s")
        time.sleep(2)
    raise ServiceError("ComfyUI did not start within 4 minutes — check its window for errors.")


# ---------------------------------------------------------------- runs

def run_dir(run_id: str) -> Path:
    if not CREATE_ID_RE.match(run_id or ""):
        raise ServiceError("Invalid creation id.")
    rd = svc.RUNS_ROOT / run_id
    if not (rd / "run_state.json").exists():
        raise ServiceError("This creation no longer exists.")
    return rd


def _first_line(err) -> str:
    return str(err or "").strip().splitlines()[0] if err else ""


def _stage_error(state, names) -> Optional[str]:
    for n in names:
        info = state.stages.get(n, {})
        if info.get("status") == "failed":
            return f"{STAGE_LABELS.get(n, n)} failed: {_first_line(info.get('error')) or 'unknown error'}"
    return None


def create(prompt: str, duration: float, aspect: str, style: str, language: str,
           music_preset: Optional[str] = None, progress=None) -> str:
    """Script + storyboard with the local LLM, then stops for review."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ServiceError("Describe the video you want first.")
    say = progress or (lambda f, m: None)
    if not _reachable(f"{_ollama_server()}/api/tags"):
        raise ServiceError(f"Ollama isn't reachable at {_ollama_server()} — start Ollama and try again.")
    aspect = aspect if aspect in svc.values(ASPECTS) else "9:16"
    language = language if language in svc.values(LANGUAGES) else "en"
    try:
        duration = min(max(float(duration), 5.0), 180.0)
    except (TypeError, ValueError):
        duration = 15.0
    bgm = svc.resolve_bgm({"music_preset": music_preset, "look": "cinematic"}) if music_preset else None
    state = cp.new_run(svc.RUNS_ROOT, prompt, duration, (style or "").strip() or "cinematic", aspect, language,
                       configured_ollama_model(), Path(bgm) if bgm else None)
    rd = cp.run_dir_for(svc.RUNS_ROOT, state.run_id)
    say(0.1, f"Writing the script with {state.llm_model}")
    state = cp.run_script(rd, state)
    if state.stages["script"]["status"] == "done":
        say(0.55, "Drawing up the storyboard")
        state = cp.run_storyboard(rd, state)
    err = _stage_error(state, ["script", "storyboard"])
    if err:
        raise ServiceError(err)
    return state.run_id


def _scene_view(s: dict) -> dict:
    out = {k: s.get(k) for k in ("scene_number", "image_prompt", "video_motion_prompt", "narration_text",
                                 "subtitle_text", "description", "mood", "shot_size", "camera_movement")}
    out["duration_seconds"] = round(float(s.get("duration_seconds") or 0), 2)
    for k, key in (("keyframe_path", "keyframe"), ("clip_path", "clip")):
        p = s.get(k)
        out[key] = svc._versioned(Path(p)) if p and Path(p).exists() else None
    return out


def state(run_id: str) -> dict:
    rd = run_dir(run_id)
    st = cp.load_run_state(rd)
    sb_path = rd / "storyboard.json"
    sb = json.loads(sb_path.read_text(encoding="utf-8")) if sb_path.exists() else {"scenes": []}
    final = rd / "final.mp4"
    stages = [{"key": k, "label": STAGE_LABELS[k], "status": st.stages[k]["status"],
               "error": _first_line(st.stages[k].get("error")), "qc": st.stages[k].get("qc")} for k in cp.STAGES]
    char = sb.get("character_identity") or None
    return {
        "run_id": run_id, "prompt": st.prompt, "duration": st.target_duration_seconds, "style": st.style,
        "aspect": st.aspect_ratio, "language": st.language, "llm_model": st.llm_model, "bgm": st.bgm_path,
        "reviewed": st.storyboard_reviewed, "stages": stages, "title": sb.get("title") or "",
        "scenes": [_scene_view(s) for s in sb.get("scenes", [])],
        "warnings": sb.get("narrative_quality_warnings", []),
        "character": char if isinstance(char, dict) else None,
        "total": round(sum(float(s.get("duration_seconds") or 0) for s in sb.get("scenes", [])), 1),
        "final": {"url": svc._versioned(final),
                  "updated": datetime.fromtimestamp(final.stat().st_mtime).isoformat(timespec="seconds")}
        if final.exists() else None,
    }


def update_scenes(run_id: str, scenes: list) -> dict:
    """Saves the reviewed storyboard edits (prompts, narration, durations
    clamped to 3–6 s as the generator expects)."""
    rd = run_dir(run_id)
    with run_lock(run_id):
        st = cp.load_run_state(rd)
        if st.storyboard_reviewed and any(st.stages[k]["status"] == "running" for k in GEN_STAGES):
            raise ServiceError("Generation is running — wait for it to finish.")
        sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
        by_n = {s["scene_number"]: s for s in sb["scenes"]}
        changed = False
        for e in scenes or []:
            s = by_n.get(int(e.get("scene_number", -1)))
            if not s:
                continue
            for k in EDITABLE:
                if k not in e or e[k] is None:
                    continue
                v = max(3.0, min(6.0, float(e[k]))) if k == "duration_seconds" else str(e[k]).strip()
                if s.get(k) != v:
                    s[k] = v
                    changed = True
                    if k == "image_prompt":            # a new prompt needs a new keyframe and clip
                        s.pop("keyframe_path", None)
                        s.pop("clip_path", None)
                    elif k == "video_motion_prompt":
                        s.pop("clip_path", None)
                    elif k == "narration_text":
                        s.pop("narration_path", None)
        if changed:
            (rd / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
            # anything already generated must be redone for the edited scenes
            st.storyboard_reviewed = False
            for k in GEN_STAGES:
                if st.stages[k]["status"] == "done":
                    st.stages[k] = {"status": "pending", "timestamp": None, "error": None, "qc": None}
            cp.save_run_state(rd, st)
    return state(run_id)


def _clamp_durations(rd: Path) -> None:
    """Every scene 3–6 s before generating (the clip model's range), as the
    review step always enforced — the LLM sometimes proposes longer scenes."""
    path = rd / "storyboard.json"
    sb = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for s in sb.get("scenes", []):
        d = max(3.0, min(6.0, float(s.get("duration_seconds") or 4.0)))
        if d != s.get("duration_seconds"):
            s["duration_seconds"] = d
            changed = True
    if changed:
        path.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")


def approve_and_generate(run_id: str, progress=None) -> dict:
    """The review gate: approve, then keyframes -> clips -> narration ->
    subtitles -> edit, each stage resuming what already exists."""
    rd = run_dir(run_id)
    say = progress or (lambda f, m: None)
    with run_lock(run_id):
        st = cp.load_run_state(rd)
        if st.stages["storyboard"]["status"] != "done":
            raise ServiceError("The storyboard isn't ready.")
        _clamp_durations(rd)
        if st.stages["keyframes"]["status"] != "done" or st.stages["clips"]["status"] != "done":
            ensure_comfyui(say)
        st = cp.approve_storyboard(rd, st)
        done = 0.0
        funcs = {"keyframes": cp.run_keyframes, "clips": cp.run_clips, "narration": cp.run_narration,
                 "subtitles": cp.run_subtitles, "edit": cp.run_edit}
        for name in GEN_STAGES:
            say(0.02 + 0.96 * done, f"{STAGE_LABELS[name]}…")
            st = funcs[name](rd, st)
            if st.stages[name]["status"] != "done":
                raise ServiceError(_stage_error(st, [name]) or f"{STAGE_LABELS[name]} failed")
            done += STAGE_WEIGHTS[name]
    say(1.0, "Done")
    final = rd / "final.mp4"
    return {"url": svc._versioned(final), "run_id": run_id}


def recent(limit: int = 8) -> list:
    out = []
    root = svc.RUNS_ROOT
    if not root.exists():
        return out
    dirs = [d for d in root.iterdir() if d.is_dir() and CREATE_ID_RE.match(d.name) and (d / "run_state.json").exists()]
    for d in sorted(dirs, key=lambda d: (d / "run_state.json").stat().st_mtime, reverse=True)[:limit]:
        try:
            st = cp.load_run_state(d)
        except Exception:
            continue
        status = "video ready" if (d / "final.mp4").exists() else (
            "storyboard to review" if st.stages["storyboard"]["status"] == "done" else st.stages["script"]["status"])
        out.append({"run_id": d.name, "prompt": st.prompt, "aspect": st.aspect_ratio, "status": status,
                    "updated": datetime.fromtimestamp((d / "run_state.json").stat().st_mtime).isoformat(timespec="minutes")})
    return out
