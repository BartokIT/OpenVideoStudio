"""Pro render engine: frame-accurate Python compositor feeding NVENC.

Replaces the per-shot FFmpeg filter chains of the V1 renderer for Media
Remix. Every output frame is a pure function of its timeline time, which
lets the timeline be split into chunks rendered in parallel processes and
stitched back with a stream copy.

Modules:
- looks.py        style presets (grade, vignette, grain, fonts, transitions)
- typography.py   animated titles, chapter cards, captions, end card
- transitions.py  frame-level transitions (fade, push, iris, light leak, ...)
- facemorph.py    landmark-driven face morph (MediaPipe FaceLandmarker)
- sources.py      photo canvases (smart crop / blurred fill) + Ken Burns, video
- timeline.py     plan.json + options -> timeline.json
- engine.py       asset prep, parallel chunk rendering, audio, final mux
"""
