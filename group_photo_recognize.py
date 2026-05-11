"""
班级合照：检测多个人脸并返回 BGR 裁剪图（按画面中从左到右排序）。
优先 DeepFace.extract_faces（多后端取检出人数最多者），失败则 OpenCV Haar 多脸检测。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

_MIN_FACE_SIDE = 40
_MAX_FACES_DEFAULT = 50


def _normalize_face_rgb(face: np.ndarray) -> np.ndarray:
    f = np.asarray(face)
    if f.dtype == np.float32 or f.dtype == np.float64:
        if f.max() <= 1.0 + 1e-6:
            f = (np.clip(f, 0, 1) * 255).astype(np.uint8)
        else:
            f = np.clip(f, 0, 255).astype(np.uint8)
    else:
        f = f.astype(np.uint8)
    if f.ndim == 2:
        f = cv2.cvtColor(f, cv2.COLOR_GRAY2RGB)
    if f.shape[-1] == 4:
        f = f[:, :, :3]
    return f


def extract_group_face_crops_bgr(
    image_bgr: np.ndarray,
    max_faces: int = _MAX_FACES_DEFAULT,
) -> list[np.ndarray]:
    """
    从合照中提取人脸裁剪（BGR），按人脸框中心 x 从左到右排序。
    支持密集场景（默认最多处理 max_faces 张脸，满足 10+ 人合照）。
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    def _crops_from_deepface_items(items: list) -> list[tuple[float, np.ndarray]]:
        out: list[tuple[float, np.ndarray]] = []
        for it in items[:max_faces]:
            if isinstance(it, dict):
                face = it.get("face")
                area = it.get("facial_area") or {}
            else:
                face = it
                area = {}
            if face is None:
                continue
            frgb = _normalize_face_rgb(face)
            if min(frgb.shape[:2]) < _MIN_FACE_SIDE:
                continue
            fbgr = cv2.cvtColor(frgb, cv2.COLOR_RGB2BGR)
            cx = float(area.get("x", 0)) + float(area.get("w", 0)) * 0.5
            out.append((cx, fbgr))
        return out

    try:
        from deepface import DeepFace

        # 神经网络检测优先用 RGB；勿在 retinaface 刚检出少量脸就停止，否则合照易卡在「个位数人脸」
        # （DeepFace 的 RetinaFace 对 pip retina-face 使用 score 阈值 0.9，远景脸常被丢弃）。
        best: list[tuple[float, np.ndarray]] = []
        for img_in in (rgb, image_bgr):
            for backend in ("mtcnn", "opencv", "retinaface"):
                try:
                    items = DeepFace.extract_faces(
                        img_path=img_in,
                        detector_backend=backend,
                        enforce_detection=False,
                        align=True,
                    )
                except Exception:
                    continue
                if not items:
                    continue
                scored = _crops_from_deepface_items(items)
                if len(scored) > len(best):
                    best = scored
        if best:
            best.sort(key=lambda t: t[0])
            return [c for _, c in best]
    except ImportError:
        pass

    return _extract_faces_opencv_multiscale(image_bgr, max_faces)


def _extract_faces_opencv_multiscale(
    image_bgr: np.ndarray,
    max_faces: int,
) -> list[np.ndarray]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    cascade_path = str(
        Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    )
    cascade = cv2.CascadeClassifier(cascade_path)
    boxes = cascade.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=3,
        minSize=(32, 32),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    if len(boxes) == 0:
        return []
    h0, w0 = gray.shape[:2]
    scored: list[tuple[float, np.ndarray]] = []
    for (x, y, w, h) in boxes:
        if w < _MIN_FACE_SIDE or h < _MIN_FACE_SIDE:
            continue
        pad_x = int(w * 0.12)
        pad_y = int(h * 0.15)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(w0, x + w + pad_x)
        y2 = min(h0, y + h + pad_y)
        crop = image_bgr[y1:y2, x1:x2]
        if crop.size == 0 or min(crop.shape[:2]) < _MIN_FACE_SIDE:
            continue
        cx = x + w * 0.5
        scored.append((cx, crop))
    scored.sort(key=lambda t: t[0])
    return [c for _, c in scored[:max_faces]]
