"""数据层：本地用 SQLite，云端设置 DATABASE_URL 后自动切换 Postgres。页面不直接写 SQL。"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

# 云端服务器不在国内时区，「今天/现在」统一按 UTC+8 取
TZ = dt.timezone(dt.timedelta(hours=8))


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL") or None
    except Exception:
        return None


DATABASE_URL = _database_url()
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    if "sslmode=" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
    _IntegrityError = psycopg2.IntegrityError
else:
    _IntegrityError = sqlite3.IntegrityError

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pin_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    height REAL,
    weight REAL,
    age INTEGER,
    sex TEXT,
    activity_level REAL,
    bmr REAL,
    target_kcal REAL,
    deficit REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    dissolved_at TEXT
);

CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'unused',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    eaten_at TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    image_path TEXT,
    note TEXT,
    kcal REAL NOT NULL DEFAULT 0,
    carb REAL NOT NULL DEFAULT 0,
    protein REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    ai_confidence REAL,
    ai_raw TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    food_name TEXT NOT NULL,
    grams REAL NOT NULL,
    kcal REAL NOT NULL,
    carb REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at TEXT NOT NULL
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    nickname TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS users_nickname_lower_idx ON users (lower(nickname));

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    height REAL,
    weight REAL,
    age INTEGER,
    sex TEXT,
    activity_level REAL,
    bmr REAL,
    target_kcal REAL,
    deficit REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pairs (
    id SERIAL PRIMARY KEY,
    user_a INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    dissolved_at TEXT
);

CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY,
    creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'unused',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    eaten_at TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    image_path TEXT,
    note TEXT,
    kcal REAL NOT NULL DEFAULT 0,
    carb REAL NOT NULL DEFAULT 0,
    protein REAL NOT NULL DEFAULT 0,
    fat REAL NOT NULL DEFAULT 0,
    ai_confidence REAL,
    ai_raw TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_items (
    id SERIAL PRIMARY KEY,
    meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    food_name TEXT NOT NULL,
    grams REAL NOT NULL,
    kcal REAL NOT NULL,
    carb REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS images (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mime TEXT NOT NULL,
    data BYTEA NOT NULL,
    created_at TEXT NOT NULL
);
"""

_inited = False


def now() -> str:
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def today() -> dt.date:
    return dt.datetime.now(TZ).date()


class _PGConnection:
    """把 psycopg2 包装成 sqlite3 风格接口：? 占位符、execute/executemany、context manager。"""

    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self._raw.close()
        return False

    def execute(self, sql, params=()):
        cur = self._raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executemany(self, sql, seq):
        cur = self._raw.cursor()
        cur.executemany(sql.replace("?", "%s"), seq)
        return cur

    def executescript(self, script):
        cur = self._raw.cursor()
        cur.execute(script)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def get_conn():
    if USE_PG:
        return _PGConnection(psycopg2.connect(DATABASE_URL))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    global _inited
    if _inited:
        return
    with closing(get_conn()) as conn:
        conn.executescript(SCHEMA_PG if USE_PG else SCHEMA_SQLITE)
        conn.commit()
    _inited = True


def _insert(conn, sql: str, params: tuple) -> int:
    """插入并返回自增 id，兼容 SQLite(lastrowid) 与 Postgres(RETURNING)。"""
    if USE_PG:
        row = conn.execute(sql + " RETURNING id", params).fetchone()
        return int(row["id"])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


# ---------- 用户 ----------

def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120_000).hex()


def create_user(nickname: str, pin: str) -> int:
    nickname = nickname.strip()
    salt = secrets.token_hex(16)
    with closing(get_conn()) as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE lower(nickname) = lower(?)", (nickname,)
        ).fetchone()
        if exists:
            raise ValueError("这个昵称已经有人用了")
        uid = _insert(
            conn,
            "INSERT INTO users (nickname, pin_hash, salt, created_at) VALUES (?,?,?,?)",
            (nickname, _hash_pin(pin, salt), salt, now()),
        )
        conn.commit()
        return uid


