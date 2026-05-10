# HTTP API 与统一 JSON

## 统一响应格式

所有以 `/api/` 开头的 JSON 接口（及登录拦截返回的 JSON）均采用同一结构：

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "人类可读说明",
  "data": {}
}
```

- **`success`**：`true` 表示业务成功；`false` 表示失败或“可预期的业务未达成”（见下文 HTTP 状态约定）。  
- **`code`**：机器可读短码，便于前端分支与日志（如 `ATTENDANCE_OK`、`NO_FACE`）。  
- **`message`**：面向用户或排错的说明文案。  
- **`data`**：载荷对象；无额外字段时为 `{}`。

辅助函数定义在根目录 **`api_json.py`**：

- `api_ok(data=..., message=..., code=...)` → HTTP **200**，`success: true`。  
- `api_err(code, message, http_status=400, data=...)` → 指定 **4xx/5xx**，`success: false`。  
- `api_result(success, code, message, data=..., http_status=200)` → 默认 **200**，用于“请求合法但业务未通过”的场景（如活体失败、未检测到人脸、库中无匹配），由 `success` 与 `code` 区分。

## HTTP 状态约定（摘要）

| 情况 | HTTP | success |
|------|------|---------|
| 成功 | 200 | true |
| 未登录 | 401 | false |
| 无教师权限 | 403 | false |
| 参数错误、解码失败等 | 400 / 413 等 | false |
| 服务器内部错误 | 500 | false |
| 活体未通过、无人脸、识别分数不足等业务结果 | **200** | **false**（使用 `api_result`） |

前端应**同时**检查 HTTP 状态与 `success`：非 2xx 时优先展示 `message`；2xx 且 `success: false` 时按 `code` 展示对应中文提示（项目内 `static/js/attendance.js` 已做映射示例）。

## 接口列表

以下均需**已登录**会话（Cookie）。未登录访问 `/api/*` 返回 401 统一 JSON。

### `GET /api/attendance/liveness-challenge`

返回随机活体动作说明。

**成功示例**（字段在 `data` 内）：

```json
{
  "success": true,
  "code": "LIVENESS_CHALLENGE_OK",
  "message": "已获取活体动作指令",
  "data": {
    "action": "blink",
    "prompt": "…"
  }
}
```

### `POST /api/attendance/capture`

**Content-Type**: `application/json`

**请求体**（摘要）：

```json
{
  "action": "blink",
  "frames": ["data:image/jpeg;base64,...", "..."]
}
```

- `action`：须与挑战接口一致，为 `blink` 或 `mouth`。  
- `frames`：多帧 base64 图片；具体数量与大小限制见 `app.py` 中 `MIN_LIVENESS_FRAMES`、`MAX_LIVENESS_*`、`MAX_UPLOAD_BYTES` 等常量。

**成功（写入考勤）**：`success: true`，`code` 如 `ATTENDANCE_OK`，业务字段在 `data`（含 `recognized`、`student_id`、`name`、`liveness_passed`、`similarity`、`dominant_emotion` 等）。

**业务未成功但 HTTP 200**（示例 `code`）：

| code | 含义 |
|------|------|
| `LIVENESS_FAILED` | 动作活体未通过 |
| `NO_FACE` | 未检测到人脸或无法提取有效特征（`ValueError` 文案在 `message`） |
| `FACE_NOT_RECOGNIZED` | 活体通过但相似度未达阈值或库中无匹配 |

**HTTP 4xx/5xx**（`api_err`）：如 `MISSING_FRAMES`、`BAD_ACTION`、`IDENTITY_MISMATCH`（学生代打卡）、`EMBEDDING_FAILED` 等，详见 `app.py` 中 `api_attendance_capture`。

### `GET /api/attendance/records`

查询考勤记录（支持查询参数筛选；学生角色仅能查本人）。

**成功**：`success: true`，`data` 内含 `count`、`rows`（行字典列表）。

### `POST /api/activity-group-photo`

**Content-Type**: `multipart/form-data`

**表单字段**：

- `activity_name`：活动名称（必填）。  
- `photo`：图片文件（扩展名限制见 `ALLOWED_PHOTO_EXT`，大小上限见 `MAX_GROUP_PHOTO_BYTES`）。

**权限**：教师；否则 403 统一 JSON。

**成功**：`success: true`，`code` 如 `GROUP_PHOTO_OK`，`data` 内含 `activity_name`、`photo_path`、`faces_detected`、`faces_recognized`、`embedding_failures`、`matched`、`time` 等。

**失败**：如 `MISSING_PHOTO`、`IMAGE_DECODE_FAILED`、`DATABASE_ERROR` 等，见 `api_activity_group_photo`。

## 前端解析参考

`static/js/api_utils.js` 提供：

- `readJsonSafe(response)`：先 `text()` 再 `JSON.parse`，区分非 JSON 与网络错误。  
- `unifiedMessage(body)`：读取标准 `message` 字段。  

考勤与合照页脚本在收到响应后，应以 **`body.success` 与 `body.data`** 为准，勿再使用历史字段名 `ok` / 顶层平铺的业务字段。
