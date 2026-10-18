# OpenVideoStudio


## 🎬 Demo Videos

### Founder Story

Why I built OpenVideoStudio:

I couldn't afford expensive AI video tools, so I built my own open-source AI studio.

▶️ Watch:
https://youtu.be/XKSgOEAzpeE


### Technical Overview

A developer-focused overview of the OpenVideoStudio pipeline.

▶️ Watch:
https://youtu.be/8VCze8sYlVg


---

**A local-first, Apache-2.0-licensed AI video creation studio.**
From one prompt to a complete video — most of it never leaves your machine.

[Install](docs/INSTALL.md) · [Architecture](docs/architecture.md) · [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Discussions](../../discussions)

### In one look

| | |
|---|---|
| **What it is** | An open-source video editor with two workspaces: **Create** turns one text prompt into a fully edited, narrated, subtitled video (script → storyboard → character/environment identity → keyframes → video clips → narration → subtitles → final video); **Remix** turns your own photos and clips into an edited film with a timeline, looks, titles and music cut to the beat. |
| **Why it exists** | Built by one developer on a 6GB laptop GPU, without a GPU farm or unlimited AI credits — so the pipeline had to actually run on modest hardware, not just a data-center demo. |
| **How it's different** | Local-first (script/storyboard/identity/keyframes/video all run on your own machine), provider-swappable by config not code, resumable with per-scene checkpointing, and a mandatory human review gate before any GPU generation starts — see [Features](#features) for what that means concretely. |
| **How to try it** | `git clone` → `pip install -r requirements.txt` → `python -m server`. Full steps in [Quick Start](#quick-start). |

*One thing worth knowing up front: narration currently uses one cloud
service by default (Edge TTS) — not buried, see
["Local by default"](#local-by-default-with-one-disclosed-exception)
below. Everything else in the pipeline runs on your own hardware.*

## Demo

![A real, unedited OpenVideoStudio run: an astronaut exploring an abandoned space station](examples/hero_demo/preview.gif)

*"Echoes of Home" — generated end-to-end from a single prompt: script →
storyboard → character/environment identity → 6 keyframes → 6 video
clips → narration → subtitles → automated edit. 2× speed above; full
32.9s video and complete provenance (prompt, models, seeds) in
[`examples/hero_demo/`](examples/hero_demo/). Not a mockup — this is the
actual pipeline, unedited. **Worth knowing:** this particular run's
character identity visibly drifts across scenes (hair/face aren't fully
consistent) — a real, disclosed instance of the gap
[Track C](docs/COMMUNITY_TRACKS.md#track-c--character-consistency) exists
to close, not something we edited around. Full account in
[`examples/hero_demo/README.md`](examples/hero_demo/README.md).*

## The editor

One local web app, one screen, no page scrolling: panels and tabs instead
of long forms. Screenshots below use AI-generated sample media from the
Create pipeline.

![Remix workspace: media bin, monitor with an animated chapter title, shot inspector and a timeline with transitions, title track and the music waveform with its beat markers](docs/images/editor-remix.webp)

*Remix — pick a folder and the plan, chapters and cuts are generated
automatically; then fine-tune on the timeline (V1 photos and clips with
their transitions, T1 titles, A1 music with beats and accents).*

| | |
|---|---|
| ![Music tab with built-in presets and cut-to-the-music modes, Look tab with eight film looks](docs/images/editor-music-looks.webp) | ![Create workspace: editable storyboard with keyframes, the review gate and the finished vertical video](docs/images/editor-create.webp) |
| *Music presets, online Creative Commons search, cuts on bars, beats or accents; eight looks with matching titles and transitions.* | *Create — an editable storyboard you review before anything runs on the GPU, then keyframes, clips, narration, subtitles and the final edit.* |

## Vision

OpenVideoStudio's near-term goal is what's already shipping: a reliable,
local-first, single-prompt-to-video pipeline that runs on consumer
hardware. Its longer-term direction is to grow into a more complete
open-source AI video production system — richer story planning, a real
character-memory model, a visual workflow editor, and community-shared
workflows — the way ComfyUI grew from a single Stable Diffusion graph
runner into a general node-based generation platform, or the way
Blender's pipeline grew around a stable open core.

None of that long-term direction is built yet. See
[`docs/architecture.md`](docs/architecture.md)'s "Long-term vision"
section and [`ROADMAP.md`](ROADMAP.md) for exactly what's real today
versus what's an aspiration with no code behind it — this README does
not blur that line.

## Architecture overview

```
Providers (Ollama · ComfyUI · Edge TTS)
        ↓
Creative pipeline (script → storyboard → identity → keyframes → clips)
        ↓
Review gate (you approve before any GPU generation runs)
        ↓
Render core (FFmpeg: narration mix, subtitle burn, freeze/motion QC)
        ↓
Final video
```

Every model category (LLM, image, video, TTS) is an interface in
`providers/base.py`; which concrete provider runs is a `config.toml`
setting, not a code change — adding one is a new file plus a two-line
registry entry in `providers/registry.py`. The creative pipeline and the
render core are also shared by **Media Remix**, a secondary tool in the
same app for editing your own photo/video library — two front-end
workflows over one render engine, not two separate video engines.

→ Full component breakdown, plus the long-term "Story Engine / Scene
Graph / Character Memory" vision architecture (not built — clearly
marked as such): [`docs/architecture.md`](docs/architecture.md).

## AI video pipeline

```
Prompt
  → Script
  → Storyboard
  → Character / Environment identity
  → Keyframes
  → AI video clips
  → Voice (narration)
  → Subtitles
  → Automated editing
  → Final video
```

One prompt goes in. A fully edited, narrated, subtitled video comes out.
Generation is checkpointed stage by stage — a scene whose keyframe/clip
already exists is skipped on rerun, so a failed run resumes instead of
restarting from scratch — and nothing renders past the storyboard until
you review and approve it.

→ Step-by-step walkthrough of what each stage does and which run
locally vs. in the cloud: [`docs/workflow.md`](docs/workflow.md).

### Local by default, with one disclosed exception

Script, storyboard, character/environment identity, keyframes, and video
clips are all generated by models running entirely on your own machine
(Ollama + ComfyUI) — none of that ever has to leave your hardware.
**Narration is the one exception today**: the default TTS provider is
Microsoft's free Edge TTS service, which sends narration text over the
network. It is an unofficial endpoint (used through the `edge-tts`
package): its use is subject to Microsoft's terms, not this project's
license, and it may stop working at any time. A fully local/offline TTS provider doesn't ship yet — see
[`docs/ISSUES_SEED.md`](docs/ISSUES_SEED.md) for that as an open
contribution. We'd rather disclose this clearly than let "local" imply
more than what's actually true today.

## Features

- **Free and open source.** Apache-2.0 licensed — no account, no
  paywall, no usage metering on the software itself. See [License](#license)
  for exactly what that does and doesn't cover.
- **Local-first.** See above — everything except narration's default
  provider runs entirely on your own hardware.
- **Consumer-GPU friendly.** Verified end-to-end on a 6GB laptop GPU (see
  [`docs/HARDWARE.md`](docs/HARDWARE.md) for exactly what's tested vs.
  expected vs. unknown — we don't claim hardware support we haven't
  verified; NVENC-capable NVIDIA GPUs only for now, no CPU/other-vendor
  encode fallback yet).
- **Provider selection is a config change, not a code change.** See
  [Architecture overview](#architecture-overview) above. An
  OpenAI-compatible adapter doesn't ship yet (tracked as a seeded issue)
  — today's shipped providers are Ollama, ComfyUI (SDXL + LTX-Video), and
  Edge TTS.
- **Resumable, with a human review gate.** Generation is checkpointed
  stage by stage; nothing renders past the storyboard until you approve
  it, and a failed run resumes instead of restarting from scratch.
- **Automated video QC.** Freeze/motion detection, schema validation, and
  narrative-quality checks run automatically during generation.

Two modes, one honest label for each:

- **Quick Mode** (shipping today): prompt → automatic generation up to a
  mandatory storyboard review checkpoint → (you approve) → automatic
  generation → final video. It's not zero-touch end-to-end by design —
  the review gate is a deliberate safety feature, not a missing one.
- **Pro Mode** (roadmap, not yet built): a guided UI over character
  design, environment design, and keyframe review as their own steps,
  plus a timeline for AI creations (Remix already has one). See [`ROADMAP.md`](ROADMAP.md) — anything
  not shipping today is labeled PLANNED, HELP WANTED, or RESEARCH, never
  presented as done.

## Installation

Verified on **Windows 10/11**, an NVIDIA GPU with **6GB+ VRAM** and
NVENC, Python 3.11+, Ollama, ComfyUI, and FFmpeg. Models (Ollama LLM,
SDXL, LTX-Video checkpoints) are multi-gigabyte downloads, not bundled in
this repository.

→ Quick orientation: [`docs/installation.md`](docs/installation.md)
→ Full step-by-step guide (prerequisites, exact model filenames and
sources, troubleshooting): [`docs/INSTALL.md`](docs/INSTALL.md)

## Quick Start

```bash
git clone <repository-url>
cd OpenVideoStudio/studio
pip install -r requirements.txt
cp .env.example .env    # set COMFYUI_ROOT
python -m server        # opens http://127.0.0.1:7870
```

On Windows, `Start_OpenVideoStudio.bat` does the last step and
`Stop_OpenVideoStudio.bat` stops everything (editor, ComfyUI, Ollama's
loaded model).

Targeting under 10 minutes once you already have the required models
downloaded. Opens the OpenVideoStudio editor, a single-screen local web
app with two workspaces:

- **Create** — the prompt-to-video pipeline above: script and storyboard
  from the local LLM, an editable storyboard you review, then keyframes,
  clips, narration, subtitles and the final edit after you approve.
  ComfyUI is started automatically when a generation needs it (from
  `COMFYUI_ROOT`); Ollama must be running.
- **Remix** — turn your own photo/video library into an edited film:
  automatic plan, monitor, timeline, media bin, looks, titles,
  transitions, music cut to the beat, projects, background renders.
  Doesn't need ComfyUI or Ollama.

Verify your install without touching a GPU:

```bash
cd studio && python -m pytest tests/ -q
```

## Roadmap

Shipped: prompt → script → storyboard → character/environment identity →
keyframes → clips → narration → subtitles → final video, local Ollama +
ComfyUI generation, resumable per-scene checkpointing, the single-screen
editor (Create + Remix with timeline, looks, music cut to the beat,
projects), 199 tests passing. Not yet built: Pro Mode's guided UI, a
timeline for AI creations, additional providers beyond Ollama/ComfyUI/Edge TTS, and the longer-term
Character Memory / Scene Graph / multi-agent direction covered in
[Vision](#vision) above.

→ Full status by version, with DONE / HELP WANTED / RESEARCH / PLANNED
labels on every line: [`ROADMAP.md`](ROADMAP.md)

## Contributing

The core pipeline is maintainer-led and tested. Everything past that is a
real, independently claimable contribution track — we deliberately didn't
build all of it ourselves so there'd be something worth contributing to.

| Track | What it covers |
|---|---|
| 🎨 [AI Art Studio](docs/COMMUNITY_TRACKS.md#track-a--ai-art--visual-development) | Character/environment bibles, reference conditioning, inpainting, Krita integration |
| 🧑 [Character Consistency](docs/COMMUNITY_TRACKS.md#track-c--character-consistency) | Visual identity drift, face-similarity QC, benchmarks |
| 🔌 [Model Gateway](docs/COMMUNITY_TRACKS.md#track-b--universal-model-gateway) | OpenAI-compatible/llama.cpp/vLLM providers, enterprise endpoints |
| 🎬 [Video Models](docs/COMMUNITY_TRACKS.md#track-d--provider-integrations) | Additional image/video model adapters |
| 🎞 [Timeline Editor](docs/COMMUNITY_TRACKS.md#track-f--timeline--editor) | Scene reorder, trimming, transitions, subtitle editor |
| 🧪 [AI Video QC](docs/COMMUNITY_TRACKS.md#track-g--ai-video-qc) | Final-video freeze QC, duplicate-shot/audio QC, quality scoring |
| 🐧 [Linux](docs/COMMUNITY_TRACKS.md#track-e--platform-support) / 🍎 [macOS](docs/COMMUNITY_TRACKS.md#track-e--platform-support) | Platform support beyond the currently-tested Windows setup |
| 🌍 [Translation](docs/COMMUNITY_TRACKS.md#track-h--documentation--localization) / 📚 [Documentation](docs/COMMUNITY_TRACKS.md#track-h--documentation--localization) | Localization, install guides, tutorials |

Start here: [`docs/good-first-issues.md`](docs/good-first-issues.md) has
beginner-friendly starter tasks (both live issues and not-yet-filed
ideas), and [`docs/contribution.md`](docs/contribution.md) /
[`CONTRIBUTING.md`](CONTRIBUTING.md) cover the contribution process end
to end — forking, branching, PRs, DCO sign-off, and how contribution
turns into repository access over time. New here? Start with a
Discussion or a `good first issue` before taking on something large.

## Community

- **[GitHub Discussions](../../discussions)** — usage questions, ideas,
  and workflow sharing live here, not in Issues. See
  [`docs/community.md`](docs/community.md) for what each category is for.
- **Issues** — structured templates for
  [bugs](.github/ISSUE_TEMPLATE/bug_report.md),
  [features](.github/ISSUE_TEMPLATE/feature_request.md),
  [model/provider requests](.github/ISSUE_TEMPLATE/model_request.md), and
  [workflow shares](.github/ISSUE_TEMPLATE/workflow_share.md).
- **[Code of Conduct](CODE_OF_CONDUCT.md)** — Contributor Covenant 2.1;
  applies to all project spaces.
- **[Governance](GOVERNANCE.md)** — how the project is run, and exactly
  how contribution turns into Trusted Contributor / Reviewer / Maintainer
  status. Sponsors never buy governance — see `GOVERNANCE.md`'s
  "Sponsors do not buy governance" section.
- **[Support](SUPPORT.md)** — where to get help, and how to reach
  maintainers for non-security issues.
- **Security** — please report vulnerabilities privately; see
  [`SECURITY.md`](SECURITY.md). Do not open a public issue.

## Why I built this

I didn't start OpenVideoStudio with access to expensive GPUs or a large
AI budget — the opposite. My main machine is a laptop with an RTX 3060
6GB GPU (see [`docs/HARDWARE.md`](docs/HARDWARE.md) for exactly what's
verified on it, not just claimed). Paying per-generation credits just to
experiment wasn't something I could keep doing indefinitely, and the
hardware itself isn't particularly powerful either. So instead of
solving the problem with more compute, I built the workflow: prompt →
script → storyboard → keyframes → clips → narration → subtitles →
assembled video, made to actually run end-to-end on the machine I
already had.

It's still far from finished. Character identity drifts across scenes
more than I'd like — see the hero demo's own disclosure above and
[Track C](docs/COMMUNITY_TRACKS.md#track-c--character-consistency), the
open track that exists specifically to fix this. More providers need
integrating, the editor is still spec-only, and Linux/macOS support
isn't there yet. Rather than keep building all of that alone behind a
closed door, I'd rather open it now — to developers, creators, and
researchers, especially anyone else working without unlimited GPUs or
API budgets. Found a bug? Open an issue. Have an idea? Start a
Discussion. Can fix even one small thing? Send a PR — see
[`CONTRIBUTING.md`](CONTRIBUTING.md). I'd like the Contributors page to
eventually have more than one name on it.

## Project status

Actively developed. See [`CHANGELOG.md`](CHANGELOG.md) for what's shipped
and [`ROADMAP.md`](ROADMAP.md) for what's next. Governance model in
[`GOVERNANCE.md`](GOVERNANCE.md); security policy in
[`SECURITY.md`](SECURITY.md).

## License

[Apache License 2.0](LICENSE). See
[`docs/LICENSE_STRATEGY.md`](docs/LICENSE_STRATEGY.md) for the full
comparison against MIT/GPLv3/AGPLv3 and why Apache-2.0 was chosen — in
short, MIT-level adoption-friendliness plus an explicit patent grant,
which matters for a project this close to fast-moving AI/model tooling.
Contributors sign off commits via [DCO](https://developercertificate.org/)
(`git commit -s`) rather than a CLA — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

Bundled fonts in [`studio/assets/fonts/`](studio/assets/fonts/) are
third-party works under the SIL Open Font License 1.1 (see their
`OFL.txt`). Music you find through Remix's **Online** tab keeps its own
Creative Commons licence (credit saved next to the track and added to the
closing card); model weights are downloaded separately under their own
licences (see [`docs/INSTALL.md`](docs/INSTALL.md)).

The license covers this repository's code. It does not cover the
OpenVideoStudio name, logo, or official release channels — see
[`GOVERNANCE.md`](GOVERNANCE.md#brand-control) for how those stay
separately protected, and why a permissive code license doesn't hand
them away.
