"""Frame-level transitions. Each takes the outgoing frame A, incoming frame
B (uint8 RGB, same size), progress p in [0,1] and a context dict, and
returns the composited frame. All are deterministic (seeded by ctx["seed"])
so parallel render chunks agree frame-for-frame."""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from .typography import ease_in_out, ease_out_cubic


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _mix(a: np.ndarray, b: np.ndarray, w: float) -> np.ndarray:
    w = _clamp(w)
    if w <= 0:
        return a
    if w >= 1:
        return b
    return cv2.addWeighted(a, 1 - w, b, w, 0)


def _mix_mask(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Per-pixel mix with float mask m (h, w) in [0,1] (1 = B)."""
    m3 = m[..., None]
    return (a.astype(np.float32) * (1 - m3) + b.astype(np.float32) * m3).astype(np.uint8)


def _scale_about_center(img: np.ndarray, s: float, angle: float = 0.0, dx: float = 0, dy: float = 0) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, s)
    m[0, 2] += dx
    m[1, 2] += dy
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _fast_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma < 0.5:
        return img
    h, w = img.shape[:2]
    f = 4 if sigma > 6 else 2
    small = cv2.resize(img, (w // f, h // f), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma / f)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


# --------------------------------------------------------------- basics

def fade(a, b, p, ctx):
    return _mix(a, b, ease_in_out(p))


def fade_black(a, b, p, ctx):
    if p < 0.5:
        return cv2.convertScaleAbs(a, alpha=1 - ease_in_out(p * 2))
    return cv2.convertScaleAbs(b, alpha=ease_in_out(p * 2 - 1))


def fade_white(a, b, p, ctx):
    white = np.full_like(a, 255)
    if p < 0.5:
        return _mix(a, white, ease_in_out(p * 2) * 0.95)
    return _mix(white, b, 0.05 + 0.95 * ease_in_out(p * 2 - 1))


def flash(a, b, p, ctx):
    base = _mix(a, b, _clamp((p - 0.4) / 0.2))
    peak = np.exp(-((p - 0.5) / 0.13) ** 2)
    return cv2.addWeighted(base, 1.0, np.full_like(a, 255), float(peak) * 0.9, 0)


def blur_dissolve(a, b, p, ctx):
    e = ease_in_out(p)
    sigma = np.sin(np.pi * p) * 18 * a.shape[0] / 1080
    return _mix(_fast_blur(a, sigma), _fast_blur(b, sigma), e)


def luma_dissolve(a, b, p, ctx):
    h, w = b.shape[:2]
    lum = ctx.get("_luma")
    if lum is None:
        g = cv2.cvtColor(cv2.resize(b, (w // 4, h // 4), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
        g = cv2.GaussianBlur(g, (0, 0), 6).astype(np.float32) / 255.0
        lum = cv2.resize(g, (w, h), interpolation=cv2.INTER_LINEAR)
        ctx["_luma"] = lum
    e = ease_in_out(p)
    soft = 0.25
    m = np.clip((e * (1 + soft) - (1 - lum)) / soft, 0, 1)
    return _mix_mask(a, b, m)


# ---------------------------------------------------------------- motion

def _push(a, b, p, dx_dir, dy_dir, blur=False):
    h, w = a.shape[:2]
    e = ease_in_out(p) if not blur else _whip_ease(p)
    ox, oy = -dx_dir * e * w, -dy_dir * e * h
    out = np.empty_like(a)
    ma = np.float32([[1, 0, ox], [0, 1, oy]])
    mb = np.float32([[1, 0, ox + dx_dir * w], [0, 1, oy + dy_dir * h]])
    fa = cv2.warpAffine(a, ma, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    fb = cv2.warpAffine(b, mb, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    # the two frames tile the screen exactly; add them (borders are black)
    cv2.add(fa, fb, dst=out)
    if blur:
        speed = np.sin(np.pi * p) ** 2
        k = int(speed * w * 0.12) | 1
        if k > 1:
            out = cv2.blur(out, (k, 1) if dx_dir else (1, k))
    return out


def _whip_ease(p):
    # slow-fast-slow with most travel concentrated in the middle
    return _clamp(0.5 + 0.5 * np.tanh((p - 0.5) * 7) / np.tanh(3.5))


def slide_left(a, b, p, ctx):
    return _push(a, b, p, 1, 0)


def slide_right(a, b, p, ctx):
    return _push(a, b, p, -1, 0)


def slide_up(a, b, p, ctx):
    return _push(a, b, p, 0, 1)


def slide_down(a, b, p, ctx):
    return _push(a, b, p, 0, -1)


def whip_pan(a, b, p, ctx):
    return _push(a, b, p, 1 if ctx.get("seed", 0) % 2 == 0 else -1, 0, blur=True)


def _wipe(a, b, p, axis: int, reverse: bool):
    h, w = a.shape[:2]
    e = ease_in_out(p)
    n = w if axis == 1 else h
    edge = n * 0.12
    xs = np.arange(n, dtype=np.float32)
    if reverse:
        xs = xs[::-1]
    m = np.clip((e * (n + edge) - xs) / edge, 0, 1)
    m = np.broadcast_to(m[None, :], (h, w)) if axis == 1 else np.broadcast_to(m[:, None], (h, w))
    return _mix_mask(a, b, m)


def wipe_right(a, b, p, ctx):
    return _wipe(a, b, p, 1, False)


def wipe_left(a, b, p, ctx):
    return _wipe(a, b, p, 1, True)


def wipe_down(a, b, p, ctx):
    return _wipe(a, b, p, 0, False)


def blinds(a, b, p, ctx):
    """Venetian blinds: horizontal slats open one after another."""
    h, w = a.shape[:2]
    slats = 8
    sh = h / slats
    ys = np.arange(h, dtype=np.float32)
    idx = np.floor(ys / sh)
    local = np.abs((ys - idx * sh) / sh - 0.5) * 2  # 0 at slat centre, 1 at its edges
    delay = idx / slats * 0.25
    e = np.clip((p - delay) / 0.75, 0, 1)
    e = e * e * (3 - 2 * e)
    soft = 0.25
    m = np.clip((e * (1 + soft) - local) / soft, 0, 1)
    return _mix_mask(a, b, np.broadcast_to(m[:, None], (h, w)))


def cover_left(a, b, p, ctx):
    """B slides in over A, which recedes and darkens slightly."""
    h, w = a.shape[:2]
    e = ease_in_out(p)
    under = _scale_about_center(a, 1 - 0.06 * e)
    under = cv2.convertScaleAbs(under, alpha=1 - 0.45 * e)
    ox = (1 - e) * w
    mb = np.float32([[1, 0, ox], [0, 1, 0]])
    fb = cv2.warpAffine(b, mb, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    x0 = int(np.ceil(ox))
    out = under.copy()
    out[:, x0:] = fb[:, x0:]
    # soft shadow on the leading edge
    if 0 < x0 < w:
        sw = max(int(w * 0.03), 2)
        s0 = max(x0 - sw, 0)
        ramp = np.linspace(1.0, 0.55, x0 - s0, dtype=np.float32)[None, :, None]
        out[:, s0:x0] = (out[:, s0:x0].astype(np.float32) * ramp).astype(np.uint8)
    return out


def wipe_diagonal(a, b, p, ctx):
    h, w = a.shape[:2]
    e = ease_in_out(p)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = (xx / w + yy / h) / 2
    edge = 0.1
    m = np.clip((e * (1 + edge) - d) / edge, 0, 1)
    return _mix_mask(a, b, m)


def circle_open(a, b, p, ctx):
    h, w = a.shape[:2]
    e = ease_in_out(p)
    cx, cy = ctx.get("focus_b", (w / 2, h / 2))
    r_max = np.hypot(max(cx, w - cx), max(cy, h - cy))
    r = e * r_max * 1.05
    edge = 0.08 * h
    m = _radial(w, h, cx, cy)
    m = np.clip((r - m) / edge, 0, 1)
    return _mix_mask(a, b, m)


def circle_close(a, b, p, ctx):
    """Reverse iris: B closes in from the edges toward the centre."""
    h, w = a.shape[:2]
    e = ease_in_out(p)
    cx, cy = w / 2, h / 2
    r_max = np.hypot(cx, cy) * 1.05
    r = (1 - e) * r_max
    edge = 0.08 * h
    m = np.clip((_radial(w, h, cx, cy) - r) / edge, 0, 1)
    return _mix_mask(a, b, m)


@lru_cache(maxsize=8)
def _radial_cached(w, h, cx, cy):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)


def _radial(w, h, cx, cy):
    return _radial_cached(w, h, int(cx), int(cy))


def zoom_in(a, b, p, ctx):
    """Zoom punch: A rushes toward camera with radial blur, B lands from a
    slight over-zoom."""
    e = ease_in_out(p)
    if p < 0.5:
        q = p * 2
        s = 1 + 0.9 * q * q
        frames = [_scale_about_center(a, s * (1 + 0.04 * i * q)) for i in range(3)]
        out = frames[0]
        for f in frames[1:]:
            out = cv2.addWeighted(out, 0.6, f, 0.4, 0)
    else:
        q = (p - 0.5) * 2
        s = 1.6 - 0.6 * ease_out_cubic(q)
        frames = [_scale_about_center(b, s * (1 + 0.04 * i * (1 - q))) for i in range(3)]
        out = frames[0]
        for f in frames[1:]:
            out = cv2.addWeighted(out, 0.6, f, 0.4, 0)
    # brief brightness bloom across the cut hides the switch
    bloom = np.exp(-((p - 0.5) / 0.12) ** 2) * 0.35
    return cv2.convertScaleAbs(out, alpha=1 + bloom, beta=0) if e else out


def zoom_out(a, b, p, ctx):
    """A pulls away into the distance while B settles in from a slight zoom."""
    h, w = a.shape[:2]
    e = ease_in_out(p)
    fb = _scale_about_center(b, 1.25 - 0.25 * ease_out_cubic(p))
    fb = _fast_blur(fb, (1 - e) * 4 * h / 1080)
    s = 1 - 0.45 * e
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
    fa = cv2.warpAffine(a, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    mask = cv2.warpAffine(np.ones((h, w), np.float32), m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT)
    q = mask * (1 - ease_in_out((p - 0.2) / 0.7))
    return _mix_mask(fb, fa, q)


def spin(a, b, p, ctx):
    d = 1 if ctx.get("seed", 0) % 2 == 0 else -1
    if p < 0.5:
        q = ease_in_out(p * 2)
        out = _scale_about_center(a, 1 + 0.5 * q, angle=d * 70 * q)
    else:
        q = ease_out_cubic((p - 0.5) * 2)
        out = _scale_about_center(b, 1.5 - 0.5 * q, angle=-d * 70 * (1 - q))
    speed = np.sin(np.pi * p)
    return _fast_blur(out, speed * 6 * a.shape[0] / 1080)


# ---------------------------------------------------------------- light

@lru_cache(maxsize=16)
def _leak_pattern(w: int, h: int, seed: int, burn: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sw, sh = w // 8, h // 8
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    acc = np.zeros((sh, sw, 3), np.float32)
    palette = [(1.0, 0.55, 0.15), (1.0, 0.35, 0.25), (1.0, 0.8, 0.45), (0.95, 0.45, 0.6)]
    if burn:
        palette = [(1.0, 0.45, 0.05), (1.0, 0.75, 0.3), (1.0, 0.95, 0.8)]
    for _ in range(5 if not burn else 7):
        cx = rng.uniform(-0.2, 1.2) * sw
        cy = rng.uniform(-0.2, 1.2) * sh
        r = rng.uniform(0.25, 0.7) * sw
        col = np.array(palette[rng.integers(len(palette))], np.float32)
        g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))
        acc += g[..., None] * col * rng.uniform(0.5, 1.0)
    acc = cv2.GaussianBlur(acc, (0, 0), sw * 0.03)
    return acc / max(acc.max(), 1e-3)


def _screen(base: np.ndarray, light: np.ndarray, strength: float) -> np.ndarray:
    b = base.astype(np.float32) / 255.0
    l = np.clip(light * strength, 0, 1)
    return ((1 - (1 - b) * (1 - l)) * 255).astype(np.uint8)


def _leak(a, b, p, ctx, burn: bool):
    h, w = a.shape[:2]
    seed = int(ctx.get("seed", 0))
    pat = _leak_pattern(w, h, seed, burn)
    # the leak drifts across the frame while it blooms
    shift = int((p - 0.5) * pat.shape[1] * 0.4)
    pat = np.roll(pat, shift, axis=1)
    light = cv2.resize(pat, (w, h), interpolation=cv2.INTER_LINEAR)
    base = _mix(a, b, ease_in_out((p - 0.25) / 0.5))
    strength = np.sin(np.pi * p) ** 1.5 * (0.8 if burn else 0.7)
    out = _screen(base, light, strength)
    if burn and 0.4 < p < 0.6:
        out = cv2.addWeighted(out, 1.0, np.full_like(out, 255), float(np.exp(-((p - 0.5) / 0.05) ** 2)) * 0.3, 0)
    return out


def light_leak(a, b, p, ctx):
    return _leak(a, b, p, ctx, burn=False)


def film_burn(a, b, p, ctx):
    return _leak(a, b, p, ctx, burn=True)


# ---------------------------------------------------------------- glitch

def glitch(a, b, p, ctx):
    h, w = a.shape[:2]
    rng = np.random.default_rng(int(ctx.get("seed", 0)) * 1000 + int(p * 1000))
    src = a if p < 0.5 else b
    if 0.35 < p < 0.65 and rng.random() < 0.5:
        src = b if src is a else a
    intensity = np.sin(np.pi * p)
    out = src.copy()
    # RGB split
    shift = int(intensity * w * 0.012) + 1
    out[..., 0] = np.roll(src[..., 0], shift, axis=1)
    out[..., 2] = np.roll(src[..., 2], -shift, axis=1)
    # horizontal slice displacement
    for _ in range(int(intensity * 14)):
        y0 = int(rng.uniform(0, h))
        bh = int(rng.uniform(0.01, 0.07) * h)
        dx = int(rng.normal(0, 0.06) * w * intensity)
        out[y0:y0 + bh] = np.roll(out[y0:y0 + bh], dx, axis=1)
    # scanlines
    if intensity > 0.5:
        out[::3] = (out[::3].astype(np.uint16) * 7 // 10).astype(np.uint8)
    return out


def cut(a, b, p, ctx):
    return a if p < 0.5 else b


TRANSITIONS = {
    "fade": fade, "fade_black": fade_black, "fade_white": fade_white, "flash": flash,
    "blur_dissolve": blur_dissolve, "luma_dissolve": luma_dissolve,
    "slide_left": slide_left, "slide_right": slide_right, "slide_up": slide_up, "slide_down": slide_down,
    "whip_pan": whip_pan, "wipe_right": wipe_right, "wipe_left": wipe_left, "wipe_down": wipe_down,
    "wipe_diagonal": wipe_diagonal, "blinds": blinds, "cover_left": cover_left,
    "circle_open": circle_open, "circle_close": circle_close, "zoom_in": zoom_in, "zoom_out": zoom_out,
    "spin": spin,
    "light_leak": light_leak, "film_burn": film_burn, "glitch": glitch, "cut": cut,
}

# relative length vs the look's base transition duration
DURATION_FACTOR = {
    "morph": 1.6, "whip_pan": 0.6, "glitch": 0.5, "flash": 0.7, "zoom_in": 0.75, "spin": 0.8,
    "light_leak": 1.3, "film_burn": 1.3, "fade_black": 1.3, "fade_white": 1.2, "cut": 0.0,
    "slide_left": 0.8, "slide_right": 0.8, "slide_up": 0.8, "slide_down": 0.8,
    "zoom_out": 0.9, "cover_left": 0.85, "blinds": 1.1,
}

LABELS = {
    "morph": "Face morph", "fade": "Crossfade", "fade_black": "Dip to black", "fade_white": "Dip to white",
    "flash": "Flash", "blur_dissolve": "Blur dissolve", "luma_dissolve": "Luma dissolve",
    "slide_left": "Push left", "slide_right": "Push right", "slide_up": "Push up", "slide_down": "Push down",
    "whip_pan": "Whip pan", "wipe_right": "Soft wipe right", "wipe_left": "Soft wipe left",
    "wipe_down": "Soft wipe down", "wipe_diagonal": "Diagonal wipe", "blinds": "Blinds",
    "cover_left": "Slide over", "circle_open": "Iris open", "circle_close": "Iris close",
    "zoom_in": "Zoom punch", "zoom_out": "Zoom out", "spin": "Spin", "light_leak": "Light leak",
    "film_burn": "Film burn", "glitch": "Glitch", "cut": "Hard cut",
}


def apply(name: str, a: np.ndarray, b: np.ndarray, p: float, ctx: dict) -> np.ndarray:
    if name == "morph":
        from . import facemorph
        if ctx.get("pts_a") is not None and ctx.get("pts_b") is not None:
            return facemorph.morph(a, b, ctx["pts_a"], ctx["pts_b"], p, ctx)
        return fade(a, b, p, ctx)
    return TRANSITIONS.get(name, fade)(a, b, _clamp(p), ctx)
