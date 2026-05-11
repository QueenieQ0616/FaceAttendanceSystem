"""
班级考勤系统 — Flask 应用入口。
初始化 SQLite 数据库并提供基础路由。
"""
import os
import sqlite3
import uuid
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from api_json import api_err, api_ok, api_result

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "attendance.db"
UPLOAD_DIR = BASE_DIR / "uploads"
STUDENTS_UPLOAD_DIR = UPLOAD_DIR / "students"
ACTIVITIES_UPLOAD_DIR = UPLOAD_DIR / "activities"

ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_BATCH_STUDENT_PHOTO_EXT = {".jpg", ".jpeg", ".png"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BATCH_STUDENT_FILES = 300
MAX_GROUP_PHOTO_BYTES = 25 * 1024 * 1024
MIN_LIVENESS_FRAMES = 10
MAX_LIVENESS_FRAMES = 22
MAX_LIVENESS_PAYLOAD_BYTES = 22 * 1024 * 1024
MAX_ATTENDANCE_QUERY = 2000
MAX_ATTENDANCE_EXPORT = 10000


def _attendance_filter_clause(
    args,
    forced_student_id: str | None = None,
) -> tuple[str, list]:
    """根据查询参数构造 WHERE 子句；学生端强制只看本人学号。"""
    parts: list[str] = []
    params = []
    if forced_student_id:
        parts.append("student_id = ?")
        params.append(forced_student_id)
    else:
        student_id = (args.get("student_id") or "").strip()
        name = (args.get("name") or "").strip()
        if student_id:
            parts.append("student_id LIKE ?")
            params.append(f"%{student_id}%")
        if name:
            parts.append("name LIKE ?")
            params.append(f"%{name}%")
    date_from = (args.get("date_from") or "").strip()
    date_to = (args.get("date_to") or "").strip()
    if date_from:
        parts.append("date(time) >= date(?)")
        params.append(date_from)
    if date_to:
        parts.append("date(time) <= date(?)")
        params.append(date_to)
    clause = " AND ".join(parts) if parts else "1=1"
    return clause, params


def _fetch_attendance_rows(
    db,
    args,
    limit: int,
    forced_student_id: str | None = None,
):
    clause, params = _attendance_filter_clause(args, forced_student_id=forced_student_id)
    sql = (
        "SELECT id, student_id, name, time, status, liveness_result, emotion "
        f"FROM attendance WHERE {clause} ORDER BY time DESC LIMIT ?"
    )
    return db.execute(sql, (*params, limit)).fetchall()


def _attendance_row_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _activity_stats_filters(args) -> tuple[str, list]:
    """activities 表筛选：活动名称模糊、按记录日期区间。"""
    parts: list[str] = []
    params = []
    activity_name = (args.get("activity_name") or "").strip()
    date_from = (args.get("date_from") or "").strip()
    date_to = (args.get("date_to") or "").strip()
    if activity_name:
        parts.append("activity_name LIKE ?")
        params.append(f"%{activity_name}%")
    if date_from:
        parts.append("date(time) >= date(?)")
        params.append(date_from)
    if date_to:
        parts.append("date(time) <= date(?)")
        params.append(date_to)
    clause = " AND ".join(parts) if parts else "1=1"
    return clause, params


def _session_attendance_forced_student_id() -> str | None:
    if session.get("role") == "student":
        return session.get("student_id")
    return None


def _teacher_required():
    if session.get("role") != "teacher":
        if request.path.startswith("/api/"):
            return api_err("FORBIDDEN", "需要教师权限。", http_status=403)
        flash("需要教师权限。", "error")
        return redirect(url_for("index"))
    return None


def _student_may_access_upload(rel_path: str, student_id: str | None, db) -> bool:
    if not student_id:
        return False
    row = db.execute(
        "SELECT face_image_path FROM students WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    if row and row["face_image_path"] == rel_path:
        return True
    ok = db.execute(
        "SELECT 1 FROM activities WHERE photo_path = ? AND student_id = ? LIMIT 1",
        (rel_path, student_id),
    ).fetchone()
    return ok is not None


def _seed_auth_users(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM users WHERE username = ?", ("teacher",)).fetchone():
        return
    conn.execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        ("teacher", generate_password_hash("teacher123"), "teacher"),
    )


def _sync_student_login_accounts(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT student_id FROM students"):
        sid = r["student_id"]
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (sid,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (sid, generate_password_hash(sid), "student"),
        )


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 学生：学号 student_id（业务主键）、人脸路径与特征向量（BLOB，如 float32 序列化字节）
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    class_name TEXT,
    major TEXT,
    gender TEXT,
    face_image_path TEXT,
    face_embedding BLOB
);

-- 考勤记录：student_id 关联 students.student_id；name 为打卡时冗余姓名快照
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    status TEXT NOT NULL,
    liveness_result TEXT,
    emotion TEXT,
    FOREIGN KEY (student_id) REFERENCES students (student_id)
);

-- 活动参与
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_name TEXT NOT NULL,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    photo_path TEXT,
    FOREIGN KEY (student_id) REFERENCES students (student_id)
);

