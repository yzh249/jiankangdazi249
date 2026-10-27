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
# 先判断有没有 Postgres URL（env + secrets），再决定本地文件落哪
# 源码目录在云端只读；没配 Postgres 时 SQLite 和上传文件统一放 /tmp
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
    # Postgres 模式图片存 DB，DATA_DIR 基本不用
    DATA_DIR = Path("/tmp/jiankangdazi")
    try:
        import psycopg2
        import psycopg2.extras
        if "sslmode=" not in DATABASE_URL:
            DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
        _IntegrityError = psycopg2.IntegrityError
    except Exception as exc:
        # 没装 psycopg2 或平台不支持 → 回退 SQLite
        import sys
        print(f"⚠️ psycopg2 import failed, falling back to SQLite: {exc}", file=sys.stderr)
        USE_PG = False
        _IntegrityError = sqlite3.IntegrityError
else:
    # SQLite 模式：桌面 → 应用目录；云端 Linux → /tmp（源码只读）
    DATA_DIR = Path("/tmp/jiankangdazi") if os.name != "nt" else (BASE_DIR / "data")
    _IntegrityError = sqlite3.IntegrityError

UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
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

CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_type TEXT NOT NULL,
    duration_min REAL NOT NULL DEFAULT 0,
    kcal_burned REAL NOT NULL DEFAULT 0,
    note TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS exercises_user_time_idx ON exercises (user_id, recorded_at);

CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, record_date)
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    public_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS users_public_id_lower_idx ON users (lower(public_id));

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

CREATE TABLE IF NOT EXISTS exercises (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_type TEXT NOT NULL,
    duration_min REAL NOT NULL DEFAULT 0,
    kcal_burned REAL NOT NULL DEFAULT 0,
    note TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS exercises_user_time_idx ON exercises (user_id, recorded_at);

CREATE TABLE IF NOT EXISTS weights (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, record_date)
);
"""

_inited = False

# 每日记录类型（新建记录时由用户自选）
RECORD_TYPES = ("饮食记录", "运动记录", "体重记录")

# 常用运动类型（运动记录表单用）
EXERCISE_TYPES = (
    "跑步", "快走", "骑行", "游泳", "力量训练",
    "球类运动", "跳绳", "瑜伽", "其他",
)


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

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def get_conn():
    if USE_PG:
        return _PGConnection(psycopg2.connect(DATABASE_URL))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + synchronous=NORMAL：崩溃后数据不易损坏，读写并发更稳（持久化加固）
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db() -> None:
    global _inited
    if _inited:
        return
    with closing(get_conn()) as conn:
        # 迁移：旧 schema 没有 public_id，DROP 重建（只执行一次）
        has_public_id = conn.execute(
            "SELECT 1 FROM pragma_table_info('users') WHERE name = 'public_id'"
        ).fetchone() if not USE_PG else conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='public_id'"
        ).fetchone()
        if not has_public_id:
            conn.executescript(
                """
                DROP TABLE IF EXISTS meal_items;
                DROP TABLE IF EXISTS meals;
                DROP TABLE IF EXISTS images;
                DROP TABLE IF EXISTS exercises;
                DROP TABLE IF EXISTS weights;
                DROP TABLE IF EXISTS pairs;
                DROP TABLE IF EXISTS profiles;
                DROP TABLE IF EXISTS users;
                """
                if not USE_PG else
                "DROP TABLE IF EXISTS meal_items, meals, images, exercises, weights, "
                "pairs, profiles, users CASCADE"
            )
            conn.commit()
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


# ---------- 用户（纯 ID 制，无密码） ----------

def get_or_create_user(public_id: str) -> int:
    """ID 存在则登录，不存在则自动注册。返回 user_id。"""
    public_id = (public_id or "").strip()
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE lower(public_id) = lower(?)",
            (public_id,),
        ).fetchone()
        if row:
            return int(row["id"])
        uid = _insert(
            conn,
            "INSERT INTO users (public_id, created_at) VALUES (?,?)",
            (public_id, now()),
        )
        conn.commit()
        return uid


def get_user(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_public_id(public_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(public_id) = lower(?)",
            ((public_id or "").strip(),),
        ).fetchone()
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


def bind_by_public_id(user_id: int, partner_public_id: str) -> tuple[bool, str]:
    """直接输入对方 ID 绑定搭子，无需邀请码。"""
    partner_public_id = (partner_public_id or "").strip()
    if not partner_public_id:
        return False, "请输入对方 ID"
    if get_active_pair(user_id):
        return False, "你已经有搭子了，先解绑才能绑定新的人"

    partner = get_user_by_public_id(partner_public_id)
    if not partner:
        return False, "这个 ID 不存在，请让对方先登录一次"
    if int(partner["id"]) == int(user_id):
        return False, "不能绑定自己"
    if get_active_pair(int(partner["id"])):
        return False, "对方已经有搭子了"

    with closing(get_conn()) as conn:
        _start_pair(conn, user_id, int(partner["id"]))
        conn.commit()
    return True, f"绑定成功，你的搭子是 {partner['public_id']}"


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


# ---------- 饮食记录 ----------

def _item_totals(items: list[dict]) -> dict:
    return {
        "kcal": round(sum(float(i["kcal"]) for i in items), 1),
        "carb": round(sum(float(i["carb"]) for i in items), 1),
        "protein": round(sum(float(i["protein"]) for i in items), 1),
        "fat": round(sum(float(i["fat"]) for i in items), 1),
    }


def _insert_items(conn, meal_id: int, items: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO meal_items (meal_id, food_name, grams, kcal, carb, protein, fat, source)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (meal_id, i["food_name"], i["grams"], i["kcal"], i["carb"],
             i["protein"], i["fat"], i.get("source", "manual"))
            for i in items
        ],
    )


def add_meal(user_id: int, eaten_at: str, meal_type: str, image_path: str | None,
             note: str, items: list[dict], ai_confidence: float | None = None,
             ai_raw: str | None = None) -> int:
    if not items:
        raise ValueError("至少需要一条食物明细")
    totals = _item_totals(items)
    with closing(get_conn()) as conn:
        meal_id = _insert(
            conn,
            """INSERT INTO meals (user_id, eaten_at, meal_type, image_path, note,
                                  kcal, carb, protein, fat, ai_confidence, ai_raw, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, eaten_at, meal_type, image_path, note,
             totals["kcal"], totals["carb"], totals["protein"], totals["fat"],
             ai_confidence, ai_raw, now()),
        )
        _insert_items(conn, meal_id, items)
        conn.commit()
    return meal_id


