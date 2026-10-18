"""Background jobs for long editor operations (plan generation, restyles,
renders, downloads) with progress the front-end polls."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    run_id: Optional[str] = None
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    created: float = field(default_factory=time.time)
    finished: Optional[float] = None

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "run_id": self.run_id, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message, "result": self.result,
                "error": self.error}


class JobManager:
    """Two workers: a long render doesn't block a quick edit on another run
    (operations on the same run are serialised by the service's run lock)."""

    def __init__(self, workers: int = 2, keep: int = 200):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ovs-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def submit(self, kind: str, fn: Callable[..., Any], *args, run_id: Optional[str] = None,
               user_error: tuple = (), **kwargs) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, run_id=run_id)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()

        def progress(frac: float, msg: str = "") -> None:
            job.progress = min(max(float(frac or 0.0), 0.0), 1.0)
            if msg:
                job.message = msg

        def run():
            job.status = "running"
            try:
                job.result = fn(*args, progress=progress, **kwargs)
                job.progress, job.status = 1.0, "done"
            except user_error as e:          # expected, shown as is
                job.error, job.status = str(e), "error"
            except Exception as e:           # bug: keep the traceback in the server log
                traceback.print_exc()
                job.error, job.status = f"{type(e).__name__}: {e}", "error"
            finally:
                job.finished = time.time()

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def active(self, run_id: Optional[str] = None) -> list[Job]:
        return [j for j in self._jobs.values() if j.status in ("queued", "running")
                and (run_id is None or j.run_id == run_id)]

    def _trim(self) -> None:
        done = [j for j in self._jobs.values() if j.finished]
        if len(done) > self._keep:
            for j in sorted(done, key=lambda j: j.finished)[: len(done) - self._keep]:
                self._jobs.pop(j.id, None)
