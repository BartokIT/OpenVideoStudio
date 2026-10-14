"""Cutting to the music: rhythm analysis (tempo, bars, accents, energy),
align_plan_to_music in every mode, text holds that keep cuts on the beat,
beat-length transitions, and the pipeline wiring."""
from __future__ import annotations

import json

import pytest

import audio
import music
import pipeline
from pro import looks
from pro.timeline import build_timeline, text_min_holds


def _on_grid(t, step, tol=1e-3):
    return abs(t / step - round(t / step)) * step < tol


def _rhythm(duration=60.0, accents=None, energy=None):
    beats = [round(0.5 * k, 3) for k in range(1, int(duration / 0.5))]
    return {"tempo": 120.0, "beat": 0.5, "meter": 4, "beats": beats,
            "downbeats": [b for b in beats if _on_grid(b, 2.0)],
            "accents": accents or [], "energy": energy or [], "energy_step": 0.5, "duration": duration}


def _plan(durations, types=None, chapters=None):
    shots = []
    for i, d in enumerate(durations):
        shots.append({"shot_id": f"s{i}", "type": (types or {}).get(i, "image"), "asset_path": f"{i}.jpg",
                      "duration": d, "enabled": True, "chapter_id": (chapters or {}).get(i, 0), "order": i,
                      "reason": "base", "title_text": None})
    return {"shots": shots, "chapters": []}


def _cuts(plan):
    t, out = 0.0, []
    for s in plan["shots"]:
        if s["enabled"]:
            t += s["duration"]
            out.append(round(t, 3))
    return out


# ----------------------------------------------------------- analysis

def test_analyze_rhythm_on_a_real_track(tmp_path):
    wav = music.synthesize("soft_beat", tmp_path / "beat.wav", seconds=24.0)  # 100 BPM, kick on every beat
    r = audio.analyze_rhythm(wav)
    assert r["version"] == audio.RHYTHM_VERSION and abs(r["duration"] - 24.0) < 0.1
    assert len(r["beats"]) >= 20
    # 100 BPM = 0.6 s; trackers may lock to half/double time
    assert any(abs(r["beat"] - x) < 0.06 for x in (0.3, 0.6, 1.2)), r["beat"]
    assert r["meter"] in (3, 4)
    gaps = [b - a for a, b in zip(r["downbeats"], r["downbeats"][1:])]
    assert gaps and all(abs(g - r["meter"] * r["beat"]) < 0.25 for g in gaps[1:-1])
    assert r["accents"] and all(0.35 <= s <= 1.0 for _, s in r["accents"])
    assert len(r["accents"]) < 0.6 * len(r["beats"]) * (2 if r["beat"] < 0.45 else 1)   # accents are selective
    assert r["tempo"] <= 135
    assert r["energy"] and all(0.0 <= e <= 1.0 for e in r["energy"])


# ----------------------------------------------------------- alignment

def test_bars_mode_cuts_on_downbeats():
    out = audio.align_plan_to_music(_plan([4.3, 5.1, 3.4, 6.2]), _rhythm(), "bars")
    assert all(_on_grid(c, 2.0) for c in _cuts(out)), _cuts(out)
    assert out["music"]["mode"] == "bars" and out["music"]["beat"] == 0.5 and out["beat_aligned"]
    assert all("+music_bars" in s["reason"] for s in out["shots"])


def test_beats_mode_cuts_on_beats_close_to_the_plan():
    plan = _plan([4.3, 5.1, 3.4, 6.2])
    out = audio.align_plan_to_music(plan, _rhythm(), "beats")
    cuts = _cuts(out)
    assert all(_on_grid(c, 0.5) for c in cuts)
    for planned, got in zip(_cuts(plan), cuts):
        assert abs(planned - got) <= 1.0


def test_accents_pull_cuts_onto_strong_hits():
    out = audio.align_plan_to_music(_plan([3.5, 4.0]), _rhythm(accents=[[3.0, 1.0], [7.5, 0.9]]), "accents")
    assert _cuts(out)[:2] == [3.0, 7.5]


def test_follow_cuts_faster_when_the_music_is_loud():
    energy = [1.0] * 20 + [0.0] * 100          # loud for the first 10 s, then quiet
    out = audio.align_plan_to_music(_plan([4.0] * 6), _rhythm(energy=energy), "follow")
    d = [s["duration"] for s in out["shots"]]
    assert d[0] < 3.0
    starts = [0.0] + _cuts(out)[:-1]
    quiet = [s["duration"] for s, t0 in zip(out["shots"], starts) if t0 > 11]
    assert quiet and all(x > 5.0 for x in quiet)


def test_videos_are_never_stretched_and_text_holds_are_respected():
    plan = _plan([2.2, 2.0, 3.0], types={0: "video"})
    out = audio.align_plan_to_music(plan, _rhythm(), "bars", min_holds={"s1": 4.5})
    d = [s["duration"] for s in out["shots"]]
    assert d[0] <= 2.2 + 1e-6
    assert d[1] >= 4.5


