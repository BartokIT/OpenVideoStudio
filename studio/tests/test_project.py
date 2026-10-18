"""Tests for core/project.py (save / load a Media Remix project) and the
project round trip through the editor service."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pipeline
import project


def _run_with_plan(tmp_path, files):
    runs = tmp_path / "runs"
    state = pipeline.new_run(runs, tmp_path, "cinematic", 90.0, None, "folder")
    run_dir = pipeline.run_dir_for(runs, state.run_id)
    shots = []
    for i, f in enumerate(files):
        shots.append({"shot_id": f"s_{i:04d}", "asset_id": f"a{i}", "asset_path": str(f), "relative_path": f.name,
                      "type": "image", "chapter_id": 0, "order": i, "enabled": True, "duration": 4.0 + i,
                      "reason": "base", "quality_score": 60.0, "timestamp": "2020-01-01T00:00:00",
                      "title_text": "Nonna" if i == 1 else None, "transition": "glitch" if i == 2 else None,
                      "motion": "pan_left" if i == 0 else None})
    plan = {"shots": shots, "chapters": [{"chapter_id": 0, "title": "Chapter 1 · Mare"}], "total_planned_duration": 15.0}
    (run_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    state.render_options = {"look": "cinematic", "title": "Estate", "music_preset": "gentle_piano", "beat_sync": False,
                            "music_volume": 0.3, "music_credit_on": True}
    state.bgm_path = None
    for st in ("scan", "score", "plan"):
        state.stages[st]["status"] = "done"
    pipeline.save_run_state(run_dir, state)
    return runs, run_dir, state


def test_save_and_load_reuses_origin_run_and_flags_missing_files(tmp_path):
    files = [tmp_path / f"p{i}.jpg" for i in range(3)]
    for f in files:
        f.write_bytes(b"x")
    runs, run_dir, state = _run_with_plan(tmp_path, files)
    path = project.save_project(run_dir, state, tmp_path / "projects" / "estate.ovsp.json", "Estate 1990")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == project.FORMAT and data["name"] == "Estate 1990"
    assert data["plan"]["shots"][2]["transition"] == "glitch" and data["render_options"]["title"] == "Estate"
    assert project.project_name(path) == "Estate 1990"
    assert [p.name for p in project.list_projects(tmp_path / "projects")] == ["estate.ovsp.json"]

    # edit the live plan, then delete one photo: loading restores the saved plan and disables the missing shot
    (run_dir / "plan.json").write_text(json.dumps({"shots": [], "chapters": []}), encoding="utf-8")
    files[1].unlink()
    out_dir, st, report = project.load_project(path, runs)
    assert out_dir == run_dir and report["reused_run"] is True and report["missing"] == ["p1.jpg"]
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert [s["shot_id"] for s in plan["shots"]] == ["s_0000", "s_0001", "s_0002"]
    assert plan["shots"][1]["enabled"] is False and plan["shots"][1]["reason"] == "missing_file"
    assert plan["shots"][0]["motion"] == "pan_left" and plan["total_planned_duration"] == 10.0
    assert st.render_options["title"] == "Estate" and st.style == "cinematic" and st.plan_reviewed is False
    assert all(st.stages[k]["status"] == "done" for k in ("scan", "score", "plan"))
    assert st.stages["render"]["status"] == "pending"


def test_load_into_fresh_run_when_origin_is_gone(tmp_path):
    files = [tmp_path / "a.jpg"]
    files[0].write_bytes(b"x")
    runs, run_dir, state = _run_with_plan(tmp_path, files)
    path = project.save_project(run_dir, state, tmp_path / "x.ovsp.json", "X")
    import shutil
    shutil.rmtree(run_dir)
    out_dir, st, report = project.load_project(path, runs)
    assert out_dir.exists() and (out_dir / "run_state.json").exists() and report["reused_run"] is False
    assert st.source_folder == str(tmp_path.resolve()) and st.target_duration_seconds == 90.0 and st.sort_mode == "folder"
    assert json.loads((out_dir / "plan.json").read_text(encoding="utf-8"))["shots"][0]["asset_path"] == str(files[0])


def test_read_project_rejects_other_files(tmp_path):
    bad = tmp_path / "bad.ovsp.json"
    bad.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        project.read_project(bad)
