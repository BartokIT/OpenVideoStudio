# Architecture

This document has two parts, and they are deliberately not the same
diagram:

1. **Current architecture** — what actually runs today, named after the
   real modules in this repository.
2. **Long-term vision** — the direction the project is aiming for. None
   of the vision-stage components exist yet. Where the two overlap,
   the current architecture is what's real; the vision is what
   `ROADMAP.md`'s "Long-term vision" section tracks as PLANNED.

If a term in this document isn't in the current-architecture section,
it hasn't been built.

## Current architecture (implemented)

```
Prompt
  → Script                      (creative/script.py)
  → Storyboard                  (creative/storyboard.py)
  → Character / Environment
    Identity                    (creative/identity.py)
  → Keyframes                   (creative/keyframes.py)
  → AI video clips               (creative/clips.py)
  → Narration                   (creative/narration.py)
  → Subtitles                   (creative/subtitles.py)
  → Automated editing / render  (core/render.py)
  → Final video
```

Orchestration lives in `creative/pipeline.py` (the AI Creation pipeline)
and `core/pipeline.py` (Media Remix, a separate personal-media tool
sharing the same render/audio/scoring core — see below). Both are driven
from the editor:

```
studio/web (single-page app, no build step)
   ↕ JSON API + background jobs
studio/server (FastAPI, 127.0.0.1:7870, `python -m server`)
   ↓
core/create_service.py   (Create: storyboard review, generation, ComfyUI on demand)
core/studio_service.py   (Remix: plan edits, timeline, frames, renders, projects, music)
   ↓
creative/pipeline.py · core/pipeline.py · core/pro/ (render engine)
```

The services hold all the behaviour as plain functions; the server only
exposes them (long operations run as jobs whose progress the page polls)
and serves files from the runs folder and the music library only.

### Components

- **Providers** (`providers/`) — one interface per model category
  (`LLMProvider`, `ImageProvider`, `VideoProvider`, `TTSProvider`,
  defined in `providers/base.py`). Which concrete implementation runs is
  a `config.toml` setting, not a code change. Shipped today:
  `providers/llm/ollama_provider.py` (Ollama), `providers/image/comfyui_sdxl.py`
  and `providers/video/comfyui_ltx.py` (ComfyUI), `providers/tts/edge_tts_provider.py`
  (Edge TTS, cloud). Registration is one new file plus a two-line entry
  in `providers/registry.py` — see
  [`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md)'s Model Gateway track for
  adding more.
- **Creative pipeline** (`creative/`) — the AI Creation stages listed
  above, each a standalone module operating on a shared storyboard `dict`
  that accumulates fields as it passes through each stage.
- **Review gate** — the pipeline stops after storyboard generation and
  waits for human approval (editable scene cards in the editor) before any
  GPU generation starts. This is a deliberate safety/cost checkpoint, not
  a missing automation.
- **Checkpointing** — each scene's keyframe/clip is written to the run
  directory; a scene whose artifact already exists is skipped on rerun,
  so a failed run resumes instead of restarting from scratch.
- **Render core** (`core/render.py`, `core/audio.py`, `core/plan.py`,
  `core/scan.py`, `core/score.py`) — FFmpeg assembly, subtitle burning
  (`.ass`), and audio mixing. Shared between the AI Creation pipeline and
  **Media Remix**, a separate tool in the same app for editing your own
  photo/video library — they are two different front-end workflows over
  the same underlying render core, not two separate video engines.
- **GPU sequencing** — the pipeline never keeps two heavy models
  resident at once (Ollama unloads before ComfyUI/SDXL loads, which frees
  before ComfyUI/LTX loads). This is what makes the 6GB-VRAM target in
  [`HARDWARE.md`](HARDWARE.md) achievable; it is a runtime discipline in
  `creative/pipeline.py`, not a separate scheduler component.

### What this is not (today)

No agent framework, no scene graph data structure, no persistent
character-memory store, and no plugin SDK exist in the current code.
Character/environment consistency today is a single structured identity
object generated once per project and re-injected verbatim into every
scene's prompt (`creative/identity.py`) — a prompt-engineering approach,
not a learned or graph-based memory system. It measurably reduces drift
versus the free-text approach it replaced, but visual identity still
drifts across scenes in practice — see the hero demo's own disclosure in
[`../README.md`](../README.md) and
[`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md)'s Character Consistency
track, which exists specifically because this isn't solved yet.

## Long-term vision (not implemented — PLANNED)

The project's direction is to grow from a single-prompt pipeline into a
more complete open-source AI video production system. None of the boxes
below beyond what's listed in "Current architecture" exist in code today;
this is a target shape, not a status report. See `ROADMAP.md`'s
"Long-term vision" section for how these map to community tracks and
maintainer-led work.

```
Idea / Prompt
  ↓
Story Engine            — richer narrative planning than today's
                           single script-generation call
  ↓
Storyboard Generation    — implemented today (creative/storyboard.py)
  ↓
Scene Graph              — a structured, queryable representation of
                           scenes/characters/objects/relationships,
                           replacing today's flat per-scene dict
  ↓
Character Memory         — a persistent identity/appearance store,
                           beyond today's single-shot identity object
  ↓
AI Generation Pipeline   — implemented today (keyframes → clips)
  ↓
Video Editing Pipeline   — today: automated assembly only; a real
                           timeline editor is Track F, HELP WANTED
  ↓
Final Film
```

This is intentionally aspirational language ("aims to become"). Treat
every box that isn't also in the "Current architecture" diagram as not
built. If you want to work on closing this gap, `ROADMAP.md`'s Long-term
vision section and [`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md) are the
places to start — several of these (Character Memory, Scene Graph) don't
have an owner yet.

## Related documents

- [`workflow.md`](workflow.md) — the same pipeline, described from the
  operator's point of view (what you click, what you wait for, what you
  approve).
- [`installation.md`](installation.md) / [`INSTALL.md`](INSTALL.md) — how
  to run this.
- [`../ROADMAP.md`](../ROADMAP.md) — status of every stage above.
- [`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md) — claimable work toward
  the vision architecture.
