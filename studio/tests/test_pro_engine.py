"""Tests for the pro render engine (core/pro): chapter labels, transition
catalogue, typography rasterising, timeline building and face morph."""
from __future__ import annotations

import numpy as np
import pytest

from pro import facemorph, looks, transitions, typography
from pro.timeline import build_timeline, chapter_label


@pytest.mark.parametrize("raw,expected", [
    ("Chapter 1 · 1-Matrimonio", ("Matrimonio", "")),
    ("Chapter 3 · 1990-09 - Ponza", ("Ponza", "Settembre 1990")),
    ("Chapter 2 · 1989-09-16 - Compleanno Marco 6 anni", ("Compleanno Marco 6 anni", "16 Settembre 1989")),
    ("Chapter 4 · 1984", ("1984", "")),
    ("Chapter 5 · 2026-10-11", ("11 Ottobre 2026", "")),
    ("Chapter 1 · (root)", ("", "")),
])
def test_chapter_label(raw, expected):
    assert chapter_label(raw, "it") == expected


def test_every_transition_returns_frame_of_same_shape():
    a = np.full((90, 160, 3), 40, np.uint8)
    b = np.full((90, 160, 3), 200, np.uint8)
    for name in transitions.TRANSITIONS:
        for p in (0.0, 0.3, 0.5, 0.8, 1.0):
            out = transitions.apply(name, a, b, p, {"seed": 3})
            assert out.shape == a.shape and out.dtype == np.uint8, name


def test_fade_endpoints():
    a = np.zeros((20, 32, 3), np.uint8)
    b = np.full((20, 32, 3), 255, np.uint8)
    assert transitions.apply("fade", a, b, 0.0, {}).max() == 0
    assert transitions.apply("fade", a, b, 1.0, {}).min() == 255


def test_morph_without_landmarks_falls_back_to_fade():
    a = np.zeros((40, 64, 3), np.uint8)
    b = np.full((40, 64, 3), 255, np.uint8)
    out = transitions.apply("morph", a, b, 0.5, {})
    assert 100 < out.mean() < 160


def test_morph_with_synthetic_landmarks_is_identity_at_endpoints():
    h, w = 120, 200
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    b = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    pts = np.stack([rng.uniform(60, 140, 478), rng.uniform(30, 90, 478)], axis=1).astype(np.float32)
    out0 = facemorph.morph(a, b, pts, pts + 3, 0.0, {})
    out1 = facemorph.morph(a, b, pts, pts + 3, 1.0, {})
    assert np.abs(out0.astype(int) - a.astype(int)).mean() < 6
    assert np.abs(out1.astype(int) - b.astype(int)).mean() < 6


@pytest.mark.parametrize("anim", typography.ANIMATIONS)
def test_text_overlay_draws_for_every_animation(anim):
    look = looks.get_look("cinematic")
    card = typography.title_card(look, "Hello World", "Subtitle", "Kicker", 0.0, 4.0, anim=anim)
    ov = typography.overlay_from_dict(typography.serialisable(card), look, 640, 360)
    frame = np.zeros((360, 640, 3), np.uint8)
    out = ov.draw(frame.copy(), 2.5)
    assert out.shape == frame.shape
    assert out.max() > 100  # text actually rendered
    assert ov.draw(frame.copy(), 5.0).max() == 0  # inactive after end


def test_text_avoids_faces():
    look = looks.get_look("family_memory")
    card = typography.chapter_card(look, "Nascita", "1984", 0.0, 4.0)
    ov = typography.overlay_from_dict(typography.serialisable(card), look, 1920, 1080)
    ov.avoid = [(860, 420, 1060, 660)]  # a face right in the middle
    ov._build()
    x0, y0, x1, y1 = ov.block
    assert y1 < 420 or y0 > 660


def test_grade_is_identity_for_clean_look():
    img = np.random.default_rng(1).integers(0, 255, (16, 16, 3), dtype=np.uint8)
    assert np.array_equal(looks.apply_grade(img, looks.get_look("clean").grade), img)


