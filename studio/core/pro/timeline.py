"""plan.json + render options + prepared asset metadata -> timeline.

Timeline semantics: shot i occupies [start_i, end_i) where boundaries are
the cumulative plan durations, so the total length equals the planned
duration (and beat-aligned cut points stay on the beat). A transition of
length T is centred on each boundary; the shot's source therefore has to
be visible over [start - T_in/2, end + T_out/2] (vis_start / vis_end).
"""
from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Optional

from .looks import Look
from . import typography as ty
from .transitions import DURATION_FACTOR, TRANSITIONS

MONTHS = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}

# camera motions a user may force on a photo (plan shot "motion"); None/"" = auto from the look
MOTION_LABELS = {
    "zoom_in": "Zoom in", "zoom_out": "Zoom out", "zoom_in_fast": "Zoom in (fast)",
    "pan_left": "Pan left", "pan_right": "Pan right", "pan_up": "Pan up", "drift": "Drift",
}

DEFAULT_OPTIONS = {
    "look": "family_memory",
    "title": "",
    "subtitle": "",
    "closing_text": "",
    "transition_mode": "auto",      # auto | mixed | morph | <transition name> (signature, mixed with style)
    "transition_only": False,       # with a named transition: use it for every cut
    "transition_speed": 1.0,        # multiplier on transition length
    "facemorph": "auto",            # off | auto | always
    "chapter_titles": True,
    "captions": True,
    "title_anim": None,             # override look animation
    "font": None,                   # override look title font family
    "language": "it",
    "photo_fit": "auto",            # auto | crop | fit
    "seed": 7,
}


def merge_options(options: Optional[dict]) -> dict:
    out = dict(DEFAULT_OPTIONS)
    for k, v in (options or {}).items():
        if v is not None:
            out[k] = v
    return out


def _format_date(y: str, m: Optional[str], d: Optional[str], lang: str) -> str:
    months = MONTHS.get(lang, MONTHS["en"])
    if m and 1 <= int(m) <= 12:
        mon = months[int(m) - 1]
        if lang == "it":
            mon = mon.capitalize()
        if d and lang == "it":
            return f"{int(d)} {mon} {y}"
        if d:
            return f"{mon} {int(d)}, {y}"
        return f"{mon} {y}"
    return y


def chapter_label(raw: str, lang: str = "it") -> tuple[str, str]:
    """'Chapter 3 · 1990-09 - Ponza' -> ('Ponza', 'Settembre 1990')."""
    name = re.sub(r"^Chapter \d+ · ", "", raw or "").strip()
    if name == "(root)":
        return "", ""
    # pure ISO date chapters from date-sorted runs
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        return _format_date(*m.groups(), lang), ""
    name = re.sub(r"^\d{1,3}\s*[-_.)]\s*", "", name)  # "1-Matrimonio" -> "Matrimonio"
    m = re.match(r"^(\d{4})(?:[-_.](\d{1,2}))?(?:[-_.](\d{1,2}))?\s*(?:[-–_]\s*(.*))?$", name)
    if m:
        y, mo, d, rest = m.groups()
        date = _format_date(y, mo, d, lang)
        rest = (rest or "").strip()
        return (rest, date) if rest else (date, "")
    return name.replace("_", " ").strip(), ""


def _pick(pool: dict, rng: random.Random, avoid=None) -> str:
    """Weighted random pick. Weights are flattened (w**0.6) so the style's
    favourite still leads but doesn't drown the rest of the palette."""
    if isinstance(avoid, str):
        avoid = [avoid]
    avoid = set(avoid or [])
    items = [(k, w ** 0.6) for k, w in pool.items() if k in TRANSITIONS and k not in avoid and w > 0]
    if not items:
        items = [(k, w ** 0.6) for k, w in pool.items() if k in TRANSITIONS and w > 0] or [("fade", 1.0)]
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    for k, w in items:
        r -= w
        if r <= 0:
            return k
    return items[-1][0]


