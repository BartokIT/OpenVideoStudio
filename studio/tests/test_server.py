"""End-to-end tests for the dedicated editor (server/ + core/studio_service.py):
a real run created through the API on generated photos, edits, a restyle,
frames, projects, music upload and the file-serving guard."""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

import studio_service as svc
from pro import preview as pro_preview


def _photo(path, seed):
    rng = np.random.default_rng(seed)
    img = np.zeros((480, 720, 3), np.uint8)
    img[:] = rng.integers(40, 200, 3)
    for _ in range(12):   # a few shapes so photos differ and aren't flagged as duplicates
        x, y = rng.integers(0, 640), rng.integers(0, 400)
        cv2.rectangle(img, (int(x), int(y)), (int(x) + 80, int(y) + 60), [int(v) for v in rng.integers(0, 255, 3)], -1)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient

    old_prefix = pro_preview.FILE_URL_PREFIX
    old_roots = (svc.RUNS_ROOT, svc.ASSETS_MUSIC, svc.PROJECTS_DIR)
    base = tmp_path_factory.mktemp("editor")
    from server.app import app   # sets FILE_URL_PREFIX to "/files?path="
    svc.configure(runs_root=base / "runs", assets_music=base / "music", projects_dir=base / "projects")
    media = base / "media"
    for i in range(3):
        _photo(media / "1-Mare" / f"m{i}.jpg", i)
    for i in range(2):
        _photo(media / "2-Monti" / f"n{i}.jpg", 10 + i)
    with TestClient(app) as c:
        c.media = media
        c.base = base
        yield c
    pro_preview.FILE_URL_PREFIX = old_prefix
    svc.RUNS_ROOT, svc.ASSETS_MUSIC, svc.PROJECTS_DIR = old_roots


def _wait(client, job, timeout=120):
    t0 = time.time()
    while job["status"] in ("queued", "running"):
        assert time.time() - t0 < timeout, job
        time.sleep(0.2)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", job
    return job["result"]


@pytest.fixture(scope="module")
def run_id(client):
    job = client.post("/api/runs", json={"folder": str(client.media), "target_duration": 30, "sort_mode": "folder",
                                         "options": {"look": "clean", "title": "Estate"}}).json()
    return _wait(client, job)


