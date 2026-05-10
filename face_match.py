"""与人脸库比对：余弦相似度（特征已 L2 归一化时等价于点积）。"""
from __future__ import annotations

import os

import numpy as np


def find_best_student_match(db, query_embedding: bytes) -> tuple[str | None, str | None, float]:
    """
    在 students.face_embedding 中查找与 query 维度一致且相似度最高的记录。
    若最高分低于环境变量 FACE_MATCH_THRESHOLD（默认 0.52），返回 (None, None, best_score)。
    """
    if not query_embedding:
        return None, None, -1.0
    q = np.frombuffer(query_embedding, dtype=np.float32)
    if q.size == 0:
        return None, None, -1.0
    qn = q.nbytes
    rows = db.execute(
        "SELECT student_id, name, face_embedding FROM students "
        "WHERE face_embedding IS NOT NULL"
    ).fetchall()
    best_sim = -1.0
    best_sid: str | None = None
    best_name: str | None = None
    for row in rows:
        blob = row["face_embedding"]
        if not blob or len(blob) != qn:
            continue
        v = np.frombuffer(blob, dtype=np.float32)
        sim = float(np.dot(q, v))
        if sim > best_sim:
            best_sim = sim
            best_sid = row["student_id"]
            best_name = row["name"]
    thr = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.52"))
    if best_sid is not None and best_sim >= thr:
        return best_sid, best_name, best_sim
    return None, None, best_sim


def find_best_student_match_excluding(
    db,
    query_embedding: bytes,
    exclude: set[str],
) -> tuple[str | None, str | None, float]:
    """
    在库中查找与 query 最相似且 student_id 不在 exclude 集合中的学生。
    阈值优先 GROUP_FACE_THRESHOLD，否则 FACE_MATCH_THRESHOLD（默认 0.52）。
    """
    if not query_embedding:
        return None, None, -1.0
    q = np.frombuffer(query_embedding, dtype=np.float32)
    if q.size == 0:
        return None, None, -1.0
    qn = q.nbytes
    rows = db.execute(
        "SELECT student_id, name, face_embedding FROM students "
        "WHERE face_embedding IS NOT NULL"
    ).fetchall()
    best_sim = -1.0
    best_sid: str | None = None
    best_name: str | None = None
    for row in rows:
        sid = row["student_id"]
        if sid in exclude:
            continue
        blob = row["face_embedding"]
        if not blob or len(blob) != qn:
            continue
        v = np.frombuffer(blob, dtype=np.float32)
        sim = float(np.dot(q, v))
        if sim > best_sim:
            best_sim = sim
            best_sid = sid
            best_name = row["name"]
    thr = float(
        os.environ.get(
            "GROUP_FACE_THRESHOLD",
            os.environ.get("FACE_MATCH_THRESHOLD", "0.52"),
        )
    )
    if best_sid is not None and best_sim >= thr:
        return best_sid, best_name, best_sim
    return None, None, best_sim