def _face_ok(meta: Optional[dict], width: int, min_frac: float, strict: bool = True) -> bool:
    """Morph only reads well when one face dominates the picture: on group
    shots every other person would ghost through the dissolve."""
    if not meta or not meta.get("landmarks") or not meta.get("faces"):
        return False
    faces = meta["faces"]
    face_h_out = faces[0]["h"] * width / meta["canvas_w"]
    if face_h_out < min_frac * width * 9 / 16:
        return False
    if strict and len(faces) > 1:
        a0 = faces[0]["w"] * faces[0]["h"]
        if faces[1]["w"] * faces[1]["h"] > 0.35 * a0:
            return False
    return True


def _bounds(cw: int, ch: int, z: float) -> tuple:
    hw, hh = cw / z / 2, ch / z / 2
    return hw, cw - hw, hh, ch - hh


def _clampc(v, lo, hi):
    return min(max(v, lo), hi) if lo <= hi else (lo + hi) / 2


def _camera(motion: str, meta: dict, zoom: float) -> dict:
    cw, ch = meta["canvas_w"], meta["canvas_h"]
    faces = meta.get("faces") or []
    if faces:
        f = faces[0]
        fx, fy = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
    else:
        fx, fy = cw / 2, ch / 2
    if meta.get("mode") == "fit" and motion.startswith("pan"):
        motion = "zoom_in"
    zoom = max(zoom, 1.02)
    lo_x, hi_x, lo_y, hi_y = _bounds(cw, ch, zoom)
    tx, ty_ = _clampc(fx, lo_x, hi_x), _clampc(fy, lo_y, hi_y)
    if motion == "zoom_out":
        return {"z0": zoom, "cx0": tx, "cy0": ty_, "z1": 1.0, "cx1": cw / 2, "cy1": ch / 2}
    if motion == "pan_right":
        return {"z0": zoom, "cx0": lo_x, "cy0": ty_, "z1": zoom, "cx1": hi_x, "cy1": ty_}
    if motion == "pan_left":
        return {"z0": zoom, "cx0": hi_x, "cy0": ty_, "z1": zoom, "cx1": lo_x, "cy1": ty_}
    if motion == "pan_up":
        return {"z0": zoom, "cx0": tx, "cy0": hi_y, "z1": zoom, "cx1": tx, "cy1": lo_y}
    if motion == "drift":
        z = 1 + (zoom - 1) * 0.6
        lo_x, hi_x, lo_y, hi_y = _bounds(cw, ch, z * 1.05)
        return {"z0": z, "cx0": lo_x + (hi_x - lo_x) * 0.3, "cy0": lo_y + (hi_y - lo_y) * 0.6,
                "z1": z * 1.05, "cx1": lo_x + (hi_x - lo_x) * 0.7, "cy1": lo_y + (hi_y - lo_y) * 0.4}
    if motion == "zoom_in_fast":
        z1 = zoom * 1.08
        lo_x, hi_x, lo_y, hi_y = _bounds(cw, ch, z1)
        return {"z0": 1.0, "cx0": cw / 2, "cy0": ch / 2, "z1": z1,
                "cx1": _clampc(fx, lo_x, hi_x), "cy1": _clampc(fy, lo_y, hi_y)}
    return {"z0": 1.0, "cx0": cw / 2, "cy0": ch / 2, "z1": zoom, "cx1": tx, "cy1": ty_}


