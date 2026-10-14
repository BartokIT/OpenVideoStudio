import json
import sys
from pathlib import Path

import pytest

_STUDIO_ROOT = Path(__file__).resolve().parent.parent
for p in (_STUDIO_ROOT, _STUDIO_ROOT / "core"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture
def svc_run(tmp_path, monkeypatch):
    """make(plan, options) -> (svc, run_id, run_dir): a Media Remix run in a
    temporary runs folder, with the (slow) timeline rebuild stubbed out so
    tests exercise the editing logic of core/studio_service.py only."""
    import pipeline
    import studio_service as svc

    monkeypatch.setattr(svc, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(svc, "PROJECTS_DIR", tmp_path / "projects")
    rebuilds = []
    monkeypatch.setattr(svc, "rebuild", lambda run_id, progress=None, t=None, select=None:
                        rebuilds.append(select) or {"selected": select, "playhead": t or 0.0})

    def make(plan: dict, options: dict | None = None):
        state = pipeline.new_run(svc.RUNS_ROOT, tmp_path, "clean", 60.0, None, "folder")
        rd = pipeline.run_dir_for(svc.RUNS_ROOT, state.run_id)
        (rd / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        state.render_options = {"look": "clean", **(options or {})}
        pipeline.save_run_state(rd, state)
        svc.rebuilds = rebuilds
        return svc, state.run_id, rd

    return make
