"""Stage-based, resumable orchestration: scan -> score -> plan -> [review
gate] -> render -> audio/final.

Deliberately NOT a "Full Auto" black box: run_render() is never called
automatically after run_plan() finishes. The caller (the editor) must present
plan.json for review and get an explicit go-ahead first. This mirrors a
safety pattern found in an earlier private orchestrator, which
deliberately disabled its own fully-automatic mode so QC decisions
couldn't be skipped by automation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import scan as scan_mod
import score as score_mod
import plan as plan_mod
import render as render_mod
import audio as audio_mod

STAGES = ["scan", "score", "plan", "render", "audio"]


@dataclass
class RunState:
    run_id: str
    source_folder: str
    style: str
    target_duration_seconds: float
    bgm_path: Optional[str]
    created_at: str
    updated_at: str
    current_stage: Optional[str] = None
    stages: dict = field(default_factory=lambda: {
        s: {"status": "pending", "timestamp": None, "error": None, "qc": None} for s in STAGES
    })
    plan_reviewed: bool = False
    sort_mode: str = "date"  # see plan.PlanConfig.sort_mode
    # pro engine options (look, titles, transitions, facemorph, quality,
    # music...) — see core/pro/timeline.py DEFAULT_OPTIONS
    render_options: dict = field(default_factory=dict)


RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}


def set_render_options(run_dir: Path, state: RunState, options: dict) -> RunState:
    """Stores render options and re-arms render+audio: the plan table may
    have been edited even when the options didn't change."""
    state.render_options = dict(options)
    for s in ("render", "audio"):
        state.stages[s] = {"status": "pending", "timestamp": None, "error": None, "qc": None}
    save_run_state(Path(run_dir), state)
    return state


def run_dir_for(runs_root: Path, run_id: str) -> Path:
    return Path(runs_root) / run_id


def _now() -> str:
    return datetime.now().isoformat()


def new_run(runs_root: Path, source_folder: Path, style: str, target_duration_seconds: float,
            bgm_path: Optional[Path] = None, sort_mode: str = "date") -> RunState:
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    rd = run_dir_for(runs_root, run_id)
    n = 1
    while rd.exists():  # two runs started within the same second must not share a directory
        n += 1
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S") + f"_{n}"
        rd = run_dir_for(runs_root, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "logs").mkdir(exist_ok=True)

    state = RunState(
        run_id=run_id, source_folder=str(Path(source_folder).resolve()), style=style,
        target_duration_seconds=target_duration_seconds,
        bgm_path=str(bgm_path) if bgm_path else None,
        created_at=_now(), updated_at=_now(), sort_mode=sort_mode,
    )
    save_run_state(rd, state)
    return state


def load_run_state(run_dir: Path) -> RunState:
    data = json.loads((Path(run_dir) / "run_state.json").read_text(encoding="utf-8"))
    return RunState(**data)


def save_run_state(run_dir: Path, state: RunState) -> None:
    state.updated_at = _now()
    Path(run_dir, "run_state.json").write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log(run_dir: Path, stage: str, message: str) -> None:
    log_path = Path(run_dir) / "logs" / f"{stage}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{_now()}] {message}\n")


def _mark(state: RunState, stage: str, status: str, error: Optional[str] = None, qc: Optional[dict] = None) -> None:
    state.stages[stage] = {"timestamp": _now(), "status": status, "error": error, "qc": qc}
    state.current_stage = stage


def _stage_ok(state: RunState, stage: str) -> bool:
    return state.stages.get(stage, {}).get("status") == "done"


def run_scan(run_dir: Path, state: RunState, force: bool = False) -> RunState:
    run_dir = Path(run_dir)
    if _stage_ok(state, "scan") and not force:
        return state
    _mark(state, "scan", "running")
    save_run_state(run_dir, state)
    try:
        assets_path = run_dir / "assets.json"
        scan_mod.scan(Path(state.source_folder), assets_path)
        payload = json.loads(assets_path.read_text(encoding="utf-8"))
        count = payload["count"]
        qc = {"asset_count": count}
        if count == 0:
            _mark(state, "scan", "failed", error="no_media_found", qc=qc)
        else:
            _mark(state, "scan", "done", qc=qc)
        _log(run_dir, "scan", f"found {count} assets")
    except Exception as e:
        _mark(state, "scan", "failed", error=f"{e}\n{traceback.format_exc()}")
        _log(run_dir, "scan", f"FAILED: {e}")
    save_run_state(run_dir, state)
    return state