def _align_for_morph(prev: dict, cur: dict, width: int, height: int) -> None:
    """Rewrites cur's starting camera so its face lands where prev's face is
    at the end of the transition: the morph then only has to reshape, not
    fly the face across the frame."""
    from .sources import camera_matrix
    import numpy as np

    pm, cm = prev["photo"], cur["photo"]
    lm_a = np.asarray(pm["landmarks"], np.float32)
    lm_b = np.asarray(cm["landmarks"], np.float32)
    from .facemorph import eye_distance, face_center

    def a_end_points():
        mat = camera_matrix(prev["camera"], 1.0, width, pm["canvas_w"], pm["canvas_h"], height)
        return lm_a @ mat[:, :2].T + mat[:, 2]

    pts_a = a_end_points()
    eye_a, eye_b = eye_distance(pts_a), eye_distance(lm_b)
    if eye_b < 1 or eye_a < 1:
        return
    z = eye_a / eye_b * cm["canvas_w"] / width
    fa = face_center(lm_a)
    ca_cam = prev["camera"]
    if z < 1.0:
        # B's face is bigger than B can be shrunk to: push A in on its face
        # at the end of its shot instead, so the two meet in the middle
        z_end = min(ca_cam["z1"] / z, 2.2)
        lo_x, hi_x, lo_y, hi_y = _bounds(pm["canvas_w"], pm["canvas_h"], z_end)
        ca_cam["z1"] = float(z_end)
        ca_cam["cx1"] = float(_clampc(fa[0], lo_x, hi_x))
        ca_cam["cy1"] = float(_clampc(fa[1], lo_y, hi_y))
        pts_a = a_end_points()
        eye_a = eye_distance(pts_a)
    s = eye_a / eye_b
    z = s * cm["canvas_w"] / width
    z = min(max(z, 1.0), 2.2)
    s = width * z / cm["canvas_w"]
    ca, cb = face_center(pts_a), face_center(lm_b)
    cx = cb[0] - (ca[0] - width / 2) / s
    cy = cb[1] - (ca[1] - height / 2) / s
    lo_x, hi_x, lo_y, hi_y = _bounds(cm["canvas_w"], cm["canvas_h"], z)
    cam = cur["camera"]
    cam["z0"], cam["cx0"], cam["cy0"] = z, _clampc(cx, lo_x, hi_x), _clampc(cy, lo_y, hi_y)
    # settle gently instead of continuing a big zoom
    if cam["z1"] < z * 0.8:
        cam["z1"] = max(z * 0.85, 1.0)
        lo_x, hi_x, lo_y, hi_y = _bounds(cm["canvas_w"], cm["canvas_h"], cam["z1"])
        cam["cx1"] = _clampc(cb[0], lo_x, hi_x)
        cam["cy1"] = _clampc(cb[1], lo_y, hi_y)
    for k in list(cam):
        cam[k] = float(cam[k])

    # second pass: B may have hit the canvas edge, so steer A's final framing
    # to put its face exactly where B's face actually starts
    mb = camera_matrix(cam, 0.0, width, cm["canvas_w"], cm["canvas_h"], height)
    pb = face_center(lm_b @ mb[:, :2].T + mb[:, 2])
    s_a = width * ca_cam["z1"] / pm["canvas_w"]
    lo_x, hi_x, lo_y, hi_y = _bounds(pm["canvas_w"], pm["canvas_h"], ca_cam["z1"])
    ca_cam["cx1"] = float(_clampc(fa[0] - (pb[0] - width / 2) / s_a, lo_x, hi_x))
    ca_cam["cy1"] = float(_clampc(fa[1] - (pb[1] - height / 2) / s_a, lo_y, hi_y))
    for k in list(ca_cam):
        ca_cam[k] = float(ca_cam[k])


def _morph_compatible(prev: dict, cur: dict, width: int, height: int) -> bool:
    import numpy as np
    from .sources import camera_matrix
    from .facemorph import eye_distance, face_center

    pm, cm = prev["photo"], cur["photo"]
    ma = camera_matrix(prev["camera"], 1.0, width, pm["canvas_w"], pm["canvas_h"], height)
    mb = camera_matrix(cur["camera"], 0.0, width, cm["canvas_w"], cm["canvas_h"], height)
    pa = np.asarray(pm["landmarks"], np.float32) @ ma[:, :2].T + ma[:, 2]
    pb = np.asarray(cm["landmarks"], np.float32) @ mb[:, :2].T + mb[:, 2]
    ea, eb = eye_distance(pa), eye_distance(pb)
    if min(ea, eb) < width * 0.012:
        return False
    ratio = ea / eb
    dist = float(np.linalg.norm(face_center(pa) - face_center(pb)))
    return 0.66 <= ratio <= 1.5 and dist <= 0.12 * width


