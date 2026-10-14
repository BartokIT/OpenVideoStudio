"""Animated typography: titles, chapter cards, captions and end cards.

Text is rasterised once with Pillow into small premultiplied RGBA sprites
(per line, word or character depending on the animation) and composited
onto each frame with per-unit transforms. That gives animations FFmpeg's
drawtext can't do: per-letter staggered reveals, tracking-in, blur-in,
word pops, typewriter, wipes — plus soft drop shadows, accent rules,
plates and legibility scrims.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .looks import FontSpec, Look

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
WIN_FONTS = Path(r"C:\Windows\Fonts")

# family -> candidate files (first existing wins). Bundled OFL fonts first,
# Windows system fonts as fallback so the engine never hard-fails on fonts.
FONT_FAMILIES: dict[str, list[tuple[Path, Optional[str]]]] = {
    "playfair": [(FONTS_DIR / "PlayfairDisplay-VF.ttf", None), (WIN_FONTS / "georgia.ttf", None)],
    "playfair_italic": [(FONTS_DIR / "PlayfairDisplay-Italic-VF.ttf", None), (WIN_FONTS / "georgiai.ttf", None)],
    "montserrat": [(FONTS_DIR / "Montserrat-VF.ttf", None), (WIN_FONTS / "segoeui.ttf", None)],
    "inter": [(FONTS_DIR / "Inter-VF.ttf", None), (WIN_FONTS / "segoeuib.ttf", None)],
    "bebas": [(FONTS_DIR / "BebasNeue-Regular.ttf", None), (WIN_FONTS / "impact.ttf", None)],
    "greatvibes": [(FONTS_DIR / "GreatVibes-Regular.ttf", None), (WIN_FONTS / "segoesc.ttf", None)],
    "cormorant": [(FONTS_DIR / "CormorantGaramond-VF.ttf", None), (WIN_FONTS / "pala.ttf", None)],
    "georgia": [(WIN_FONTS / "georgia.ttf", None)],
    "segoe": [(WIN_FONTS / "segoeui.ttf", None)],
}
FALLBACK_FONT = WIN_FONTS / "arial.ttf"

FONT_CHOICES = {
    "Auto (from style)": None,
    "Playfair Display (elegant serif)": "playfair",
    "Playfair Italic": "playfair_italic",
    "Cormorant Garamond (luxury serif)": "cormorant",
    "Great Vibes (calligraphy)": "greatvibes",
    "Montserrat (modern sans)": "montserrat",
    "Inter (clean sans)": "inter",
    "Bebas Neue (bold condensed)": "bebas",
}

ANIMATIONS = ["fade_up", "letters_rise", "tracking_in", "blur_in", "pop", "typewriter", "wipe", "slide_right"]

_ANIM_UNIT = {
    "fade_up": "line", "letters_rise": "char", "tracking_in": "char", "blur_in": "line",
    "pop": "word", "typewriter": "char", "wipe": "line", "slide_right": "line",
}


@lru_cache(maxsize=64)
def get_font(family: str, weight: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = list(FONT_FAMILIES.get(family, []))
    custom = FONTS_DIR / family
    if custom.suffix.lower() in (".ttf", ".otf") and custom.exists():
        candidates.insert(0, (custom, None))
    for path, _ in candidates:
        if not path.exists():
            continue
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:
            continue
        try:
            names = [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
            want = weight.replace(" ", "").lower()
            match = next((n for n in names if n.replace(" ", "").lower() == want), None)
            if match:
                font.set_variation_by_name(match)
        except (OSError, AttributeError, ValueError):
            pass  # static font: weight is fixed by the file
        return font
    return ImageFont.truetype(str(FALLBACK_FONT), size)


# ------------------------------------------------------------------ easing

def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(p: float) -> float:
    p = _clamp(p)
    return 1 - (1 - p) ** 3


def ease_out_quint(p: float) -> float:
    p = _clamp(p)
    return 1 - (1 - p) ** 5


def ease_in_out(p: float) -> float:
    p = _clamp(p)
    return p * p * (3 - 2 * p)


def ease_out_back(p: float, k: float = 1.7) -> float:
    p = _clamp(p)
    return 1 + (k + 1) * (p - 1) ** 3 + k * (p - 1) ** 2


# ------------------------------------------------------------- rasterising

@dataclass
class Sprite:
    rgb: np.ndarray    # float32 premultiplied RGB (h, w, 3)
    a: np.ndarray      # float32 alpha (h, w, 1)
    x: float           # top-left in frame coords at rest
    y: float
    order: int = 0     # unit index for staggering
    center: float = 0  # unit centre x relative to its line centre (for tracking)

    @property
    def w(self) -> int:
        return self.a.shape[1]

    @property
    def h(self) -> int:
        return self.a.shape[0]


def _to_sprite(img: Image.Image, x: float, y: float, order: int = 0, center: float = 0.0) -> Optional[Sprite]:
    arr = np.asarray(img, dtype=np.float32) / 255.0
    alpha = arr[..., 3:4]
    ys, xs = np.nonzero(alpha[..., 0] > 0.002)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    alpha = alpha[y0:y1, x0:x1]
    rgb = arr[y0:y1, x0:x1, :3] * alpha
    return Sprite(np.ascontiguousarray(rgb), np.ascontiguousarray(alpha), x + x0, y + y0, order, center)


@dataclass
class LineSpec:
    text: str
    font: FontSpec
    color: tuple
    role: str = "text"   # text | rule
    gap_after: float = 0.35  # in units of this line's font size
    opacity: float = 1.0


@dataclass
class LaidLine:
    spec: LineSpec
    font: ImageFont.FreeTypeFont
    text: str
    x: float           # left edge in frame coords
    y: float           # top (ascender line)
    width: float
    height: float
    char_x: list       # x offset of each char from line left
    tracking: float


def _measure(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> tuple[list, float]:
    xs = []
    for i in range(len(text)):
        xs.append(font.getlength(text[:i]) + i * tracking)
    width = font.getlength(text) + max(len(text) - 1, 0) * tracking if text else 0.0
    return xs, width


def wrap_text(text: str, font: ImageFont.FreeTypeFont, tracking: float, max_w: float, max_lines: int = 3) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if _measure(trial, font, tracking)[1] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines


# ----------------------------------------------------------------- overlay

class TextOverlay:
    """One animated text block bound to a time window on the timeline."""

    def __init__(self, spec: dict, look: Look, width: int, height: int):
        self.spec = spec
        self.look = look
        self.W, self.H = width, height
        self.k = height / 1080.0
        self.start = float(spec["start"])
        self.end = float(spec["end"])
        self.anim = spec.get("anim") or "fade_up"
        self.unit = _ANIM_UNIT.get(self.anim, "line")
        self.layout = spec.get("layout", "center")
        self.decoration = spec.get("decoration", "none")
        self.in_dur = float(spec.get("in_dur", 1.2))
        self.out_dur = float(spec.get("out_dur", 0.7))
        self.scrim = float(spec.get("scrim", 0.0))
        self.avoid: list = []  # face boxes (output coords) the block should not cover
        self._built = False

    # ---------------------------------------------------------- layout
    def _build(self) -> None:
        self._built = True
        W, H, k = self.W, self.H, self.k
        lines: list[LineSpec] = [LineSpec(**l) if isinstance(l, dict) else l for l in self.spec["lines"]]
        max_w = W * float(self.spec.get("max_width", 0.84))

        laid: list[LaidLine] = []
        for ls in lines:
            if ls.role == "rule":
                laid.append(LaidLine(ls, None, "", 0, 0, 0, max(2.0, 2.2 * k), [], 0))
                continue
            text = ls.text.upper() if ls.font.upper else ls.text
            size = max(int(ls.font.size * k), 8)
            font = get_font(ls.font.family, ls.font.weight, size)
            tracking = ls.font.tracking * size
            _, width = _measure(text, font, tracking)
            if width > max_w:  # shrink to fit long titles
                size = max(int(size * max_w / width), 8)
                font = get_font(ls.font.family, ls.font.weight, size)
                tracking = ls.font.tracking * size
            char_x, width = _measure(text, font, tracking)
            asc, desc = font.getmetrics()
            laid.append(LaidLine(ls, font, text, 0, 0, width, asc + desc, char_x, tracking))

        # vertical stacking
        total_h = 0.0
        for i, ll in enumerate(laid):
            total_h += ll.height
            if i < len(laid) - 1:
                ref = ll.font.size if ll.font else 30 * k
                total_h += ll.spec.gap_after * ref
        text_w = max([ll.width for ll in laid if ll.font] or [0])

        bar = letterbox_bar(W, H, self.spec.get("letterbox", 0.0))
        margin_x = W * 0.075
        if self.layout == "center":
            top = (H - total_h) / 2 + H * float(self.spec.get("y_offset", 0.0))
            if self.avoid:
                top = self._avoid_faces(top, total_h, text_w, bar)
        elif self.layout in ("lower_left", "lower_third", "plate"):
            top = H - bar - H * 0.11 - total_h
        elif self.layout == "bottom":
            top = H - bar - H * 0.085 - total_h
        else:
            top = (H - total_h) / 2
        align_left = self.layout in ("lower_left", "lower_third", "plate")
        left_base = margin_x + (24 * k if self.decoration == "bar" else 0)

        y = top
        for i, ll in enumerate(laid):
            if ll.font is None:  # rule
                rw = text_w * 0.5 if not align_left else 90 * k
                rw = max(rw, 60 * k)
                ll.width = rw
                ll.x = left_base if align_left else (W - rw) / 2
                ll.y = y
            else:
                ll.x = left_base if align_left else (W - ll.width) / 2
                ll.y = y
            y += ll.height
            if i < len(laid) - 1:
                ref = ll.font.size if ll.font else 30 * k
                y += ll.spec.gap_after * ref
        self.laid = laid
        self.block = (min(ll.x for ll in laid), top, max(ll.x + ll.width for ll in laid), top + total_h)

        # unit sprites
        self.sprites: list[Sprite] = []
        self.rules: list[LaidLine] = [ll for ll in laid if ll.font is None]
        order = 0
        for ll in laid:
            if ll.font is None:
                continue
            color = tuple(int(c) for c in ll.spec.color)
            if self.unit == "line":
                self.sprites.append(self._raster(ll, 0, len(ll.text), order, color))
                order += 1
            elif self.unit == "word":
                i = 0
                for word in ll.text.split(" "):
                    if word:
                        self.sprites.append(self._raster(ll, i, i + len(word), order, color))
                        order += 1
                    i += len(word) + 1
            else:
                for i, ch in enumerate(ll.text):
                    if ch.strip():
                        self.sprites.append(self._raster(ll, i, i + 1, order, color))
                    order += 1
        self.sprites = [s for s in self.sprites if s is not None]
        self.n_units = max(order, 1)
        self.shadow = self._shadow_sprite()
        self.scrim_mask = self._scrim_mask() if self.scrim > 0 else None

    def _avoid_faces(self, top: float, total_h: float, text_w: float, bar: int) -> float:
        """Slides a centred block up/down so it doesn't sit on a face."""
        W, H = self.W, self.H
        x0, x1 = (W - text_w) / 2 - 20 * self.k, (W + text_w) / 2 + 20 * self.k
        lo, hi = bar + H * 0.07, H - bar - H * 0.07 - total_h

        def overlap(y):
            area = 0.0
            for fx0, fy0, fx1, fy1 in self.avoid:
                # pad faces: the whole head matters, not just the detector box
                ph = (fy1 - fy0) * 0.45
                ix = max(0.0, min(x1, fx1 + ph) - max(x0, fx0 - ph))
                iy = max(0.0, min(y + total_h, fy1 + ph) - max(y, fy0 - ph * 1.4))
                area += ix * iy
            return area

        candidates = [top] + [min(max(top + H * d, lo), hi) for d in (0.26, -0.26, 0.34, -0.34, 0.16, -0.16)]
        best = min(candidates, key=lambda y: (overlap(y) > 0, overlap(y), abs(y - top)))
        return best

    def _raster(self, ll: LaidLine, i0: int, i1: int, order: int, color: tuple) -> Optional[Sprite]:
        font = ll.font
        pad = int(font.size * 0.6) + 4
        x_from = ll.char_x[i0]
        x_to = ll.char_x[i1 - 1] + font.getlength(ll.text[i1 - 1]) if i1 > i0 else x_from
        w = int(x_to - x_from + 2 * pad) + 2
        h = int(ll.height + 2 * pad)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fill = color + (int(255 * ll.spec.opacity),)
        if ll.tracking == 0 and i1 - i0 > 1:
            d.text((pad, pad), ll.text[i0:i1], font=font, fill=fill)
        else:
            for j in range(i0, i1):
                d.text((pad + ll.char_x[j] - x_from, pad), ll.text[j], font=font, fill=fill)
        ox = ll.x + x_from - pad
        oy = ll.y - pad
        center = (x_from + x_to) / 2 - ll.width / 2
        return _to_sprite(img, ox, oy, order, center)

    def _shadow_sprite(self) -> Optional[Sprite]:
        strength = float(self.spec.get("shadow", self.look.text_shadow))
        if strength <= 0 or not self.sprites:
            return None
        x0 = int(min(s.x for s in self.sprites)) - 40
        y0 = int(min(s.y for s in self.sprites)) - 40
        x1 = int(max(s.x + s.w for s in self.sprites)) + 40
        y1 = int(max(s.y + s.h for s in self.sprites)) + 40
        a = np.zeros((y1 - y0, x1 - x0), np.float32)
        for s in self.sprites:
            xx, yy = int(s.x) - x0, int(s.y) - y0
            a[yy:yy + s.h, xx:xx + s.w] = np.maximum(a[yy:yy + s.h, xx:xx + s.w], s.a[..., 0])
        sigma = max(2.0, 6.0 * self.k)
        a = cv2.GaussianBlur(a, (0, 0), sigma) * strength
        # wide, faint second pass reads as ambient occlusion behind thin type
        a = np.clip(a + cv2.GaussianBlur(a, (0, 0), sigma * 4) * 0.6, 0, 1)
        off = 3 * self.k
        return Sprite(np.zeros(a.shape + (3,), np.float32), a[..., None], x0 + off, y0 + off * 1.3)

    def _scrim_mask(self) -> np.ndarray:
        W, H = self.W, self.H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        if self.layout == "center":
            cx, cy = W / 2, (self.block[1] + self.block[3]) / 2
            r = np.sqrt(((xx - cx) / (W * 0.55)) ** 2 + ((yy - cy) / (H * 0.45)) ** 2)
            m = np.clip(1 - r, 0, 1) ** 0.8 * 0.8 + 0.2
        elif self.layout in ("lower_left", "plate", "lower_third"):
            gy = np.clip((yy - H * 0.45) / (H * 0.55), 0, 1)
            gx = np.clip(1 - xx / (W * 0.9), 0, 1)
            m = gy ** 1.4 * (0.5 + 0.5 * gx)
        else:  # bottom
            m = np.clip((yy - H * 0.55) / (H * 0.45), 0, 1) ** 1.5
        return np.clip(m, 0, 1).astype(np.float32)

    # ------------------------------------------------------- animation
    def _unit_state(self, s: Sprite, tau: float, hold_p: float, out_p: float) -> tuple:
        """Returns (dx, dy, alpha, scale, blur) for a unit at local time tau."""
        k, anim = self.k, self.anim
        if anim == "letters_rise":
            p = (tau - s.order * 0.035) / 0.65
            e = ease_out_cubic(p)
            st = [0, (1 - e) * 0.45 * s.h, ease_in_out(p), 1.0, (1 - e) * 2.5 * k]
        elif anim == "tracking_in":
            p = (tau - self._line_of(s) * 0.3) / self.in_dur
            e = ease_out_quint(p)
            spread = 0.55 * (1 - e) + 0.03 * hold_p
            st = [s.center * spread, 0, ease_in_out(p * 1.3), 1.0, (1 - e) * 7 * k]
        elif anim == "blur_in":
            p = (tau - s.order * 0.3) / self.in_dur
            e = ease_out_cubic(p)
            st = [0, 0, ease_in_out(p), 1.07 - 0.07 * e + 0.015 * hold_p, (1 - e) * 16 * k]
        elif anim == "pop":
            p = (tau - s.order * 0.09) / 0.42
            st = [0, (1 - ease_out_cubic(p)) * 0.15 * s.h, _clamp(p * 3), 0.35 + 0.65 * ease_out_back(p, 2.2), 0]
        elif anim == "typewriter":
            p = (tau - s.order * 0.055) / 0.06
            st = [0, 0, _clamp(p), 1.0, 0]
        elif anim == "wipe":
            p = (tau - s.order * 0.2) / self.in_dur
            e = ease_out_quint(p)
            st = [(1 - e) * -0.02 * self.W, 0, 1.0 if p > 0 else 0.0, 1.0, 0, e]
        elif anim == "slide_right":
            p = (tau - s.order * 0.15) / self.in_dur
            e = ease_out_quint(p)
            st = [(1 - e) * -0.05 * self.W, 0, ease_in_out(p * 1.5), 1.0, 0]
        else:  # fade_up
            p = (tau - s.order * 0.18) / self.in_dur
            e = ease_out_cubic(p)
            st = [0, (1 - e) * 0.035 * self.H - hold_p * 0.006 * self.H, ease_in_out(p), 1.0, 0]

        if out_p > 0:
            o = ease_in_out(out_p)
            st[2] *= 1 - o
            if anim == "blur_in":
                st[4] += o * 12 * k
            elif anim == "pop":
                st[3] *= 1 - 0.2 * o
            elif anim == "tracking_in":
                st[0] += s.center * 0.15 * o
                st[4] += o * 4 * k
            else:
                st[1] -= o * 0.015 * self.H
        return st

    def _line_of(self, s: Sprite) -> int:
        for i, ll in enumerate([l for l in self.laid if l.font is not None]):
            if ll.y - ll.font.size <= s.y <= ll.y + ll.height:
                return i
        return 0

    def progress(self, t: float) -> tuple[float, float, float]:
        tau = t - self.start
        life = self.end - self.start
        hold_p = _clamp(tau / max(life, 1e-3))
        out_p = _clamp((tau - (life - self.out_dur)) / max(self.out_dur, 1e-3))
        return tau, hold_p, out_p

    def active(self, t: float) -> bool:
        return self.start <= t < self.end

    def draw(self, frame: np.ndarray, t: float) -> np.ndarray:
        if not self.active(t):
            return frame
        if not self._built:
            self._build()
        tau, hold_p, out_p = self.progress(t)
        block_in = ease_in_out(tau / max(self.in_dur * 0.8, 0.2))
        block_alpha = block_in * (1 - ease_in_out(out_p))

        if self.scrim_mask is not None and block_alpha > 0.01:
            m = 1.0 - self.scrim * block_alpha * self.scrim_mask
            frame = (frame.astype(np.float32) * m[..., None]).astype(np.uint8)

        if self.decoration == "plate" and block_alpha > 0:
            self._draw_plate(frame, tau, out_p)

        if self.shadow is not None:
            _blend(frame, self.shadow, self.shadow.x, self.shadow.y, block_alpha)

        for s in self.sprites:
            st = self._unit_state(s, tau, hold_p, out_p)
            dx, dy, alpha, scale, blur = st[:5]
            reveal = st[5] if len(st) > 5 else None
            if alpha <= 0.003:
                continue
            _draw_sprite(frame, s, dx, dy, alpha, scale, blur, reveal)

        self._draw_rules(frame, tau, out_p)
        if self.decoration == "bar":
            self._draw_bar(frame, tau, out_p)
        return frame

    def _draw_rules(self, frame: np.ndarray, tau: float, out_p: float) -> None:
        if self.decoration not in ("line",):
            return
        color = tuple(int(c) for c in self.look.accent_color)
        for ll in self.rules:
            p = ease_out_quint((tau - 0.35) / 1.1)
            a = p * (1 - ease_in_out(out_p))
            if a <= 0:
                continue
            w = ll.width * p
            cx = ll.x + ll.width / 2 if self.layout == "center" else ll.x + w / 2
            th = ll.height
            x0, x1 = cx - w / 2, cx + w / 2
            _fill_rect(frame, x0, ll.y, x1, ll.y + th, color, a * 0.95)

    def _draw_bar(self, frame: np.ndarray, tau: float, out_p: float) -> None:
        color = tuple(int(c) for c in self.look.accent_color)
        x0, y0, x1, y1 = self.block
        p = ease_out_quint(tau / 0.7)
        a = 1 - ease_in_out(out_p)
        bw = 7 * self.k
        bx = x0 - 24 * self.k
        h = (y1 - y0) * p
        _fill_rect(frame, bx, y1 - h, bx + bw, y1, color, a)

    def _draw_plate(self, frame: np.ndarray, tau: float, out_p: float) -> None:
        x0, y0, x1, y1 = self.block
        pad_x, pad_y = 28 * self.k, 18 * self.k
        p = ease_out_quint(tau / 0.55)
        a = 1 - ease_in_out(out_p)
        right = x0 - pad_x + (x1 - x0 + 2 * pad_x) * p
        _fill_rect(frame, x0 - pad_x, y0 - pad_y, right, y1 + pad_y, (12, 12, 16), 0.62 * a)
        color = tuple(int(c) for c in self.look.accent_color)
        _fill_rect(frame, x0 - pad_x, y0 - pad_y, x0 - pad_x + 8 * self.k, y1 + pad_y, color, a)


