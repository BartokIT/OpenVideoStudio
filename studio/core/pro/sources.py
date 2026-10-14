"""Shot sources.

Photos are prepared once into a graded "canvas" (output aspect, 1.25x the
output resolution for Ken Burns headroom) and then moved with a sub-pixel
affine camera every frame. Photos whose aspect differs a lot from the
output (portrait scans, square prints) are not brutally cropped: they sit
over a blurred, darkened copy of themselves, optionally with a drop shadow
or an instant-photo border — the "professional slideshow" treatment.

Video shots are decoded by an FFmpeg pipe with the look's colour grade
baked into a 3D LUT, so videos match the graded photos.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

from .looks import Grade, Look, apply_grade

CANVAS_SCALE = 1.25


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return np.asarray(im.convert("RGB"))


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    interp = cv2.INTER_AREA if (w < iw or h < ih) else cv2.INTER_CUBIC
    return cv2.resize(img, (w, h), interpolation=interp)


def _union(faces: list[dict], min_frac: float = 0.25) -> Optional[tuple]:
    if not faces:
        return None
    big = faces[0]["w"] * faces[0]["h"]
    keep = [f for f in faces if f["w"] * f["h"] >= big * min_frac]
    x0 = min(f["x"] for f in keep)
    y0 = min(f["y"] for f in keep)
    x1 = max(f["x"] + f["w"] for f in keep)
    y1 = max(f["y"] + f["h"] for f in keep)
    return x0, y0, x1, y1


def prepare_photo(src: str, out_jpg: str, width: int, height: int, look_key: str,
                  fit: str = "auto", index: int = 0) -> dict:
    """Builds the graded canvas for one photo and returns its metadata
    (canvas path/size, mode, face boxes and landmarks in canvas coords)."""
    from . import facemorph
    from .looks import get_look

    look = get_look(look_key)
    img = _load_rgb(Path(src))
    ih, iw = img.shape[:2]
    target = width / height
    ratio = iw / ih
    CW, CH = int(round(width * CANVAS_SCALE / 2)) * 2, int(round(height * CANVAS_SCALE / 2)) * 2

    faces = []
    try:
        faces = facemorph.detect_faces(img)
    except Exception:
        faces = []

    mode = fit
    frame_pts = None
    if fit == "auto":
        mode = "crop" if abs(math.log(ratio / target)) < 0.30 else "fit"

    if mode == "crop":
        if ratio > target:
            cw, ch = ih * target, ih
        else:
            cw, ch = iw, iw / target
        u = _union(faces)
        if u:
            fx = (u[0] + u[2]) / 2
            fy = (u[1] + u[3]) / 2
            # rule of thirds: faces a little above centre
            left = min(max(fx - cw / 2, 0), iw - cw)
            top = min(max(fy - ch * 0.42, 0), ih - ch)
        else:
            left, top = (iw - cw) / 2, (ih - ch) / 2
        x0, y0 = int(round(left)), int(round(top))
        crop = img[y0:y0 + int(round(ch)), x0:x0 + int(round(cw))]
        canvas = _resize(crop, CW, CH)
        s = CW / crop.shape[1]
        to_canvas = lambda x, y: ((x - x0) * s, (y - y0) * s)
    else:
        # blurred background fill
        if ratio > target:
            bw, bh = ih * target, ih
        else:
            bw, bh = iw, iw / target
        bx, by = (iw - bw) / 2, (ih - bh) / 2
        bg = img[int(by):int(by + bh), int(bx):int(bx + bw)]
        bg = cv2.resize(bg, (CW // 10, CH // 10), interpolation=cv2.INTER_AREA)
        bg = cv2.GaussianBlur(bg, (0, 0), 4)
        bg = cv2.resize(bg, (CW, CH), interpolation=cv2.INTER_CUBIC)
        bg = cv2.convertScaleAbs(bg, alpha=0.55, beta=0)

        frame = look.photo_frame
        max_h = CH * (0.80 if frame == "polaroid" else 0.86)
        max_w = CW * 0.86
        s = min(max_h / ih, max_w / iw)
        fw, fh = int(iw * s), int(ih * s)
        fg = _resize(img, fw, fh)
        canvas = bg.copy()
        angle = 0.0
        if frame == "polaroid":
            border = int(fh * 0.045)
            bottom = int(fh * 0.16)
            paper = np.full((fh + border + bottom, fw + 2 * border, 3), (246, 243, 236), np.uint8)
            paper[border:border + fh, border:border + fw] = fg
            fg_full, off = paper, (border, border)
            angle = [-2.2, 1.6, -1.1, 2.4, -1.8, 0.9][index % 6]
        else:
            fg_full, off = fg, (0, 0)
        ph, pw = fg_full.shape[:2]
        px, py = (CW - pw) // 2, (CH - ph) // 2 - (int(CH * 0.01) if frame == "polaroid" else 0)

        if frame in ("shadow", "polaroid"):
            sh = np.zeros((CH, CW), np.float32)
            so = int(CH * 0.012)
            sh[py + so:py + so + ph, px + so:px + so + pw] = 1.0
            sh = cv2.GaussianBlur(sh, (0, 0), CH * 0.018) * 0.75
            canvas = (canvas.astype(np.float32) * (1 - sh[..., None])).astype(np.uint8)

        layer = np.zeros((CH, CW, 3), np.uint8)
        mask = np.zeros((CH, CW), np.float32)
        layer[py:py + ph, px:px + pw] = fg_full
        mask[py:py + ph, px:px + pw] = 1.0
        if angle:
            m = cv2.getRotationMatrix2D((CW / 2, CH / 2), angle, 1.0)
            layer = cv2.warpAffine(layer, m, (CW, CH), flags=cv2.INTER_CUBIC)
            mask = cv2.warpAffine(mask, m, (CW, CH), flags=cv2.INTER_LINEAR)
        else:
            m = None
        m3 = mask[..., None]
        canvas = (canvas.astype(np.float32) * (1 - m3) + layer.astype(np.float32) * m3).astype(np.uint8)
        # print outline (corners + edge midpoints): morph anchors so the
        # photo's edges glide between frames instead of bending
        rect = np.array([[px, py], [px + pw / 2, py], [px + pw, py], [px + pw, py + ph / 2], [px + pw, py + ph],
                         [px + pw / 2, py + ph], [px, py + ph], [px, py + ph / 2]], np.float32)
        if m is not None:
            rect = rect @ m[:, :2].T.astype(np.float32) + m[:, 2].astype(np.float32)
        frame_pts = rect.round(2).tolist()

        def to_canvas(x, y, s=s, off=off, px=px, py=py, m=m):
            cx, cy = x * s + off[0] + px, y * s + off[1] + py
            if m is not None:
                cx, cy = m[0, 0] * cx + m[0, 1] * cy + m[0, 2], m[1, 0] * cx + m[1, 1] * cy + m[1, 2]
            return cx, cy

    canvas_faces = []
    for f in faces:
        x0c, y0c = to_canvas(f["x"], f["y"])
        x1c, y1c = to_canvas(f["x"] + f["w"], f["y"] + f["h"])
        if x1c < 0 or y1c < 0 or x0c > CW or y0c > CH:
            continue
        canvas_faces.append({"x": float(x0c), "y": float(y0c), "w": float(x1c - x0c), "h": float(y1c - y0c),
                             "score": f["score"]})

    landmarks = None
    if canvas_faces and facemorph.available():
        try:
            pts = facemorph.detect_landmarks(canvas, canvas_faces[0])
            if pts is not None:
                landmarks = pts.round(2).tolist()
        except Exception:
            landmarks = None

    canvas = apply_grade(canvas, look.grade)
    Path(out_jpg).parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 97])
    Path(out_jpg).write_bytes(buf.tobytes())

    return {
        "canvas": str(out_jpg), "canvas_w": CW, "canvas_h": CH, "mode": mode,
        "faces": canvas_faces, "landmarks": landmarks, "src_w": iw, "src_h": ih, "frame_pts": frame_pts,
    }


# ----------------------------------------------------------- photo camera

def camera_matrix(cam: dict, u: float, width: int, canvas_w: int, canvas_h: int, height: int) -> np.ndarray:
    """Affine canvas->output for motion progress u in [0,1]."""
    # gentle ease: mostly linear so motion never visibly stops under a transition
    e = 0.65 * u + 0.35 * (u * u * (3 - 2 * u))
    z = cam["z0"] * (cam["z1"] / cam["z0"]) ** e
    cx = cam["cx0"] + (cam["cx1"] - cam["cx0"]) * e
    cy = cam["cy0"] + (cam["cy1"] - cam["cy0"]) * e
    half_w = canvas_w / z / 2
    half_h = canvas_h / z / 2
    cx = min(max(cx, half_w), canvas_w - half_w)
    cy = min(max(cy, half_h), canvas_h - half_h)
    s = width * z / canvas_w
    return np.float32([[s, 0, width / 2 - cx * s], [0, s, height / 2 - cy * s]])


class PhotoSource:
    def __init__(self, shot: dict, width: int, height: int):
        self.shot = shot
        self.W, self.H = width, height
        self.meta = shot["photo"]
        self._canvas = None
        self._lm = np.asarray(self.meta["landmarks"], np.float32) if self.meta.get("landmarks") else None

    def canvas(self) -> np.ndarray:
        if self._canvas is None:
            data = np.fromfile(self.meta["canvas"], dtype=np.uint8)
            self._canvas = cv2.cvtColor(cv2.imdecode(data, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        return self._canvas

    def _u(self, t: float) -> float:
        a, b = self.shot["vis_start"], self.shot["vis_end"]
        return min(max((t - a) / max(b - a, 1e-3), 0.0), 1.0)

    def matrix(self, t: float) -> np.ndarray:
        return camera_matrix(self.shot["camera"], self._u(t), self.W, self.meta["canvas_w"], self.meta["canvas_h"], self.H)

    def frame(self, t: float) -> np.ndarray:
        return cv2.warpAffine(self.canvas(), self.matrix(t), (self.W, self.H), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REFLECT)

    def landmarks(self, t: float) -> Optional[np.ndarray]:
        if self._lm is None:
            return None
        m = self.matrix(t)
        return self._lm @ m[:, :2].T + m[:, 2]

    def frame_points(self, t: float) -> Optional[np.ndarray]:
        if not self.meta.get("frame_pts"):
            return None
        m = self.matrix(t)
        return np.asarray(self.meta["frame_pts"], np.float32) @ m[:, :2].T + m[:, 2]

    def focus(self, t: float) -> tuple:
        faces = self.meta.get("faces") or []
        m = self.matrix(t)
        if faces:
            f = faces[0]
            x, y = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
        else:
            x, y = self.meta["canvas_w"] / 2, self.meta["canvas_h"] / 2
        return (float(m[0, 0] * x + m[0, 2]), float(m[1, 1] * y + m[1, 2]))

    def close(self):
        self._canvas = None


# ------------------------------------------------------------------ video

def write_cube_lut(grade: Grade, path: Path, size: int = 33) -> Optional[Path]:
    if grade == Grade():
        return None
    r = np.linspace(0, 255, size, dtype=np.float32)
    # .cube order: red varies fastest
    b, g, rr = np.meshgrid(r, r, r, indexing="ij")
    lattice = np.stack([rr, g, b], axis=-1).reshape(1, -1, 3)
    graded = apply_grade(np.clip(lattice + 0.5, 0, 255).astype(np.uint8), grade).reshape(-1, 3) / 255.0
    lines = [f"LUT_3D_SIZE {size}"] + [f"{c[0]:.5f} {c[1]:.5f} {c[2]:.5f}" for c in graded]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def _ff_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:")


class VideoSource:
    def __init__(self, shot: dict, width: int, height: int, fps: int):
        self.shot = shot
        self.W, self.H, self.fps = width, height, fps
        self.proc = None
        self.next_index = 0
        self.last = None
        self.eof = False

    def _vf(self) -> str:
        W, H = self.W, self.H
        meta = self.shot["video"]
        vw, vh = meta.get("w") or W, meta.get("h") or H
        lut = self.shot.get("lut")
        tail = f",lut3d=file='{_ff_path(Path(lut))}'" if lut else ""
        if vw and vh and abs(math.log((vw / vh) / (W / H))) < 0.30:
            return (f"fps={self.fps},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                    f"crop={W}:{H},setsar=1{tail},format=rgb24")
        sw, sh = W // 10, H // 10
        fw, fh = int(W * 0.94) // 2 * 2, int(H * 0.94) // 2 * 2
        return (f"fps={self.fps},split[a][b];"
                f"[a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},gblur=sigma=4,"
                f"scale={W}:{H}:flags=bicubic,eq=brightness=-0.18:saturation=0.9[bg];"
                f"[b]scale={fw}:{fh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{tail},format=rgb24")

    def _open(self, start_index: int) -> None:
        self.close()
        offset = start_index / self.fps
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{offset:.3f}", "-i", self.shot["asset_path"],
               "-an", "-vf", self._vf(), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.W * self.H * 3 * 2)
        self.next_index = start_index
        self.eof = False

    def _read(self) -> Optional[np.ndarray]:
        n = self.W * self.H * 3
        buf = self.proc.stdout.read(n)
        if len(buf) < n:
            self.eof = True
            return None
        self.next_index += 1
        return np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3).copy()

    def frame(self, t: float) -> np.ndarray:
        local = max(t - self.shot["vis_start"], 0.0)
        idx = int(round(local * self.fps))
        if self.proc is None or idx < self.next_index - 1 or idx > self.next_index + self.fps * 2:
            self._open(idx)
        while not self.eof and self.next_index <= idx:
            f = self._read()
            if f is not None:
                self.last = f
        if self.last is None:
            return np.zeros((self.H, self.W, 3), np.uint8)
        return self.last.copy()  # callers draw on frames in place

    def landmarks(self, t: float):
        return None

    def focus(self, t: float) -> tuple:
        return (self.W / 2, self.H / 2)

    def close(self):
        if self.proc is not None:
            try:
                self.proc.stdout.close()
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None


def probe_video(path: str) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:stream_side_data=rotation:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    w, h = v.get("width"), v.get("height")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if rot in (90, -90, 270, -270) and w and h:
        w, h = h, w
    try:
        dur = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        dur = 0.0
    return {"w": w, "h": h, "duration": dur, "has_audio": any(s.get("codec_type") == "audio" for s in streams)}