def run_score(run_dir: Path, state: RunState, force: bool = False) -> RunState:
    run_dir = Path(run_dir)
    if not _stage_ok(state, "scan"):
        _mark(state, "score", "failed", error="scan_not_done")
        save_run_state(run_dir, state)
        return state
    if _stage_ok(state, "score") and not force:
        return state
    _mark(state, "score", "running")
    save_run_state(run_dir, state)
    try:
        assets_path = run_dir / "assets.json"
        score_mod.score_assets(assets_path, assets_path)
        payload = json.loads(assets_path.read_text(encoding="utf-8"))
        scored = [a for a in payload["assets"] if not a.get("error") and not a.get("score_error")]
        qc = {"scored_count": len(scored), "total_count": len(payload["assets"])}
        if not scored:
            _mark(state, "score", "failed", error="nothing_scored_successfully", qc=qc)
        else:
            _mark(state, "score", "done", qc=qc)
        _log(run_dir, "score", f"scored {len(scored)}/{len(payload['assets'])} assets")
    except Exception as e:
        _mark(state, "score", "failed", error=f"{e}\n{traceback.format_exc()}")
        _log(run_dir, "score", f"FAILED: {e}")
    save_run_state(run_dir, state)
    return state


def run_plan(run_dir: Path, state: RunState, force: bool = False) -> RunState:
    run_dir = Path(run_dir)
    if not _stage_ok(state, "score"):
        _mark(state, "plan", "failed", error="score_not_done")
        save_run_state(run_dir, state)
        return state
    if _stage_ok(state, "plan") and not force:
        return state
    _mark(state, "plan", "running")
    save_run_state(run_dir, state)
    try:
        assets_path = run_dir / "assets.json"
        plan_path = run_dir / "plan.json"
        cfg = plan_mod.PlanConfig(target_duration_seconds=state.target_duration_seconds, sort_mode=state.sort_mode)
        plan_mod.write_plan(assets_path, plan_path, cfg)
        p = json.loads(plan_path.read_text(encoding="utf-8"))
        qc = {
            "shot_count": len(p["shots"]),
            "enabled_shot_count": sum(1 for s in p["shots"] if s["enabled"]),
            "total_planned_duration": p["total_planned_duration"],
        }
        if qc["enabled_shot_count"] == 0:
            _mark(state, "plan", "failed", error="no_enabled_shots", qc=qc)
        else:
            _mark(state, "plan", "done", qc=qc)
        state.plan_reviewed = False  # every new/rerun plan needs re-review
        _log(run_dir, "plan", f"{qc}")
    except Exception as e:
        _mark(state, "plan", "failed", error=f"{e}\n{traceback.format_exc()}")
        _log(run_dir, "plan", f"FAILED: {e}")
    save_run_state(run_dir, state)
    return state


def approve_plan(run_dir: Path, state: RunState) -> RunState:
    """Explicit review-gate confirmation. render() refuses to run without this."""
    state.plan_reviewed = True
    save_run_state(Path(run_dir), state)
    return state


def _render_cfg(state: RunState) -> "render_mod.RenderConfig":
    cfg = render_mod.RenderConfig.from_toml(Path(__file__).resolve().parent.parent / "config.toml")
    res = RESOLUTIONS.get(str(state.render_options.get("resolution", "")).lower())
    if res:
        cfg.width, cfg.height = res
        if res[1] >= 2160:
            cfg.bitrate, cfg.maxrate, cfg.bufsize = "40M", "60M", "80M"
    return cfg


def _render_options(state: RunState) -> dict:
    opts = dict(state.render_options)
    opts.setdefault("look", state.style)
    return opts


def rhythm_for(run_dir: Path, bgm_path: Path) -> dict:
    """audio.analyze_rhythm with a per-run cache keyed by the music file's
    size+mtime (the analysis takes seconds; the editor asks on every rebuild)."""
    bgm_path = Path(bgm_path)
    try:
        st = bgm_path.stat()
        key = f"{bgm_path}|{st.st_size}|{int(st.st_mtime)}|v{audio_mod.RHYTHM_VERSION}"
    except OSError:
        return {}
    cache = Path(run_dir) / "render_work" / "rhythm.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data["rhythm"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    rhythm = audio_mod.analyze_rhythm(bgm_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "rhythm": rhythm}), encoding="utf-8")
    return rhythm


def beats_for(run_dir: Path, bgm_path: Path) -> list[float]:
    return rhythm_for(run_dir, bgm_path).get("beats", [])