def get_meal(meal_id: int, user_id: int | None = None):
    sql = "SELECT * FROM meals WHERE id = ?"
    params: list = [meal_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with closing(get_conn()) as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row else None


def get_meals(user_id: int, day: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) = ?"
            " ORDER BY eaten_at ASC",
            (user_id, day),
        ).fetchall()
    return [dict(r) for r in rows]


def list_meals(user_id: int, start: str, end: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT * FROM meals
               WHERE user_id = ? AND substr(eaten_at, 1, 10) BETWEEN ? AND ?
               ORDER BY eaten_at DESC""",
            (user_id, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def get_meal_items(meal_id: int) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM meal_items WHERE meal_id = ? ORDER BY id", (meal_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_meal(meal_id: int, user_id: int, eaten_at: str, meal_type: str,
                note: str, items: list[dict]) -> bool:
    """改自己的饮食记录；对方记录写不进去（WHERE 带 user_id）。"""
    if not items:
        return False
    totals = _item_totals(items)
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT id FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """UPDATE meals SET eaten_at = ?, meal_type = ?, note = ?,
                      kcal = ?, carb = ?, protein = ?, fat = ?
               WHERE id = ? AND user_id = ?""",
            (eaten_at, meal_type, note, totals["kcal"], totals["carb"],
             totals["protein"], totals["fat"], meal_id, user_id),
        )
        conn.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
        _insert_items(conn, meal_id, items)
        conn.commit()
    return True


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
        if not row or int(row["user_id"]) != int(user_id):
            return False
        img = row["image_path"]
        if img and img.startswith("dbimg:"):
            conn.execute("DELETE FROM images WHERE id = ?", (int(img[6:]),))
        conn.execute("DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
        conn.commit()
    return True


# ---------- 运动记录 ----------

def add_exercise(user_id: int, recorded_at: str, exercise_type: str,
                 duration_min: float, kcal_burned: float, note: str = "") -> int:
    with closing(get_conn()) as conn:
        rid = _insert(
            conn,
            """INSERT INTO exercises (user_id, exercise_type, duration_min,
                                      kcal_burned, note, recorded_at, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, exercise_type, float(duration_min), float(kcal_burned),
             note, recorded_at, now()),
        )
        conn.commit()
    return rid


