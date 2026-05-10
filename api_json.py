"""统一 JSON API 响应格式：success / code / message / data。"""
from __future__ import annotations

from typing import Any, Mapping

from flask import jsonify


def api_ok(
    *,
    data: Mapping[str, Any] | None = None,
    message: str = "操作成功",
    code: str = "SUCCESS",
):
    return jsonify(
        {
            "success": True,
            "code": code,
            "message": message,
            "data": dict(data) if data is not None else {},
        }
    )


def api_err(
    code: str,
    message: str,
    *,
    http_status: int = 400,
    data: Mapping[str, Any] | None = None,
):
    return (
        jsonify(
            {
                "success": False,
                "code": code,
                "message": message,
                "data": dict(data) if data is not None else {},
            }
        ),
        http_status,
    )


def api_result(
    success: bool,
    code: str,
    message: str,
    *,
    data: Mapping[str, Any] | None = None,
    http_status: int = 200,
):
    """业务结果（如活体未通过、未检测到人脸）：默认 HTTP 200，由 success=false 与 code 区分。"""
    resp = jsonify(
        {
            "success": success,
            "code": code,
            "message": message,
            "data": dict(data) if data is not None else {},
        }
    )
    if http_status != 200:
        return resp, http_status
    return resp
