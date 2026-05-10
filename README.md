# 班级考勤系统（项目骨架）

基于 **Flask**、**SQLite**、**原生 HTML/CSS/JavaScript** 的班级考勤系统初始结构。

更完整的**开发文档**（环境、架构、API）见目录 [`doc/`](doc/README.md)。

## 目录说明

| 路径 | 说明 |
|------|------|
| `app.py` | Flask 应用入口，数据库初始化与路由 |
| `templates/` | Jinja2 页面模板 |
| `static/css/`、`static/js/` | 样式与前端脚本 |
| `database/` | SQLite 文件目录（首次运行后生成 `attendance.db`） |
| `uploads/` | 附件或上传文件存放目录（可按需使用） |

## 环境要求

- Python 3.10+（建议 3.11 或 3.12）

## 安装与运行

在项目根目录执行：

```bash
cd d:\face_final_project
python -m venv .venv
```

**Windows（PowerShell）激活虚拟环境：**

```powershell
.\.venv\Scripts\Activate.ps1
```

**安装依赖：**

```bash
pip install -r requirements.txt
```

**启动开发服务器：**

```bash
python app.py
```

浏览器访问：<http://127.0.0.1:5000/> ，应能看到首页「班级考勤系统」。

## 数据库

首次启动时会在 `database/attendance.db` 中创建示例表结构：

- `students`：学号、姓名等学生信息  
- `attendance_records`：与 `student_id` 关联的考勤记录（日期、状态等）

可在 `app.py` 的 `init_db()` 中继续扩展表结构或迁移逻辑。

## 生产环境提示

- 将 `SECRET_KEY` 通过环境变量注入，勿使用代码中的默认值。  
- 关闭 `debug=True`，使用 Gunicorn 等 WSGI 服务器部署。
