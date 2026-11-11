"""SQLite-хранилище: пользователи, документы и аудит."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SEED_USERS = [
    {
        "id": "anna",
        "name": "Анна Ковалёва",
        "role": "boss",
        "role_label": "Директор",
        "dept": "Дирекция",
        "acls": ["all", "fin", "hr", "prod", "mkt", "support", "legal"],
        "email": "anna.kovaleva@fotoprint.by",
    },
    {
        "id": "igor",
        "name": "Игорь Мельник",
        "role": "employee",
        "role_label": "Руководитель производства",
        "dept": "Производство",
        "acls": ["all", "prod"],
        "email": "igor.melnik@fotoprint.by",
    },
    {
        "id": "maria",
        "name": "Мария Гринь",
        "role": "employee",
        "role_label": "Поддержка клиентов",
        "dept": "Поддержка",
        "acls": ["all", "support"],
        "email": "maria.grin@fotoprint.by",
    },
    {
        "id": "olga",
        "name": "Ольга Савчук",
        "role": "employee",
        "role_label": "Маркетинг",
        "dept": "Маркетинг",
        "acls": ["all", "mkt"],
        "email": "olga.savchuk@fotoprint.by",
    },
    {
        "id": "pavel",
        "name": "Павел Орлов",
        "role": "employee",
        "role_label": "Финансы",
        "dept": "Финансы",
        "acls": ["all", "fin"],
        "email": "pavel.orlov@fotoprint.by",
    },
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('boss', 'employee')),
                role_label TEXT NOT NULL,
                dept TEXT NOT NULL,
                acls TEXT NOT NULL,
                email TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS docs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                acl TEXT NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                obj TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                meta TEXT NOT NULL DEFAULT '{}',
                masked_preview TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id, ts DESC);
            CREATE TABLE IF NOT EXISTS meeting_ai (
                event_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                transcript TEXT NOT NULL,
                summary TEXT NOT NULL,
                decisions TEXT NOT NULL,
                tasks TEXT NOT NULL,
                risks TEXT NOT NULL,
                open_questions TEXT NOT NULL,
                stt TEXT NOT NULL,
                llm TEXT NOT NULL
            );
            """
        )
        for user in SEED_USERS:
            conn.execute(
                """
                INSERT INTO users (id, name, role, role_label, dept, acls, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    role=excluded.role,
                    role_label=excluded.role_label,
                    dept=excluded.dept,
                    acls=excluded.acls,
                    email=excluded.email
                """,
                (
                    user["id"],
                    user["name"],
                    user["role"],
                    user["role_label"],
                    user["dept"],
                    json.dumps(user["acls"], ensure_ascii=False),
                    user["email"],
                ),
            )

        docs_path: Path = settings.data_dir / "docs.json"
        if docs_path.exists():
            docs = json.loads(docs_path.read_text(encoding="utf-8"))
            for doc in docs:
                conn.execute(
                    """
                    INSERT INTO docs (id, title, date, acl, text)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        date=excluded.date,
                        acl=excluded.acl,
                        text=excluded.text
                    """,
                    (doc["id"], doc["title"], doc["date"], doc["acl"], doc["text"]),
                )


def row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    user = dict(row)
    user["acls"] = json.loads(user["acls"])
    return user


def get_user(user_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row_to_user(row)


def list_users() -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    return [row_to_user(row) for row in rows]


def get_doc(doc_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def list_docs(acls: list[str]) -> list[dict[str, Any]]:
    if not acls:
        return []
    placeholders = ",".join("?" for _ in acls)
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM docs WHERE acl IN ({placeholders}) ORDER BY date DESC",
            tuple(acls),
        ).fetchall()
    return [dict(row) for row in rows]


def all_docs() -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM docs ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def log_audit(
    *,
    user_id: str,
    role: str,
    action: str,
    obj: str = "",
    result: str = "",
    meta: dict[str, Any] | None = None,
    masked_preview: str = "",
) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO audit (ts, user_id, role, action, obj, result, meta, masked_preview)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now().isoformat(),
                user_id,
                role,
                action,
                obj[:200],
                result[:500],
                json.dumps(meta or {}, ensure_ascii=False),
                masked_preview[:2000],
            ),
        )


def list_audit(user: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with db_conn() as conn:
        if user["role"] == "boss":
            rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user["id"], limit),
            ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["meta"] = json.loads(item["meta"] or "{}")
        out.append(item)
    return out


def save_meeting_ai(
    event_id: str,
    title: str,
    transcript: str,
    result: dict[str, Any],
    stt_engine: str = "vosk",
) -> dict[str, Any]:
    created_at = utc_now().isoformat()
    llm = "deepseek" if result.get("used_llm") else "fallback"
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO meeting_ai
                (event_id, created_at, title, transcript, summary, decisions, tasks, risks, open_questions, stt, llm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                created_at=excluded.created_at,
                title=excluded.title,
                transcript=excluded.transcript,
                summary=excluded.summary,
                decisions=excluded.decisions,
                tasks=excluded.tasks,
                risks=excluded.risks,
                open_questions=excluded.open_questions,
                stt=excluded.stt,
                llm=excluded.llm
            """,
            (
                event_id,
                created_at,
                title,
                transcript,
                result.get("summary", ""),
                json.dumps(result.get("decisions", []), ensure_ascii=False),
                json.dumps(result.get("tasks", []), ensure_ascii=False),
                json.dumps(result.get("risks", []), ensure_ascii=False),
                json.dumps(result.get("open_questions", []), ensure_ascii=False),
                stt_engine,
                llm,
            ),
        )
    return get_meeting_ai(event_id) or {}


def get_meeting_ai(event_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM meeting_ai WHERE event_id = ?", (event_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in ("decisions", "tasks", "risks", "open_questions"):
        item[key] = json.loads(item[key] or "[]")
    item["used_llm"] = item["llm"] == "deepseek"
    return item
