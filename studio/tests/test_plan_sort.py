"""Tests for Media Remix plan ordering.

sort_mode="folder" follows the folder tree (natural sort) for archives of
scanned photos whose timestamps are meaningless; one chapter per folder.
Also covers a mixed photo+video folder: video creation_time is tz-aware
while EXIF/mtime timestamps are naive, which used to crash clustering.
"""
from __future__ import annotations

import json

import plan
from score import assign_temporal_clusters


def _asset(rel: str, ts: str, type_: str = "image") -> dict:
    return {
        "id": rel, "path": f"C:/root/{rel}", "relative_path": rel, "type": type_,
        "timestamp": ts, "quality_score": 70.0, "face_count": 1, "largest_face_ratio": 0.1,
        "duration": 5.0 if type_ == "video" else None,
    }


def _write(tmp_path, assets):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"assets": assets}), encoding="utf-8")
    return path


def test_folder_mode_uses_natural_folder_then_filename_order(tmp_path):
    assets = [
        _asset("10-Late/a.jpg", "2000-01-01T00:00:00"),
        _asset("2-Mid/sub/b.jpg", "1990-01-01T00:00:00"),
        _asset("2-Mid/img10.jpg", "2020-01-01T00:00:00"),
        _asset("2-Mid/img2.jpg", "2021-01-01T00:00:00"),
        _asset("1-Early/z.jpg", "2030-01-01T00:00:00"),
        _asset("root.jpg", "2040-01-01T00:00:00"),
    ]
    p = plan.build_plan(_write(tmp_path, assets), plan.PlanConfig(target_duration_seconds=999, sort_mode="folder"))

    assert [s["relative_path"] for s in p["shots"]] == [
        "root.jpg", "1-Early/z.jpg", "2-Mid/img2.jpg", "2-Mid/img10.jpg", "2-Mid/sub/b.jpg", "10-Late/a.jpg",
    ]
    assert [c["title"] for c in p["chapters"]] == [
        "Chapter 1 · (root)", "Chapter 2 · 1-Early", "Chapter 3 · 2-Mid", "Chapter 4 · sub", "Chapter 5 · 10-Late",
    ]


def test_date_mode_still_sorts_chronologically(tmp_path):
    assets = [_asset("b/x.jpg", "2001-01-01T00:00:00"), _asset("a/y.jpg", "2002-01-01T00:00:00")]
    p = plan.build_plan(_write(tmp_path, assets), plan.PlanConfig(target_duration_seconds=999))
    assert [s["relative_path"] for s in p["shots"]] == ["b/x.jpg", "a/y.jpg"]


def test_temporal_clusters_accept_mixed_naive_and_aware_timestamps():
    assets = [
        {"timestamp": "1994-02-01T10:00:00"},
        {"timestamp": "1994-02-01T12:00:00+00:00"},
    ]
    assign_temporal_clusters(assets, 30)
    assert [a["temporal_cluster"] for a in assets] == [0, 1]
