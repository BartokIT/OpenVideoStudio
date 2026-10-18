"""Tests for core/create_service.py (AI creation in the editor) with the
LLM and GPU stages mocked: the configured model reaches the pipeline, the
review gate holds, scene edits invalidate what was generated, ComfyUI is
started only when needed, and failures surface as readable errors."""
from __future__ import annotations

import json

import pytest

import create_service as cs
import creative.pipeline as cp
import studio_service as svc


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cs, "_reachable", lambda url, timeout=2.0: True)
    return tmp_path / "runs"


def _fake_storyboard(n=3):
    return {"title": "Echoes", "scenes": [
        {"scene_number": i + 1, "image_prompt": f"image {i + 1}", "video_motion_prompt": "slow push-in",
         "narration_text": f"line {i + 1}", "duration_seconds": 4.0, "mood": "calm"} for i in range(n)]}


def _fake_script_and_storyboard(monkeypatch, fail_script=False):
    def run_script(rd, state, force=False):
        if fail_script:
            cp._mark(state, "script", "failed", error="Ollama is not reachable\ntraceback…")
        else:
            (rd / "script.json").write_text("{}", encoding="utf-8")
            cp._mark(state, "script", "done", qc={"scene_count": 3})
        cp.save_run_state(rd, state)
        return state

    def run_storyboard(rd, state, force=False):
        (rd / "storyboard.json").write_text(json.dumps(_fake_storyboard()), encoding="utf-8")
        cp._mark(state, "storyboard", "done", qc={"scene_count": 3})
        cp.save_run_state(rd, state)
        return state

    monkeypatch.setattr(cp, "run_script", run_script)
    monkeypatch.setattr(cp, "run_storyboard", run_storyboard)