def music_sync_mode(state: RunState) -> Optional[str]:
    """None when cuts don't follow the music (no music, or "Cut on the
    beat" off); otherwise one of audio.SYNC_MODES. Runs saved before the
    modes existed keep the old gentle nudge."""
    if not (state.bgm_path and state.render_options.get("beat_sync")):
        return None
    mode = state.render_options.get("music_sync") or "nudge"
    return mode if mode in audio_mod.SYNC_MODES else "nudge"


def _beat_synced_plan(run_dir: Path, state: RunState) -> Path:
    """When music is set and "Cut on the beat" is on, moves the cut points
    onto the music (see audio.align_plan_to_music) into plan_render.json.
    plan.json — the reviewed plan — is never modified."""
    plan_path = run_dir / "plan.json"
    mode = music_sync_mode(state)
    if not mode:
        return plan_path
    try:
        from pro.timeline import text_min_holds

        rhythm = rhythm_for(run_dir, Path(state.bgm_path))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        holds = text_min_holds(plan, _render_options(state))
        synced = audio_mod.align_plan_to_music(plan, rhythm, mode, holds)
        out = run_dir / "plan_render.json"
        out.write_text(json.dumps(synced, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(run_dir, "render", f"music sync ({mode}): {rhythm.get('tempo')} BPM, "
                                f"{len(rhythm.get('beats', []))} beats, {len(rhythm.get('accents', []))} accents")
        return out
    except Exception as e:
        _log(run_dir, "render", f"music sync skipped: {e}")
        return plan_path


def prepare_editor(run_dir: Path, state: RunState, progress=None, thumbs: bool = True) -> dict:
    """Builds what the editor UI shows: thumbnails for every shot and the
    960x540 edit timeline (same build_timeline the render uses, with the
    current render options and beat sync). Returns {"timeline", "thumbs"}."""
    from pro import preview as pro_preview

    run_dir = Path(run_dir)
    work_dir = run_dir / "render_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda f, m: None)
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    cfg = _render_cfg(state)
    out: dict = {"thumbs": {}}
    if thumbs:
        say(0.0, "Thumbnails")
        out["thumbs"] = pro_preview.thumbnails(plan["shots"], work_dir, workers=6,
                                               progress=lambda f, m: say(0.3 * f, m))
    out["audio"] = None
    if state.bgm_path and Path(state.bgm_path).exists():
        say(0.3, "Analysing music")
        try:
            rhythm = rhythm_for(run_dir, Path(state.bgm_path))
        except Exception as e:
            _log(run_dir, "render", f"rhythm analysis skipped: {e}")
            rhythm = {}
        out["audio"] = pro_preview.bgm_analysis(Path(state.bgm_path), work_dir, rhythm.get("beats", []),
                                                rhythm=rhythm)
    plan_path = _beat_synced_plan(run_dir, state)
    plan_for_tl = json.loads(plan_path.read_text(encoding="utf-8"))
    tl, _ = pro_preview.build_edit_timeline(plan_for_tl, work_dir, _render_options(state), cfg,
                                            progress=lambda f, m: say(0.4 + 0.6 * f, m))
    out["timeline"] = tl
    say(1.0, "Timeline ready")
    return out


def render_preview(run_dir: Path, state: RunState, seconds: float = 15.0, progress=None) -> Optional[Path]:
    """Fast low-res render of the first shots with the current options, so
    a look can be judged in seconds before committing to the full render."""
    run_dir = Path(run_dir)
    cfg = _render_cfg(state)
    cfg.width, cfg.height = 960, 540
    out = run_dir / "preview.mp4"
    plan_path = _beat_synced_plan(run_dir, state)  # the preview must cut to the music like the final
    result = render_mod.render_plan(plan_path, run_dir / "render_work", out, cfg, None,
                                    options=_render_options(state), progress=progress, preview_seconds=seconds)
    _log(run_dir, "render", f"preview: {result.get('status')} {result.get('error') or ''}")
    return out if result.get("status") == "ok" else None


def run_render(run_dir: Path, state: RunState, force: bool = False, progress=None) -> RunState:
    run_dir = Path(run_dir)
    if not _stage_ok(state, "plan"):
        _mark(state, "render", "failed", error="plan_not_done")
        save_run_state(run_dir, state)
        return state
    if not state.plan_reviewed:
        _mark(state, "render", "failed", error="plan_not_reviewed")
        save_run_state(run_dir, state)
        return state
    if _stage_ok(state, "render") and not force:
        return state
    _mark(state, "render", "running")
    save_run_state(run_dir, state)
    try:
        plan_path = _beat_synced_plan(run_dir, state)
        work_dir = run_dir / "render_work"
        output_path = run_dir / "output.mp4"
        render_json_path = run_dir / "render.json"
        cfg = _render_cfg(state)
        result = render_mod.render_plan(plan_path, work_dir, output_path, cfg, render_json_path,
                                        options=_render_options(state), progress=progress)
        qc = {"succeeded": result["succeeded"], "failed": result["failed"], "status": result["status"]}
        for k in ("elapsed_seconds", "duration", "encoder"):
            if k in result:
                qc[k] = result[k]
        if result["status"] != "ok":
            _mark(state, "render", "failed", error=result.get("error") or "render_failed", qc=qc)
        else:
            _mark(state, "render", "done", qc=qc)
        _log(run_dir, "render", f"{qc}")
    except Exception as e:
        _mark(state, "render", "failed", error=f"{e}\n{traceback.format_exc()}")
        _log(run_dir, "render", f"FAILED: {e}")
    save_run_state(run_dir, state)
    return state


def run_audio(run_dir: Path, state: RunState, force: bool = False) -> RunState:
    run_dir = Path(run_dir)
    if not _stage_ok(state, "render"):
        _mark(state, "audio", "failed", error="render_not_done")
        save_run_state(run_dir, state)
        return state
    if _stage_ok(state, "audio") and not force:
        return state
    _mark(state, "audio", "running")
    save_run_state(run_dir, state)
    try:
        output_path = run_dir / "output.mp4"
        final_path = run_dir / "final.mp4"
        cfg = audio_mod.AudioConfig.from_toml(Path(__file__).resolve().parent.parent / "config.toml")
        if state.render_options.get("music_volume") is not None:
            cfg.bgm_volume = float(state.render_options["music_volume"])
        bgm_path = Path(state.bgm_path) if state.bgm_path else None
        ok, log = audio_mod.mix_bgm(output_path, bgm_path, final_path, cfg)
        qc = {"final_exists": final_path.exists()}
        if not ok or not final_path.exists():
            _mark(state, "audio", "failed", error=log or "mix_failed", qc=qc)
        else:
            _mark(state, "audio", "done", qc=qc)
        _log(run_dir, "audio", f"{qc}")
    except Exception as e:
        _mark(state, "audio", "failed", error=f"{e}\n{traceback.format_exc()}")
        _log(run_dir, "audio", f"FAILED: {e}")
    save_run_state(run_dir, state)
    return state


def run_to_plan(run_dir: Path, state: RunState) -> RunState:
    """Runs scan -> score -> plan, stopping at the review gate. Resumable:
    stages already marked 'done' are skipped."""
    state = run_scan(run_dir, state)
    if not _stage_ok(state, "scan"):
        return state
    state = run_score(run_dir, state)
    if not _stage_ok(state, "score"):
        return state
    state = run_plan(run_dir, state)
    return state


def run_after_review(run_dir: Path, state: RunState, progress=None) -> RunState:
    """Runs render -> audio. Only proceeds if the plan has been explicitly
    approved via approve_plan()."""
    state = run_render(run_dir, state, progress=progress)
    if not _stage_ok(state, "render"):
        return state
    state = run_audio(run_dir, state)
    return state


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the V1 pipeline end-to-end (CLI/testing use)")
    parser.add_argument("source_folder", type=Path)
    parser.add_argument("--runs-root", type=Path, default=Path(__file__).resolve().parent.parent / "runs")
    parser.add_argument("--style", default="Family Memory")
    parser.add_argument("--target-seconds", type=float, default=180.0)
    parser.add_argument("--bgm", type=Path, default=None)
    parser.add_argument("--sort", choices=["date", "folder"], default="date")
    parser.add_argument("--auto-approve", action="store_true", help="skip manual review gate (CLI testing only)")
    args = parser.parse_args()

    st = new_run(args.runs_root, args.source_folder, args.style, args.target_seconds, args.bgm, args.sort)
    rd = run_dir_for(args.runs_root, st.run_id)
    st = run_to_plan(rd, st)
    print(json.dumps(st.stages, indent=2))

    if args.auto_approve and _stage_ok(st, "plan"):
        st = approve_plan(rd, st)
        st = run_after_review(rd, st)
        print(json.dumps(st.stages, indent=2))