TITLE_HOLD, CLOSING_HOLD, CHAPTER_HOLD = 6.0, 5.5, 4.5


def text_min_holds(plan: dict, options: Optional[dict]) -> dict:
    """shot_id -> minimum seconds for shots that carry the opening title,
    the closing card or a chapter card. Shared by build_timeline and the
    music alignment, so cutting to the music already leaves room for text
    and no shot has to be lengthened afterwards (which would push every
    following cut off the beat)."""
    opts = merge_options(options)
    shots = [s for s in plan.get("shots", []) if s.get("enabled")]
    if not shots:
        return {}
    out: dict = {}

    def hold(sid, v):
        out[sid] = max(out.get(sid, 0.0), v)

    if opts.get("title"):
        hold(shots[0]["shot_id"], TITLE_HOLD)
    if opts.get("closing_text") or opts.get("music_credit"):
        hold(shots[-1]["shot_id"], CLOSING_HOLD)
    if opts.get("chapter_titles"):
        prev = None
        for i, s in enumerate(shots):
            if s.get("chapter_id") != prev and not (i == 0 and opts.get("title")) and not s.get("hide_text"):
                hold(s["shot_id"], CHAPTER_HOLD)
            prev = s.get("chapter_id")
    return out


def auto_chapter_text(plan: dict, shot_id: str, options: Optional[dict]) -> str:
    """The chapter title build_timeline would put on this shot from the
    folder name / date ("" when the shot doesn't start a chapter in the cut,
    chapter titles are off, or the opening/closing card takes the shot)."""
    opts = merge_options(options)
    if not opts.get("chapter_titles"):
        return ""
    shots = [s for s in sorted(plan.get("shots", []), key=lambda s: s.get("order", 0)) if s.get("enabled")]
    chapters = {c["chapter_id"]: c.get("title", "") for c in plan.get("chapters", [])}
    prev = object()
    for i, s in enumerate(shots):
        start = s.get("chapter_id") != prev
        prev = s.get("chapter_id")
        if s["shot_id"] != shot_id:
            continue
        if not start or (i == 0 and opts.get("title")):
            return ""
        if i == len(shots) - 1 and (opts.get("closing_text") or opts.get("music_credit")):
            return ""
        return chapter_label(chapters.get(s.get("chapter_id"), ""), opts.get("language", "it"))[0]
    return ""