def test_configured_ollama_model_reads_config_toml(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[providers]\nollama_model = "sentinel-model:1b"\n', encoding="utf-8")
    monkeypatch.setattr(svc, "CONFIG_PATH", cfg)
    assert cs.configured_ollama_model() == "sentinel-model:1b"
    cfg.write_text("[providers]\n", encoding="utf-8")
    assert cs.configured_ollama_model() == "qwen3:8b"


def test_create_passes_the_configured_model_and_stops_at_review(runs, tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[providers]\nollama_model = "sentinel-model:1b"\n', encoding="utf-8")
    monkeypatch.setattr(svc, "CONFIG_PATH", cfg)
    _fake_script_and_storyboard(monkeypatch)
    run_id = cs.create("A lighthouse at night", 20, "16:9", "noir", "en")
    st = cs.state(run_id)
    assert st["llm_model"] == "sentinel-model:1b" and st["aspect"] == "16:9" and st["style"] == "noir"
    assert not st["reviewed"] and st["title"] == "Echoes" and len(st["scenes"]) == 3
    assert [s["status"] for s in st["stages"]][:3] == ["done", "done", "pending"]
    assert st["final"] is None and st["total"] == 12.0
    assert any(r["run_id"] == run_id and r["status"] == "storyboard to review" for r in cs.recent())


def test_create_reports_a_readable_error(runs, monkeypatch):
    _fake_script_and_storyboard(monkeypatch, fail_script=True)
    with pytest.raises(svc.ServiceError, match="Script failed: Ollama is not reachable$"):
        cs.create("x", 15, "9:16", "", "en")
    with pytest.raises(svc.ServiceError, match="Describe"):
        cs.create("   ", 15, "9:16", "", "en")


def test_create_refuses_when_ollama_is_down(runs, monkeypatch):
    monkeypatch.setattr(cs, "_reachable", lambda url, timeout=2.0: False)
    with pytest.raises(svc.ServiceError, match="Ollama isn't reachable"):
        cs.create("x", 15, "9:16", "", "en")


def test_scene_edits_are_clamped_and_invalidate_generated_media(runs, monkeypatch):
    _fake_script_and_storyboard(monkeypatch)
    run_id = cs.create("x", 15, "9:16", "", "en")
    rd = cs.run_dir(run_id)
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    for s in sb["scenes"]:
        s["keyframe_path"], s["clip_path"], s["narration_path"] = "k.png", "c.mp4", "n.mp3"
    (rd / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")
    state = cp.load_run_state(rd)
    state.storyboard_reviewed = True
    for k in cs.GEN_STAGES:
        cp._mark(state, k, "done")
    cp.save_run_state(rd, state)

    st = cs.update_scenes(run_id, [{"scene_number": 1, "image_prompt": "a red boat", "duration_seconds": 9},
                                   {"scene_number": 2, "narration_text": "new line"},
                                   {"scene_number": 99, "image_prompt": "ignored"}])
    sb = {s["scene_number"]: s for s in json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))["scenes"]}
    assert sb[1]["image_prompt"] == "a red boat" and sb[1]["duration_seconds"] == 6.0
    assert "keyframe_path" not in sb[1] and "clip_path" not in sb[1]          # regenerate image and clip
    assert sb[2]["keyframe_path"] == "k.png" and "narration_path" not in sb[2]
    assert sb[3]["clip_path"] == "c.mp4"                                    # untouched scene reused
    assert not st["reviewed"] and all(s["status"] == "pending" for s in st["stages"][2:])


def test_a_moved_run_finds_its_media_by_name(runs, monkeypatch, tmp_path):
    _fake_script_and_storyboard(monkeypatch)
    run_id = cs.create("x", 15, "9:16", "", "en")
    rd = cs.run_dir(run_id)
    (rd / "keyframes").mkdir()
    (rd / "keyframes" / "scene_01.png").write_bytes(b"png")
    old = tmp_path / "old_install" / "runs" / run_id               # where the run used to live
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    sb["scenes"][0]["keyframe_path"] = str(old / "keyframes" / "scene_01.png")
    sb["scenes"][1]["keyframe_path"] = str(old / "keyframes" / "scene_02.png")   # really missing
    (rd / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")

    scenes = cs.state(run_id)["scenes"]
    assert scenes[0]["keyframe"] and "scene_01.png" in scenes[0]["keyframe"]
    assert scenes[1]["keyframe"] is None

    cs._relocate_media(rd)
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    assert sb["scenes"][0]["keyframe_path"] == str(rd / "keyframes" / "scene_01.png")
    assert sb["scenes"][1]["keyframe_path"] == str(old / "keyframes" / "scene_02.png")


def test_generate_approves_starts_comfy_only_when_needed_and_runs_stages(runs, monkeypatch, tmp_path):
    _fake_script_and_storyboard(monkeypatch)
    run_id = cs.create("x", 15, "9:16", "", "en")
    rd = cs.run_dir(run_id)
    calls = []
    monkeypatch.setattr(cs, "ensure_comfyui", lambda progress=None: calls.append("comfy"))

    def stage(name):
        def run(rd_, state, force=False):
            assert state.storyboard_reviewed, "review gate bypassed"
            calls.append(name)
            if name == "edit":
                (rd_ / "final.mp4").write_bytes(b"\0" * 2000)
            cp._mark(state, name, "done")
            cp.save_run_state(rd_, state)
            return state
        return run

    for name in cs.GEN_STAGES:
        monkeypatch.setattr(cp, f"run_{name}", stage(name))
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    sb["scenes"][0]["duration_seconds"], sb["scenes"][1]["duration_seconds"] = 6.73, 2.1   # LLM proposals
    (rd / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")
    progress = []
    res = cs.approve_and_generate(run_id, lambda f, m: progress.append(f))
    durations = [s["duration_seconds"] for s in json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))["scenes"]]
    assert durations == [6.0, 3.0, 4.0]                                  # clamped to 3–6 s at approval
    assert calls == ["comfy", "keyframes", "clips", "narration", "subtitles", "edit"]
    assert res["url"].startswith("/files?path=") or "final.mp4" in res["url"]
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert cs.state(run_id)["final"] is not None

    calls.clear()
    cs.approve_and_generate(run_id)   # keyframes and clips done: ComfyUI not needed
    assert "comfy" not in calls


def test_generate_stops_at_a_failed_stage(runs, monkeypatch):
    _fake_script_and_storyboard(monkeypatch)
    run_id = cs.create("x", 15, "9:16", "", "en")
    monkeypatch.setattr(cs, "ensure_comfyui", lambda progress=None: None)

    def failing(rd, state, force=False):
        cp._mark(state, "keyframes", "failed", error="incomplete_keyframes")
        cp.save_run_state(rd, state)
        return state

    monkeypatch.setattr(cp, "run_keyframes", failing)
    monkeypatch.setattr(cp, "run_clips", lambda *a, **k: pytest.fail("clips must not run after a failure"))
    with pytest.raises(svc.ServiceError, match="Keyframes failed: incomplete_keyframes"):
        cs.approve_and_generate(run_id)


def test_comfy_portable_dir_and_missing_install(tmp_path, monkeypatch):
    portable = tmp_path / "ComfyUI_windows_portable"
    (portable / "python_embeded").mkdir(parents=True)
    (portable / "python_embeded" / "python.exe").write_bytes(b"")
    (portable / "ComfyUI").mkdir()
    (portable / "ComfyUI" / "main.py").write_text("")
    monkeypatch.delenv("COMFYUI_PORTABLE", raising=False)
    monkeypatch.setenv("COMFYUI_ROOT", str(portable / "ComfyUI"))
    assert cs.comfy_portable_dir() == portable
    monkeypatch.setenv("COMFYUI_ROOT", str(tmp_path / "nowhere" / "ComfyUI"))
    assert cs.comfy_portable_dir() is None
    monkeypatch.setattr(cs, "_reachable", lambda url, timeout=2.0: False)
    with pytest.raises(svc.ServiceError, match="can't be started automatically"):
        cs.ensure_comfyui()


def test_run_ids_are_validated(runs):
    with pytest.raises(svc.ServiceError):
        cs.run_dir("../../etc")
    with pytest.raises(svc.ServiceError):
        cs.run_dir("create_missing")
