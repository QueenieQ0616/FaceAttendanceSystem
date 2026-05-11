"""
动作活体检测：使用 MediaPipe FaceLandmarker (新版 Task API)
支持自动下载模型文件或使用本地模型。
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

# ------------------------- 模型准备 -------------------------
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_PATH = Path(__file__).resolve().parent / "face_landmarker.task"

def _ensure_model() -> Path:
    """如果本地没有模型文件，则自动下载。"""
    if not MODEL_PATH.exists():
        print("正在下载 MediaPipe 人脸关键点模型（约 10MB）...")
        try:
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            print("模型下载完成。")
        except Exception as e:
            raise RuntimeError(f"无法下载活体检测模型，请手动下载至 {MODEL_PATH}") from e
    return MODEL_PATH

# 导入 mediapipe
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core import base_options as mp_base_options
from mediapipe import Image, ImageFormat

# ------------------------- 辅助函数 -------------------------
_LEFT_EYE = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)
_MOUTH_VERT = (82, 87)
_MOUTH_HORZ = (78, 308)


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _eye_aspect_ratio(landmarks, idxs: tuple[int, ...]) -> float:
    p = [np.array([landmarks[i].x, landmarks[i].y], dtype=np.float64) for i in idxs]
    v1 = _dist(p[1], p[5])
    v2 = _dist(p[2], p[4])
    h = _dist(p[0], p[3]) + 1e-8
    return (v1 + v2) / (2.0 * h)


def _mouth_aspect_ratio(landmarks) -> float:
    p82 = np.array([landmarks[82].x, landmarks[82].y], dtype=np.float64)
    p87 = np.array([landmarks[87].x, landmarks[87].y], dtype=np.float64)
    p78 = np.array([landmarks[78].x, landmarks[78].y], dtype=np.float64)
    p308 = np.array([landmarks[308].x, landmarks[308].y], dtype=np.float64)
    vert = _dist(p82, p87)
    horz = _dist(p78, p308) + 1e-8
    return vert / horz


def _resize_long_side(img: np.ndarray, max_side: int = 480) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    s = max_side / float(m)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _count_blinks(ears: list[float | None]) -> int:
    open_th = float(os.environ.get("LIVENESS_EAR_OPEN", "0.26"))
    closed_th = float(os.environ.get("LIVENESS_EAR_CLOSED", "0.19"))
    vals = [e for e in ears if e is not None]
    if len(vals) < 4:
        return 0
    state = "open" if vals[0] > closed_th else "closed"
    blinks = 0
    for e in vals:
        if e is None:
            continue
        if state == "open" and e < closed_th:
            state = "closed"
        elif state == "closed" and e > open_th:
            blinks += 1
            state = "open"
    return blinks


# ------------------------- 活体检测主函数 -------------------------
def evaluate_action_liveness(
    frames_bgr: list[np.ndarray],
    action: str,
) -> tuple[bool, str, list[float | None], list[float | None]]:
    """
    分析连续帧是否完成指定动作。
    """
    action = (action or "").strip().lower()
    if action not in ("blink", "mouth"):
        return False, f"不支持的动作类型：{action}", [], []

    # 确保模型文件存在
    model_path = _ensure_model()

    # 创建检测器（图像模式）
    base_options = mp_base_options.BaseOptions(model_asset_path=str(model_path))
    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        num_faces=1,
        running_mode=vision.RunningMode.IMAGE,
        min_face_detection_confidence=0.45,
        min_tracking_confidence=0.45,
    )

    detector = vision.FaceLandmarker.create_from_options(options)
    ears: list[float | None] = []
    mars: list[float | None] = []

    for img_bgr in frames_bgr:
        small = _resize_long_side(img_bgr, 480)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        mp_image = Image(image_format=ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)

        if not result.face_landmarks:
            ears.append(None)
            mars.append(None)
            continue

        landmarks = result.face_landmarks[0]
        le = _eye_aspect_ratio(landmarks, _LEFT_EYE)
        re = _eye_aspect_ratio(landmarks, _RIGHT_EYE)
        ears.append(float((le + re) / 2.0))
        mars.append(_mouth_aspect_ratio(landmarks))

    detector.close()

    valid_ear = sum(1 for e in ears if e is not None)
    valid_mar = sum(1 for m in mars if m is not None)
    min_face_frames = max(4, int(len(frames_bgr) * 0.35))
    if valid_ear < min_face_frames:
        return (
            False,
            f"有效人脸帧过少（{valid_ear}/{len(frames_bgr)}），请正对摄像头并重试。",
            ears,
            mars,
        )

    if action == "blink":
        need = int(os.environ.get("LIVENESS_BLINK_MIN", "2"))
        n = _count_blinks(ears)
        if n >= need:
            return True, f"眨眼动作通过（检测到 {n} 次有效眨眼，要求≥{need}）。", ears, mars
        return (
            False,
            f"未检测到活体。",
            ears,
            mars,
        )

    # mouth
    open_th = float(os.environ.get("LIVENESS_MAR_OPEN", "0.32"))
    sustain = int(os.environ.get("LIVENESS_MAR_SUSTAIN_FRAMES", "3"))
    best_run = 0
    cur = 0
    for m in mars:
        if m is not None and m >= open_th:
            cur += 1
            if cur > best_run:
                best_run = cur
        else:
            cur = 0
    mx = max((m for m in mars if m is not None), default=0.0)
    if best_run >= sustain:
        return (
            True,
            f"张嘴动作通过（MAR≥{open_th} 的连续帧 {best_run}，最大 MAR≈{mx:.3f}）。",
            ears,
            mars,
        )
    return (
        False,
        f"未检测到活体。",
        ears,
        mars,
    )


def pick_best_frame_for_face(
    frames_bgr: Iterable[np.ndarray],
) -> np.ndarray | None:
    frames = list(frames_bgr)
    if not frames:
        return None
    return max(frames, key=lambda im: im.shape[0] * im.shape[1])