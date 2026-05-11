# 架构与模块说明

## 技术栈概览

| 层级 | 技术 |
|------|------|
| 后端 | Python 3、Flask、SQLite（`sqlite3`） |
| 前端 | Jinja2 模板、原生 HTML/CSS/JavaScript |
| 视觉 / 算法 | OpenCV、MediaPipe（活体）、DeepFace + TensorFlow（特征 / 情绪）、自研比对逻辑 |

## 目录结构（核心）

```
face_final_project/
├── app.py                 # Flask 应用工厂、路由、数据库初始化与业务编排
├── api_json.py            # 统一 API JSON：api_ok / api_err / api_result
├── face_embed.py          # 人脸特征提取、情绪分析等
├── face_match.py          # 与人脸库的余弦相似度比对（考勤 / 合照）
├── liveness_actions.py    # 多帧动作活体（与 MediaPipe 配合）
├── group_photo_recognize.py  # 合照多脸检测与裁剪
├── requirements.txt
├── database/              # SQLite 目录（运行后含 attendance.db）
├── uploads/
│   ├── students/          # 学生登记照
│   └── activities/      # 活动合照原图
├── templates/             # 页面模板（含 includes/site_nav.html）
├── static/
│   ├── css/style.css
│   └── js/                # attendance.js、activity_group.js、api_utils.js 等
└── doc/                   # 开发文档（本目录）
```

## 应用生命周期

1. **`create_app()`**（`app.py`）  
   注册配置、`teardown` 关闭数据库连接、`before_request` 登录校验等。

2. **`init_db()`**  
   确保 `database/`、`uploads/` 子目录存在；执行 `SCHEMA_SQL` 建表；种子教师账号、同步学生登录账号。

3. **`get_db()`**  
   按请求在 `g` 上缓存 SQLite 连接，`row_factory=sqlite3.Row`。

## 数据库表（逻辑关系）

| 表名 | 用途 |
|------|------|
| `students` | 学号 `student_id`（业务主键）、姓名、班级、人脸图路径、`face_embedding`（BLOB） |
| `attendance` | 考勤流水：学号、姓名快照、时间、状态、活体摘要、情绪 |
| `activities` | 活动合照识别结果：活动名、学号、姓名、时间、合照相对路径 |
| `emotion_records` | 情绪记录（含来源，如考勤） |
| `users` | 登录用户：`username`、密码哈希、`role`（`teacher` / `student`） |

外键：`attendance`、`activities`、`emotion_records` 引用 `students(student_id)`。

## 权限模型

- **未登录**：可访问 `login`、`static`；访问页面会跳转登录；访问 `/api/*` 返回统一 JSON 401（见 `api.md`）。
- **教师 `teacher`**：学生管理、合照上传、统计与导出等。
- **学生**：用户名一般为学号，初始密码与学号同步（见 `_sync_student_login_accounts`）；考勤页仅能本人打卡（服务端校验识别结果与 `session["student_id"]` 一致）。

种子教师（若库中无 `teacher` 用户）：用户名 `teacher`，默认密码 `teacher123`（**生产环境务必修改**）。

## 核心业务流（简述）

### 摄像头考勤

1. 前端 `GET /api/attendance/liveness-challenge` 获取随机动作（眨眼 / 张嘴）说明。  
2. 用户开启摄像头，约 3 秒内采集多帧 JPEG（base64）`POST /api/attendance/capture`。  
3. 后端：`liveness_actions` 判定活体 → 选帧 → `face_embed` 提特征 → `face_match` 与库比对 → 通过则写入 `attendance` 与 `emotion_records`。

### 活动合照

1. 教师上传表单：`POST /api/activity-group-photo`（multipart：`activity_name`、`photo`）。  
2. `group_photo_recognize` 多脸裁剪 → 逐脸嵌入与 `find_best_student_match_excluding` 去重匹配 → 写入 `activities` 并保存图片到 `uploads/activities/`。

## 关键 Python 模块

| 模块 | 职责 |
|------|------|
| `api_json.py` | 统一响应结构，避免前端解析混乱 |
| `face_embed.py` | 从 BGR 图像提取 embedding、主导情绪等 |
| `face_match.py` | `find_best_student_match`、`find_best_student_match_excluding`；阈值见环境变量 |
| `liveness_actions.py` | 多帧 + 动作类型的活体评分 |
| `group_photo_recognize.py` | 合照人脸检测与排序裁剪 |

## 静态资源与前端约定

- 考勤页脚本：`static/js/attendance.js`，依赖 `api_utils.js` 解析统一 JSON 与摄像头错误文案。  
- 合照页：`static/js/activity_group.js`。  
- 全局样式：`static/css/style.css`。

扩展新页面时，建议继续通过 `url_for` 注入 API 地址（见现有模板中的 `window.*_URL` 模式），并保持 API 使用 `api_json` 中的辅助函数返回。
