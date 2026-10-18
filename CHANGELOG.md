# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Dates reflect when work landed in the private development repository this
public repository was prepared from.

## Unreleased — English launchers, screenshots, licence review (2026-10-18)

### Added
- README (English and Chinese): an "The editor" section with screenshots
  of Remix and Create, taken with AI-generated sample media
  (`docs/images/`).
- `NOTICE`: states that this is a modified fork and lists the bundled
  third-party fonts (SIL OFL 1.1); modified upstream files carry a
  "Modified in 2026" line (Apache-2.0 §4(b)).

### Changed
- Launchers renamed to English: `Start_OpenVideoStudio.bat`,
  `Stop_OpenVideoStudio.bat` (messages in English too); `.gitattributes`
  keeps CRLF for `.bat` files.
- Online music: tracks under a CC **ND** (no derivatives) licence are
  flagged in red and can't be added — syncing music to pictures is an
  adaptation, which ND forbids. The footnote now says so.
- `studio/assets/fonts/OFL.txt` lists the copyright line of every bundled
  font family, not just Montserrat.
- README: Edge TTS is called out as an unofficial Microsoft endpoint
  governed by Microsoft's terms; the licence section covers fonts, online
  music and model weights; stale "no timeline editor" / "67/67 tests"
  statements updated.

### Fixed
- Create: after moving the project folder, a creation's keyframes and
  clips disappeared from the storyboard (the storyboard stores absolute
  paths) and approving again regenerated them. They are now found by name
  in the run's own `keyframes/` and `clips/`, and the paths are rewritten
  before generating.
- Media bin: a video tile showed its film icon at full size over the
  thumbnail.

## Unreleased — one editor, no Gradio (2026-10-13)

### Added
- **Create workspace** in the editor (switch Remix / Create at the top):
  prompt, length, format, style, language and music → script and
  storyboard from the local LLM → one editable card per scene (image
  prompt, camera/motion, narration, seconds; keyframes appear as they
  are generated, clips can be played) → **Approve and generate** →
  keyframes, clips, narration, subtitles, final edit with live stage
  status and the video in the side panel. Recent creations in their own
  tab. Ollama / ComfyUI status lights in the top bar.
- `core/create_service.py`: AI creation for the API. The review gate is
  unchanged (approving is the only way to reach the GPU stages, each of
  which re-checks it); scene durations are clamped to 3–6 s on approval;
  editing a scene after a generation invalidates only that scene's
  keyframe/clip (image or motion prompt) or narration, so approving again
  regenerates just what changed.
- ComfyUI is started on demand (new console window) when a generation
  needs keyframes or clips and it isn't running, from `COMFYUI_ROOT` or
  `COMFYUI_PORTABLE`; a running ComfyUI is reused.

### Removed
- The Gradio app (`studio/app.py`) and its UI-only tests; Gradio is no
  longer a dependency. `requirements.txt` now lists what the editor
  actually uses (`fastapi`, `uvicorn`, `python-multipart`; `httpx` for
  tests). Tests that covered `app.py` logic were moved to the services.
- `Avvia_Editor.bat`. The launchers are now English-named:
  `Start_OpenVideoStudio.bat` starts the editor (port 7870) without
  ComfyUI; `Stop_OpenVideoStudio.bat` stops ports 7870 and 8188.

### Fixed
- Narration failed with `403 … speech.platform.bing.com`: Edge TTS
  rejects older clients; `edge-tts>=7.3.1`.
- With a long film (e.g. 10 minutes) the timeline widened the whole page
  beyond the window: the right panel, the top-bar buttons and the
  transport ended up off-screen and the monitor looked empty. The page is
  now pinned to the window width and the timeline scrolls inside its own
  box.
