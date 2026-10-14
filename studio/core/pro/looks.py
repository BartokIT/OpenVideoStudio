"""Style presets ("looks") and the per-frame finishing effects they use.

A look bundles everything that makes a paid slideshow service feel
designed rather than assembled: a colour grade, vignette/grain/letterbox
finishing, Ken Burns intensity, a curated transition palette and a
typography system (fonts, colours, title layout and animation).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class FontSpec:
    family: str            # key in typography.FONT_FAMILIES
    weight: str = "Regular"
    size: float = 64.0     # px at 1080p, scaled with output height
    tracking: float = 0.0  # extra letter spacing, in em
    upper: bool = False
    italic: bool = False


@dataclass(frozen=True)
class Grade:
    exposure: float = 0.0      # stops
    contrast: float = 0.0      # -1..1, S-curve strength
    saturation: float = 1.0
    temperature: float = 0.0   # -1 (cool) .. 1 (warm)
    tint: float = 0.0          # -1 (green) .. 1 (magenta)
    lift: float = 0.0          # 0..0.2, raises blacks (faded film)
    shadows: tuple = (0.0, 0.0, 0.0)     # additive RGB tint in shadows
    highlights: tuple = (0.0, 0.0, 0.0)  # additive RGB tint in highlights
    sepia: float = 0.0         # 0..1 blend toward sepia monochrome
    mono: float = 0.0          # 0..1 blend toward black & white


@dataclass(frozen=True)
class Look:
    key: str
    label: str
    description: str
    grade: Grade = Grade()
    vignette: float = 0.25
    grain: float = 0.0
    letterbox: float = 0.0          # target aspect of the visible area, 0 = off
    flicker: float = 0.0
    dust: float = 0.0
    gate_weave: float = 0.0
    photo_frame: str = "none"       # "none" | "shadow" | "polaroid" for fit-mode photos
    zoom: float = 1.14              # Ken Burns max zoom
    motions: tuple = ("zoom_in", "pan_right", "zoom_out", "pan_left")
    transitions: dict = field(default_factory=lambda: {"fade": 1.0})
    transition_seconds: float = 1.0
    chapter_transition: str = "fade_black"
    # extra "strong" transitions rotated with chapter_transition at chapter
    # boundaries, so chapter changes don't all look identical
    chapter_pool: tuple = ()
    # typography
    title_font: FontSpec = FontSpec("playfair", "Regular", 104)
    subtitle_font: FontSpec = FontSpec("montserrat", "Light", 30, 0.35, True)
    chapter_font: FontSpec = FontSpec("playfair", "Regular", 78)
    chapter_sub_font: FontSpec = FontSpec("montserrat", "Medium", 24, 0.4, True)
    caption_font: FontSpec = FontSpec("montserrat", "Medium", 40)
    accent_font: Optional[FontSpec] = None   # script font used above titles
    text_color: tuple = (255, 255, 255)
    accent_color: tuple = (230, 196, 140)
    title_layout: str = "center"       # center | lower_left | split
    chapter_layout: str = "center"     # center | lower_left
    caption_layout: str = "lower_third"  # lower_third | bottom | plate
    title_anim: str = "tracking_in"
    chapter_anim: str = "fade_up"
    caption_anim: str = "fade_up"
    decoration: str = "line"           # line | bar | plate | none
    text_shadow: float = 0.55
    fade_in: float = 1.0
    fade_out: float = 2.0


LOOKS: dict[str, Look] = {}


def _register(look: Look) -> Look:
    LOOKS[look.key] = look
    return look


_register(Look(
    key="family_memory", label="Family Memory",
    description="Warm, soft and nostalgic. Elegant serif titles with a handwritten accent.",
    grade=Grade(exposure=0.05, contrast=0.12, saturation=1.05, temperature=0.18, lift=0.03,
                shadows=(0.0, 0.0, 0.015), highlights=(0.02, 0.01, -0.01)),
    vignette=0.30, grain=0.025, zoom=1.12, photo_frame="shadow",
    transitions={"fade": 2, "blur_dissolve": 1.6, "luma_dissolve": 1.4, "light_leak": 0.7, "circle_open": 0.8,
                 "slide_left": 0.7, "slide_right": 0.6, "wipe_right": 0.7, "zoom_out": 0.8, "cover_left": 0.6,
                 "wipe_diagonal": 0.5},
    transition_seconds=1.2, chapter_transition="light_leak", chapter_pool=("fade_black", "fade_white", "blinds"),
    title_font=FontSpec("playfair", "Regular", 108), subtitle_font=FontSpec("montserrat", "Light", 28, 0.38, True),
    chapter_font=FontSpec("playfair", "Regular", 80), chapter_sub_font=FontSpec("montserrat", "Medium", 22, 0.42, True),
    caption_font=FontSpec("playfair_italic", "Regular", 44), accent_font=FontSpec("greatvibes", "Regular", 70),
    accent_color=(240, 205, 150), title_anim="tracking_in", chapter_anim="letters_rise", caption_anim="fade_up",
    caption_layout="bottom",
))

_register(Look(
    key="cinematic", label="Cinematic",
    description="Teal & orange film grade, 2.39:1 letterbox, wide-tracked minimal titles.",
    grade=Grade(exposure=-0.05, contrast=0.28, saturation=0.92, temperature=0.05, lift=0.02,
                shadows=(-0.025, 0.01, 0.04), highlights=(0.04, 0.015, -0.03)),
    vignette=0.35, grain=0.035, letterbox=2.39, zoom=1.10,
    motions=("zoom_in", "pan_right", "zoom_out", "pan_left", "drift"),
    transitions={"fade": 1.6, "fade_black": 1.0, "blur_dissolve": 1.2, "luma_dissolve": 1.0, "zoom_in": 0.8,
                 "zoom_out": 0.8, "slide_left": 0.6, "wipe_left": 0.6, "cover_left": 0.7, "whip_pan": 0.5,
                 "circle_close": 0.4},
    transition_seconds=1.1, chapter_transition="fade_black", chapter_pool=("light_leak", "whip_pan", "flash"),
    title_font=FontSpec("montserrat", "Light", 84, 0.45, True), subtitle_font=FontSpec("montserrat", "Regular", 24, 0.6, True),
    chapter_font=FontSpec("montserrat", "SemiBold", 58, 0.35, True), chapter_sub_font=FontSpec("montserrat", "Light", 22, 0.5, True),
    caption_font=FontSpec("montserrat", "Light", 34, 0.12, False),
    accent_color=(255, 170, 90), title_anim="tracking_in", chapter_anim="blur_in", caption_anim="blur_in",
    decoration="line", caption_layout="bottom", fade_in=1.5, fade_out=2.5,
))

_register(Look(
    key="wedding", label="Elegant Wedding",
    description="Bright, airy pastel grade. Script calligraphy with fine serif — luxury invitation style.",
    grade=Grade(exposure=0.12, contrast=-0.05, saturation=0.88, temperature=0.08, tint=0.05, lift=0.05,
                highlights=(0.02, 0.01, 0.015)),
    vignette=0.18, grain=0.012, zoom=1.10, photo_frame="shadow",
    transitions={"fade": 2, "fade_white": 1.0, "light_leak": 1.0, "blur_dissolve": 1.6, "circle_open": 0.8,
                 "luma_dissolve": 1.0, "wipe_diagonal": 0.6, "zoom_out": 0.6, "cover_left": 0.5},
    transition_seconds=1.4, chapter_transition="fade_white", chapter_pool=("light_leak", "blinds", "circle_close"),
    title_font=FontSpec("greatvibes", "Regular", 150), subtitle_font=FontSpec("cormorant", "Medium", 34, 0.32, True),
    chapter_font=FontSpec("greatvibes", "Regular", 110), chapter_sub_font=FontSpec("cormorant", "SemiBold", 26, 0.4, True),
    caption_font=FontSpec("cormorant", "Medium", 46), accent_font=None,
    accent_color=(226, 200, 160), title_anim="blur_in", chapter_anim="blur_in", caption_anim="fade_up",
    decoration="line", caption_layout="bottom", text_shadow=0.45, fade_in=1.5, fade_out=3.0,
))

_register(Look(
    key="travel", label="Travel Documentary",
    description="Punchy, saturated grade. Bold condensed titles and location lower-thirds.",
    grade=Grade(exposure=0.03, contrast=0.22, saturation=1.18, temperature=0.04,
                shadows=(-0.01, 0.0, 0.02), highlights=(0.02, 0.01, -0.01)),
    vignette=0.22, grain=0.0, zoom=1.16,
    motions=("zoom_in", "pan_right", "pan_left", "zoom_out", "pan_up"),
    transitions={"slide_left": 1.2, "slide_right": 0.8, "whip_pan": 1.2, "zoom_in": 1.0, "zoom_out": 0.8,
                 "fade": 1.2, "wipe_right": 0.8, "wipe_down": 0.5, "slide_up": 0.6, "cover_left": 0.8,
                 "circle_open": 0.5},
    transition_seconds=0.8, chapter_transition="whip_pan", chapter_pool=("fade_black", "blinds", "flash"),
    title_font=FontSpec("bebas", "Regular", 170, 0.06, True), subtitle_font=FontSpec("montserrat", "SemiBold", 28, 0.3, True),
    chapter_font=FontSpec("bebas", "Regular", 120, 0.05, True), chapter_sub_font=FontSpec("montserrat", "SemiBold", 24, 0.3, True),
    caption_font=FontSpec("montserrat", "SemiBold", 36), accent_color=(255, 196, 0),
    title_layout="lower_left", chapter_layout="lower_left", caption_layout="plate",
    title_anim="wipe", chapter_anim="wipe", caption_anim="slide_right", decoration="bar",
))

_register(Look(
    key="vintage", label="Vintage Film",
    description="Faded super-8 look: sepia tones, grain, flicker, dust and instant-photo frames.",
    grade=Grade(exposure=0.02, contrast=0.1, saturation=0.65, temperature=0.3, lift=0.09, sepia=0.35,
                shadows=(0.02, 0.0, -0.02), highlights=(0.03, 0.015, -0.03)),
    vignette=0.5, grain=0.07, flicker=0.035, dust=1.0, gate_weave=1.0, zoom=1.08, photo_frame="polaroid",
    transitions={"fade": 2, "fade_black": 1.2, "film_burn": 1.0, "luma_dissolve": 1.2, "blur_dissolve": 0.8,
                 "circle_close": 0.6, "wipe_left": 0.5, "flash": 0.4},
    transition_seconds=1.2, chapter_transition="film_burn", chapter_pool=("fade_black", "circle_close"),
    title_font=FontSpec("playfair_italic", "Regular", 100), subtitle_font=FontSpec("cormorant", "SemiBold", 32, 0.3, True),
    chapter_font=FontSpec("playfair_italic", "Regular", 76), chapter_sub_font=FontSpec("cormorant", "SemiBold", 26, 0.35, True),
    caption_font=FontSpec("playfair_italic", "Regular", 42), text_color=(250, 240, 220), accent_color=(220, 180, 120),
    title_anim="typewriter", chapter_anim="typewriter", caption_anim="fade_up", caption_layout="bottom",
    fade_in=1.5, fade_out=3.0,
))

_register(Look(
    key="dynamic", label="Modern Dynamic",
    description="High-energy social style: kinetic word-pop titles, glitch, zoom and whip transitions.",
    grade=Grade(exposure=0.04, contrast=0.3, saturation=1.22, temperature=-0.03,
                shadows=(-0.01, 0.0, 0.03), highlights=(0.02, 0.0, -0.01)),
    vignette=0.2, grain=0.0, zoom=1.2,
    motions=("zoom_in", "zoom_out", "pan_right", "pan_left", "zoom_in_fast"),
    transitions={"zoom_in": 1.5, "zoom_out": 1.0, "whip_pan": 1.5, "glitch": 1.0, "slide_up": 1, "slide_left": 1,
                 "slide_down": 0.7, "flash": 0.9, "spin": 0.6, "cover_left": 0.8, "blinds": 0.5, "wipe_diagonal": 0.6},
    transition_seconds=0.6, chapter_transition="glitch", chapter_pool=("flash", "spin", "whip_pan"),
    title_font=FontSpec("inter", "Black", 128, -0.02, True), subtitle_font=FontSpec("inter", "SemiBold", 30, 0.25, True),
    chapter_font=FontSpec("inter", "ExtraBold", 96, -0.01, True), chapter_sub_font=FontSpec("inter", "Medium", 24, 0.25, True),
    caption_font=FontSpec("inter", "Bold", 46), accent_color=(255, 64, 129),
    title_anim="pop", chapter_anim="pop", caption_anim="pop", caption_layout="plate", decoration="plate",
    fade_in=0.4, fade_out=1.2,
))

_register(Look(
    key="black_white", label="Classic Black & White",
    description="Rich monochrome with deep contrast and timeless serif typography.",
    grade=Grade(exposure=0.03, contrast=0.3, saturation=1.0, mono=1.0, lift=0.02),
    vignette=0.4, grain=0.04, zoom=1.10, photo_frame="shadow",
    transitions={"fade": 2, "fade_black": 0.8, "luma_dissolve": 1.4, "blur_dissolve": 1.4, "circle_open": 0.6,
                 "circle_close": 0.5, "wipe_left": 0.6, "zoom_out": 0.6, "blinds": 0.4},
    transition_seconds=1.3, chapter_transition="fade_black", chapter_pool=("fade_white", "film_burn"),
    title_font=FontSpec("cormorant", "Light", 120, 0.08, False), subtitle_font=FontSpec("montserrat", "Light", 26, 0.5, True),
    chapter_font=FontSpec("cormorant", "Regular", 86), chapter_sub_font=FontSpec("montserrat", "Light", 22, 0.5, True),
    caption_font=FontSpec("cormorant", "Medium", 44), accent_color=(220, 220, 220),
    title_anim="letters_rise", chapter_anim="letters_rise", caption_anim="fade_up", caption_layout="bottom",
))

_register(Look(
    key="clean", label="Clean (no grade)",
    description="Natural colours, gentle motion, modern sans-serif titles.",
    grade=Grade(), vignette=0.0, grain=0.0, zoom=1.10,
    transitions={"fade": 2, "slide_left": 1, "slide_right": 0.7, "blur_dissolve": 1, "wipe_right": 0.7,
                 "cover_left": 0.7, "zoom_out": 0.6},
    transition_seconds=1.0, chapter_transition="fade_black", chapter_pool=("fade_white", "blinds"),
    title_font=FontSpec("inter", "SemiBold", 96, -0.01), subtitle_font=FontSpec("inter", "Regular", 30, 0.2, True),
    chapter_font=FontSpec("inter", "SemiBold", 72), chapter_sub_font=FontSpec("inter", "Regular", 24, 0.2, True),
    caption_font=FontSpec("inter", "Medium", 40), accent_color=(120, 190, 255),
    title_anim="fade_up", chapter_anim="fade_up", caption_anim="fade_up", decoration="none",
))

# Old V1 style names keep working.
_ALIASES = {"family memory": "family_memory", "travel documentary": "travel"}


def get_look(name: Optional[str]) -> Look:
    if not name:
        return LOOKS["family_memory"]
    key = str(name).strip()
    if key in LOOKS:
        return LOOKS[key]
    low = key.lower()
    if low in _ALIASES:
        return LOOKS[_ALIASES[low]]
    for look in LOOKS.values():
        if look.label.lower() == low:
            return look
    return LOOKS["family_memory"]


def look_with_overrides(look: Look, **overrides) -> Look:
    clean = {k: v for k, v in overrides.items() if v is not None}
    return replace(look, **clean) if clean else look


# ---------------------------------------------------------------- grading

def apply_grade(rgb: np.ndarray, g: Grade) -> np.ndarray:
    """Float colour pipeline on a uint8 RGB image. Used once per photo canvas
    (photos are static) and per frame only for video sources."""
    if g == Grade():
        return rgb
    x = rgb.astype(np.float32) * (1.0 / 255.0)

    if g.exposure:
        x *= 2.0 ** g.exposure
    if g.temperature or g.tint:
        t, m = g.temperature, g.tint
        gains = np.array([1 + 0.10 * t + 0.03 * m, 1 - 0.05 * m, 1 - 0.12 * t + 0.03 * m], np.float32)
        x *= gains

    luma = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)

    if g.mono or g.sepia:
        gray = np.repeat(luma[..., None], 3, axis=2)
        if g.mono:
            x = x * (1 - g.mono) + gray * g.mono
        if g.sepia:
            sep = np.clip(gray * np.array([1.07, 0.95, 0.76], np.float32) + np.array([0.03, 0.01, -0.01], np.float32), 0, 1.2)
            x = x * (1 - g.sepia) + sep * g.sepia

    if g.saturation != 1.0:
        l3 = luma[..., None]
        x = l3 + (x - l3) * g.saturation

    np.clip(x, 0, 1, out=x)

    if g.contrast:
        # Blend toward a smoothstep S-curve (positive) or flatten (negative).
        s = x * x * (3 - 2 * x)
        x = x + (s - x) * g.contrast * 1.6

    if any(g.shadows) or any(g.highlights):
        l = np.clip(luma, 0, 1)[..., None]
        sh = (1 - l) ** 2
        hi = l ** 2
        x = x + sh * np.array(g.shadows, np.float32) + hi * np.array(g.highlights, np.float32)

    if g.lift:
        x = g.lift + x * (1 - g.lift * 0.9)

    return (np.clip(x, 0, 1) * 255.0 + 0.5).astype(np.uint8)


# --------------------------------------------------------------- finishing

@lru_cache(maxsize=8)
def vignette_mask(w: int, h: int, strength: float) -> np.ndarray:
    """3-channel uint8 multiplier (255 = untouched) for cv2.multiply."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    r = np.sqrt(nx * nx * 0.85 + ny * ny * 1.0)
    falloff = np.clip((r - 0.55) / 0.9, 0, 1)
    falloff = falloff * falloff * (3 - 2 * falloff)
    m = 1.0 - strength * falloff
    m8 = (m * 255).astype(np.uint8)
    return cv2.merge([m8, m8, m8])


