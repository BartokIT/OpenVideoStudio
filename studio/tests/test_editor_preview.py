"""Tests for the editor layer (core/pro/preview.py + core/studio_service.py):
thumbnails, the 540p edit timeline, frames at the playhead, cut previews,
the per-shot camera motion override, plan edits and the media list."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from pro import looks, preview
from pro.timeline import MOTION_LABELS, build_timeline


def _photo(path: Path, w=640, h=480, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.imwrite(str(path), img)
    return path


def _shots(paths, enabled=None):
    out = []
    for i, p in enumerate(paths):
        out.append({"shot_id": f"s_{i:04d}", "asset_id": f"a{i}", "asset_path": str(p), "relative_path": p.name,
                    "type": "image", "chapter_id": 0, "order": i, "enabled": True if enabled is None else enabled[i],
                    "duration": 3.0, "reason": "base", "quality_score": 70.0, "timestamp": "2020-01-01T00:00:00",
                    "title_text": None})
    return out


def test_motion_override_forces_camera():
    shots = [{"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 4.0, "enabled": True,
              "chapter_id": 0, "title_text": None, "motion": "pan_left" if i == 1 else None} for i in range(3)]
    meta = {"canvas": "x.jpg", "canvas_w": 2400, "canvas_h": 1350, "mode": "crop", "faces": [], "landmarks": None}
    prepared = {s["shot_id"]: meta for s in shots}
    tl = build_timeline({"shots": shots, "chapters": []}, prepared, {}, looks.get_look("clean"), 1280, 720, 25)
    assert tl["shots"][1]["motion"] == "pan_left"
    assert tl["shots"][1]["camera"]["cx0"] > tl["shots"][1]["camera"]["cx1"]
    assert set(MOTION_LABELS) >= {"zoom_in", "pan_left", "drift"}


def test_thumbnails_are_cached_and_placeholder_on_bad_file(tmp_path):
    good = _photo(tmp_path / "a.jpg")
    bad = tmp_path / "b.jpg"
    bad.write_bytes(b"not an image")
    shots = _shots([good, bad])
    thumbs = preview.thumbnails(shots, tmp_path / "work")
    assert set(thumbs) == {"s_0000", "s_0001"}
    for p in thumbs.values():
        img = cv2.imread(p)
        assert img is not None and img.shape[:2] == (preview.THUMB_H, preview.THUMB_W)
    first = {k: Path(v).stat().st_mtime_ns for k, v in thumbs.items()}
    thumbs2 = preview.thumbnails(shots, tmp_path / "work")
    assert {k: Path(v).stat().st_mtime_ns for k, v in thumbs2.items()} == first  # cache hit, not rewritten


class _Cfg:
    fps = 25
    workers = 2
    codec = "libx264"
    bitrate, maxrate, bufsize, cq = "2M", "3M", "4M", 23


@pytest.fixture
def edit_timeline(tmp_path):
    paths = [_photo(tmp_path / f"p{i}.jpg", seed=i) for i in range(3)]
    plan = {"shots": _shots(paths, enabled=[True, False, True]), "chapters": [{"chapter_id": 0, "title": "Chapter 1 · Test"}]}
    work = tmp_path / "work"
    tl, tl_path = preview.build_edit_timeline(plan, work, {"look": "clean", "title": "Hello"}, _Cfg())
    return plan, tl, tl_path, work


def test_edit_timeline_only_has_enabled_shots_at_edit_resolution(edit_timeline):
    plan, tl, tl_path, work = edit_timeline
    assert [s["shot_id"] for s in tl["shots"]] == ["s_0000", "s_0002"]
    assert (tl["width"], tl["height"]) == (preview.EDIT_W, preview.EDIT_H)
    assert tl_path.exists() and preview.load_edit_timeline(work)["total"] == tl["total"]
    assert any(o["kind"] == "title" for o in tl["overlays"])


def test_frame_at_renders_any_time_and_describes_it(edit_timeline):
    plan, tl, tl_path, work = edit_timeline
    f0 = preview.frame_at(tl_path, 0.0)
    assert f0.shape == (preview.EDIT_H, preview.EDIT_W, 3) and f0.dtype == np.uint8
    mid = preview.frame_at(tl_path, tl["total"] / 2)
    assert mid.shape == f0.shape
    end = preview.frame_at(tl_path, tl["total"] + 5)  # clamped, no crash
    assert end.shape == f0.shape
    d = preview.describe_time(tl, tl["transitions"][0]["start"] + 0.01)
    assert d["transition"] == 0 and d["shot"] == 0
    assert "title" in preview.describe_time(tl, 1.0)["texts"]


def test_renderer_cache_refreshes_when_timeline_changes(edit_timeline):
    plan, tl, tl_path, work = edit_timeline
    preview.frame_at(tl_path, 0.5)
    r1 = preview._RENDERERS[str(tl_path)][1]
    preview.build_edit_timeline(plan, work, {"look": "clean"}, _Cfg())
    preview.frame_at(tl_path, 0.5)
    assert preview._RENDERERS[str(tl_path)][1] is not r1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_cut_writes_short_clip(edit_timeline):
    plan, tl, tl_path, work = edit_timeline
    out = work / "cuts" / "cut_000.mp4"
    ok, err = preview.render_cut(tl, tl_path, 0, out, _Cfg(), pad=0.3)
    assert ok, err
    assert out.exists() and out.stat().st_size > 1000


def test_format_time():
    assert preview.format_time(0) == "00:00.00"
    assert preview.format_time(75.5) == "01:15.50"


# ----------------------------------------------------- editing service

def _plan_json(rd):
    return json.loads((rd / "plan.json").read_text(encoding="utf-8"))


def test_update_and_move_round_trip(tmp_path, svc_run):
    paths = [_photo(tmp_path / f"p{i}.jpg", seed=i) for i in range(3)]
    svc, run_id, rd = svc_run({"shots": _shots(paths), "chapters": []})

    svc.edit(run_id, "update", "s_0001", {"enabled": False, "duration": 6.25, "motion": "pan_left",
                                          "text": "  Nonna  ", "transition": "Light leak"})
    s = {x["shot_id"]: x for x in _plan_json(rd)["shots"]}["s_0001"]
    assert (s["enabled"], s["duration"], s["duration_locked"], s["motion"], s["title_text"], s["transition"]) == \
        (False, 6.25, True, "pan_left", "Nonna", "light_leak")
    assert svc.rebuilds[-1] is None                      # disabled: nothing to select on the timeline

    def order():
        return [x["shot_id"] for x in _plan_json(rd)["shots"]]

    # s_0001 is now disabled: moving s_0002 earlier skips over it and lands before s_0000
    svc.edit(run_id, "move_by", "s_0002", {"delta": -1})
    assert order() == ["s_0002", "s_0000", "s_0001"] and svc.rebuilds[-1] == "s_0002"
    svc.edit(run_id, "move_by", "s_0002", {"delta": -1})     # already first: no-op, not an error
    assert order() == ["s_0002", "s_0000", "s_0001"]
    svc.edit(run_id, "move_by", "s_0002", {"delta": 1})
    assert order() == ["s_0000", "s_0002", "s_0001"]

    info = svc.shot_info(run_id, "s_0001")
    assert info["name"] == "p1.jpg" and info["enabled"] is False and info["duration"] == 6.25
    assert info["motion"] == "pan_left" and info["text"] == "Nonna" and info["transition"] == "light_leak"
    assert info["excluded"] == "removed by you" and info["timeline"] is None


def test_timeline_edits_and_unknown_action(tmp_path, svc_run):
    paths = [_photo(tmp_path / f"p{i}.jpg", seed=i) for i in range(4)]
    svc, run_id, rd = svc_run({"shots": _shots(paths, enabled=[True, True, False, True]), "chapters": []})
    svc.edit(run_id, "duration", "s_0000", {"duration": 7.123})
    svc.edit(run_id, "toggle", "s_0002")
    svc.edit(run_id, "caption", "s_0002", {"text": " Mare "})
    saved = {x["shot_id"]: x for x in _plan_json(rd)["shots"]}
    assert saved["s_0000"]["duration"] == 7.12 and saved["s_0000"]["duration_locked"]
    assert saved["s_0002"]["enabled"] is True and saved["s_0002"]["title_text"] == "Mare"
    with pytest.raises(svc.ServiceError, match="Unknown edit"):
        svc.edit(run_id, "fly", "s_0002")
    with pytest.raises(svc.ServiceError, match="Shot not found"):
        svc.edit(run_id, "toggle", "nope")


def test_move_before():
    import studio_service as svc

    plan = {"shots": _shots([Path(f"p{i}.jpg") for i in range(4)], enabled=[True, True, False, True]), "chapters": []}
    assert svc.move_before(plan, "s_0003", "s_0000") is True
    assert [s["shot_id"] for s in plan["shots"]] == ["s_0003", "s_0000", "s_0001", "s_0002"]
    assert svc.move_before(plan, "s_0003", None) is True   # to the end of the cut (after the last enabled)
    assert [s["shot_id"] for s in plan["shots"]] == ["s_0000", "s_0001", "s_0003", "s_0002"]
    assert svc.move_before(plan, "s_0001", "s_0003") is False   # already there


def test_selection_survives_the_following_playhead_update(tmp_path, svc_run):
    paths = [_photo(tmp_path / f"p{i}.jpg", seed=i) for i in range(2)]
    svc, run_id, rd = svc_run({"shots": _shots(paths), "chapters": []})
    (rd / "render_work").mkdir(exist_ok=True)
    (rd / "render_work" / svc.TIMELINE_VIEW).write_text(json.dumps({"playhead": 0.0, "selected": None, "total": 10.0}),
                                                       encoding="utf-8")
    assert svc.set_view_cursor(run_id, 3.0, "s_0001") == {"playhead": 3.0, "selected": "s_0001"}
    assert svc.set_view_cursor(run_id, 3.5) == {"playhead": 3.5, "selected": "s_0001"}   # a later scrub keeps it
    assert svc.set_view_cursor(run_id, 99)["playhead"] == 10.0                          # clamped to the film


def test_media_list_marks_excluded_media(tmp_path):
    import studio_service as svc

    paths = [_photo(tmp_path / f"p{i}.jpg", seed=i) for i in range(5)]
    shots = _shots(paths, enabled=[True, False, False, False, False])
    shots[1]["relative_path"] = "1990-09 - Ponza/p1.jpg"
    shots[2]["reason"] = "base+budget_suppressed"
    shots[3]["reason"] = "missing_file"
    shots[4]["reason"] = "duplicate_suppressed"
    thumbs = preview.thumbnails(shots, tmp_path / "work")
    media = svc.media_list({"shots": shots, "chapters": []}, thumbs)

    assert [m["id"] for m in media] == [s["shot_id"] for s in shots]
    assert media[0]["excluded"] is None and media[0]["thumb"] == preview.file_url(thumbs["s_0000"])
    assert media[1]["folder"] == "1990-09 - Ponza" and media[0]["folder"] == "(root)"
    assert [m["excluded"]["label"] for m in media[1:]] == ["removed by you", "over the target length", "file missing",
                                                           "duplicate"]
    assert [Path(m["thumb"]).name for m in media[1:]] == ["s_0001_off3_manual.jpg", "s_0002_off3_budget.jpg",
                                                          "s_0003_off3_missing.jpg", "s_0004_off3_duplicate.jpg"]


def test_excluded_thumbnail_is_veiled_with_a_small_badge(tmp_path):
    paths = [_photo(tmp_path / "p0.jpg", seed=0)]
    thumbs = preview.thumbnails(_shots(paths), tmp_path / "work")
    marked = preview.excluded_thumb(thumbs["s_0000"], "manual")
    orig = cv2.imread(thumbs["s_0000"]).astype(float)
    off = cv2.imread(marked).astype(float)
    assert off.shape == orig.shape
    h, w = off.shape[:2]
    body = (slice(h // 3, h - 20), slice(w // 3, w - 20))
    ratio = off[body].mean() / orig[body].mean()
    assert 0.65 < ratio < 0.9                                        # veiled, but the photo stays readable
    r = int(h * 0.09)
    x0 = (w - h) // 2
    band = max(h // 45, 3)
    cx, cy = x0 + r + 7, band + r + 7
    badge = off[cy - 2:cy + 3, cx - 2:cx + 3]
    assert badge.mean() > 150                                        # the white slash crosses the badge centre
    assert cx - r - 2 >= x0 and cy - r - 2 >= 0                      # top-left of the visible square, not cropped
    assert r < h * 0.12                                              # small
    mtime = Path(marked).stat().st_mtime_ns
    assert preview.excluded_thumb(thumbs["s_0000"], "manual") == marked
    assert Path(marked).stat().st_mtime_ns == mtime                  # cached


def test_timeline_view_is_compact_and_marks_overrides(edit_timeline):
    plan, tl, tl_path, work = edit_timeline
    plan["shots"][2]["transition"] = "glitch"
    plan["shots"][2]["title_text"] = "Nonna"
    plan["chapters"] = [{"chapter_id": 0, "title": "Chapter 1 · 1990-09 - Ponza"}]
    audio = {"name": "song.mp3", "duration": 90.0, "peak_seconds": 0.1, "peaks": [0.1, 0.5], "beats": [1.0, 2.0]}
    view = preview.timeline_view(tl, plan, {"s_0000": "C:/x/a.jpg"}, audio, playhead=1.5, selected="s_0002", snap=False)
    assert [s["id"] for s in view["shots"]] == ["s_0000", "s_0002"]
    assert view["shots"][0]["thumb"] == "/files?path=C:/x/a.jpg" and view["shots"][1]["thumb"] is None
    assert view["shots"][1]["caption"] == "Nonna"
    assert view["transitions"][0]["override"] is True and view["transitions"][0]["into"] == "s_0002"
    assert view["chapters"] == [{"id": 0, "name": "1990-09 - Ponza", "start": 0.0, "end": view["total"]}]
    assert any(t["kind"] == "title" and "Hello" in t["text"] and not t["editable"] for t in view["texts"])
    assert view["audio"]["beats"] == [1.0, 2.0] and view["playhead"] == 1.5 and view["selected"] == "s_0002"
    assert view["snap"] is False
    assert "landmarks" not in json.dumps(view)