-- 情绪记录
CREATE TABLE IF NOT EXISTS emotion_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    emotion TEXT NOT NULL,
    source TEXT,
    FOREIGN KEY (student_id) REFERENCES students (student_id)
);

-- 登录用户（password 建议仅存哈希，由业务层写入）
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student'
);

CREATE INDEX IF NOT EXISTS idx_attendance_student_time
    ON attendance (student_id, time);
CREATE INDEX IF NOT EXISTS idx_attendance_time ON attendance (time);
CREATE INDEX IF NOT EXISTS idx_activities_activity ON activities (activity_name);
CREATE INDEX IF NOT EXISTS idx_activities_student ON activities (student_id);
CREATE INDEX IF NOT EXISTS idx_emotion_student_time
    ON emotion_records (student_id, time);
CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
"""


def _migrate_stale_schema(conn):
    """若存在早期骨架的 students（无 student_id 等列），先删掉旧表再建新结构。"""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='students'"
    )
    if not cur.fetchone():
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(students)")}
    if "student_id" in cols and "class_name" in cols:
        return
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS attendance_records;
        DROP TABLE IF EXISTS attendance;
        DROP TABLE IF EXISTS activities;
        DROP TABLE IF EXISTS emotion_records;
        DROP TABLE IF EXISTS students;
        PRAGMA foreign_keys = ON;
        """
    )


def init_db():
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    STUDENTS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVITIES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)

    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate_stale_schema(conn)
        conn.executescript(SCHEMA_SQL)
        _ensure_students_major_gender_columns(conn)
        conn.execute(
            "UPDATE users SET role = 'teacher' WHERE username = 'teacher' "
            "AND role NOT IN ('teacher', 'student')"
        )
        _seed_auth_users(conn)
        _sync_student_login_accounts(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_students_major_gender_columns(conn: sqlite3.Connection) -> None:
    """为已有库补充 major / gender 列（CREATE TABLE IF NOT EXISTS 不会改已有表结构）。"""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='students'")
    if cur.fetchone() is None:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(students)")}
    if "major" not in cols:
        conn.execute("ALTER TABLE students ADD COLUMN major TEXT")
    if "gender" not in cols:
        conn.execute("ALTER TABLE students ADD COLUMN gender TEXT")


def _safe_unlink_upload_rel(rel_path: str | None) -> None:
    if not rel_path:
        return
    fp = (UPLOAD_DIR / rel_path).resolve()
    try:
        fp.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return
    if fp.is_file():
        try:
            fp.unlink()
        except OSError:
            pass


def _save_student_face_to_disk(student_id: str, photo, ext: str) -> tuple[Path, str]:
    """
    将上传流保存为唯一文件名，避免覆盖。
    仅对学号段使用 secure_filename；原始中文文件名不参与磁盘文件名。
    """
    STUDENTS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    id_part = secure_filename(student_id) or uuid.uuid4().hex[:8]
    ext_l = ext.lower()
    if ext_l not in ALLOWED_PHOTO_EXT:
        ext_l = ".jpg"
    fname = f"{id_part}_{uuid.uuid4().hex[:12]}{ext_l}"
    save_path = STUDENTS_UPLOAD_DIR / fname
    rel_store = f"students/{fname}"
    photo.save(str(save_path))
    return save_path, rel_store


def _validate_upload_size(photo, max_bytes: int = MAX_UPLOAD_BYTES) -> str | None:
    try:
        photo.seek(0, os.SEEK_END)
        size = photo.tell()
        photo.seek(0)
    except OSError:
        return "无法读取上传文件。"
    if size > max_bytes:
        return f"文件过大（上限 {max_bytes // (1024 * 1024)}MB）。"
    if size == 0:
        return "文件为空。"
    return None


def _parse_batch_student_filename(original_filename: str) -> tuple[dict | None, str | None]:
    """
    解析「学号-姓名-专业-性别.扩展名」。
    从原始 basename 解析（保留中文）；磁盘存储另用唯一文件名。
    """
    name_only = Path(original_filename or "").name
    if not name_only or name_only in (".", ".."):
        return None, "文件名为空或非法"
    p = Path(name_only)
    ext = p.suffix.lower()
    if ext not in ALLOWED_BATCH_STUDENT_PHOTO_EXT:
        return None, f"不支持的图片格式（仅 jpg / jpeg / png），当前：{ext or '无扩展名'}"
    stem = p.stem.strip()
    parts = stem.split("-")
    if len(parts) != 4:
        return None, "文件名格式错误：应为「学号-姓名-专业-性别」，用英文连字符 - 分成恰好 4 段"
    student_id, name, major, gender = (x.strip() for x in parts)
    if not student_id or not name or not major or not gender:
        return None, "文件名格式错误：学号、姓名、专业、性别均不能为空"
    return (
        {
            "student_id": student_id,
            "name": name,
            "major": major,
            "gender": gender,
            "ext": ext,
            "original_filename": name_only,
        },
        None,
    )


def _ensure_login_user_for_student(db, student_id: str) -> None:
    try:
        db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (student_id, generate_password_hash(student_id), "student"),
        )
    except sqlite3.IntegrityError:
        pass