def test_old_style_names_map_to_looks():
    assert looks.get_look("Family Memory").key == "family_memory"
    assert looks.get_look("Travel Documentary").key == "travel"
    assert looks.get_look("nope").key == "family_memory"


def _photo_meta(face=True):
    meta = {"canvas": "x.jpg", "canvas_w": 2400, "canvas_h": 1350, "mode": "crop", "faces": [], "landmarks": None}
    if face:
        meta["faces"] = [{"x": 1000, "y": 400, "w": 400, "h": 400, "score": 0.9}]
    return meta


def test_timeline_total_matches_plan_and_transitions_are_centred():
    shots = [{"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 4.0, "enabled": True,
              "chapter_id": i // 2, "title_text": None} for i in range(5)]
    plan = {"shots": shots, "chapters": [{"chapter_id": 0, "title": "Chapter 1 · 1-Mare"},
                                         {"chapter_id": 1, "title": "Chapter 2 · 1990-09 - Ponza"},
                                         {"chapter_id": 2, "title": "Chapter 3 · Fine"}]}
    prepared = {s["shot_id"]: _photo_meta() for s in shots}
    look = looks.get_look("travel")
    tl = build_timeline(plan, prepared, {"look": "travel", "chapter_titles": True}, look, 1920, 1080, 25)
    assert tl["total"] == pytest.approx(sum(s["duration"] for s in tl["shots"]))
    for tr in tl["transitions"]:
        boundary = tl["shots"][tr["a"]]["end"]
        assert tr["start"] < boundary < tr["end"]
    # a chapter card on the first shot of chapters 1 and 2
    kinds = [(o["kind"], o["shot"]) for o in tl["overlays"]]
    assert ("chapter", 2) in kinds and ("chapter", 4) in kinds
    # chapter boundaries use the look's chapter transition
    assert tl["transitions"][1]["type"] in (look.chapter_transition, *look.chapter_pool)


def test_forced_transition_mode_and_per_shot_override():
    shots = [{"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 4.0, "enabled": True,
              "chapter_id": 0, "title_text": None, "transition": "glitch" if i == 2 else None} for i in range(4)]
    prepared = {s["shot_id"]: _photo_meta(face=False) for s in shots}
    tl = build_timeline({"shots": shots, "chapters": []}, prepared,
                        {"transition_mode": "whip_pan", "transition_only": True},
                        looks.get_look("dynamic"), 1280, 720, 25)
    assert [t["type"] for t in tl["transitions"]] == ["whip_pan", "glitch", "whip_pan"]


def _many_shots(n, chapter_every=0):
    return [{"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 4.0, "enabled": True,
             "chapter_id": (i // chapter_every) if chapter_every else 0, "title_text": None} for i in range(n)]


@pytest.mark.parametrize("look_key", list(looks.LOOKS))
def test_auto_transitions_vary_within_a_style(look_key):
    shots = _many_shots(40, chapter_every=4)
    prepared = {s["shot_id"]: _photo_meta(face=False) for s in shots}
    tl = build_timeline({"shots": shots, "chapters": []}, prepared, {"look": look_key},
                        looks.get_look(look_key), 1280, 720, 25)
    types = [t["type"] for t in tl["transitions"]]
    assert len(set(types)) >= 6
    assert all(a != b for a, b in zip(types, types[1:]))  # never the same twice in a row
    chapter_types = {t["type"] for t in tl["transitions"] if (t["a"] + 1) % 4 == 0}
    assert len(chapter_types) >= 2


def test_favoured_transition_leads_but_does_not_monopolise():
    shots = _many_shots(41)
    prepared = {s["shot_id"]: _photo_meta(face=False) for s in shots}
    tl = build_timeline({"shots": shots, "chapters": []}, prepared, {"transition_mode": "zoom_in"},
                        looks.get_look("cinematic"), 1280, 720, 25)
    types = [t["type"] for t in tl["transitions"]]
    share = types.count("zoom_in") / len(types)
    assert 0.25 <= share <= 0.6
    assert len(set(types)) >= 5
