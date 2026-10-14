# Installation

This page is a quick orientation. The full, step-by-step guide — with
exact model filenames, download sources, and troubleshooting — lives in
[`INSTALL.md`](INSTALL.md) and is the source of truth; this page won't
duplicate it and risk drifting out of sync.

## Before you start

OpenVideoStudio is **not** a hosted service — there's no server to sign
up for. You run it on your own machine, against your own local Ollama
and ComfyUI installs. Realistic expectations going in:

- **Verified platform:** Windows 10/11 only. Linux/macOS have known gaps
  (a hardcoded subtitle font path, NVENC-only final encoding, a
  Windows-only "open output folder" button) — see
  [`HARDWARE.md`](HARDWARE.md) for the full compatibility matrix and
  [`COMMUNITY_TRACKS.md`](COMMUNITY_TRACKS.md) Track E if you want to
  help close them.
- **Hardware:** an NVIDIA GPU with 6GB+ VRAM and NVENC support is the
  only configuration actually tested end-to-end. CPU-only is not
  supported for final video encoding — no fallback exists yet.
- **Models are not bundled.** Ollama's LLM and ComfyUI's SDXL/LTX-Video
  checkpoints are multi-gigabyte downloads you fetch yourself; see
  `INSTALL.md` for exact filenames and sources.
- **One network call by default.** Narration uses Edge TTS (Microsoft's
  free cloud text-to-speech). Everything else — script, storyboard,
  identity, keyframes, video — runs locally.
- **Time budget:** under 10 minutes once the models are already
  downloaded; the model downloads themselves are the long part.

## The five things you'll set up

1. Python 3.11+, Ollama, ComfyUI, and FFmpeg (with NVENC) — see
   prerequisites in `INSTALL.md`.
2. This repository, plus `studio/requirements.txt`.
3. The four required model files, saved under the exact filenames the
   code expects (`INSTALL.md` has the full table with sources).
4. `studio/.env`, pointing `COMFYUI_ROOT` at your ComfyUI install.
5. `ollama serve` running, then `python -m server` (the editor starts
   ComfyUI by itself when a generation needs it).

→ **Full instructions:** [`INSTALL.md`](INSTALL.md)

## After installing

Verify everything's wired up correctly without touching a GPU:

```bash
cd studio
python -m pytest tests/ -q
```

This runs against fakes/mocks for every provider — it confirms your
Python environment and the pipeline's own logic are sound, not that
Ollama/ComfyUI themselves are reachable. For that, run `python -m server`
and try a short prompt in the Create workspace.

Ran into something not covered here or in `INSTALL.md`'s troubleshooting
section? Open a
[Hardware report](../.github/ISSUE_TEMPLATE/hardware_report.md) or a
[Bug report](../.github/ISSUE_TEMPLATE/bug_report.md) issue.
