# 环境与运行

## 环境要求

- **操作系统**：Windows / macOS / Linux 均可；摄像头考勤建议在 Windows 上使用 Chrome 或 Edge。
- **Python**：3.10 及以上（推荐 3.11 或 3.12）。
- **硬件**：人脸特征与情绪分析依赖 TensorFlow / DeepFace，首次运行会下载模型；建议具备足够内存与磁盘空间。

## 依赖说明

依赖列表见项目根目录 `requirements.txt`，主要包括：

- **Flask**：Web 框架与路由。
- **OpenCV（headless）**：图像解码与部分检测逻辑。
- **DeepFace / TensorFlow**：人脸检测、特征与情绪分析（体积与安装时间较长）。
- **MediaPipe**：多帧活体动作判定。
- **NumPy、openpyxl**：数值计算与考勤 Excel 导出。

## 使用 venv（推荐与 README 一致）

在项目根目录执行：

```bash
cd d:\face_final_project
python -m venv .venv
```

**Windows PowerShell** 激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

若提示脚本策略限制，可先执行：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

安装依赖并启动：

```bash
pip install -r requirements.txt
python app.py
```

浏览器访问：`http://127.0.0.1:5000/`。

## 使用 conda

```powershell
conda create -n face_attendance python=3.11 -y
conda activate face_attendance
cd d:\face_final_project
pip install -r requirements.txt
python app.py
```

说明：在已激活的 conda 环境中使用 `pip install -r requirements.txt`，包会安装到当前环境。

## 配置项

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | Flask 会话密钥。生产环境**必须**通过环境变量设置；开发默认见 `app.py`。 |

人脸比对阈值（可选，见 `face_match.py`）：

| 变量 | 说明 |
|------|------|
| `FACE_MATCH_THRESHOLD` | 考勤等单脸比对余弦相似度阈值，默认 `0.52`。 |
| `GROUP_FACE_THRESHOLD` | 合照多脸比对阈值；未设置时回退为 `FACE_MATCH_THRESHOLD`。 |

## 摄像头与浏览器

- 使用 **`http://127.0.0.1:5000`** 或 **`http://localhost:5000`** 访问，以便浏览器授予摄像头权限。
- 避免仅用局域网 IP 且非 HTTPS 时部分浏览器限制 `getUserMedia` 的情况（以浏览器策略为准）。

## 常见问题

1. **`pip install` 很慢或失败**  
   可换国内 PyPI 镜像；TensorFlow 需与 Python 版本匹配，请对照官方说明。

2. **首次启动慢或占用高**  
   DeepFace / TF 会加载模型，属正常现象。

3. **数据库文件位置**  
   首次运行后在 `database/attendance.db` 生成（见 `architecture.md`）。

4. **生产部署**  
   关闭 `app.py` 中 `debug=True`，使用 Gunicorn / Waitress 等 WSGI 服务，并设置 `SECRET_KEY`。