def letterbox_bar(w: int, h: int, aspect: float) -> int:
    if not aspect or w / h >= aspect:
        return 0
    return max((h - int(round(w / aspect))) // 2, 0)


def _fill_rect(frame: np.ndarray, x0: float, y0: float, x1: float, y1: float, color: tuple, alpha: float) -> None:
    H, W = frame.shape[:2]
    xa, xb = max(int(round(x0)), 0), min(int(round(x1)), W)
    ya, yb = max(int(round(y0)), 0), min(int(round(y1)), H)
    if xb <= xa or yb <= ya or alpha <= 0:
        return
    region = frame[ya:yb, xa:xb].astype(np.float32)
    region = region * (1 - alpha) + np.array(color, np.float32) * alpha
    frame[ya:yb, xa:xb] = region.astype(np.uint8)


def _blend(frame: np.ndarray, s: Sprite, x: float, y: float, alpha: float,
           rgb: Optional[np.ndarray] = None, a: Optional[np.ndarray] = None) -> None:
    rgb = s.rgb if rgb is None else rgb
    a = s.a if a is None else a
    H, W = frame.shape[:2]
    h, w = a.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    x0, y0 = max(xi, 0), max(yi, 0)
    x1, y1 = min(xi + w, W), min(yi + h, H)
    if x1 <= x0 or y1 <= y0 or alpha <= 0:
        return
    sx0, sy0 = x0 - xi, y0 - yi
    sa = a[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)] * alpha
    srgb = rgb[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)] * (alpha * 255.0)
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(region * (1 - sa) + srgb, 0, 255).astype(np.uint8)