def test_locked_duration_is_kept_to_the_nearest_beat():
    plan = _plan([3.2, 4.0])
    plan["shots"][0]["duration_locked"] = True
    out = audio.align_plan_to_music(plan, _rhythm(accents=[[2.0, 1.0]]), "accents")
    assert out["shots"][0]["duration"] == 3.0   # nearest beat, the strong hit at 2.0 is ignored


def test_chapter_changes_prefer_bars():
    plan = _plan([3.4, 3.4], chapters={1: 1})
    out = audio.align_plan_to_music(plan, _rhythm(), "beats")
    assert _cuts(out)[0] == 4.0   # 3.5 is nearer, but a chapter change lands on the bar


def test_music_shorter_than_the_film_loops_the_grid():
    out = audio.align_plan_to_music(_plan([4.1] * 8), _rhythm(duration=7.75), "beats")
    assert _cuts(out)[-1] > 20
    period = 7.75
    for c in _cuts(out):
        assert any(abs(c - (b + k * period)) < 1e-3 for k in range(6) for b in _rhythm(duration=7.75)["beats"]), c


def test_nudge_mode_is_the_old_behaviour_and_too_few_beats_is_a_no_op():
    plan = _plan([4.3, 5.1])
    assert audio.align_plan_to_music(plan, _rhythm(), "nudge") == audio.align_plan_to_beats(plan, _rhythm()["beats"])
    assert audio.align_plan_to_music(plan, {"beats": [1.0, 2.0]}, "bars") is plan


# ------------------------------------------------- timeline integration

def test_text_min_holds():
    plan = _plan([3.0] * 5, chapters={2: 1, 3: 1, 4: 2})
    holds = text_min_holds(plan, {"title": "T", "closing_text": "Fine", "chapter_titles": True})
    assert holds == {"s0": 6.0, "s2": 4.5, "s4": 5.5}
    assert text_min_holds(plan, {"chapter_titles": False, "music_credit": "x"}) == {"s4": 5.5}


def _meta():
    return {"canvas": "x.jpg", "canvas_w": 2400, "canvas_h": 1350, "mode": "crop", "faces": [], "landmarks": None}


def test_aligned_plan_keeps_its_cuts_and_transitions_last_half_beats():
    plan = _plan([4.3, 5.1, 3.4, 6.2, 4.4], chapters={3: 1})
    opts = {"look": "clean", "title": "Estate", "chapter_titles": True}
    out = audio.align_plan_to_music(plan, _rhythm(), "bars", text_min_holds(plan, opts))
    prepared = {s["shot_id"]: _meta() for s in out["shots"]}
    tl = build_timeline(out, prepared, opts, looks.get_look("clean"), 1280, 720, 25)
    assert [round(s["end"], 3) for s in tl["shots"]] == _cuts(out)   # no text hold pushed a cut off the bar
    assert tl["music"]["mode"] == "bars"
    for tr in tl["transitions"]:
        if tr["type"] != "cut":
            a, b = tl["shots"][tr["a"]], tl["shots"][tr["b"]]
            clamped = tr["duration"] >= 0.45 * min(a["duration"], b["duration"]) - 1e-3
            assert clamped or _on_grid(tr["duration"], 0.25), tr


# ---------------------------------------------------------- pipeline

def test_pipeline_uses_the_chosen_mode(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    state = pipeline.new_run(runs, tmp_path, "clean", 30.0, None, "folder")
    run_dir = pipeline.run_dir_for(runs, state.run_id)
    (run_dir / "plan.json").write_text(json.dumps(_plan([4.3, 5.1, 3.4])), encoding="utf-8")
    song = tmp_path / "song.wav"
    song.write_bytes(b"x")
    monkeypatch.setattr(pipeline, "rhythm_for", lambda rd, p: _rhythm())

    state.render_options = {"look": "clean", "beat_sync": False}
    assert pipeline._beat_synced_plan(run_dir, state) == run_dir / "plan.json"   # no music
    state.bgm_path = str(song)
    assert pipeline._beat_synced_plan(run_dir, state) == run_dir / "plan.json"   # sync off

    state.render_options = {"look": "clean", "beat_sync": True, "music_sync": "bars"}
    out = json.loads(pipeline._beat_synced_plan(run_dir, state).read_text(encoding="utf-8"))
    assert out["music"]["mode"] == "bars" and all(_on_grid(c, 2.0) for c in _cuts(out))
    assert json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))["shots"][0]["duration"] == 4.3

    state.render_options = {"look": "clean", "beat_sync": True}   # runs saved before the modes existed
    assert pipeline.music_sync_mode(state) == "nudge"


def test_presets_suggest_a_cut_style(tmp_path):
    tracks = {t.key: t for t in music.library(tmp_path)}
    assert tracks["gentle_piano"].sync == "bars" and tracks["gentle_piano"].beat_sync
    assert tracks["sunny_strum"].sync == "accents" and tracks["soft_beat"].sync == "follow"
