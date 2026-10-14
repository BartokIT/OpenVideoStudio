"""Landmark-driven face morph.

Faces are located with the existing MediaPipe face detector, then the
FaceLandmarker (478-point mesh, assets/face_landmarker.task) runs on a crop
around the largest face — more robust than running it on the full frame
for the small faces typical of family/group photos.

The morph is the classic piecewise-affine one: Delaunay triangulation of
face mesh + a "halo" around the head + frame border points, both images
warped toward the interpolated shape and cross-dissolved. Warp maps are
rasterised at 1/4 resolution with a triangle-id buffer and fully vectorised
affine evaluation, then upsampled — seamless and fast enough per frame.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_ASSETS = Path(__file__).resolve().parents[2] / "assets"
LANDMARKER_PATH = _ASSETS / "face_landmarker.task"
DETECTOR_PATH = _ASSETS / "face_detector.tflite"

# MediaPipe face-mesh oval, clockwise from the forehead.
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LEFT_EYE_OUTER, RIGHT_EYE_OUTER = 33, 263

_detector = None
_landmarker = None


def available() -> bool:
    return LANDMARKER_PATH.exists()


def _get_detector():
    global _detector
    if _detector is None:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        opts = mp_vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(DETECTOR_PATH)),
            min_detection_confidence=0.45,
        )
        _detector = mp_vision.FaceDetector.create_from_options(opts)
    return _detector


def _get_landmarker():
    global _landmarker
    if _landmarker is None and available():
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(LANDMARKER_PATH)),
            num_faces=1, min_face_detection_confidence=0.3, min_face_presence_confidence=0.3,
        )
        _landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def _mp_image(rgb: np.ndarray):
    from mediapipe import Image as MPImage, ImageFormat
    return MPImage(image_format=ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


def detect_faces(rgb: np.ndarray, max_side: int = 1600) -> list[dict]:
    """Face boxes in rgb's pixel coordinates, largest first."""
    h, w = rgb.shape[:2]
    f = min(1.0, max_side / max(h, w))
    small = cv2.resize(rgb, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA) if f < 1 else rgb
    res = _get_detector().detect(_mp_image(small))
    faces = []
    for det in res.detections:
        bb = det.bounding_box
        faces.append({
            "x": bb.origin_x / f, "y": bb.origin_y / f, "w": bb.width / f, "h": bb.height / f,
            "score": float(det.categories[0].score) if det.categories else 0.0,
        })
    faces.sort(key=lambda b: b["w"] * b["h"], reverse=True)
    return faces


def detect_landmarks(rgb: np.ndarray, face: Optional[dict] = None) -> Optional[np.ndarray]:
    """(478, 2) float32 landmark array in rgb's pixel coords, or None."""
    lm = _get_landmarker()
    if lm is None:
        return None
    h, w = rgb.shape[:2]
    if face is None:
        faces = detect_faces(rgb)
        if not faces:
            return None
        face = faces[0]
    cx, cy = face["x"] + face["w"] / 2, face["y"] + face["h"] / 2
    side = max(face["w"], face["h"]) * 2.4
    x0, y0 = int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0))
    x1, y1 = int(min(cx + side / 2, w)), int(min(cy + side / 2, h))
    crop = rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    scale = 1.0
    if max(crop.shape[:2]) < 384:  # landmarker wants a reasonably sized face
        scale = 384 / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    res = lm.detect(_mp_image(crop))
    if not res.face_landmarks:
        return None
    ch, cw = crop.shape[:2]
    pts = np.array([[p.x * cw / scale + x0, p.y * ch / scale + y0] for p in res.face_landmarks[0]], np.float32)
    return pts


def eye_distance(pts: np.ndarray) -> float:
    return float(np.linalg.norm(pts[LEFT_EYE_OUTER] - pts[RIGHT_EYE_OUTER]))


def face_center(pts: np.ndarray) -> np.ndarray:
    return pts[FACE_OVAL].mean(axis=0)


# ------------------------------------------------------------------ morph