def apply_vignette(frame: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0:
        return frame
    h, w = frame.shape[:2]
    return cv2.multiply(frame, vignette_mask(w, h, round(strength, 3)), scale=1 / 255)


@lru_cache(maxsize=4)
def _grain_tiles(w: int, h: int, amount: float, seed: int = 7):
    rng = np.random.default_rng(seed)
    tiles = []
    for _ in range(6):
        n = rng.normal(0, amount * 255, (h // 2 + 1, w // 2 + 1)).astype(np.float32)
        n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)  # film grain is soft, not per-pixel
        n3 = cv2.merge([n, n, n])
        pos = np.clip(n3, 0, 255).astype(np.uint8)
        neg = np.clip(-n3, 0, 255).astype(np.uint8)
        tiles.append((pos, neg))
    return tiles


def apply_grain(frame: np.ndarray, amount: float, frame_index: int) -> np.ndarray:
    if amount <= 0:
        return frame
    h, w = frame.shape[:2]
    pos, neg = _grain_tiles(w, h, round(amount, 4))[frame_index % 6]
    return cv2.subtract(cv2.add(frame, pos), neg)


def letterbox_bars(w: int, h: int, aspect: float) -> int:
    if aspect <= 0 or w / h >= aspect:
        return 0
    visible = int(round(w / aspect))
    return max((h - visible) // 2, 0)


def apply_letterbox(frame: np.ndarray, bar: int) -> np.ndarray:
    if bar > 0:
        frame[:bar] = 0
        frame[-bar:] = 0
    return frame


def apply_film_damage(frame: np.ndarray, look: Look, frame_index: int, fps: int) -> np.ndarray:
    """Flicker, gate weave, dust and the odd scratch — deterministic per frame
    so parallel chunks produce identical results."""
    rng = np.random.default_rng(frame_index * 7919 + 13)
    h, w = frame.shape[:2]
    if look.gate_weave:
        dx = np.sin(frame_index * 0.71) * 0.6 * look.gate_weave + rng.normal(0, 0.25)
        dy = np.sin(frame_index * 0.37 + 1.3) * 0.9 * look.gate_weave + rng.normal(0, 0.3)
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        frame = cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if look.flicker:
        gain = 1.0 + rng.normal(0, look.flicker)
        frame = cv2.convertScaleAbs(frame, alpha=float(gain), beta=0)
    if look.dust:
        scale = h / 1080
        for _ in range(int(rng.poisson(2.2 * look.dust))):
            x, y = int(rng.uniform(0, w)), int(rng.uniform(0, h))
            r = max(1, int(rng.uniform(1, 4) * scale))
            shade = int(rng.choice([20, 235]))
            cv2.circle(frame, (x, y), r, (shade, shade, shade), -1, cv2.LINE_AA)
        if rng.random() < 0.06 * look.dust:
            x = int(rng.uniform(w * 0.1, w * 0.9))
            cv2.line(frame, (x, 0), (x + int(rng.normal(0, 6)), h), (200, 200, 200), 1, cv2.LINE_AA)
        if rng.random() < 0.02 * look.dust:
            # short hair/fibre
            x, y = int(rng.uniform(0, w)), int(rng.uniform(0, h))
            pts = np.cumsum(rng.normal(0, 6 * scale, (8, 2)), axis=0).astype(np.int32) + [x, y]
            cv2.polylines(frame, [pts], False, (25, 25, 25), 1, cv2.LINE_AA)
    return frame