def _upsert_student_face_record(
    db,
    student_id: str,
    name: str,
    class_name: str | None,
    major: str | None,
    gender: str | None,
    rel_store: str,
    emb_blob: bytes,
) -> None:
    existing = db.execute(
        "SELECT face_image_path FROM students WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    old_rel = existing["face_image_path"] if existing else None
    if existing:
        db.execute(
            "UPDATE students SET name = ?, class_name = ?, major = ?, gender = ?, "
            "face_image_path = ?, face_embedding = ? WHERE student_id = ?",
            (name, class_name, major, gender, rel_store, emb_blob, student_id),
        )
    else:
        db.execute(
            "INSERT INTO students (student_id, name, class_name, major, gender, face_image_path, face_embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_id, name, class_name, major, gender, rel_store, emb_blob),
        )
    if old_rel and old_rel != rel_store:
        _safe_unlink_upload_rel(old_rel)


def _strip_data_url(b64: str) -> str:
    if isinstance(b64, str) and b64.startswith("data:"):
        parts = b64.split(",", 1)
        return parts[1] if len(parts) == 2 else ""
    return b64 or ""


def _decode_b64_to_bgr(raw: bytes):
    import cv2
    import numpy as np

    nparr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-in-production")
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

    app.teardown_appcontext(close_db)

    @app.before_request
    def enforce_login():
        ep = request.endpoint
        if ep in ("login", "logout", "static", None):
            return
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return api_err("UNAUTHORIZED", "请先登录后再访问接口。", http_status=401)
            return redirect(url_for("login", next=request.url))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("index"))
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            db = get_db()
            row = db.execute(
                "SELECT id, username, password, role FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row and check_password_hash(row["password"], password):
                role = (row["role"] or "").strip().lower()
                if role not in ("teacher", "student"):
                    flash("账号角色无效，请联系管理员。", "error")
                    return render_template("login.html")
                if role == "student":
                    st = db.execute(
                        "SELECT 1 FROM students WHERE student_id = ?",
                        (username,),
                    ).fetchone()
                    if not st:
                        flash("该学号未在人脸库建档，请联系教师。", "error")
                        return render_template("login.html")
                    session["student_id"] = username
                else:
                    session.pop("student_id", None)
                session["user_id"] = row["id"]
                session["username"] = row["username"]
                session["role"] = role
                flash("登录成功。", "success")
                nxt = (request.form.get("next") or request.args.get("next") or "").strip() or url_for(
                    "index"
                )
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("index")
                return redirect(nxt)
            flash("用户名或密码错误。", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("已退出登录。", "info")
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/uploads/<path:rel_path>")
    def serve_upload(rel_path):
        target = (UPLOAD_DIR / rel_path).resolve()
        try:
            target.relative_to(UPLOAD_DIR.resolve())
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        if session.get("role") == "student":
            db = get_db()
            if not _student_may_access_upload(rel_path, session.get("student_id"), db):
                abort(403)
        return send_from_directory(UPLOAD_DIR, rel_path)

    @app.route("/students", methods=["GET", "POST"])
    def students_manage():
        err = _teacher_required()
        if err is not None:
            return err
        db = get_db()
        if request.method == "POST":
            return _students_create(db)
        rows = db.execute(
            "SELECT id, student_id, name, class_name, major, gender, face_image_path "
            "FROM students ORDER BY id DESC"
        ).fetchall()
        return render_template("students.html", students=rows)

    @app.route("/api/students/batch-import", methods=["POST"])
    def api_students_batch_import():
        err = _teacher_required()
        if err is not None:
            return err
        files = request.files.getlist("photos")
        files = [f for f in files if f and getattr(f, "filename", None)]
        if not files:
            return api_err("NO_FILES", "未选择任何文件或文件名为空。", http_status=400)
        if len(files) > MAX_BATCH_STUDENT_FILES:
            return api_err(
                "TOO_MANY_FILES",
                f"单次最多上传 {MAX_BATCH_STUDENT_FILES} 个文件。",
                http_status=400,
            )

        results: list[dict] = []
        success_count = 0
        failure_count = 0
        from face_embed import extract_face_embedding_bytes

        for photo in files:
            orig = photo.filename or ""
            base_result: dict = {"filename": Path(orig).name or orig, "ok": False}
            try:
                parsed, parse_err = _parse_batch_student_filename(orig)
                if parse_err:
                    base_result["reason"] = parse_err
                    base_result["display"] = f"失败：{base_result['filename']} {parse_err}"
                    failure_count += 1
                    results.append(base_result)
                    continue

                sz_err = _validate_upload_size(photo)
                if sz_err:
                    base_result["reason"] = sz_err
                    base_result["display"] = (
                        f"失败：{parsed['student_id']}-{parsed['name']} {sz_err}"
                    )
                    failure_count += 1
                    results.append(base_result)
                    continue

                save_path, rel_store = _save_student_face_to_disk(
                    parsed["student_id"], photo, parsed["ext"]
                )
                try:
                    emb_blob, _method = extract_face_embedding_bytes(save_path)
                except ValueError as e:
                    save_path.unlink(missing_ok=True)
                    msg = str(e) or "检测不到人脸"
                    base_result["reason"] = msg
                    base_result["student_id"] = parsed["student_id"]
                    base_result["name"] = parsed["name"]
                    base_result["display"] = f"失败：{parsed['student_id']}-{parsed['name']} {msg}"
                    failure_count += 1
                    results.append(base_result)
                    continue
                except Exception as e:
                    save_path.unlink(missing_ok=True)
                    base_result["reason"] = f"特征提取异常：{e!s}"
                    base_result["student_id"] = parsed["student_id"]
                    base_result["name"] = parsed["name"]
                    base_result["display"] = (
                        f"失败：{parsed['student_id']}-{parsed['name']} 特征提取失败"
                    )
                    failure_count += 1
                    results.append(base_result)
                    continue

                db = get_db()
                try:
                    _upsert_student_face_record(
                        db,
                        parsed["student_id"],
                        parsed["name"],
                        None,
                        parsed["major"],
                        parsed["gender"],
                        rel_store,
                        emb_blob,
                    )
                    _ensure_login_user_for_student(db, parsed["student_id"])
                    db.commit()
                except Exception as e:
                    db.rollback()
                    save_path.unlink(missing_ok=True)
                    base_result["reason"] = f"数据库错误：{e!s}"
                    base_result["student_id"] = parsed["student_id"]
                    base_result["name"] = parsed["name"]
                    base_result["display"] = (
                        f"失败：{parsed['student_id']}-{parsed['name']} 写入数据库失败"
                    )
                    failure_count += 1
                    results.append(base_result)
                    continue

                success_count += 1
                results.append(
                    {
                        "filename": parsed["original_filename"],
                        "ok": True,
                        "student_id": parsed["student_id"],
                        "name": parsed["name"],
                        "major": parsed["major"],
                        "gender": parsed["gender"],
                        "reason": None,
                        "display": f"成功：{parsed['student_id']}-{parsed['name']} 导入成功",
                    }
                )
            except Exception as e:
                base_result["reason"] = f"未预期错误：{e!s}"
                base_result["display"] = f"失败：{base_result['filename']} {base_result['reason']}"
                failure_count += 1
                results.append(base_result)

        total = len(files)
        return api_ok(
            data={
                "total": total,
                "success_count": success_count,
                "failure_count": failure_count,
                "results": results,
            },
            message=f"批量导入结束：成功 {success_count}，失败 {failure_count}。",
            code="BATCH_STUDENT_IMPORT_DONE",
        )

    @app.route("/students/<int:row_id>/delete", methods=["POST"])
    def students_delete(row_id):
        err = _teacher_required()
        if err is not None:
            return err
        db = get_db()
        row = db.execute(
            "SELECT student_id, face_image_path FROM students WHERE id = ?",
            (row_id,),
        ).fetchone()
        if row is None:
            flash("该学生不存在或已删除。", "error")
            return redirect(url_for("students_manage"))
        sid = row["student_id"]
        rel = row["face_image_path"]
        db.execute("DELETE FROM attendance WHERE student_id = ?", (sid,))
        db.execute("DELETE FROM activities WHERE student_id = ?", (sid,))
        db.execute("DELETE FROM emotion_records WHERE student_id = ?", (sid,))
        db.execute("DELETE FROM users WHERE username = ?", (sid,))
        db.execute("DELETE FROM students WHERE id = ?", (row_id,))
        db.commit()
        if rel:
            fp = (UPLOAD_DIR / rel).resolve()
            try:
                fp.relative_to(UPLOAD_DIR.resolve())
            except ValueError:
                fp = None
            if fp is not None and fp.is_file():
                try:
                    fp.unlink()
                except OSError:
                    pass
        flash("已删除该学生及相关关联记录。", "success")
        return redirect(url_for("students_manage"))

    @app.route("/attendance")
    def attendance_page():
        return render_template("attendance.html")

    @app.route("/emotion-stats")
    def emotion_stats():
        db = get_db()
        group = (request.args.get("group") or "student").lower()
        if group not in ("student", "date"):
            group = "student"
        my_sid = _session_attendance_forced_student_id()
        if my_sid:
            total = db.execute(
                "SELECT COUNT(*) AS c FROM emotion_records WHERE source = 'attendance' "
                "AND student_id = ?",
                (my_sid,),
            ).fetchone()["c"]
            if group == "student":
                rows = db.execute(
                    "SELECT student_id, name, emotion, COUNT(*) AS cnt "
                    "FROM emotion_records WHERE source = 'attendance' AND student_id = ? "
                    "GROUP BY student_id, name, emotion "
                    "ORDER BY cnt DESC",
                    (my_sid,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT date(time) AS day, emotion, COUNT(*) AS cnt "
                    "FROM emotion_records WHERE source = 'attendance' AND student_id = ? "
                    "GROUP BY date(time), emotion "
                    "ORDER BY day DESC, cnt DESC",
                    (my_sid,),
                ).fetchall()
        else:
            total = db.execute(
                "SELECT COUNT(*) AS c FROM emotion_records WHERE source = 'attendance'"
            ).fetchone()["c"]
            if group == "student":
                rows = db.execute(
                    "SELECT student_id, name, emotion, COUNT(*) AS cnt "
                    "FROM emotion_records WHERE source = 'attendance' "
                    "GROUP BY student_id, name, emotion "
                    "ORDER BY student_id COLLATE NOCASE, cnt DESC"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT date(time) AS day, emotion, COUNT(*) AS cnt "
                    "FROM emotion_records WHERE source = 'attendance' "
                    "GROUP BY date(time), emotion "
                    "ORDER BY day DESC, cnt DESC"
                ).fetchall()
        return render_template(
            "emotion_stats.html",
            group=group,
            rows=rows,
            total=total,
            student_only=my_sid is not None,
        )

    @app.route("/activity-stats")
    def activity_stats():
        err = _teacher_required()
        if err is not None:
            return err
        db = get_db()
        clause, params = _activity_stats_filters(request.args)
        sql = (
            "SELECT student_id, name, COUNT(*) AS cnt "
            f"FROM activities WHERE {clause} "
            "GROUP BY student_id, name "
            "ORDER BY cnt DESC, student_id COLLATE NOCASE"
        )
        rows = db.execute(sql, params).fetchall()
        total_rows = db.execute(
            f"SELECT COUNT(*) AS c FROM activities WHERE {clause}", params
        ).fetchone()["c"]
        filters = {
            "activity_name": (request.args.get("activity_name") or "").strip(),
            "date_from": (request.args.get("date_from") or "").strip(),
            "date_to": (request.args.get("date_to") or "").strip(),
        }
        chart_rows = [
            {
                "student_id": r["student_id"],
                "name": r["name"],
                "cnt": int(r["cnt"]),
                "label": f"{r['student_id']}",
                "title": f"{r['name']}（{r['student_id']}）",
            }
            for r in rows
        ]
        return render_template(
            "activity_stats.html",
            rows=rows,
            filters=filters,
            chart_rows=chart_rows,
            total_records=int(total_rows),
            student_count=len(rows),
        )

    @app.route("/attendance-records")
    def attendance_records():
        db = get_db()
        forced = _session_attendance_forced_student_id()
        rows = _fetch_attendance_rows(
            db, request.args, MAX_ATTENDANCE_QUERY, forced_student_id=forced
        )
        filters = {
            "date_from": (request.args.get("date_from") or "").strip(),
            "date_to": (request.args.get("date_to") or "").strip(),
            "student_id": (forced or (request.args.get("student_id") or "").strip()),
            "name": ("" if forced else (request.args.get("name") or "").strip()),
        }
        from urllib.parse import urlencode

        export_query = urlencode({k: v for k, v in filters.items() if v})
        return render_template(
            "attendance_records.html",
            rows=rows,
            filters=filters,
            export_query=export_query,
            row_count=len(rows),
            max_query=MAX_ATTENDANCE_QUERY,
            max_export=MAX_ATTENDANCE_EXPORT,
            student_restricted=forced is not None,
        )

    @app.route("/attendance-records/export")
    def attendance_records_export():
        from datetime import datetime
        from io import BytesIO

        from openpyxl import Workbook

        db = get_db()
        forced = _session_attendance_forced_student_id()
        clause, params = _attendance_filter_clause(
            request.args, forced_student_id=forced
        )
        sql = (
            "SELECT student_id, name, time, status, liveness_result, emotion "
            f"FROM attendance WHERE {clause} ORDER BY time DESC LIMIT ?"
        )
        rows = db.execute(sql, (*params, MAX_ATTENDANCE_EXPORT)).fetchall()
        wb = Workbook()
        ws = wb.active
        ws.title = "考勤记录"
        ws.append(
            [
                "学号",
                "姓名",
                "考勤时间",
                "考勤状态",
                "活体检测结果",
                "情绪类型",
            ]
        )
        for r in rows:
            ws.append(
                [
                    r["student_id"],
                    r["name"],
                    r["time"],
                    r["status"],
                    r["liveness_result"] or "",
                    r["emotion"] or "",
                ]
            )
        bio = BytesIO()
        wb.save(bio)
        bio.seek(0)
        fname = f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            bio,
            as_attachment=True,
            download_name=fname,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/api/attendance/records", methods=["GET"])
    def api_attendance_records():
        db = get_db()
        forced = _session_attendance_forced_student_id()
        rows = _fetch_attendance_rows(
            db, request.args, MAX_ATTENDANCE_QUERY, forced_student_id=forced
        )
        return api_ok(
            data={
                "count": len(rows),
                "rows": [_attendance_row_dict(r) for r in rows],
            },
            message="查询成功",
            code="ATTENDANCE_RECORDS_OK",
        )

    @app.route("/activity-group-photo")
    def activity_group_photo_page():
        err = _teacher_required()
        if err is not None:
            return err
        return render_template("activity_group_photo.html")

    @app.route("/api/activity-group-photo", methods=["POST"])
    def api_activity_group_photo():
        err = _teacher_required()
        if err is not None:
            return err
        import cv2
        import numpy as np

        from face_embed import extract_face_embedding_from_crop_bgr, analyze_dominant_emotion_bgr
        from face_match import find_best_student_match_excluding
        from group_photo_recognize import extract_group_face_crops_bgr

        db = get_db()
        activity_name = (request.form.get("activity_name") or "").strip()
        if not activity_name:
            return api_err(
                "MISSING_ACTIVITY_NAME",
                "请填写活动名称后再上传。",
                http_status=400,
            )
        photo = request.files.get("photo")
        if photo is None or photo.filename == "":
            return api_err("MISSING_PHOTO", "请选择要上传的合照文件。", http_status=400)
        raw_name = secure_filename(photo.filename) or "group.jpg"
        ext = Path(raw_name).suffix.lower()
        if ext not in ALLOWED_PHOTO_EXT:
            return api_err(
                "UNSUPPORTED_IMAGE_TYPE",
                "仅支持 JPG、JPEG、PNG、WebP 格式的图片。",
                http_status=400,
            )
        photo.seek(0, os.SEEK_END)
        size = photo.tell()
        photo.seek(0)
        if size > MAX_GROUP_PHOTO_BYTES:
            return api_err(
                "FILE_TOO_LARGE",
                f"图片过大（单文件上限 {MAX_GROUP_PHOTO_BYTES // (1024 * 1024)}MB），请压缩后重试。",
                http_status=413,
            )

        ACTIVITIES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}{ext}"
        save_path = ACTIVITIES_UPLOAD_DIR / fname
        rel_store = f"activities/{fname}"
        try:
            photo.save(str(save_path))
        except OSError as e:
            return api_err(
                "UPLOAD_SAVE_FAILED",
                f"保存上传文件失败：{e}",
                http_status=500,
            )

        data = np.fromfile(str(save_path), dtype=np.uint8)
        img_bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img_bgr is None:
            save_path.unlink(missing_ok=True)
            return api_err(
                "IMAGE_DECODE_FAILED",
                "无法解析上传的图片，请确认文件未损坏且为有效图片格式。",
                http_status=400,
            )

        crops = extract_group_face_crops_bgr(img_bgr)
        matched: list[dict] = []
        used: set[str] = set()
        embed_failures = 0
        for crop in crops:
            try:
                emb, _m = extract_face_embedding_from_crop_bgr(crop)
            except Exception:
                embed_failures += 1
                continue
            sid, name, sim = find_best_student_match_excluding(db, emb, used)
            if sid is not None and name is not None:
                used.add(sid)
                # ---------- 新增：分析该人脸情绪 ----------
                emotion = "未识别"
                try:
                    # 确保裁剪图有效（至少 40x40 像素）
                    if crop.shape[0] >= 40 and crop.shape[1] >= 40:
                        emotion = analyze_dominant_emotion_bgr(crop)
                        if not emotion or emotion.strip().lower() in ("unknown", ""):
                            emotion = "未识别"
                    else:
                        emotion = "人脸太小"
                except Exception:
                    emotion = "分析失败"
                # -----------------------------------------
                matched.append(
                    {
                        "student_id": sid,
                        "name": name,
                        "similarity": round(float(sim), 4),
                        "emotion": emotion,   # 添加情绪字段
                    }
                )

        row_time = db.execute("SELECT datetime('now','localtime')").fetchone()[0]
        try:
            for m in matched:
                db.execute(
                    "INSERT INTO activities (activity_name, student_id, name, time, photo_path) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (activity_name, m["student_id"], m["name"], row_time, rel_store),
                )
            db.commit()
        except sqlite3.Error as e:
            db.rollback()
            save_path.unlink(missing_ok=True)
            return api_err(
                "DATABASE_ERROR",
                f"写入活动记录失败：{e}",
                http_status=500,
            )

        return api_ok(
            data={
                "activity_name": activity_name,
                "photo_path": rel_store,
                "faces_detected": len(crops),
                "faces_recognized": len(matched),
                "embedding_failures": embed_failures,
                "matched": matched,
                "time": row_time,
            },
            message="合照识别处理完成",
            code="GROUP_PHOTO_OK",
        )

    @app.route("/api/attendance/liveness-challenge", methods=["GET"])
    def api_liveness_challenge():
        import random

        pool = [
            {
                "action": "blink",
                "prompt": "请在接下来约 3 秒采集过程中连续眨眼至少 2 次，保持正脸、光线均匀。",
            },
            {
                "action": "mouth",
                "prompt": "请在约 3 秒内张大嘴巴并保持约 1 秒再合拢；采集时勿大幅转头。",
            },
        ]
        row = random.choice(pool)
        return api_ok(
            data={"action": row["action"], "prompt": row["prompt"]},
            message="已获取活体动作指令",
            code="LIVENESS_CHALLENGE_OK",
        )

    @app.route("/api/attendance/capture", methods=["POST"])
    def api_attendance_capture():
        import base64

        from face_embed import analyze_dominant_emotion_bgr, extract_face_embedding_from_bgr
        from face_match import find_best_student_match
        from liveness_actions import evaluate_action_liveness, pick_best_frame_for_face

        db = get_db()
        payload = request.get_json(silent=True) or {}
        frames_in = payload.get("frames")
        action = (payload.get("action") or "").strip().lower()
        row_time = db.execute("SELECT datetime('now','localtime')").fetchone()[0]

        if not isinstance(frames_in, list) or len(frames_in) == 0:
            return api_err(
                "MISSING_FRAMES",
                "请按页面提示完成多帧采集后再提交（单张图片已不再支持）。",
                http_status=400,
            )
        if action not in ("blink", "mouth"):
            return api_err(
                "BAD_ACTION",
                "缺少或非法的 action，请先获取活体挑战指令。",
                http_status=400,
            )

        frames_bgr = []
        total_raw = 0
        for i, item in enumerate(frames_in[:MAX_LIVENESS_FRAMES]):
            if not isinstance(item, str) or not item.strip():
                continue
            b64 = _strip_data_url(item)
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return api_err(
                    "INVALID_FRAME",
                    f"第 {i + 1} 帧 base64 无法解析。",
                    http_status=400,
                )
            total_raw += len(raw)
            if total_raw > MAX_LIVENESS_PAYLOAD_BYTES:
                return api_err(
                    "PAYLOAD_TOO_LARGE",
                    "多帧数据总体积过大，请降低分辨率或缩短采集时间。",
                    http_status=413,
                )
            if len(raw) > MAX_UPLOAD_BYTES:
                return api_err(
                    "FRAME_TOO_LARGE",
                    f"第 {i + 1} 帧过大（单帧上限 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB）。",
                    http_status=413,
                )
            img = _decode_b64_to_bgr(raw)
            if img is None:
                return api_err(
                    "FRAME_DECODE_FAILED",
                    f"第 {i + 1} 帧无法解码为图片。",
                    http_status=400,
                )
            frames_bgr.append(img)

        if len(frames_bgr) < MIN_LIVENESS_FRAMES:
            return api_err(
                "TOO_FEW_FRAMES",
                f"有效帧数不足（当前 {len(frames_bgr)}，至少需要 {MIN_LIVENESS_FRAMES} 帧）。",
                http_status=400,
            )

        liv_ok, liv_detail, _ears, _mars = evaluate_action_liveness(frames_bgr, action)
        liv_label = f"mediapipe_{action}:{'pass' if liv_ok else 'fail'}"

        if not liv_ok:
            return api_result(
                False,
                "LIVENESS_FAILED",
                liv_detail,
                data={
                    "liveness_passed": False,
                    "liveness_result": liv_label,
                    "liveness_detail": liv_detail,
                    "recognized": False,
                    "time": row_time,
                    "action": action,
                },
                http_status=200,
            )

        img = pick_best_frame_for_face(frames_bgr)
        if img is None:
            return api_err("NO_USABLE_FRAME", "未找到可用帧。", http_status=400)

        try:
            emb, _method = extract_face_embedding_from_bgr(img)
        except ValueError as e:
            return api_result(
                False,
                "NO_FACE",
                str(e),
                data={
                    "liveness_passed": True,
                    "liveness_result": liv_label,
                    "liveness_detail": liv_detail,
                    "recognized": False,
                    "time": row_time,
                    "action": action,
                },
                http_status=200,
            )
        except Exception as e:
            return api_err(
                "EMBEDDING_FAILED",
                f"人脸特征提取失败：{e}",
                http_status=500,
            )

        sid, name, sim = find_best_student_match(db, emb)

        if sid is None:
            return api_result(
                False,
                "FACE_NOT_RECOGNIZED",
                "活体检测已通过，但未在库中找到匹配人脸（可尝试调低 FACE_MATCH_THRESHOLD）。",
                data={
                    "liveness_passed": True,
                    "liveness_result": liv_label,
                    "liveness_detail": liv_detail,
                    "recognized": False,
                    "time": row_time,
                    "similarity": round(float(sim), 4),
                    "action": action,
                },
                http_status=200,
            )

        if session.get("role") == "student" and sid != session.get("student_id"):
            return api_err(
                "IDENTITY_MISMATCH",
                "人脸识别与当前登录账号不一致，不能代他人考勤。",
                http_status=403,
            )

        status = "present"
        db_row_liveness = f"{liv_label}|{liv_detail[:200]}"
        dominant_emotion = analyze_dominant_emotion_bgr(img)
        db.execute(
            "INSERT INTO attendance (student_id, name, time, status, liveness_result, emotion) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, name, row_time, status, db_row_liveness, dominant_emotion),
        )
        db.execute(
            "INSERT INTO emotion_records (student_id, name, time, emotion, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, name, row_time, dominant_emotion, "attendance"),
        )
        db.commit()

        return api_ok(
            data={
                "liveness_passed": True,
                "liveness_result": liv_label,
                "liveness_detail": liv_detail,
                "recognized": True,
                "student_id": sid,
                "name": name,
                "time": row_time,
                "status": status,
                "similarity": round(float(sim), 4),
                "dominant_emotion": dominant_emotion,
                "emotion": dominant_emotion,
                "action": action,
            },
            message=f"考勤成功：{name}（{sid}）",
            code="ATTENDANCE_OK",
        )

    return app


def _students_create(db):
    student_id = (request.form.get("student_id") or "").strip()
    name = (request.form.get("name") or "").strip()
    class_name = (request.form.get("class_name") or "").strip()
    photo = request.files.get("photo")
    if not student_id or not name:
        flash("学号与姓名为必填项。", "error")
        return redirect(url_for("students_manage"))
    if photo is None or photo.filename == "":
        flash("请选择学生照片。", "error")
        return redirect(url_for("students_manage"))
    raw_name = secure_filename(photo.filename) or "photo"
    ext = Path(raw_name).suffix.lower()
    if ext not in ALLOWED_PHOTO_EXT:
        flash("照片仅支持 JPG、JPEG、PNG、WebP。", "error")
        return redirect(url_for("students_manage"))
    sz_err = _validate_upload_size(photo)
    if sz_err:
        flash(sz_err, "error")
        return redirect(url_for("students_manage"))
    save_path, rel_store = _save_student_face_to_disk(student_id, photo, ext)
    try:
        from face_embed import extract_face_embedding_bytes

        emb_blob, _method = extract_face_embedding_bytes(save_path)
    except ValueError as e:
        save_path.unlink(missing_ok=True)
        flash(str(e), "error")
        return redirect(url_for("students_manage"))
    except Exception as e:
        save_path.unlink(missing_ok=True)
        flash(f"处理照片时出错：{e}", "error")
        return redirect(url_for("students_manage"))
    try:
        db.execute(
            "INSERT INTO students (student_id, name, class_name, major, gender, face_image_path, face_embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_id, name, class_name or None, None, None, rel_store, emb_blob),
        )
        try:
            db.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (student_id, generate_password_hash(student_id), "student"),
            )
        except sqlite3.IntegrityError:
            pass
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        save_path.unlink(missing_ok=True)
        flash("该学号已存在。", "error")
        return redirect(url_for("students_manage"))
    flash("学生已添加，人脸特征已入库。", "success")
    return redirect(url_for("students_manage"))


app = create_app()

with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
