"""OpenVideoStudio — JSON API + the single-page front-end in studio/web.

Two workspaces: Remix (edit your own photos and clips) and Create (AI
video from a prompt). Runs locally on 127.0.0.1. Long operations return a
job id; poll /api/jobs/{id}.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STUDIO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(STUDIO_ROOT / ".env")
for _p in (STUDIO_ROOT, STUDIO_ROOT / "core"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import create_service as create  # noqa: E402
import studio_service as svc  # noqa: E402
import voices  # noqa: E402

from .jobs import JobManager  # noqa: E402

WEB = STUDIO_ROOT / "web"

app = FastAPI(title="OpenVideoStudio editor", docs_url="/api/docs", redoc_url=None)
jobs = JobManager()


def _err(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


def _job(kind: str, fn, *args, run_id: Optional[str] = None, **kwargs) -> dict:
    return jobs.submit(kind, fn, *args, run_id=run_id, user_error=(svc.ServiceError,), **kwargs).public()


# ----------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


class RevalidatedStaticFiles(StaticFiles):
    """The editor's own code and styles: the browser must revalidate them on
    every load (cheap, ETag) — otherwise after an update Chrome keeps using
    its heuristically cached copy and the page mixes old and new files."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", RevalidatedStaticFiles(directory=WEB), name="static")
app.mount("/ui", RevalidatedStaticFiles(directory=STUDIO_ROOT / "ui"), name="ui")
app.mount("/fonts", StaticFiles(directory=STUDIO_ROOT / "assets" / "fonts"), name="fonts")


@app.get("/files")
def files(path: str = Query(...)):
    """Serves thumbnails, renders and music — only from the runs folder and
    the music library, never arbitrary paths."""
    try:
        p = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, "Not found")
    for root in (svc.RUNS_ROOT, svc.ASSETS_MUSIC):
        try:
            p.relative_to(Path(root).resolve())
            break
        except ValueError:
            continue
    else:
        raise HTTPException(403, "Forbidden")
    if not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p, headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------- api

@app.get("/api/catalog")
def catalog():
    return svc.catalog()


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return j.public()


class NewRun(BaseModel):
    folder: str
    target_duration: float = 180.0
    sort_mode: str = "folder"
    options: dict = {}


@app.post("/api/runs")
def create_run(body: NewRun):
    return _job("create", svc.create_run, body.folder, body.target_duration, body.sort_mode, body.options)


@app.get("/api/runs")
def recent_runs():
    return svc.recent_runs()


@app.get("/api/runs/{run_id}")
def run_state(run_id: str):
    try:
        st = svc.editor_state(run_id)
    except svc.ServiceError as e:
        raise HTTPException(404, str(e))
    st["jobs"] = [j.public() for j in jobs.active(run_id)]
    return st


class Options(BaseModel):
    options: dict
    playhead: Optional[float] = None


@app.put("/api/runs/{run_id}/options")
def set_options(run_id: str, body: Options):
    return _job("options", svc.set_options, run_id, body.options, t=body.playhead, run_id=run_id)


class Edit(BaseModel):
    action: str
    shot_id: str
    payload: dict = {}


@app.post("/api/runs/{run_id}/edit")
def edit(run_id: str, body: Edit):
    return _job("edit", svc.edit, run_id, body.action, body.shot_id, body.payload, run_id=run_id)


class Cursor(BaseModel):
    playhead: Optional[float] = None
    selected: Optional[str] = None
    set_selected: bool = False


@app.post("/api/runs/{run_id}/cursor")
def cursor(run_id: str, body: Cursor):
    try:
        return svc.set_view_cursor(run_id, body.playhead, body.selected if body.set_selected else ...)
    except svc.ServiceError as e:
        raise _err(e)


@app.get("/api/runs/{run_id}/shots/{shot_id}")
def shot(run_id: str, shot_id: str):
    try:
        return svc.shot_info(run_id, shot_id)
    except svc.ServiceError as e:
        raise _err(e)


@app.get("/api/runs/{run_id}/frame")
def frame(run_id: str, t: float = 0.0):
    try:
        data, meta = svc.frame_jpeg(run_id, t)
    except svc.ServiceError as e:
        raise _err(e)
    headers = {"Cache-Control": "no-store", "X-Frame-T": str(meta["t"]), "X-Frame-Shot": str(meta["shot"]),
               "X-Frame-Shot-Id": meta["shot_id"], "X-Frame-Transition": meta["transition"].encode("ascii", "ignore").decode(),
               "X-Frame-Texts": ",".join(meta["texts"]), "Access-Control-Expose-Headers": "*"}
    return Response(content=data, media_type="image/jpeg", headers=headers)


@app.post("/api/runs/{run_id}/cut/{shot_id}")
def cut(run_id: str, shot_id: str):
    return _job("cut", svc.cut_preview, run_id, shot_id, run_id=run_id)


@app.post("/api/runs/{run_id}/preview")
def preview(run_id: str):
    return _job("preview", svc.render_preview, run_id, run_id=run_id)


@app.post("/api/runs/{run_id}/render")
def render(run_id: str):
    return _job("render", svc.render_final, run_id, run_id=run_id)