def test_catalog_and_pages(client):
    cat = client.get("/api/catalog").json()
    assert {l["value"] for l in cat["looks"]} >= {"family_memory", "cinematic", "clean"}
    assert [c["value"] for c in cat["music_sync"]] == ["bars", "beats", "accents", "follow", "nudge"]
    assert cat["default_options"]["look"] == "family_memory"
    assert client.get("/").status_code == 200
    for url in ("/static/js/main.js", "/static/css/app.css", "/ui/timeline.js", "/ui/timeline.css"):
        r = client.get(url)
        # after an update the browser must not keep a stale copy of the editor's own files
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", url
        assert client.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_create_run_and_state(client, run_id):
    st = client.get(f"/api/runs/{run_id}").json()
    assert st["run_id"] == run_id and len(st["media"]) == 5
    assert st["options"]["look"] == "clean" and st["options"]["title"] == "Estate"
    view = st["view"]
    assert view["shots"] and view["total"] > 0
    assert any(t["kind"] == "title" for t in view["texts"])
    assert view["shots"][0]["thumb"].startswith("/files?path=")
    thumb = client.get(view["shots"][0]["thumb"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"


def test_frame_and_shot_info(client, run_id):
    r = client.get(f"/api/runs/{run_id}/frame", params={"t": 1.5})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (540, 960)
    assert r.headers["X-Frame-Shot"] == "0"
    sid = r.headers["X-Frame-Shot-Id"]
    info = client.get(f"/api/runs/{run_id}/shots/{sid}").json()
    assert info["id"] == sid and info["enabled"] and info["timeline"]["index"] == 0 and info["preview_t"] is not None


def test_edits(client, run_id):
    st = client.get(f"/api/runs/{run_id}").json()
    ids = [s["id"] for s in st["view"]["shots"]]
    second = ids[1]
    view = _wait(client, client.post(f"/api/runs/{run_id}/edit",
                                     json={"action": "caption", "shot_id": second, "payload": {"text": "Al mare"}}).json())
    assert any(t["text"] == "Al mare" for t in view["texts"]) and view["selected"] == second

    view = _wait(client, client.post(f"/api/runs/{run_id}/edit", json={
        "action": "update", "shot_id": second, "payload": {"transition": "glitch", "motion": "pan_left", "duration": 5.5}}).json())
    tr = next(t for t in view["transitions"] if t["into"] == second)
    assert tr["type"] == "glitch" and tr["override"]
    info = client.get(f"/api/runs/{run_id}/shots/{second}").json()
    assert info["motion"] == "pan_left" and info["duration_locked"] and info["duration"] == 5.5

    view = _wait(client, client.post(f"/api/runs/{run_id}/edit",
                                     json={"action": "move", "shot_id": ids[-1], "payload": {"before": ids[0]}}).json())
    assert view["shots"][0]["id"] == ids[-1]

    view = _wait(client, client.post(f"/api/runs/{run_id}/edit",
                                     json={"action": "enable", "shot_id": second, "payload": {"enabled": False}}).json())
    assert second not in [s["id"] for s in view["shots"]]
    st = client.get(f"/api/runs/{run_id}").json()
    m = next(x for x in st["media"] if x["id"] == second)
    assert not m["enabled"] and m["excluded"]["label"] == "removed by you" and "_off3_manual" in m["thumb"]

    bad = client.post(f"/api/runs/{run_id}/edit", json={"action": "fly", "shot_id": second}).json()
    with pytest.raises(AssertionError):
        _wait(client, bad)
    assert client.get(f"/api/jobs/{bad['id']}").json()["error"].startswith("Unknown edit")


def test_restyle_keeps_selection_and_cursor(client, run_id):
    st = client.get(f"/api/runs/{run_id}").json()
    sel = st["view"]["shots"][1]["id"]
    assert client.post(f"/api/runs/{run_id}/cursor",
                       json={"playhead": 2.0, "selected": sel, "set_selected": True}).json() == {"playhead": 2.0, "selected": sel}
    opts = {**st["options"], "look": "vintage", "transition_mode": "mixed", "nonsense": 1, "music_volume": 5}
    view = _wait(client, client.put(f"/api/runs/{run_id}/options", json={"options": opts, "playhead": 2.0}).json())
    assert view["selected"] == sel and view["playhead"] == 2.0
    st = client.get(f"/api/runs/{run_id}").json()
    assert st["options"]["look"] == "vintage" and st["options"]["music_volume"] == 1.0 and "nonsense" not in st["options"]
    # unchanged options: no rebuild, same view back
    again = _wait(client, client.put(f"/api/runs/{run_id}/options", json={"options": st["options"]}).json())
    assert again["total"] == view["total"]


def test_projects_round_trip(client, run_id):
    saved = client.post("/api/projects", json={"run_id": run_id, "name": "Vacanze"}).json()
    lst = client.get("/api/projects").json()
    assert [p["name"] for p in lst] == ["Vacanze"] and lst[0]["path"] == saved["path"]
    res = _wait(client, client.post("/api/projects/open", json={"path": saved["path"]}).json())
    assert res["run_id"] == run_id and res["reused_run"] and res["missing"] == []
    assert any(r["run_id"] == run_id for r in client.get("/api/runs").json())


def test_music_upload_and_tracks(client):
    from scipy.io import wavfile

    wav = client.base / "song.wav"
    wavfile.write(str(wav), 22050, (np.sin(np.linspace(0, 3000, 22050 * 3)) * 8000).astype(np.int16))
    r = client.post("/api/music/upload", files={"file": ("La mia canzone!.wav", wav.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and r.json()["key"] == "file:La mia canzone.wav"   # "!" dropped, spaces kept
    keys = [t["key"] for t in client.get("/api/music/tracks").json()]
    assert r.json()["key"] in keys and "gentle_piano" in keys
    assert client.post("/api/music/upload", files={"file": ("x.exe", b"0" * 4000, "application/octet-stream")}).status_code == 400


def test_file_guard_and_bad_ids(client, run_id):
    assert client.get("/files", params={"path": "C:/Windows/win.ini"}).status_code in (403, 404)
    sneaky = str(svc.RUNS_ROOT / ".." / "media" / "1-Mare" / "m0.jpg")
    assert client.get("/files", params={"path": sneaky}).status_code == 403
    assert client.get("/api/runs/../../etc").status_code == 404
    assert client.get("/api/runs/run_missing_1").status_code == 404
    assert client.get(f"/api/runs/{run_id}/frame", params={"t": 1}).status_code == 200


def test_create_run_rejects_missing_folder(client):
    job = client.post("/api/runs", json={"folder": str(client.base / "nope")}).json()
    t0 = time.time()
    while job["status"] in ("queued", "running") and time.time() - t0 < 10:
        time.sleep(0.1)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "error" and "folder" in job["error"]


def test_normalize_options():
    o = svc.normalize_options({"look": "nope", "transition_speed": "9", "font": "bebas", "title_anim": "zzz",
                               "title": "  Ciao  ", "resolution": "8k", "music_sync": "follow"})
    assert o["look"] == "family_memory" and o["transition_speed"] == 2.0 and o["font"] == "bebas"
    assert o["title_anim"] is None and o["title"] == "Ciao" and o["resolution"] == "1080p" and o["music_sync"] == "follow"
    assert set(o) == set(svc.DEFAULT_OPTIONS)
