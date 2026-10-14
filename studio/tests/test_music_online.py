"""Tests for core/music_online.py (network calls mocked): parsing of the
three sources, the search cache, downloads with sidecars, and how a
downloaded track flows into the preset library and the closing-card credit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import music
import music_online as mo
from pro import looks
from pro.timeline import build_timeline


class _Resp:
    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload
        self._content = content
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


OPENVERSE = {"results": [
    {"id": "936a", "title": "Raw Vinyl", "creator": "Auditone", "url": "https://storage/x.mp3", "license": "by-nc-sa",
     "license_version": "3.0", "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
     "foreign_landing_url": "https://www.jamendo.com/track/1", "duration": 184000, "filetype": "mp32",
     "attribution": "\"Raw Vinyl\" by Auditone is licensed under CC BY-NC-SA 3.0."},
    {"id": "no-url", "title": "Broken", "creator": "x", "url": "", "license": "by"},
]}
ARCHIVE_SEARCH = {"response": {"docs": [
    {"identifier": "NS050", "title": "Another Day", "creator": "No-Source", "licenseurl": "http://creativecommons.org/licenses/by-nc-sa/4.0/"},
    {"identifier": "nolicence", "title": "Mix"},
]}}
ARCHIVE_META = {"files": [
    {"name": "01-Christmas.mp3", "format": "VBR MP3", "length": "240.9"},
    {"name": "cover.jpg", "format": "JPEG"},
    {"name": "02 - Swing Low.mp3", "format": "VBR MP3", "length": "200.43", "title": "Swing Low"},
]}
JAMENDO = {"results": [
    {"id": 11, "name": "Sunrise", "artist_name": "Ann", "duration": 201, "audio": "https://j/stream/11",
     "audiodownload": "https://j/dl/11", "audiodownload_allowed": True,
     "license_ccurl": "http://creativecommons.org/licenses/by/3.0/", "shareurl": "https://www.jamendo.com/track/11"},
    {"id": 12, "name": "Stream only", "artist_name": "Bo", "duration": 100, "audio": "https://j/stream/12",
     "audiodownload": "", "audiodownload_allowed": False, "license_ccurl": "http://creativecommons.org/licenses/by-nd/3.0/"},
]}


@pytest.fixture(autouse=True)
def _clear_cache():
    mo._CACHE.clear()
    yield
    mo._CACHE.clear()


def _fake_get(table):
    calls = []

    def get(url, params=None, headers=None):
        calls.append((url, params))
        for needle, payload in table.items():
            if needle in url:
                return _Resp(payload)
        raise AssertionError(f"unexpected url {url}")
    get.calls = calls
    return get


def test_openverse_parsing(monkeypatch):
    monkeypatch.setattr(mo, "_get", _fake_get({"openverse.org": OPENVERSE}))
    res = mo.search("piano", "openverse")
    assert len(res) == 1
    t = res[0]
    assert t.license == "CC BY NC SA 3.0" and t.duration == 184.0 and t.downloadable and t.ext == "mp3"
    assert "Auditone" in t.attribution and t.page_url.startswith("https://www.jamendo.com")
    assert t.label().startswith("Raw Vinyl — Auditone · 3:04")


def test_archive_parsing_only_licensed_items_and_mp3s(monkeypatch):
    monkeypatch.setattr(mo, "_get", _fake_get({"advancedsearch": ARCHIVE_SEARCH, "metadata/NS050": ARCHIVE_META}))
    res = mo.search("piano", "archive")
    assert [t.title for t in res] == ["01-Christmas", "Swing Low"]
    assert res[1].audio_url == "https://archive.org/download/NS050/02%20-%20Swing%20Low.mp3"
    assert res[0].license == "CC BY NC SA 4.0" and res[0].creator == "No-Source"
    assert "archive.org/details/NS050" in res[0].attribution


def test_jamendo_needs_key_and_respects_download_flag(monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    assert not mo.jamendo_available()
    with pytest.raises(RuntimeError):
        mo.search("x", "jamendo")
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "abc")
    get = _fake_get({"jamendo.com": JAMENDO})
    monkeypatch.setattr(mo, "_get", get)
    res = mo.search("sun", "jamendo", mood="upbeat")
    assert get.calls[0][1]["client_id"] == "abc" and "upbeat" in get.calls[0][1]["search"]
    assert res[0].downloadable and res[0].license == "CC BY 3.0" and "Jamendo" in res[0].attribution
    assert not res[1].downloadable and res[1].audio_url  # preview only


def test_search_is_cached_and_validates_query(monkeypatch):
    get = _fake_get({"openverse.org": OPENVERSE})
    monkeypatch.setattr(mo, "_get", get)
    mo.search("piano", "openverse")
    mo.search("Piano", "openverse")
    assert len(get.calls) == 1
    with pytest.raises(ValueError):
        mo.search("   ", "openverse")
    with pytest.raises(ValueError):
        mo.search("x", "nope")


def test_download_writes_file_and_sidecar_then_library_lists_it(tmp_path, monkeypatch):
    track = mo.OnlineTrack(source="openverse", id="936a", title="Raw Vinyl", creator="Auditone", duration=184.0,
                           license="CC BY-NC-SA 3.0", license_url="https://cc/by-nc-sa/3.0/", page_url="https://p",
                           audio_url="https://storage/x.mp3", download_url="https://storage/x.mp3",
                           attribution="\"Raw Vinyl\" by Auditone, CC BY-NC-SA 3.0")
    payload = b"ID3" + b"\0" * 5000
    monkeypatch.setattr(mo.requests, "get", lambda *a, **k: _Resp(content=payload, headers={"Content-Length": str(len(payload))}))
    msgs = []
    out = mo.download(track, tmp_path / "downloads", lambda f, m: msgs.append(m))
    assert out.exists() and out.read_bytes() == payload and out.suffix == ".mp3"
    side = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert side["attribution"] == track.attribution and side["file"] == out.name
    assert any("added" in m for m in msgs)

    tracks = music.library(tmp_path)
    dl = music.by_key(tracks, f"dl:{out.name}")
    assert dl and dl.title == "Raw Vinyl" and dl.creator == "Auditone" and dl.attribution == track.attribution
    assert not dl.builtin and Path(dl.path) == out

    stream_only = mo.OnlineTrack(**{**mo.asdict(track), "download_url": ""})
    with pytest.raises(PermissionError):
        mo.download(stream_only, tmp_path / "downloads")


def _plan():
    shots = [{"shot_id": f"s{i}", "type": "image", "asset_path": f"{i}.jpg", "duration": 4.0, "enabled": True,
              "chapter_id": 0, "title_text": None} for i in range(3)]
    meta = {"canvas": "x.jpg", "canvas_w": 2400, "canvas_h": 1350, "mode": "crop", "faces": [], "landmarks": None}
    return {"shots": shots, "chapters": []}, {s["shot_id"]: meta for s in shots}


def test_music_credit_goes_on_the_closing_card():
    plan, prepared = _plan()
    look = looks.get_look("clean")
    credit = "\"Raw Vinyl\" by Auditone, CC BY-NC-SA 3.0"
    tl = build_timeline(plan, prepared, {"music_credit": credit}, look, 1280, 720, 25)
    ends = [o for o in tl["overlays"] if o["kind"] == "end"]
    assert len(ends) == 1 and any(l["text"] == credit for l in ends[0]["lines"])
    tl2 = build_timeline(plan, prepared, {"music_credit": credit, "closing_text": "Fine"}, look, 1280, 720, 25)
    end = [o for o in tl2["overlays"] if o["kind"] == "end"][0]
    texts = [l["text"] for l in end["lines"]]
    assert "Fine" in texts and credit in texts
    tl3 = build_timeline(plan, prepared, {"closing_text": "Fine"}, look, 1280, 720, 25)
    assert all(l["text"] != credit for o in tl3["overlays"] for l in o["lines"])
