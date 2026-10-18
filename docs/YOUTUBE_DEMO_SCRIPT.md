# YouTube Demo Script

A shot-by-shot script for the full walkthrough video referenced in
`docs/LAUNCH_CONTENT.md` (Section 5). That file has the title, upload
description, and posting timing; this file is the thing you actually
read from while recording. Target length: 8–11 minutes — long enough to
show a real generation run end to end, short enough that the review gate
wait doesn't kill pacing (cut waiting time in editing; say so on screen
when you do, per the honesty note in "Editing notes" below).

**Recording setup:** the same 6GB RTX 3060 laptop the project is tested
on (see `docs/HARDWARE.md`) — the video's credibility depends on this
being the actual hardware, not a stronger machine standing in for it.

---

## 0:00–0:15 — Cold open hook

**On screen:** the final hero video already playing (a few seconds of
`examples/hero_demo/final.mp4` or a fresh run's output), no intro
graphics yet.

**Say:**
> "Everything you're about to watch me generate — script to final
> cut — came from one sentence, on this laptop's GPU. Six gigabytes of
> VRAM. That's it. Let's do it live."

**Editing note:** don't use a *different* clip than the one you generate
live later in the video — if the cold-open hero clip and the on-camera
generated clip are different runs, say so on screen (e.g. "cold open
uses an earlier run — today's run starts now") rather than letting it
look like one continuous take.

## 0:15–0:45 — Who's talking and why this exists

**On screen:** face cam or a simple title card, README's "Why I built
this" section visible or paraphrased.

**Say:**
> "I built OpenVideoStudio alone, without a GPU farm or a big AI budget
> — this laptop is the whole budget. Paying per-generation credits just
> to experiment wasn't something I could keep doing, so instead of
> buying more compute, I built a pipeline that had to actually work
> within six gigabytes. It's open source now — Apache-2.0 — and today
> I'm showing you exactly how it works, not a highlight reel."

## 0:45–1:30 — What you're about to see (the pipeline map)

**On screen:** the pipeline diagram from `README.md` / `docs/workflow.md`
— Prompt → Script → Storyboard → Character/Environment Identity →
Keyframes → Video Clips → Narration → Subtitles → Final Video.

**Say:**
> "One prompt goes in. A local model writes the script, then a
> scene-by-scene storyboard. A character and environment identity gets
> generated once and reused in every scene — that's the fix for a
> continuity problem I'll show you honestly isn't fully solved yet.
> Then local image and video models generate keyframes and clips.
> Narration, subtitles, an automated edit — final video out. Script
> through video generation: all local. One disclosed exception on
> narration, coming up in a few minutes — I'm not going to bury it."

## 1:30–2:30 — Install / environment check (compressed)

**On screen:** terminal, `docs/INSTALL.md` open in a second window.

**Say:**
> "I'm not going to make you watch a full install — that's what
> `docs/INSTALL.md` is for. Quick environment check instead: Ollama
> running, ComfyUI running with the SDXL Lightning and LTX-Video
> checkpoints in place, `.env` pointing at my ComfyUI root, and —"

**Do on screen:**
```bash
cd studio
python -m pytest tests/ -q
```

**Say:**
> "— tests passing against fakes, confirming the pipeline logic itself
> is sound before I touch a real GPU. Now the real thing:"

```bash
python -m server
```

## 2:30–3:15 — The prompt

**On screen:** the editor, Create workspace.

**Say:**
> "One prompt. I'm not cherry-picking a prompt I know works well — [type
> a genuinely new prompt on camera]. Target duration, aspect ratio — 9:16
> is the one actually validated end to end, 16:9 and 1:1 exist but
> aren't separately verified yet, so I'll stay on 9:16. Style, language.
> Generate."

## 3:15–4:15 — Script and storyboard generation

**On screen:** status log updating, then the storyboard table populating.

**Say:**
> "This is Ollama running locally, writing the script and breaking it
> into scenes — nothing here touches a GPU-heavy image or video model
> yet. [once storyboard appears] Here's the storyboard: image prompt,
> motion prompt, narration text, duration, per scene. And here's the
> character and environment identity — generated once, about to get
> reused verbatim in every scene's prompt below."

## 4:15–5:30 — The review gate (important — don't skip or rush this)

**On screen:** the editable storyboard table, full screen, enough time to
actually read it.

**Say:**
> "This is the review gate, and it's not a UI limitation — it's
> deliberate. Nothing past this point touches the GPU until I approve.
> I can edit any field here — [actually edit one field on screen, e.g.
> fix a narration line or reorder a scene] — because re-running image
> and video generation over a typo is wasted GPU time. This is Quick
> Mode, what ships today. A more guided step-by-step version of this —
> Pro Mode — is on the roadmap, not built yet; don't take anything past
> this point as more automated than it is. Approving now."

## 5:30–7:00 — Keyframes and clips generating

**On screen:** ComfyUI queue/progress, keyframes appearing one by one,
then clips.

**Say:**
> "SDXL Lightning generating keyframes — one per scene, each one getting
> that same identity text injected into its prompt. [as clips start]
> LTX-Video turning each keyframe into a short clip. Watch VRAM here if
> you want proof this fits in six gigabytes — Ollama's already unloaded,
> only one heavy model is resident at a time. This is the part that
> takes real time — I'm speeding this up in the edit, timestamped
> honestly on screen, not cut to hide how long it actually takes."

**Editing note:** speed-ramp or time-lapse this section, with an
on-screen "sped up Nx" label — don't silently cut generation time in a
way that implies it's faster than it is. If you want a real-time
reference, say the actual wall-clock time this run took, once, on
screen or in the description.

## 7:00–7:45 — Narration (the disclosed cloud step)

**On screen:** narration generating, waveform or a simple "Edge TTS"
label on screen.

**Say:**
> "Narration is the one part of this pipeline that isn't local. Default
> provider's Edge TTS — Microsoft's free cloud text-to-speech. Narration
> text goes over the network for this one step; everything before it
> stayed on this laptop. I'd rather say that plainly on camera than let
> 'local' imply more than what's actually true. A fully offline TTS
> provider doesn't ship yet — it's an open issue if that's something
> you want to build."

## 7:45–8:15 — Subtitles and final assembly

**On screen:** subtitle file generating, then FFmpeg assembly progress.

**Say:**
> "Subtitles get timed off the actual narration duration, not the
> originally planned one — LTX's frame counts round, so using the real
> duration matters. Then FFmpeg mixes narration, burns subtitles, runs a
> freeze/motion check, and assembles the final file."

## 8:15–9:15 — Watch the result, honestly

**On screen:** the finished video, played in full or near-full.

**Say:**
> "Here's what came out. [after it plays] And here's what I'm not going
> to pretend isn't there: [point to a specific frame] — character
> identity drift, scene to scene. It's a real, disclosed gap — same
> thing you'll see called out in the hero demo in the README. That's not
> a bug I'm hiding from you on a launch video; it's the actual current
> state, and it's why there's an open Character Consistency track for
> anyone who wants to help close it."

## 9:15–10:00 — What's real vs. what's roadmap

**On screen:** `ROADMAP.md` or `docs/COMMUNITY_TRACKS.md` scrolling.

**Say:**
> "To be clear about what you just watched versus what's still ahead:
> what you saw is Quick Mode, shipping today. Pro Mode's guided UI, a
> real timeline editor, more providers, Linux and macOS support — all
> open, scoped contribution tracks, not built yet. I deliberately didn't
> finish all of this myself so there'd be something real to contribute
> to."

## 10:00–end — Close

**On screen:** repo URL, Discussions link, `good first issue` label in
the GitHub UI.

**Say:**
> "It's Apache-2.0, on GitHub right now, with issues that have full
> acceptance criteria if you want to start contributing today — link
> below. If you found a bug watching this, open an issue. If you've got
> an idea, start a Discussion. I'd like the Contributors page to
> eventually have more than one name on it. Thanks for watching."

**On screen (end card):** repo URL, Discussions URL, `docs/INSTALL.md`
link, subscribe prompt if applicable.

---

## Editing notes (read before cutting the video)

- **Don't hide generation wait time by silently jump-cutting it** — speed
  ramp with a visible "sped up" label, or state the real wall-clock time
  once. The whole point of this video is credibility; a silent cut here
  undermines it more than an honest "this took 6 minutes, sped up"
  ever would.
- **Don't swap in a better-looking pre-made clip** for the live
  generation result if the live run comes out rougher than you'd like.
  If the live run has stronger identity drift than the hero demo, keep
  it and say so — that's more honest than the hero demo alone, not less.
- **Keep the Edge TTS disclosure in the video itself**, not just the
  description — viewers who don't read descriptions still deserve to
  hear it.
- **Match every hardware claim in the video to `docs/HARDWARE.md`** —
  if you ad-lib a claim on camera that isn't in that file, cut it or add
  the hedge back in during editing.
- **Timestamps for the YouTube description:** fill in real ones after
  editing (this script's minute marks are targets, not final cuts) and
  paste them under the description already drafted in
  `docs/LAUNCH_CONTENT.md` Section 5.