def build_timeline(plan: dict, prepared: dict, options: dict, look: Look, width: int, height: int,
                   fps: int) -> dict:
    opts = merge_options(options)
    lang = opts["language"]
    rng = random.Random(int(opts.get("seed", 7)))
    shots_in = [s for s in plan["shots"] if s.get("enabled")]
    chapters = {c["chapter_id"]: c for c in plan.get("chapters", [])}

    shots = []
    for s in shots_in:
        meta = prepared.get(s["shot_id"])
        if meta is None:
            continue
        shots.append({
            "shot_id": s["shot_id"], "type": s["type"], "asset_path": s["asset_path"],
            "duration": float(s["duration"]), "chapter_id": s.get("chapter_id"),
            "title_text": (s.get("title_text") or "").strip(), "transition": (s.get("transition") or "").strip(),
            "motion_override": (s.get("motion") or "").strip(),
            "hide_text": bool(s.get("hide_text")),
            **({"photo": meta} if s["type"] == "image" else {"video": meta}),
        })
    if not shots:
        raise ValueError("no renderable shots")

    if opts.get("music_credit") and not opts["closing_text"]:
        opts["closing_text"] = opts["music_credit"]
        opts["music_credit"] = ""

    # minimum holds for shots carrying text (no-ops when the plan was cut to
    # the music, which already honoured them)
    holds = text_min_holds({"shots": [{**s, "enabled": True} for s in shots]}, opts)
    for s in shots:
        if s["shot_id"] in holds:
            s["duration"] = max(s["duration"], holds[s["shot_id"]])
    for s in shots:
        if s["type"] == "video":
            s["duration"] = max(min(s["duration"], s["video"].get("duration") or s["duration"]), 1.0)

    # cameras
    motions = list(look.motions)
    for i, s in enumerate(shots):
        if s["type"] == "image":
            m = motions[(i + rng.randrange(len(motions)) if i % 3 == 2 else i) % len(motions)]
            if s["motion_override"] in MOTION_LABELS:
                m = s["motion_override"]
            s["camera"] = _camera(m, s["photo"], look.zoom)
            s["motion"] = m

    # transitions
    base = look.transition_seconds * float(opts["transition_speed"])
    music_beat = float((plan.get("music") or {}).get("beat") or 0.0)
    mode = opts["transition_mode"]
    fm = opts["facemorph"]
    only = bool(opts.get("transition_only"))
    transitions = []
    recent: list = []
    last_chapter = None
    for i in range(len(shots) - 1):
        a, b = shots[i], shots[i + 1]
        both_photo = a["type"] == "image" and b["type"] == "image"
        loose = fm == "always" or mode == "morph" or b["transition"] == "morph"
        morph_ok = both_photo and fm != "off" \
            and _face_ok(a.get("photo"), width, 0.0 if loose else 0.14, strict=not loose) \
            and _face_ok(b.get("photo"), width, 0.0 if loose else 0.14, strict=not loose)
        chapter_cut = a["chapter_id"] != b["chapter_id"]
        override = b["transition"]
        avoid = recent[-2:]
        if override and (override in TRANSITIONS or override == "morph"):
            name = override if (override != "morph" or morph_ok) else _pick(look.transitions, rng, avoid)
        elif mode == "morph":
            name = "morph" if morph_ok else _pick(look.transitions, rng, avoid)
        elif mode in TRANSITIONS and only:
            name = mode
        elif morph_ok and fm in ("auto", "always"):
            name = "morph"
        elif chapter_cut and mode != "mixed":
            # chapter changes get a "strong" transition, rotated so they
            # don't all look the same
            cpool = {look.chapter_transition: 2.0, **{k: 1.0 for k in look.chapter_pool}}
            if mode in TRANSITIONS:
                cpool[mode] = 2.0
            name = _pick(cpool, rng, [last_chapter] + recent[-1:])
            last_chapter = name
        elif mode in TRANSITIONS:
            # signature transition: the chosen one leads (~45%), the style's
            # own palette fills the rest for variety
            name = mode if (recent[-1:] != [mode] and rng.random() < 0.45) else _pick(look.transitions, rng, avoid + [mode])
        elif mode == "mixed":
            pool = {k: 1.0 for k in TRANSITIONS if k != "cut"}
            name = _pick(pool, rng, avoid)
        else:
            name = _pick(look.transitions, rng, avoid)
        dur = base * DURATION_FACTOR.get(name, 1.0)
        if name != "cut" and music_beat:
            # cut to the music: transitions last a whole number of half beats,
            # so they open and close on the rhythm, centred on the beat
            half = music_beat / 2
            dur = max(half, round(dur / half) * half)
        if name != "cut":
            dur = min(max(dur, 0.25), 0.45 * min(a["duration"], b["duration"]))
        transitions.append({"a": i, "b": i + 1, "type": name, "duration": round(dur, 3),
                            "seed": rng.randrange(1 << 30)})
        recent.append(name)

    # timing
    t = 0.0
    for i, s in enumerate(shots):
        s["start"] = round(t, 4)
        t += s["duration"]
        s["end"] = round(t, 4)
        t_in = transitions[i - 1]["duration"] if i > 0 else 0.0
        t_out = transitions[i]["duration"] if i < len(transitions) else 0.0
        s["t_in"], s["t_out"] = t_in, t_out
        s["vis_start"] = round(s["start"] - t_in / 2, 4)
        s["vis_end"] = round(s["end"] + t_out / 2, 4)
    total = shots[-1]["end"]
    for tr in transitions:
        c = shots[tr["a"]]["end"]
        tr["start"] = round(c - tr["duration"] / 2, 4)
        tr["end"] = round(c + tr["duration"] / 2, 4)

    # face-aligned morph cameras (after timing: camera progress depends on vis span)
    for tr in transitions:
        if tr["type"] == "morph":
            a, b = shots[tr["a"]], shots[tr["b"]]
            saved_a, saved = dict(a["camera"]), dict(b["camera"])
            _align_for_morph(a, b, width, height)
            forced = fm == "always" or mode == "morph" or b["transition"] == "morph"
            if not forced and not _morph_compatible(a, b, width, height):
                # faces can't be brought close enough: a morph would bend the
                # whole picture, so fall back to the look's own transition
                a["camera"], b["camera"] = saved_a, saved
                k = transitions.index(tr)
                neighbours = [t["type"] for t in transitions[max(k - 2, 0):k + 2] if t is not tr]
                tr["type"] = look.chapter_transition if a["chapter_id"] != b["chapter_id"] \
                    else _pick(look.transitions, rng, neighbours)
                tr["morph_rejected"] = True

    # text
    overlays = []
    anim = opts.get("title_anim") or None
    font = opts.get("font") or None

    def window(s, lead=0.25, tail=0.2, max_len=None):
        a = s["start"] + s["t_in"] / 2 + lead
        b = s["end"] - s["t_out"] / 2 - tail
        if max_len:
            b = min(b, a + max_len)
        return a, b

    if opts["title"]:
        a, b = window(shots[0], lead=0.5 if look.fade_in < 1.2 else look.fade_in * 0.6)
        kicker = opts.get("kicker") or ""
        overlays.append({"shot": 0, **ty.serialisable(ty.title_card(look, opts["title"], opts["subtitle"], kicker, a, b, anim, font))})

    prev_ch = shots[0]["chapter_id"]
    for i, s in enumerate(shots):
        is_chapter_start = i == 0 or s["chapter_id"] != prev_ch
        prev_ch = s["chapter_id"]
        if (i == 0 and opts["title"]) or (i == len(shots) - 1 and opts["closing_text"]):
            continue
        if s["hide_text"]:
            # the user emptied the text of this shot: no chapter card, no caption
            continue
        if is_chapter_start and opts["chapter_titles"]:
            raw = chapters.get(s["chapter_id"], {}).get("title", "")
            name, sub = chapter_label(raw, lang)
            if s["title_text"]:
                name, sub = s["title_text"], sub
            if name:
                a, b = window(s, max_len=4.2)
                if b - a > 1.5:
                    overlays.append({"shot": i, **ty.serialisable(ty.chapter_card(look, name, sub, a, b, anim, font))})
                continue
        if s["title_text"] and opts["captions"]:
            a, b = window(s, lead=0.35, max_len=5.0)
            if b - a > 1.2:
                overlays.append({"shot": i, **ty.serialisable(ty.caption_card(look, s["title_text"], a, b, width, height, None, font))})

    if opts["closing_text"]:
        s = shots[-1]
        a = s["start"] + s["t_in"] / 2 + 0.6
        b = total - 0.15
        # a licence credit for the music goes under the closing text (or
        # becomes the closing card itself when there is no closing text)
        sub = opts.get("closing_sub") or opts.get("music_credit") or ""
        overlays.append({"shot": len(shots) - 1,
                         **ty.serialisable(ty.end_card(look, opts["closing_text"], sub, a, b, anim, font))})

    return {
        "created_at": datetime.now().isoformat(),
        "width": width, "height": height, "fps": fps, "look": look.key,
        "total": round(total, 4), "frames": int(round(total * fps)),
        "shots": shots, "transitions": transitions, "overlays": overlays,
        "fade_in": look.fade_in, "fade_out": look.fade_out, "options": opts,
        "music": plan.get("music"),
    }