def verify_user(nickname: str, pin: str) -> int | None:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT id, pin_hash, salt FROM users WHERE lower(nickname) = lower(?)",
            (nickname.strip(),),
        ).fetchone()
    if not row:
        return None
    if hmac.compare_digest(row["pin_hash"], _hash_pin(pin, row["salt"])):
        return int(row["id"])
    return None


def get_user(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------- 个人目标 ----------

def get_profile(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_profile(user_id: int, height, weight, age, sex, activity_level, bmr, target_kcal, deficit):
    with closing(get_conn()) as conn:
        conn.execute(
            """INSERT INTO profiles (user_id, height, weight, age, sex, activity_level,
                                     bmr, target_kcal, deficit, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 height=excluded.height, weight=excluded.weight, age=excluded.age,
                 sex=excluded.sex, activity_level=excluded.activity_level, bmr=excluded.bmr,
                 target_kcal=excluded.target_kcal, deficit=excluded.deficit,
                 updated_at=excluded.updated_at""",
            (user_id, height, weight, age, sex, activity_level, bmr, target_kcal, deficit, now()),
        )
        conn.commit()


def get_target(user_id: int, default: float = 1800) -> float:
    p = get_profile(user_id)
    if p and p.get("target_kcal"):
        return float(p["target_kcal"])
    return float(default)


# ---------- 搭档 ----------

def get_active_pair(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM pairs WHERE status = 'active' AND (user_a = ? OR user_b = ?)",
            (user_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_partner_id(user_id: int) -> int | None:
    pair = get_active_pair(user_id)
    if not pair:
        return None
    return pair["user_b"] if pair["user_a"] == user_id else pair["user_a"]


def _start_pair(conn, a: int, b: int) -> None:
    conn.execute(
        "INSERT INTO pairs (user_a, user_b, status, created_at) VALUES (?,?, 'active', ?)",
        (a, b, now()),
    )


def create_invite(user_id: int) -> str:
    if get_active_pair(user_id):
        raise ValueError("你已经有搭子了，先解绑才能邀请新的人")
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    with closing(get_conn()) as conn:
        for _ in range(10):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            try:
                conn.execute(
                    "INSERT INTO invites (code, creator_id, status, created_at, expires_at)"
                    " VALUES (?,?,'unused',?,?)",
                    (
                        code,
                        user_id,
                        now(),
                        (dt.datetime.now(TZ) + dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                return code
            except _IntegrityError:
                continue
    raise RuntimeError("邀请码生成失败，请重试")


def latest_invite(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """SELECT * FROM invites WHERE creator_id = ? AND status = 'unused'
               AND expires_at > ? ORDER BY created_at DESC LIMIT 1""",
            (user_id, now()),
        ).fetchone()
    return dict(row) if row else None


def bind_invite(code: str, user_id: int) -> tuple[bool, str]:
    code = code.strip().upper()
    if get_active_pair(user_id):
        return False, "你已经有搭子了，先解绑才能绑定新的人"
    with closing(get_conn()) as conn:
        inv = conn.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
        if not inv:
            return False, "邀请码不存在"
        if inv["status"] != "unused":
            return False, "这个邀请码已经被用掉了"
        if inv["expires_at"] <= now():
            return False, "邀请码已过期，请让对方重新生成"
        if inv["creator_id"] == user_id:
            return False, "不能绑定自己生成的邀请码"
        partner_pair = conn.execute(
            "SELECT 1 FROM pairs WHERE status='active' AND (user_a=? OR user_b=?)",
            (inv["creator_id"], inv["creator_id"]),
        ).fetchone()
        if partner_pair:
            return False, "对方已经有搭子了"
        _start_pair(conn, int(inv["creator_id"]), user_id)
        conn.execute("UPDATE invites SET status = 'used' WHERE code = ?", (code,))
        conn.commit()
    return True, "绑定成功"


def dissolve_pair(user_id: int) -> bool:
    pair = get_active_pair(user_id)
    if not pair:
        return False
    with closing(get_conn()) as conn:
        conn.execute(
            "UPDATE pairs SET status = 'dissolved', dissolved_at = ? WHERE id = ?",
            (now(), pair["id"]),
        )
        conn.commit()
    return True


# ---------- 打卡记录 ----------

def add_meal(user_id: int, eaten_at: str, meal_type: str, image_path: str | None,
             note: str, items: list[dict], ai_confidence: float | None = None,
             ai_raw: str | None = None) -> int:
    kcal = sum(float(i["kcal"]) for i in items)
    carb = sum(float(i["carb"]) for i in items)
    protein = sum(float(i["protein"]) for i in items)
    fat = sum(float(i["fat"]) for i in items)
    with closing(get_conn()) as conn:
        meal_id = _insert(
            conn,
            """INSERT INTO meals (user_id, eaten_at, meal_type, image_path, note,
                                  kcal, carb, protein, fat, ai_confidence, ai_raw, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, eaten_at, meal_type, image_path, note, kcal, carb, protein, fat,
             ai_confidence, ai_raw, now()),
        )
        conn.executemany(
            """INSERT INTO meal_items (meal_id, food_name, grams, kcal, carb, protein, fat, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                (meal_id, i["food_name"], i["grams"], i["kcal"], i["carb"],
                 i["protein"], i["fat"], i.get("source", "manual"))
                for i in items
            ],
        )
        conn.commit()
    return meal_id


def get_meals(user_id: int, day: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) = ?"
            " ORDER BY eaten_at ASC",
            (user_id, day),
        ).fetchall()
    return [dict(r) for r in rows]


def get_meal_items(meal_id: int) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM meal_items WHERE meal_id = ? ORDER BY id", (meal_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def day_total(user_id: int, day: str) -> dict:
    with closing(get_conn()) as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(carb),0) carb,
                      COALESCE(SUM(protein),0) protein, COALESCE(SUM(fat),0) fat,
                      COUNT(*) meals
               FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) = ?""",
            (user_id, day),
        ).fetchone()
    return dict(row)


def daily_totals(user_id: int, start: str, end: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT substr(eaten_at, 1, 10) AS d, SUM(kcal) AS kcal
               FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) BETWEEN ? AND ?
               GROUP BY d ORDER BY d""",
            (user_id, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_meal(meal_id: int, user_id: int) -> bool:
    """只允许删自己的记录（对方记录删不掉）。"""
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT user_id, image_path FROM meals WHERE id = ?", (meal_id,)
        ).fetchone()
        if not row or row["user_id"] != user_id:
            return False
        img = row["image_path"]
        if img and img.startswith("dbimg:"):
            conn.execute("DELETE FROM images WHERE id = ?", (int(img[6:]),))
        conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        conn.commit()
    return True


# ---------- 图片 ----------

def _compress(data: bytes, mime: str) -> tuple[bytes, str]:
    """压到 1280px 内的 JPEG，省数据库/磁盘空间；失败就用原图。"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def save_image(data: bytes, mime: str, user_id: int) -> str:
    """云端(Postgres)存 images 表返回 dbimg:<id>；本地存文件返回相对路径。"""
    data, mime = _compress(data, mime)
    if USE_PG:
        with closing(get_conn()) as conn:
            image_id = _insert(
                conn,
                "INSERT INTO images (user_id, mime, data, created_at) VALUES (?,?,?,?)",
                (user_id, mime, psycopg2.Binary(data), now()),
            )
            conn.commit()
        return f"dbimg:{image_id}"
    ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
    name = f"{user_id}_{dt.datetime.now(TZ).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}.{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / name
    path.write_bytes(data)
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def get_image(image_ref: str | None):
    """返回 st.image 可用的内容：本地文件路径 str 或图片 bytes；没有则 None。"""
    if not image_ref:
        return None
    if image_ref.startswith("dbimg:"):
        with closing(get_conn()) as conn:
            row = conn.execute(
                "SELECT data FROM images WHERE id = ?", (int(image_ref[6:]),)
            ).fetchone()
        return bytes(row["data"]) if row else None
    p = BASE_DIR / image_ref
    return str(p) if p.exists() else None