def get_exercise(exercise_id: int, user_id: int | None = None):
    sql = "SELECT * FROM exercises WHERE id = ?"
    params: list = [exercise_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with closing(get_conn()) as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row else None


def get_exercises(user_id: int, day: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT * FROM exercises
               WHERE user_id = ? AND substr(recorded_at, 1, 10) = ?
               ORDER BY recorded_at ASC""",
            (user_id, day),
        ).fetchall()
    return [dict(r) for r in rows]


def list_exercises(user_id: int, start: str, end: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT * FROM exercises
               WHERE user_id = ? AND substr(recorded_at, 1, 10) BETWEEN ? AND ?
               ORDER BY recorded_at DESC""",
            (user_id, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def update_exercise(exercise_id: int, user_id: int, recorded_at: str,
                    exercise_type: str, duration_min: float,
                    kcal_burned: float, note: str = "") -> bool:
    with closing(get_conn()) as conn:
        cur = conn.execute(
            """UPDATE exercises SET recorded_at = ?, exercise_type = ?,
                      duration_min = ?, kcal_burned = ?, note = ?
               WHERE id = ? AND user_id = ?""",
            (recorded_at, exercise_type, float(duration_min), float(kcal_burned),
             note, exercise_id, user_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
    return True


def delete_exercise(exercise_id: int, user_id: int) -> bool:
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "DELETE FROM exercises WHERE id = ? AND user_id = ?",
            (exercise_id, user_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
    return True


def day_exercise_total(user_id: int, day: str) -> dict:
    with closing(get_conn()) as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(kcal_burned),0) kcal,
                      COALESCE(SUM(duration_min),0) minutes,
                      COUNT(*) records
               FROM exercises WHERE user_id = ? AND substr(recorded_at, 1, 10) = ?""",
            (user_id, day),
        ).fetchone()
    return dict(row)


# ---------- 体重记录（每人每天一条，重复保存即覆盖） ----------

def save_weight(user_id: int, record_date: str, weight_kg: float,
                note: str = "") -> int:
    with closing(get_conn()) as conn:
        conn.execute(
            """INSERT INTO weights (user_id, record_date, weight_kg, note, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, record_date) DO UPDATE SET
                 weight_kg = excluded.weight_kg,
                 note = excluded.note,
                 created_at = excluded.created_at""",
            (user_id, record_date, float(weight_kg), note, now()),
        )
        row = conn.execute(
            "SELECT id FROM weights WHERE user_id = ? AND record_date = ?",
            (user_id, record_date),
        ).fetchone()
        conn.commit()
    return int(row["id"]) if row else 0


def get_weight(weight_id: int, user_id: int | None = None):
    sql = "SELECT * FROM weights WHERE id = ?"
    params: list = [weight_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with closing(get_conn()) as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row else None


def get_weight_for_date(user_id: int, day: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM weights WHERE user_id = ? AND record_date = ?",
            (user_id, day),
        ).fetchone()
    return dict(row) if row else None


def latest_weight(user_id: int):
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM weights WHERE user_id = ? ORDER BY record_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def list_weights(user_id: int, start: str, end: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT * FROM weights
               WHERE user_id = ? AND record_date BETWEEN ? AND ?
               ORDER BY record_date DESC""",
            (user_id, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def daily_weights(user_id: int, start: str, end: str) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT record_date AS d, weight_kg AS kg
               FROM weights WHERE user_id = ? AND record_date BETWEEN ? AND ?
               ORDER BY record_date""",
            (user_id, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def update_weight(weight_id: int, user_id: int, record_date: str,
                  weight_kg: float, note: str = "") -> bool:
    """改自己的体重记录；日期撞上当天已有记录时返回 False。"""
    with closing(get_conn()) as conn:
        try:
            cur = conn.execute(
                """UPDATE weights SET record_date = ?, weight_kg = ?, note = ?
                   WHERE id = ? AND user_id = ?""",
                (record_date, float(weight_kg), note, weight_id, user_id),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
            conn.commit()
        except _IntegrityError:
            conn.rollback()
            return False
    return True


def delete_weight(weight_id: int, user_id: int) -> bool:
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "DELETE FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id)
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
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
