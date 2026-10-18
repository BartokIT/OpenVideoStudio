# AI Video Pipeline Workflow

This describes the actual, current AI Creation workflow (Quick Mode) step
by step — what happens, what runs on your machine versus in the cloud,
and where you're expected to intervene. For the component-level view, see
[`architecture.md`](architecture.md).

## Quick Mode (shipping today)

```
1. Prompt            → you type one idea
2. Script            → local LLM (Ollama) expands it into a scene script
3. Storyboard         → local LLM turns the script into per-scene entries
                        (image prompt, motion prompt, narration text,
                        duration)
4. Character /
   Environment identity → generated once, reused verbatim in every
                          scene's image prompt
5. ── REVIEW GATE ──  → nothing past this point runs until you approve
6. Keyframes          → local image model (ComfyUI + SDXL Lightning),
                        one per scene
7. Video clips         → local video model (ComfyUI + LTX-Video),
                        image-to-video per scene
8. Narration          → text-to-speech per scene (Edge TTS by default —
                        the one step that calls a cloud service; see
                        "Local vs. cloud" below)
9. Subtitles          → .ass file generated from narration timing
10. Automated edit     → FFmpeg assembles clips + narration + subtitles
                         + freeze/motion QC into one file
11. Final video
```

### Step-by-step detail

1. **Prompt.** One sentence to a short paragraph, entered in the editor's
   Create workspace, along with target duration, aspect ratio (9:16
   tested; 16:9/1:1 implemented but not separately validated — see
   `HARDWARE.md`), style, and language.
2. **Script.** `creative/script.py` calls the configured `LLMProvider`
   (Ollama by default) to expand the prompt into a scene-by-scene script.
3. **Storyboard.** `creative/storyboard.py` turns the script into a
   structured list of scenes, each with an image prompt, a video-motion
   prompt, narration text, and a target duration — validated against a
   schema (`creative/validation.py`) so a malformed LLM response is
   rejected rather than silently producing a broken scene.
4. **Character/environment identity.** `creative/identity.py` makes one
   focused LLM call to produce a structured description of the main
   character(s) and setting, formatted deterministically, then injects it
   verbatim into every scene's image prompt — see `architecture.md` for
   why this is a prompt-engineering technique, not a memory system.
5. **Review gate.** The storyboard is shown as one editable card per
   scene: image prompt, camera/motion prompt, narration and duration
   (3–6 s, clamped on approval). Nothing touches the GPU until you click
   **Approve and generate**; ComfyUI is started at that point if it isn't
   running.
   This is a deliberate cost/safety checkpoint: image and video generation
   is the expensive part, and re-running it because of a typo in the
   script is wasted GPU time.
6. **Keyframes.** Once approved, `creative/keyframes.py` calls the
   configured `ImageProvider` (ComfyUI running SDXL Lightning by default)
   for one keyframe per scene. Each keyframe is written to the run
   directory; if it already exists on a rerun, generation is skipped.
7. **Video clips.** `creative/clips.py` calls the configured
   `VideoProvider` (ComfyUI running LTX-Video by default) to turn each
   keyframe into a short image-to-video clip. Same
   checkpoint/skip-if-exists behavior as keyframes.
8. **Narration.** `creative/narration.py` calls the configured
   `TTSProvider` — Edge TTS by default — once per scene, and records the
   actual synthesized duration (used later for subtitle timing and
   clip-length reconciliation).
9. **Subtitles.** `creative/subtitles.py` generates a `.ass` subtitle file
   from each scene's actual narration duration (not the originally
   *planned* duration — LTX's frame-count rounding means the two can
   differ, and using the wrong one drifts every later subtitle cue).
10. **Automated edit.** `core/render.py` assembles all clips, mixes in
    narration audio, burns the subtitle file, and runs freeze/motion QC
    on the result, producing the final video via FFmpeg with NVENC.
11. **Final video.** Written to the run directory alongside the full
    storyboard JSON (prompts, seeds, timings) for provenance — see
    `examples/hero_demo/` for a real example of everything this step
    produces.

### Local vs. cloud, stage by stage

| Stage | Where it runs |
|---|---|
| Script, Storyboard, Identity | Local (Ollama) |
| Keyframes, Video clips | Local (ComfyUI) |
| Narration | **Cloud** (Edge TTS) by default; **local** with Kokoro or Chatterbox (Create → Voice) |
| Subtitles, Automated edit | Local (FFmpeg) |

The local voices are installed from the Voice panel into their own
environment — see "Local voices" in [`INSTALL.md`](INSTALL.md).

### Resumability

Every scene's keyframe and clip is checkpointed to disk. If a run fails
partway (GPU OOM, a crashed provider, closing the app), rerunning the
same run resumes from the first missing artifact rather than starting
over. Regenerating a single scene works from the editor: change its
image prompt (or its motion prompt / narration) after a generation and
approve again — only that scene's keyframe and clip (or narration) are
made again, the others are reused, and the final edit is redone.

## Pro Mode — PLANNED, not built

A guided UI over character design, environment design, and keyframe
review as their own distinct steps is on [`../ROADMAP.md`](../ROADMAP.md)
but does not exist today. The underlying pipeline stages above already
exist; the guided step-by-step UI layer over them does not. Don't rely on
documentation or marketing describing Pro Mode as available — if it
isn't in this file's walkthrough above, it isn't shipping yet.

## Remix (a separate workflow for your own media)

Not part of the AI pipeline above. The editor's Remix workspace takes your
own photos/videos and produces an edited film, using the same
FFmpeg/audio/scoring core (`core/`) as the AI pipeline's final assembly
step, with no AI generation involved: an automatic plan (order,
durations, chapters from folders and dates), then a monitor, a timeline
with transitions and text cards, looks, music cut to the beat, projects
and background renders.
