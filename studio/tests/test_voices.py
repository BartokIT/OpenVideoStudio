"""Narration voices: the catalog and its fallbacks (core/voices.py), the
voice stored per creation and changed afterwards (create_service), the
narration stage using it (creative/pipeline.py), the worker protocol of
the local engines (providers/tts/local_tts_provider.py) and the API.
Nothing here needs PyTorch, Kokoro or Chatterbox installed."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

import create_service as cs
import creative.pipeline as cp
import studio_service as svc
import voices
from providers.base import TTSResult
from providers.tts import local_tts_provider as local


@pytest.fixture
def no_local_install(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "INSTALLED", tmp_path / "installed.json")
    monkeypatch.setattr(local, "ENV_DIR", tmp_path / "env")
    monkeypatch.setattr(voices, "SAMPLES_DIR", tmp_path / "samples")


def test_resolve_falls_back_to_a_voice_the_engine_has():
    assert voices.resolve("kokoro", "it", "im_nicola") == ("kokoro", "it", "im_nicola")
    assert voices.resolve("kokoro", "it", "af_heart") == ("kokoro", "it", "if_sara")        # not an Italian voice
    assert voices.resolve("kokoro", "de", None) == ("edge_tts", "de", "de-DE-KatjaNeural")  # Kokoro has no German
    assert voices.resolve("nope", "xx", None) == ("edge_tts", "en", "en-US-AriaNeural")
    assert voices.resolve("chatterbox", "de", None) == ("chatterbox", "de", "default")
    assert "zh" not in voices.LANGUAGE_NAMES


def test_catalog_marks_local_engines_not_installed(no_local_install):
    cat = voices.catalog()
    by = {e["value"]: e for e in cat["engines"]}
    assert by["edge_tts"]["installed"] and not by["kokoro"]["installed"] and not by["chatterbox"]["installed"]
    assert set(by["kokoro"]["voices"]) == {"en", "it", "es", "fr", "pt"}
    assert {v["value"] for v in by["edge_tts"]["voices"]["it"]} >= {"it-IT-ElsaNeural", "it-IT-DiegoNeural"}
    with pytest.raises(RuntimeError, match="isn't installed"):
        voices.preview("kokoro", "it", None, Path("unused"))


def test_voice_samples_become_chatterbox_voices(no_local_install):
    vid = voices.save_sample("Nonna Pina.WAV", b"RIFF")
    assert vid == "sample:Nonna_Pina.wav"
    assert {"value": vid, "label": "My voice: Nonna_Pina", "hint": ""} in voices.voices_for("chatterbox", "it")
    assert voices.voice_arg(vid) == str(voices.SAMPLES_DIR / "Nonna_Pina.wav")
    with pytest.raises(ValueError):
        voices.save_sample("notes.txt", b"x")


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cs, "_reachable", lambda url, timeout=2.0: True)
    return tmp_path / "runs"


def _fake_llm_stages(monkeypatch):
    def run_script(rd, state, force=False):
        (rd / "script.json").write_text("{}", encoding="utf-8")
        cp._mark(state, "script", "done")
        cp.save_run_state(rd, state)
        return state

    def run_storyboard(rd, state, force=False):
        sb = {"title": "t", "scenes": [{"scene_number": i, "image_prompt": "x", "narration_text": f"riga {i}",
                                        "duration_seconds": 4.0} for i in (1, 2)]}
        (rd / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")
        cp._mark(state, "storyboard", "done")
        cp.save_run_state(rd, state)
        return state

    monkeypatch.setattr(cp, "run_script", run_script)
    monkeypatch.setattr(cp, "run_storyboard", run_storyboard)


def test_creation_keeps_its_voice_and_a_change_redoes_only_the_narration(runs, monkeypatch):
    _fake_llm_stages(monkeypatch)
    run_id = cs.create("una barchetta", 15, "9:16", "", "it", tts_engine="kokoro", tts_voice="im_nicola")
    st = cs.state(run_id)
    assert (st["language"], st["tts_engine"], st["tts_voice"]) == ("it", "kokoro", "im_nicola")

    rd = cs.run_dir(run_id)
    state = cp.load_run_state(rd)
    state.storyboard_reviewed = True
    for k in cs.GEN_STAGES:
        cp._mark(state, k, "done")
    cp.save_run_state(rd, state)
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    for s in sb["scenes"]:
        s.update(keyframe_path="k.png", clip_path="c.mp4", narration_path="n.mp3", narration_duration=2.0)
    (rd / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")

    st = cs.set_voice(run_id, "chatterbox", "default")
    assert (st["language"], st["tts_engine"], st["tts_voice"]) == ("it", "chatterbox", "default")
    status = {s["key"]: s["status"] for s in st["stages"]}
    assert status["keyframes"] == status["clips"] == "done"                     # images are kept
    assert status["narration"] == status["subtitles"] == status["edit"] == "pending"
    assert st["reviewed"]
    sb = json.loads((rd / "storyboard.json").read_text(encoding="utf-8"))
    assert all("narration_path" not in s and s["clip_path"] == "c.mp4" for s in sb["scenes"])

    st = cs.set_voice(run_id, "kokoro", "af_heart")                              # English voice, Italian script
    assert st["tts_voice"] == "if_sara" and st["language"] == "it"


def test_narration_stage_uses_the_creation_voice_and_frees_the_engine(tmp_path, monkeypatch):
    rd = tmp_path / "run"
    state = cp.new_run(tmp_path, "p", 10, "s", language="it", tts_engine="chatterbox", tts_voice="default")
    rd = cp.run_dir_for(tmp_path, state.run_id)
    (rd / "storyboard.json").write_text(json.dumps({"scenes": [{"scene_number": 1, "narration_text": "ciao"}]}),
                                        encoding="utf-8")
    state.storyboard_reviewed = True
    cp._mark(state, "clips", "done")
    calls = []

    class FakeTTS:
        def synthesize(self, text, voice=None, language="en"):
            calls.append((text, voice, language))
            out = tmp_path / "x.mp3"
            out.write_bytes(b"ID3")
            return TTSResult(audio_path=out, duration_seconds=1.5)

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(cp, "get_provider", lambda kind, name: calls.append(name) or FakeTTS())
    state = cp.run_narration(rd, state)
    assert state.stages["narration"]["status"] == "done"
    assert calls == ["chatterbox", ("ciao", "default", "it"), "closed"]


def test_local_worker_protocol_round_trip(tmp_path, monkeypatch):
    """The provider talks JSON lines to a long-lived worker; a fake worker
    stands in for the PyTorch one."""
    fake = tmp_path / "fake_worker.py"
    fake.write_text(textwrap.dedent("""
        import json, sys
        for line in sys.stdin:
            req = json.loads(line)
            if req["text"] == "boom":
                print(json.dumps({"ok": False, "error": "RuntimeError: boom"}), flush=True)
                continue
            open(req["out"], "wb").write(b"RIFF")
            print(json.dumps({"ok": True, "out": req["out"], "duration": 1.25, "voice": req["voice"]}), flush=True)
    """), encoding="utf-8")
    monkeypatch.setattr(local, "env_python", lambda: Path(sys.executable))
    monkeypatch.setattr(local, "WORKER", fake)
    monkeypatch.setattr(local, "VOICES_DIR", tmp_path)
    monkeypatch.setattr(local, "to_mp3", lambda wav, mp3: Path(mp3).write_bytes(Path(wav).read_bytes()))
    worker = local._Worker()
    monkeypatch.setattr(local, "WORKER_PROCESS", worker)
    try:
        r = local.KokoroTTSProvider().synthesize("ciao", "if_sara", "it")
        assert r.duration_seconds == 1.25 and r.audio_path.suffix == ".mp3" and r.audio_path.exists()
        pid = worker._proc.pid
        local.KokoroTTSProvider().synthesize("di nuovo", "if_sara", "it")
        assert worker._proc.pid == pid                                     # one process for every line
        with pytest.raises(RuntimeError, match="boom"):
            local.KokoroTTSProvider().synthesize("boom", None, "it")
    finally:
        worker.stop()
    assert worker._proc is None


def test_voices_api(no_local_install):
    from fastapi.testclient import TestClient
    from server.app import app

    c = TestClient(app)
    cat = c.get("/api/voices").json()
    assert [e["value"] for e in cat["engines"]] == ["edge_tts", "kokoro", "chatterbox"]
    assert {l["value"] for l in cat["languages"]} == {"en", "it", "es", "fr", "de", "pt"}
    r = c.post("/api/voices/samples", files={"file": ("me.txt", b"x")})
    assert r.status_code == 400