@app.post("/api/runs/{run_id}/open-folder")
def open_folder(run_id: str):
    try:
        svc.open_folder(run_id)
    except svc.ServiceError as e:
        raise _err(e)
    return {"ok": True}


# -------------------------------------------------------------- projects

@app.get("/api/projects")
def projects():
    return svc.list_projects()


class SaveProject(BaseModel):
    run_id: str
    name: str = ""


@app.post("/api/projects")
def save_project(body: SaveProject):
    try:
        return svc.save_project(body.run_id, body.name)
    except svc.ServiceError as e:
        raise _err(e)


class OpenProject(BaseModel):
    path: str


@app.post("/api/projects/open")
def open_project(body: OpenProject):
    return _job("open", svc.open_project, body.path)


# ----------------------------------------------------------------- music

@app.get("/api/music/tracks")
def tracks():
    return svc.music_tracks()


@app.post("/api/music/upload")
async def upload_music(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return svc.save_uploaded_music(file.filename or "music", data)
    except svc.ServiceError as e:
        raise _err(e)


@app.get("/api/music/search")
def search_music(q: str = "", source: str = "openverse", mood: Optional[str] = None):
    try:
        return svc.search_music(q, source, mood)
    except svc.ServiceError as e:
        raise _err(e)


class Download(BaseModel):
    track: dict[str, Any]


@app.post("/api/music/download")
def download_music(body: Download):
    return _job("download", svc.download_music, body.track)


# --------------------------------------------------------------- dialogs

@app.post("/api/dialog/folder")
def dialog_folder():
    return {"path": svc.pick_folder()}


@app.post("/api/dialog/project")
def dialog_project():
    return {"path": svc.pick_project_file()}


@app.get("/api/system")
def system():
    return {"disk_free_gb": svc.disk_free_gb(), "runs_root": str(svc.RUNS_ROOT)}


# ---------------------------------------------------------- AI creation

@app.get("/api/create/catalog")
def create_catalog():
    return create.catalog()


@app.get("/api/create/services")
def create_services():
    return create.services_status()


class NewCreation(BaseModel):
    prompt: str
    duration: float = 15.0
    aspect: str = "9:16"
    style: str = ""
    language: str = "en"
    music_preset: Optional[str] = None
    tts_engine: Optional[str] = None
    tts_voice: Optional[str] = None


@app.post("/api/create")
def create_new(body: NewCreation):
    return _job("create-script", create.create, body.prompt, body.duration, body.aspect, body.style,
                body.language, body.music_preset, tts_engine=body.tts_engine, tts_voice=body.tts_voice)


@app.get("/api/create")
def create_recent():
    return create.recent()


@app.get("/api/create/{run_id}")
def create_state(run_id: str):
    try:
        st = create.state(run_id)
    except svc.ServiceError as e:
        raise HTTPException(404, str(e))
    st["jobs"] = [j.public() for j in jobs.active(run_id)]
    return st


class Scenes(BaseModel):
    scenes: list[dict[str, Any]]


@app.put("/api/create/{run_id}/scenes")
def create_scenes(run_id: str, body: Scenes):
    try:
        return create.update_scenes(run_id, body.scenes)
    except svc.ServiceError as e:
        raise _err(e)


class Voice(BaseModel):
    engine: Optional[str] = None
    voice: Optional[str] = None
    language: Optional[str] = None


@app.put("/api/create/{run_id}/voice")
def create_voice(run_id: str, body: Voice):
    try:
        return create.set_voice(run_id, body.engine, body.voice)
    except svc.ServiceError as e:
        raise _err(e)


# ----------------------------------------------------------------- voices

def _voice_job(fn):
    """Install/preview errors (pip, missing model, GPU) are shown as they are."""
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, ValueError, OSError) as e:
            raise svc.ServiceError(str(e)) from e
    return run


@app.get("/api/voices")
def voices_catalog():
    return voices.catalog()


class VoiceEngine(BaseModel):
    engine: str


@app.post("/api/voices/install")
def voices_install(body: VoiceEngine):
    return _job("voice-install", _voice_job(voices.install), body.engine)


def _preview(engine, language, voice, progress=None):
    out = voices.preview(engine, language, voice, svc.RUNS_ROOT / "_voice_previews", progress)
    return {"url": svc._versioned(out)}


@app.post("/api/voices/preview")
def voices_preview(body: Voice):
    return _job("voice-preview", _voice_job(_preview), body.engine, body.language, body.voice)


@app.post("/api/voices/samples")
async def voices_sample(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return {"voice": voices.save_sample(file.filename or "voice.wav", data), "catalog": voices.catalog()}
    except ValueError as e:
        raise _err(e)


@app.post("/api/create/{run_id}/generate")
def create_generate(run_id: str):
    return _job("create-generate", create.approve_and_generate, run_id, run_id=run_id)


@app.post("/api/create/{run_id}/open-folder")
def create_open_folder(run_id: str):
    try:
        subprocess.Popen(["explorer", str(create.run_dir(run_id))])
    except svc.ServiceError as e:
        raise _err(e)
    return {"ok": True}
