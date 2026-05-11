"""
人脸特征提取：优先 DeepFace（Facenet），失败或未安装时回退到 OpenCV Haar 人脸区域向量。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def _read_image_bgr(path: str | Path) -> np.ndarray:
    p = Path(path)
    data = np.fromfile(str(p), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片，请确认格式为 JPG/PNG/WebP")
    return img


def _embedding_from_bgr(img: np.ndarray) -> tuple[bytes, str]:
    """从 BGR ndarray 提取与文件路径版本一致的人脸特征。"""
    deepface_error: Exception | None = None
    try:
        from deepface import DeepFace

        reps = DeepFace.represent(
            img_path=img,
            model_name="Facenet512",
            enforce_detection=True,
            detector_backend="opencv",
        )
        if isinstance(reps, dict):
            reps = [reps]
        if not reps:
            raise ValueError("未检测到人脸")
        emb = reps[0]["embedding"]
        arr = np.asarray(emb, dtype=np.float32).ravel()
        arr = arr / (float(np.linalg.norm(arr)) + 1e-8)
        return arr.tobytes(), "deepface-facenet"
    except ImportError:
        pass
    except Exception as e:
        deepface_error = e

    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade_path = str(
            Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        )
        cascade = cv2.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(64, 64))
        if len(faces) == 0:
            raise ValueError("未检测到人脸（OpenCV 备用方案）")
        x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
        roi = gray[y : y + h, x : x + w]
        roi = cv2.resize(roi, (128, 128))
        vec = roi.astype(np.float32).ravel() / 255.0
        n = float(np.linalg.norm(vec)) + 1e-8
        vec = vec / n
        return vec.tobytes(), "opencv-haar"
    except Exception as e2:
        if deepface_error is not None:
            raise ValueError(
                "人脸特征提取失败（DeepFace 与 OpenCV 均未成功）。"
                f" DeepFace: {deepface_error!s}；OpenCV: {e2!s}"
            ) from e2
        raise ValueError(f"人脸特征提取失败：{e2!s}") from e2


def extract_face_embedding_bytes(path: str | Path) -> tuple[bytes, str]:
    """
    返回 (float32 二进制特征, 方法标记)。
    DeepFace 不可用时使用 OpenCV 备用特征（维度与 Facenet 不同，仅作同管线内弱匹配参考）。
    """
    img = _read_image_bgr(Path(path))
    return _embedding_from_bgr(img)


def extract_face_embedding_from_jpeg_bytes(image_bytes: bytes) -> tuple[bytes, str]:
    """解码 JPEG/PNG 二进制（如摄像头上传的 base64 解码结果）并提取特征。"""
    nparr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片数据")
    return extract_face_embedding_from_bgr(img)


def extract_face_embedding_from_bgr(img: np.ndarray) -> tuple[bytes, str]:
    """从已解码的 BGR 图像提取特征（便于与情绪分析共用同一帧）。"""
    return _embedding_from_bgr(img)


def extract_face_embedding_from_crop_bgr(img: np.ndarray) -> tuple[bytes, str]:
    """
    对已裁剪的人脸小图提特征（合照场景）。
    优先 DeepFace Facenet + detector_backend=skip；失败再尝试 opencv 检测；最后回退整图 Haar 流程。
    """
    if img is None or img.size == 0:
        raise ValueError("无效人脸图块")
    h, w = img.shape[:2]
    if min(h, w) < 40:
        raise ValueError("人脸区域过小")
    try:
        from deepface import DeepFace

        # 必须与 _embedding_from_bgr / 学生入库使用的 Facenet512 维度一致，否则合照比对会全部被跳过。
        for det, enf in (("skip", False), ("opencv", True)):
            try:
                reps = DeepFace.represent(
                    img_path=img,
                    model_name="Facenet512",
                    enforce_detection=enf,
                    detector_backend=det,
                )
                if isinstance(reps, dict):
                    reps = [reps]
                if not reps:
                    continue
                emb = reps[0]["embedding"]
                arr = np.asarray(emb, dtype=np.float32).ravel()
                arr = arr / (float(np.linalg.norm(arr)) + 1e-8)
                return arr.tobytes(), "deepface-facenet512"
            except Exception:
                continue
    except ImportError:
        pass
    return _embedding_from_bgr(img)


def analyze_dominant_emotion_bgr(img: np.ndarray) -> str:
    """
    使用 DeepFace.analyze(actions=['emotion']) 提取 dominant_emotion（小写英文）。
    无法分析时返回 \"unknown\"（便于写入非空情绪字段）。
    """
    try:
        from deepface import DeepFace

        out = DeepFace.analyze(
            img_path=img,
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="opencv",
        )
        if isinstance(out, list):
            if not out:
                return "unknown"
            out = out[0]
        if not isinstance(out, dict):
            return "unknown"
        dom = out.get("dominant_emotion")
        if isinstance(dom, str) and dom.strip():
            return dom.strip().lower()
        emo = out.get("emotion")
        if isinstance(emo, dict) and emo:
            top = max(emo, key=lambda k: float(emo[k]))
            return str(top).strip().lower()
    except Exception:
        return "unknown"
    return "unknown"


def try_primary_emotion_bgr(img: np.ndarray) -> str | None:
    """兼容旧调用：返回主导情绪字符串，unknown 时视为 None。"""
    v = analyze_dominant_emotion_bgr(img)
    return None if v == "unknown" else v