def _draw_sprite(frame, s: Sprite, dx, dy, alpha, scale, blur, reveal=None) -> None:
    rgb, a = s.rgb, s.a
    x, y = s.x + dx, s.y + dy
    if abs(scale - 1) > 0.004:
        nw, nh = max(int(s.w * scale), 1), max(int(s.h * scale), 1)
        rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        a = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_LINEAR)[..., None]
        x += (s.w - nw) / 2
        y += (s.h - nh) / 2
    if blur > 0.35:
        pad = int(blur * 3) + 1
        rgb = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        a = cv2.copyMakeBorder(a, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        rgb = cv2.GaussianBlur(rgb, (0, 0), blur)
        a = cv2.GaussianBlur(a, (0, 0), blur)
        if a.ndim == 2:
            a = a[..., None]
        x -= pad
        y -= pad
    if reveal is not None and reveal < 1:
        w = a.shape[1]
        edge = max(w * 0.08, 6)
        xs = np.arange(w, dtype=np.float32)
        m = np.clip((reveal * (w + edge) - xs) / edge, 0, 1)[None, :, None]
        a = a * m
        rgb = rgb * m
    if a.ndim == 2:
        a = a[..., None]
    _blend(frame, s, x, y, alpha, rgb, a)


# --------------------------------------------------------------- templates

def _with_family(spec: FontSpec, family: Optional[str]) -> FontSpec:
    if not family:
        return spec
    from dataclasses import replace
    weight = spec.weight
    if family in ("greatvibes", "bebas"):
        weight = "Regular"
    upper = spec.upper and family != "greatvibes"
    tracking = spec.tracking if family != "greatvibes" else 0.0
    size = spec.size * (1.35 if family == "greatvibes" and spec.family != "greatvibes" else 1.0)
    size = size * (1.3 if family == "bebas" and spec.family != "bebas" else 1.0)
    return replace(spec, family=family, weight=weight, upper=upper, tracking=tracking, size=size)


def title_card(look: Look, title: str, subtitle: str, kicker: str, start: float, end: float,
               anim: Optional[str] = None, font_family: Optional[str] = None) -> dict:
    tf = _with_family(look.title_font, font_family)
    lines = []
    if look.title_layout == "lower_left":
        if kicker:
            lines.append(LineSpec(kicker, look.subtitle_font, look.accent_color, gap_after=0.4))
        lines.append(LineSpec(title, tf, look.text_color, gap_after=0.12))
        if subtitle:
            lines.append(LineSpec(subtitle, look.subtitle_font, look.text_color, gap_after=0))
        layout, deco = "lower_left", look.decoration if look.decoration != "line" else "bar"
    else:
        if kicker and look.accent_font:
            lines.append(LineSpec(kicker, look.accent_font, look.accent_color, gap_after=0.15))
        elif kicker:
            lines.append(LineSpec(kicker, look.subtitle_font, look.accent_color, gap_after=0.9))
        lines.append(LineSpec(title, tf, look.text_color, gap_after=0.32))
        if look.decoration == "line":
            lines.append(LineSpec("", tf, look.accent_color, role="rule", gap_after=0))
            lines[-2].gap_after = 0.28
            lines[-1].gap_after = 22.0 / 30.0 * (1 if subtitle else 0)
        if subtitle:
            lines.append(LineSpec(subtitle, look.subtitle_font, look.text_color, gap_after=0))
        layout, deco = "center", ("line" if look.decoration == "line" else "none")
    return {
        "kind": "title", "lines": [l.__dict__ for l in lines], "start": start, "end": end,
        "anim": anim or look.title_anim, "layout": layout, "decoration": deco,
        "in_dur": 1.8 if (anim or look.title_anim) == "tracking_in" else 1.3, "out_dur": 0.9,
        "scrim": 0.42, "letterbox": look.letterbox,
    }


def chapter_card(look: Look, name: str, sub: str, start: float, end: float,
                 anim: Optional[str] = None, font_family: Optional[str] = None) -> dict:
    cf = _with_family(look.chapter_font, font_family)
    lines = []
    if look.chapter_layout == "lower_left":
        if sub:
            lines.append(LineSpec(sub, look.chapter_sub_font, look.accent_color, gap_after=0.35))
        lines.append(LineSpec(name, cf, look.text_color, gap_after=0))
        layout, deco = "lower_left", "bar" if look.decoration in ("line", "bar") else look.decoration
    else:
        lines.append(LineSpec(name, cf, look.text_color, gap_after=0.3))
        if look.decoration == "line":
            lines.append(LineSpec("", cf, look.accent_color, role="rule", gap_after=0.0))
        if sub:
            if look.decoration == "line":
                lines[-1].gap_after = 0.9
            lines.append(LineSpec(sub, look.chapter_sub_font, look.text_color, gap_after=0))
        layout, deco = "center", ("line" if look.decoration == "line" else "none")
    a = anim or look.chapter_anim
    return {
        "kind": "chapter", "lines": [l.__dict__ for l in lines], "start": start, "end": end,
        "anim": a, "layout": layout, "decoration": deco,
        "in_dur": 1.6 if a == "tracking_in" else 1.1, "out_dur": 0.7,
        "scrim": 0.38, "letterbox": look.letterbox,
    }


def caption_card(look: Look, text: str, start: float, end: float, width: int, height: int,
                 anim: Optional[str] = None, font_family: Optional[str] = None) -> dict:
    cf = _with_family(look.caption_font, font_family)
    k = height / 1080
    font = get_font(cf.family, cf.weight, max(int(cf.size * k), 8))
    max_w = width * (0.62 if look.caption_layout != "bottom" else 0.78)
    wrapped = wrap_text(text.upper() if cf.upper else text, font, cf.tracking * font.size, max_w)
    lines = [LineSpec(t, cf, look.text_color, gap_after=0.22) for t in wrapped]
    lines[-1].gap_after = 0
    layout = look.caption_layout
    deco = "plate" if layout == "plate" else ("bar" if layout == "lower_third" else "none")
    a = anim or look.caption_anim
    return {
        "kind": "caption", "lines": [l.__dict__ for l in lines], "start": start, "end": end,
        "anim": a, "layout": layout, "decoration": deco, "in_dur": 0.9, "out_dur": 0.6,
        "scrim": 0.0 if layout == "plate" else 0.4, "letterbox": look.letterbox,
    }


def end_card(look: Look, text: str, sub: str, start: float, end: float,
             anim: Optional[str] = None, font_family: Optional[str] = None) -> dict:
    card = title_card(look, text, sub, "", start, end, anim, font_family)
    card["kind"] = "end"
    card["out_dur"] = min(1.6, (end - start) * 0.35)
    for l in card["lines"]:
        if l["role"] == "text" and l["font"] == _with_family(look.title_font, font_family):
            l["font"] = FontSpec(**{**l["font"].__dict__, "size": l["font"].size * 0.8})
    return card


def overlay_from_dict(d: dict, look: Look, width: int, height: int) -> TextOverlay:
    d = dict(d)
    d["lines"] = [
        {**l, "font": l["font"] if isinstance(l["font"], FontSpec) else FontSpec(**l["font"]),
         "color": tuple(l["color"])}
        for l in d["lines"]
    ]
    return TextOverlay(d, look, width, height)


def serialisable(card: dict) -> dict:
    out = dict(card)
    out["lines"] = [{**l, "font": l["font"].__dict__ if isinstance(l["font"], FontSpec) else l["font"],
                     "color": list(l["color"])} for l in card["lines"]]
    return out