- The editor's scripts and styles are served with `Cache-Control:
  no-cache` (revalidated via ETag), so after an update the browser no
  longer mixes cached old files with new ones.

## Unreleased — dedicated editor front-end (2026-10-13)

### Added
- **OpenVideoStudio editor** for Media Remix: a single-screen web
  application (`studio/web`, no build step) served by a local FastAPI
  server (`studio/server`, `python -m server`, http://127.0.0.1:7870).
  Everything fits one screen with no page scrolling,
  down to 1366×768: top bar (project name, Projects, Save, Preview 15 s,
  Render), Media / Music / Online tabs on the left, the monitor with
  transport in the centre, Shot / Look / Text / Cuts / Export tabs on the
  right, the timeline docked at the bottom and a status bar with job
  progress. Home screen with a new-project form, saved projects and recent
  sessions.
- Monitor: exact frame at the playhead, draft playback (frames + music in
  sync, ~30 fps), previous/next cut, cut previews played in place;
  renders open in a player.
- Every edit is immediate (no "Apply" step): inspector fields, drag on the
  timeline, include/leave out from Media, options; long operations run
  as background jobs with progress (`/api/jobs/{id}`), edits are queued in
  order. Keyboard: Space play/pause, ←/→ (Shift = 5 s), `,` `.` cuts,
  Ctrl+S save, Ctrl+O projects, Del on the timeline.
- `core/studio_service.py`: the editor's logic as plain functions
  (options normalisation, music, plan edits, rebuilds, frames, renders,
  projects, music library) and the choice tables.
- The timeline (`ui/timeline.js`) is hosted with a small shim providing
  the component API it was written against.
- `/files` serves only from the runs folder and the music library.

## Unreleased — cut to the music (2026-10-12)

### Added
- `audio.analyze_rhythm()`: tempo, beats, meter (3/4 or 4/4) and bar lines,
  accents (strong hits with a 0..1 strength) and an energy curve. Busy
  accompaniments that make the tracker lock to double time are halved
  above 135 BPM. Cached per run (`render_work/rhythm.json`).
- `audio.align_plan_to_music()` and **Music → How the photos change with
  the music**: *On the bars* (cuts on the first beat of a bar), *On every
  beat*, *On the accents* (strong hits, also off-beat), *Follow the music*
  (accents, and shots get shorter when the music is loud and longer when
  it is quiet), *Light nudge* (the previous ≤0.6 s behaviour). Chapter
  changes prefer a bar line; video clips are never stretched past their
  source; a duration set by hand is kept, rounded to the nearest beat.
- Transitions last a whole number of half beats when cutting to the music.
- Music presets suggest a cut style by mood (bars for slow pieces, accents
  for upbeat, follow for energetic); `library.toml` accepts `sync = "…"`.
- Timeline A1 track: bar lines (full height), beats (ticks), accents
  (dots), tempo/meter and the active cut style; snapping uses bar lines in
  *On the bars* mode.

### Added (media bin)
- Media that are not in the film are marked in the media bin: a light grey
  veil (the photo stays readable), thin coloured bands and a small "not
  allowed" badge in the top-left corner of the visible (centre-cropped)
  area, colour by reason (red = removed by you, amber =
  duplicate, grey-blue = over the target length, dark grey = file
  missing); the caption starts with ⊘ and states the reason
  (`preview.excluded_thumb`, cached next to the thumbnail).

### Fixed
- Selecting a clip on the timeline was undone by the playhead update that
  follows the click, so the Del key had nothing to remove; the selection
  is now kept in the saved timeline view.
- Emptying the text of a shot that starts a folder/chapter did not remove
  the chapter card: an empty override meant "automatic", so the folder name
  came back. Such shots now get `hide_text` (no chapter card, no caption);
  typing the folder title again restores the automatic card. The inspector
  shows the automatic title in the text field and says when it is hidden.
- Double-clicking a chapter card on the timeline offered "Ponza · Settembre
  1990" for editing, so an edit duplicated the date line; it now offers the
  title only.
- Text holds (opening title 6 s, chapter cards 4.5 s, closing card 5.5 s)
  were applied after beat alignment and pushed every following cut off the
  beat; they are now computed first (`timeline.text_min_holds`).
- The 15-second quick preview ignored beat sync.

## Unreleased — editor UI, phase B: timeline + music presets (2026-10-12)

### Added
- A real timeline (`ui/timeline.js` + `ui/timeline.css`, hosted by a
  `gr.HTML` component with `js_on_load`, no build step): ruler with chapter
  band, V1 track with clips in proportion to their duration (thumbnails,
  video marker), transitions drawn on the joins (orange = auto, yellow =
  chosen, pink = face morph), T1 text track (title / chapter / caption /
  closing cards), A1 music track with waveform and beat ticks, fade in/out
  hatching, draggable playhead synced with the monitor. Interactions:
  click to select, drag a clip to reorder, drag its right edge for the
  duration (snap to beats), double-click a caption/chapter card to edit it,
  Del removes the selected shot from the cut, arrows/Home/End move the
  playhead, zoom slider + Fit. Replaces the phase-A filmstrip.
- Music presets (`core/music.py`, **Music → Music preset**): six built-in
  pieces synthesised locally on first use (Gentle piano, Warm strings,
  First dance, Sunny strum, Soft beat, Quiet air — one per mood), "Auto —
  match the look", and the user's own files from `assets/music/`
  (optional `library.toml` metadata). Picking a preset applies its
  suggested music volume and cut-on-beat.
- Online music search (`core/music_online.py`, **Music → Search online**,
  opt-in network feature): Openverse (CC aggregator, no key), Internet
  Archive (netlabels / public domain) and Jamendo (optional
  `JAMENDO_CLIENT_ID`, preview + download only where the artist allows it).
  Results show licence and credit, can be previewed, and "Use this track"
  saves the file to `assets/music/downloads` with a JSON sidecar; the
  track becomes a preset and its credit line goes on the closing card
  (`music_credit` option, checkbox to disable).
- Save / load projects (`core/project.py`, toolbar row "Project name ·
  Save project · Saved projects · Load · Open file…"): a `.ovsp.json`
  snapshot in `studio/projects/` holding the source folder and ordering,
  the reviewed plan with every edit, the render options and the music.
  Loading reuses the original run's caches when it still exists, restores
  every control, and disables shots whose media file has gone missing.
- Option changes that leave the options unchanged no longer rebuild the
  timeline (so restoring controls on load is free).
- `audio.load_mono()`: ffmpeg-based decoding so beat detection and the
  waveform work for m4a/mp3/ogg, not only wav; beats are cached per run.
- `preview.timeline_view()` / `bgm_analysis()`: compact timeline data and
  waveform peaks for the UI.

## Unreleased — editor UI, phase A (2026-10-12)

### Added
- Media Remix is laid out like an editor: media bin (every scanned file,
  grouped by folder, disabled/duplicate ones marked), a monitor that
  renders the exact frame at the playhead through the pro compositor
  (`core/pro/preview.py`, 960x540), an inspector for the selected shot
  (in/out of the cut, duration, camera motion, caption, transition in,
  move earlier/later) and a filmstrip of the cut in order showing each
  shot's duration, the transition leading into it and a text marker.
- "Preview this cut": renders ~1 s before/after the transition into the
  selected shot as a short clip.
- Per-shot camera motion override (`motion` in plan.json), honoured by
  `build_timeline`.
- Every option change (look, titles, transitions, music, framing) rebuilds
  the edit timeline so the monitor and filmstrip always match what the
  final render will do. The plan table remains available as "Table view".
- `pipeline.prepare_editor()`: thumbnails + edit timeline for a run.

## v0.4.1 — 2026-10-12

### Changed
- More variety inside each look: every style now has 7–12 transitions,
  weights are flattened, the same transition never appears twice in a row
  (and is avoided for two cuts), chapter changes rotate between several
  "strong" transitions.
- Picking a specific transition now makes it the style's *signature*
  (about half of the regular cuts) instead of using it for every cut;
  the new "Use only the favoured transition" checkbox restores the old
  behaviour.
- Plan table: the `transition` column is a picker — click a cell to choose
  from a dropdown (no free text).

### Added
- Transitions: Zoom out, Slide over, Iris close, Blinds, Soft wipe
  left/down.

## v0.4 — 2026-10-11 · Pro render engine (Media Remix)

### Added
- `core/pro/`: new frame-accurate compositor replacing the per-shot FFmpeg
  chains for Media Remix (`[pro] engine = "legacy"` in config.toml restores
  the V1 renderer). Timeline split into chunks rendered by parallel worker
  processes, each feeding its own NVENC encoder — a 4-minute 1080p film
  renders in about 1.5 minutes on an RTX 5080.
- 8 looks (Family Memory, Cinematic, Elegant Wedding, Travel Documentary,
  Vintage Film, Modern Dynamic, Classic B&W, Clean): colour grade (also
  applied to video clips via a generated 3D LUT), vignette, film grain,
  2.39:1 letterbox, flicker/dust/gate weave, curated transition palettes.
- Animated typography with bundled OFL fonts (Playfair Display, Cormorant
  Garamond, Montserrat, Inter, Bebas Neue, Great Vibes): opening title
  with kicker/subtitle/accent rule, automatic chapter cards from folder
  names and dates ("1990-09 - Ponza" → "Ponza · Settembre 1990"),
  per-photo captions, closing card. Animations: tracking-in, letters rise,
  blur-in, word pop, typewriter, wipe, slide, fade-up. Text moves out of
  the way of detected faces and gets a legibility scrim + soft shadow.
- 20 transitions: crossfade, dip to black/white, flash, blur dissolve,
  luma dissolve, push ×4, whip pan, soft/diagonal wipe, iris, zoom punch,
  spin, light leak, film burn, glitch, hard cut — plus **face morph**:
  478-point MediaPipe face mesh (`assets/face_landmarker.task`),
  thin-plate-spline warp, cameras automatically re-framed so the two faces
  line up; used automatically only between clear single-subject portraits.
- Smart photo framing: face-aware rule-of-thirds crop, or (portrait scans,
  square prints) the whole photo over a blurred fill with drop shadow or
  instant-photo border.
- Audio: clip sound laid out under transitions with fades, music ducking
  (sidechain) and -16 LUFS loudness normalisation; optional cut-on-beat.
- UI: style/title/transition/face-morph/music/export panels, 15-second
  540p style preview, render progress, per-shot `transition` column,
  720p / 1080p / 4K export.

## v0.3 — 2026-08-19

### Added
- `creative/identity.py`: canonical character/environment identity,
  generated once per project via a focused LLM call, formatted
  deterministically, and reused verbatim across every scene's keyframe
  prompt.
- Storyboard continuity fields: `previous_scene_id`,
  `continuity_from_previous`, `narrative_purpose`, `visual_change`,
  `camera_change`, `allow_generated_text`.
- `check_narrative_quality`: soft, non-raising warnings for duplicate
  narrative purpose, missing continuity, and invalid scene references.
- Anti-text negative-prompt suppression (`ANTI_TEXT_NEGATIVE_PROMPT`),
  applied unless a scene explicitly needs readable in-image text.
- Optional img2img reference-image path on the SDXL provider (available
  infrastructure, not yet wired into the default pipeline).
- Strict semantic validation on LLM JSON output at both the identity and
  storyboard boundaries (rejects parseable-but-wrong-shaped responses,
  e.g. a JSON string `"false"` where a real boolean is required).

### Fixed
- `creative/keyframes.py` was still reading storyboard fields
  (`visual_identity`, `character_continuity`, `environment_continuity`)
  removed by the identity refactor — keyframe prompts would have silently
  lost all identity text.
- A Python `bool("false") == True` coercion bug that could silently
  invert `allow_generated_text` and disable anti-text suppression.

### Changed
- `visual_identity` (a single free-text string) replaced by structured
  `character_identity`/`environment_identity` objects.

## v0.2

### Added
- Duration-accuracy fixes driven by actual narration word count, not
  fixed padding.
- LTX freeze/motion QC with a real regression test proving the fixed
  threshold catches what the old one missed.
- Storyboard schema validation.
- Per-scene checkpointing and resumable runs.
- Prompt-based visual continuity via a single shared `visual_identity`
  string (superseded by v0.3's structured identity).

### Fixed
- Narration truncation (clips trimmed shorter than their narration).
- Subtitle timing drift (cues keyed to the wrong duration source).
- Several ComfyUI VRAM-lifecycle bugs (`/free` failures silently
  swallowed, timed-out jobs not cancelled before retry).

## v0.1-alpha

### Added
- Initial prompt → script → storyboard → keyframes → clips → narration →
  subtitles → final video pipeline.
- Local generation via Ollama (script/storyboard) and ComfyUI (SDXL
  Lightning keyframes, LTX-Video clips).
- Edge TTS narration, FFmpeg/NVENC final assembly.
