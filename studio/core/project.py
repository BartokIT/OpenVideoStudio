"""Save / load a Media Remix project.

A project file (<name>.ovsp.json) is a snapshot of everything the editor
needs: the source folder and its ordering, the reviewed plan (with every
edit: order, durations, captions, transitions, camera motions), the
render options (look, titles, transitions, music, export) and the music
file. Loading restores the plan into the original run directory when it
still exists (so thumbnails and prepared canvases are reused) or into a
fresh run otherwise. Media files are referenced by path, not copied: a
shot whose file has gone missing is disabled and reported.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import pipeline

FORMAT = "ovsp/1"
SUFFIX = ".ovsp.json"


def slug(name: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", name or "", flags=re.UNICODE).strip().replace(" ", "_")
    return s[:60] or "project"


def list_projects(projects_dir: Path) -> list[Path]:
    projects_dir = Path(projects_dir)
    if not projects_dir.exists():
        return []
    return sorted((p for p in projects_dir.iterdir() if p.name.endswith(SUFFIX)),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def project_name(path: Path) -> str:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("name") or Path(path).name[:-len(SUFFIX)]
    except (OSError, json.JSONDecodeError):
        return Path(path).name[:-len(SUFFIX)]


def save_project(run_dir: Path, state: pipeline.RunState, path: Path, name: str) -> Path:
    run_dir, path = Path(run_dir), Path(path)
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    data = {
        "format": FORMAT,
        "name": name or path.name[:-len(SUFFIX)],
        "saved_at": datetime.now().isoformat(),
        "app": "OpenVideoStudio",
        "origin_run_id": state.run_id,
        "source_folder": state.source_folder,
        "sort_mode": state.sort_mode,
        "target_duration_seconds": state.target_duration_seconds,
        "bgm_path": state.bgm_path,
        "render_options": dict(state.render_options),
        "plan": plan,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_project(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or "plan" not in data or "shots" not in data["plan"]:
        raise ValueError("Not an OpenVideoStudio project file.")
    return data


def load_project(path: Path, runs_root: Path) -> tuple[Path, pipeline.RunState, dict]:
    """Restores the project into a run directory and returns
    (run_dir, state, report). report = {"missing": [...names], "reused_run": bool}."""
    data = read_project(path)
    runs_root = Path(runs_root)
    origin = runs_root / str(data.get("origin_run_id") or "")
    reused = bool(data.get("origin_run_id")) and (origin / "run_state.json").exists()
    if reused:
        run_dir = origin
        state = pipeline.load_run_state(run_dir)
    else:
        state = pipeline.new_run(runs_root, Path(data["source_folder"]), data["render_options"].get("look", "family_memory"),
                                 float(data.get("target_duration_seconds") or 180.0),
                                 Path(data["bgm_path"]) if data.get("bgm_path") else None,
                                 data.get("sort_mode", "date"))
        run_dir = pipeline.run_dir_for(runs_root, state.run_id)

    plan = data["plan"]
    missing = []
    for s in plan["shots"]:
        if not Path(s["asset_path"]).exists():
            missing.append(Path(s["asset_path"]).name)
            if s.get("enabled"):
                s["enabled"] = False
                s["reason"] = "missing_file"
    plan["total_planned_duration"] = round(sum(s["duration"] for s in plan["shots"] if s["enabled"]), 2)
    (run_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "assets.json").touch(exist_ok=True)  # scan/score artefacts are not needed to render a saved plan

    state.source_folder = data.get("source_folder", state.source_folder)
    state.sort_mode = data.get("sort_mode", state.sort_mode)
    state.target_duration_seconds = float(data.get("target_duration_seconds") or state.target_duration_seconds)
    state.bgm_path = data.get("bgm_path") if data.get("bgm_path") and Path(data["bgm_path"]).exists() else None
    state.render_options = dict(data.get("render_options") or {})
    state.style = state.render_options.get("look", state.style)
    now = datetime.now().isoformat()
    for stage in ("scan", "score", "plan"):
        info = state.stages.get(stage) or {}
        if info.get("status") != "done":
            state.stages[stage] = {"timestamp": now, "status": "done", "error": None,
                                   "qc": {"restored_from": str(path)}}
    for stage in ("render", "audio"):
        state.stages[stage] = {"status": "pending", "timestamp": None, "error": None, "qc": None}
    state.plan_reviewed = False
    pipeline.save_run_state(run_dir, state)
    return run_dir, state, {"missing": missing, "reused_run": reused, "name": data.get("name", "")}


def state_summary(state: pipeline.RunState) -> dict:
    return asdict(state)
