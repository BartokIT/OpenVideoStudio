"""Tests for core/music.py: the preset catalogue, look → mood matching, the
local synthesiser and the user's own library folder."""
from __future__ import annotations

from pathlib import Path

import numpy as np

import music


def test_library_lists_builtins_and_user_files(tmp_path):
    tracks = music.library(tmp_path)
    assert [t.key for t in tracks] == list(music.BUILTIN)
    assert all(t.builtin and t.path is None for t in tracks)
    assert {t.mood for t in tracks} == set(music.MOODS)

    (tmp_path / "my_song.mp3").write_bytes(b"\0" * 10)
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "library.toml").write_text(
        '[[track]]\nfile = "my_song.mp3"\ntitle = "My song"\nmood = "upbeat"\nvolume = 0.5\nbeat_sync = true\n',
        encoding="utf-8")
    tracks = music.library(tmp_path)
    mine = music.by_key(tracks, "file:my_song.mp3")
    assert mine and mine.title == "My song" and mine.mood == "upbeat" and mine.volume == 0.5 and mine.beat_sync
    assert not mine.builtin and Path(mine.path).exists()
    assert music.by_key(tracks, "file:notes.txt") is None


def test_pick_for_look_matches_mood(tmp_path):
    tracks = music.library(tmp_path)
    assert music.pick_for_look("travel", tracks).mood == "upbeat"
    assert music.pick_for_look("wedding", tracks).mood == "romantic"
    assert music.pick_for_look("unknown look", tracks).mood == "nostalgic"


def test_synthesize_every_preset_is_audible_and_normalised(tmp_path):
    from scipy.io import wavfile

    for key in music.BUILTIN:
        out = music.synthesize(key, tmp_path / f"{key}.wav", seconds=6.0)
        sr, data = wavfile.read(str(out))
        assert sr == music.SR and data.ndim == 2 and data.shape[1] == 2
        assert abs(len(data) / sr - 6.0) < 0.05
        peak = np.abs(data).max() / 32767
        assert 0.7 < peak <= 1.0, key
        assert data[sr * 2: sr * 4].std() > 200, key  # not silence in the middle


def test_ensure_track_generates_builtin_once(tmp_path, monkeypatch):
    real = music.synthesize
    monkeypatch.setattr(music, "synthesize", lambda key, out, seconds=3.0, seed=11: real(key, out, seconds=3.0))
    tr = music.by_key(music.library(tmp_path), "quiet_air")
    msgs = []
    done = music.ensure_track(tr, tmp_path, lambda f, m: msgs.append(m))
    assert done.path and Path(done.path).exists() and Path(done.path).suffix in (".m4a", ".wav")
    assert any("Quiet air" in m for m in msgs)
    again = music.ensure_track(music.by_key(music.library(tmp_path), "quiet_air"), tmp_path)
    assert again.path == done.path  # cached: listed with a path, not regenerated
