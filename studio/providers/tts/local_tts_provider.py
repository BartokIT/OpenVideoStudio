"""TTSProvider for the local engines (Kokoro, Chatterbox).

They run in their own environment (studio/voices/env) through
providers/tts/local_worker.py: one long-lived worker process per editor,
so a model is loaded once for all the scenes of a narration and the GPU
is freed when the worker goes idle or close() is called.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

from providers.base import TTSResult

STUDIO_ROOT = Path(__file__).resolve().parents[2]
VOICES_DIR = STUDIO_ROOT / "voices"
ENV_DIR = VOICES_DIR / "env"
WORKER = Path(__file__).with_name("local_worker.py")
IDLE_SECONDS = 180            # the worker (and the model in VRAM) goes away after this long unused
FIRST_CALL_TIMEOUT = 1800     # the first call may download the model (Chatterbox ~3 GB)
CALL_TIMEOUT = 600


def env_python() -> Path:
    return ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class _Worker:
    """The shared worker process; requests are serialized."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._timer: Optional[threading.Timer] = None
        self._warm: set = set()

    def _start(self) -> None:
        py = env_python()
        if not py.exists():
            raise RuntimeError("Local voices aren't installed — open Create → Voice and click Install.")
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        log = open(VOICES_DIR / "worker.log", "a", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
               "TRANSFORMERS_VERBOSITY": "error", "PYTHONWARNINGS": "ignore"}
        self._proc = subprocess.Popen([str(py), "-X", "utf8", str(WORKER)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                                      bufsize=1, creationflags=flags, env=env)
        self._lines = queue.Queue()
        self._warm = set()
        out = self._proc.stdout

        def pump() -> None:
            for line in out:
                self._lines.put(line)
            self._lines.put("")            # EOF: the worker died

        threading.Thread(target=pump, daemon=True).start()

    def request(self, req: dict, timeout: Optional[float] = None) -> dict:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            if not self._proc or self._proc.poll() is not None:
                self._start()
            key = req.get("engine")
            wait = timeout or (CALL_TIMEOUT if key in self._warm else FIRST_CALL_TIMEOUT)
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()
            try:
                line = self._lines.get(timeout=wait)
            except queue.Empty:
                self.stop()
                raise RuntimeError(f"The local voice didn't answer within {int(wait)} s.")
            if not line:
                self.stop()
                raise RuntimeError(f"The local voice worker stopped — see {VOICES_DIR / 'worker.log'}.")
            res = json.loads(line)
            if res.get("ok") and key:
                self._warm.add(key)
            self._timer = threading.Timer(IDLE_SECONDS, self.stop)
            self._timer.daemon = True
            self._timer.start()
            return res

    def stop(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            p, self._proc = self._proc, None
            if p and p.poll() is None:
                try:
                    p.stdin.close()
                    p.wait(timeout=10)
                except Exception:
                    p.kill()


WORKER_PROCESS = _Worker()


def synthesize_wav(engine: str, text: str, language: str, voice: Optional[str], out: Path) -> float:
    res = WORKER_PROCESS.request({"engine": engine, "text": text, "language": language,
                                  "voice": voice or "", "out": str(out)})
    if not res.get("ok"):
        raise RuntimeError(f"{engine}: {res.get('error') or 'synthesis failed'}")
    return float(res.get("duration") or 0.0)


def to_mp3(wav: Path, mp3: Path) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k",
                           str(mp3)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg couldn't encode the narration: {proc.stderr.strip()[-300:]}")


class LocalTTSProvider:
    engine = ""

    def synthesize(self, text: str, voice: Optional[str] = None, language: str = "en") -> TTSResult:
        tmp = Path(tempfile.gettempdir())
        stem = f"ovs_{self.engine}_{uuid.uuid4().hex[:10]}"
        wav, mp3 = tmp / f"{stem}.wav", tmp / f"{stem}.mp3"
        duration = synthesize_wav(self.engine, text, language, voice, wav)
        to_mp3(wav, mp3)
        wav.unlink(missing_ok=True)
        return TTSResult(audio_path=mp3, duration_seconds=duration, word_timings=None)

    def close(self) -> None:
        """Frees the GPU right away instead of waiting for the idle timeout."""
        WORKER_PROCESS.stop()


class KokoroTTSProvider(LocalTTSProvider):
    engine = "kokoro"


class ChatterboxTTSProvider(LocalTTSProvider):
    engine = "chatterbox"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synthesize one line with a local voice")
    parser.add_argument("engine", choices=["kokoro", "chatterbox"])
    parser.add_argument("text")
    parser.add_argument("--language", default="en")
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()
    cls = KokoroTTSProvider if args.engine == "kokoro" else ChatterboxTTSProvider
    r = cls().synthesize(args.text, args.voice, args.language)
    print(r.audio_path, f"{r.duration_seconds:.2f}s")
    WORKER_PROCESS.stop()
    sys.exit(0)