def _control_points(pts: np.ndarray, w: int, h: int) -> np.ndarray:
    """Face mesh + two halo rings (hair/neck move with the face) + border."""
    oval = pts[FACE_OVAL]
    c = oval.mean(axis=0)
    halo1 = c + (oval - c) * 1.35
    halo2 = c + (oval - c) * 1.8
    border = np.array([[0, 0], [w / 2, 0], [w - 1, 0], [w - 1, h / 2], [w - 1, h - 1],
                       [w / 2, h - 1], [0, h - 1], [0, h / 2],
                       [w / 4, 0], [3 * w / 4, 0], [w / 4, h - 1], [3 * w / 4, h - 1],
                       [0, h / 4], [0, 3 * h / 4], [w - 1, h / 4], [w - 1, 3 * h / 4]], np.float32)
    return np.vstack([pts[:468], halo1, halo2, border]).astype(np.float32)


def _grid(w: int, h: int, f: int = 8) -> tuple[np.ndarray, int, int]:
    sw, sh = max(w // f, 2), max(h // f, 2)
    # small-pixel centres expressed in full-res coords, matching cv2.resize
    xs = (np.arange(sw, dtype=np.float32) + 0.5) * (w / sw) - 0.5
    ys = (np.arange(sh, dtype=np.float32) + 0.5) * (h / sh) - 0.5
    gx, gy = np.meshgrid(xs, ys)
    return np.stack([gx.ravel(), gy.ravel()], axis=1), sw, sh


def _warp_maps(pts_m: np.ndarray, pts_src: np.ndarray, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Thin-plate-spline backward map (output pixel -> source pixel).
    Smooth everywhere, so unlike a piecewise-affine mesh it can't tear or
    fold when the two faces differ a lot in pose."""
    from scipy.interpolate import RBFInterpolator
    grid, sw, sh = _grid(w, h)
    rbf = RBFInterpolator(pts_m.astype(np.float64), (pts_src - pts_m).astype(np.float64),
                          kernel="thin_plate_spline", smoothing=2.0, degree=1)
    disp = rbf(grid).astype(np.float32).reshape(sh, sw, 2)
    dx = cv2.resize(disp[..., 0], (w, h), interpolation=cv2.INTER_CUBIC)
    dy = cv2.resize(disp[..., 1], (w, h), interpolation=cv2.INTER_CUBIC)
    base_x, base_y = _base(w, h)
    return base_x + dx, base_y + dy


_BASE: dict = {}


def _base(w: int, h: int):
    if (w, h) not in _BASE:
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        _BASE[(w, h)] = (gx, gy)
    return _BASE[(w, h)]


def _subset(ctrl: np.ndarray) -> np.ndarray:
    # every 3rd mesh point + the full oval keeps the spline well conditioned
    keep = sorted(set(range(0, 468, 3)) | set(FACE_OVAL) | {LEFT_EYE_OUTER, RIGHT_EYE_OUTER, 1, 13, 14, 61, 291})
    return np.vstack([ctrl[keep], ctrl[468:]])


def morph(a: np.ndarray, b: np.ndarray, pts_a: np.ndarray, pts_b: np.ndarray, p: float, ctx: dict) -> np.ndarray:
    h, w = a.shape[:2]
    ca = _subset(_control_points(np.asarray(pts_a, np.float32), w, h))
    cb = _subset(_control_points(np.asarray(pts_b, np.float32), w, h))
    if ctx.get("extra_a") is not None and ctx.get("extra_b") is not None:
        ca = np.vstack([ca, ctx["extra_a"]])
        cb = np.vstack([cb, ctx["extra_b"]])

    # shape moves on a smooth curve; colour dissolve is concentrated in the
    # middle so each face stays crisp at its end of the transition
    sp = p * p * (3 - 2 * p)
    cp = np.clip((p - 0.2) / 0.6, 0, 1)
    cp = cp * cp * (3 - 2 * cp)
    cm = (1 - sp) * ca + sp * cb

    mxa, mya = _warp_maps(cm, ca, w, h)
    mxb, myb = _warp_maps(cm, cb, w, h)
    wa = cv2.remap(a, mxa, mya, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    wb = cv2.remap(b, mxb, myb, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.addWeighted(wa, 1 - cp, wb, cp, 0)
