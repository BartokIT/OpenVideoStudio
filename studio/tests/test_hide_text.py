"""Emptying the text of a shot that starts a chapter (folder) must remove
the chapter card, not fall back to the folder name. Regression for:
"se metto il testo vuoto ad una cartella, non mi leva il testo dal video".
"""
from __future__ import annotations

import json

import pytest

from pro import looks, preview
from pro.timeline import auto_chapter_text, build_timeline, text_min_holds


def _plan():
    shots = []
    for i in range(5):
        shots.append({"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 5.0,
                      "enabled": True, "order": i, "chapter_id": 0 if i < 2 else 1, "title_text": None,
                      "reason": "base"})
    return {"shots": shots, "chapters": [{"chapter_id": 0, "title": "Chapter 1 · 1-Matrimonio"},
                                         {"chapter_id": 1, "title": "Chapter 2 · 1990-09 - Ponza"}]}


def _meta():
    return {"canvas": "x.jpg", "canvas_w": 2400, "canvas_h": 1350, "mode": "crop", "faces": [], "landmarks": None}


def _tl(plan, opts=None):
    prepared = {s["shot_id"]: _meta() for s in plan["shots"]}
    return build_timeline(plan, prepared, {"look": "clean", "chapter_titles": True, **(opts or {})},
                          looks.get_look("clean"), 1280, 720, 25)


def _cards(tl):
    return [(o["kind"], tl["shots"][o["shot"]]["shot_id"]) for o in tl["overlays"]]


def test_auto_chapter_text():
    plan = _plan()
    assert auto_chapter_text(plan, "s0", {}) == "Matrimonio"
    assert auto_chapter_text(plan, "s2", {}) == "Ponza"
    assert auto_chapter_text(plan, "s1", {}) == ""                      # not a chapter start
    assert auto_chapter_text(plan, "s0", {"title": "Film"}) == ""       # the opening title takes it
    assert auto_chapter_text(plan, "s2", {"chapter_titles": False}) == ""


def test_hidden_chapter_card_is_removed_and_frees_its_hold():
    plan = _plan()
    assert ("chapter", "s2") in _cards(_tl(plan))
    plan["shots"][2]["hide_text"] = True
    cards = _cards(_tl(plan))
    assert ("chapter", "s2") not in cards and ("caption", "s2") not in cards
    assert ("chapter", "s0") in cards                                   # other folders untouched
    assert "s2" not in text_min_holds(plan, {"chapter_titles": True})


def _shot(rd, sid):
    return {s["shot_id"]: s for s in json.loads((rd / "plan.json").read_text(encoding="utf-8"))["shots"]}[sid]


def test_emptying_a_folder_title_on_the_timeline_hides_it_and_typing_brings_it_back(svc_run):
    svc, run_id, rd = svc_run(_plan(), {"chapter_titles": True})
    svc.edit(run_id, "caption", "s2", {"text": "  "})
    s = _shot(rd, "s2")
    assert s["hide_text"] is True and s["title_text"] is None
    info = svc.shot_info(run_id, "s2")
    assert info["hide_text"] and info["text"] == "" and info["auto_title"] == "Ponza"

    svc.edit(run_id, "caption", "s2", {"text": "Ponza"})
    s = _shot(rd, "s2")
    assert s["hide_text"] is False and s["title_text"] is None           # back to automatic

    svc.edit(run_id, "caption", "s2", {"text": "Estate a Ponza"})
    assert _shot(rd, "s2")["title_text"] == "Estate a Ponza"


def test_empty_text_on_a_folder_hides_it_but_on_a_photo_just_clears(svc_run):
    svc, run_id, rd = svc_run(_plan(), {"chapter_titles": True})
    info = svc.shot_info(run_id, "s2")
    assert info["text"] == "Ponza" and info["auto_title"] == "Ponza"      # the automatic title is shown
    svc.edit(run_id, "update", "s2", {"text": ""})
    assert _shot(rd, "s2")["hide_text"] is True

    svc.edit(run_id, "update", "s3", {"text": "Nonna"})
    svc.edit(run_id, "update", "s3", {"text": ""})
    s3 = _shot(rd, "s3")
    assert s3["title_text"] is None and not s3.get("hide_text")         # a plain photo has nothing to hide


def test_timeline_edit_text_is_the_title_only_not_the_date():
    plan = _plan()
    tl = _tl(plan)
    view = preview.timeline_view(tl, plan, {})
    ch = next(t for t in view["texts"] if t["kind"] == "chapter" and t["shot"] == "s2")
    assert "Settembre 1990" in ch["text"] and ch["edit_text"] == "Ponza"
    plan["shots"][2]["title_text"] = "Estate"
    view = preview.timeline_view(_tl(plan), plan, {})
    assert next(t for t in view["texts"] if t["shot"] == "s2")["edit_text"] == "Estate"
