"""SQLite-хранилище: пользователи, документы и аудит."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SEED_FOLDERS = [
    ("F-REG", "Регламенты и общее", "all"),
    ("F-SUP", "Поддержка", "support"),
    ("F-PROD", "Производство", "prod"),
    ("F-MKT", "Маркетинг", "mkt"),
    ("F-FIN", "Финансы", "fin"),
    ("F-HR", "HR", "hr"),
    ("F-LEGAL", "Юридическое", "legal"),
    ("F-MAIL", "Письма", "all"),
]

ACL_FOLDER = {
    "all": "F-REG",
    "support": "F-SUP",
    "prod": "F-PROD",
    "mkt": "F-MKT",
    "fin": "F-FIN",
    "hr": "F-HR",
    "legal": "F-LEGAL",
}

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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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
            CREATE TABLE IF NOT EXISTS folders (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                acl TEXT NOT NULL DEFAULT 'all',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS meeting_tasks (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                event_title TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                owner TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL DEFAULT '',
                deadline TEXT NOT NULL DEFAULT '',
                basis TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                idem_key TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_meeting_tasks_user ON meeting_tasks(owner_id, created_by);
            """
        )
        _ensure_column(conn, "docs", "folder_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "docs", "source_type", "TEXT NOT NULL DEFAULT 'doc'")
        _ensure_column(conn, "docs", "created_by", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "docs", "created_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "meeting_ai", "protocol", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "meeting_ai", "edited_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "meeting_ai", "feedback", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "meeting_ai", "created_by", "TEXT NOT NULL DEFAULT ''")

        for folder_id, title, acl in SEED_FOLDERS:
            conn.execute(
                """
                INSERT INTO folders (id, title, acl)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title, acl=excluded.acl
                """,
                (folder_id, title, acl),
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
            seeded_ids = [doc["id"] for doc in docs]
            # Встроенные документы, которых больше нет в docs.json, убираем.
            # Загруженные пользователями (created_by) не трогаем.
            conn.execute(
                f"DELETE FROM docs WHERE source_type='doc' AND (created_by IS NULL OR created_by='') "
                f"AND id NOT IN ({','.join('?' for _ in seeded_ids)})",
                tuple(seeded_ids),
            )
            for doc in docs:
                conn.execute(
                    """
                    INSERT INTO docs (id, title, date, acl, text, folder_id, source_type)
                    VALUES (?, ?, ?, ?, ?, ?, 'doc')
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        date=excluded.date,
                        acl=excluded.acl,
                        text=excluded.text,
                        folder_id=excluded.folder_id
                    """,
                    (
                        doc["id"],
                        doc["title"],
                        doc["date"],
                        doc["acl"],
                        doc["text"],
                        ACL_FOLDER.get(doc["acl"], "F-REG"),
                    ),
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


def list_folders(acls: list[str]) -> list[dict[str, Any]]:
    if not acls:
        return []
    placeholders = ",".join("?" for _ in acls)
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT f.id, f.title, f.acl, f.created_by,
                   COUNT(d.id) AS doc_count
            FROM folders f
            LEFT JOIN docs d
              ON d.folder_id = f.id AND d.acl IN ({placeholders})
            WHERE f.acl IN ({placeholders})
            GROUP BY f.id
            ORDER BY f.title
            """,
            tuple(acls) + tuple(acls),
        ).fetchall()
    return [dict(row) for row in rows]


def create_folder(title: str, acl: str, created_by: str) -> dict[str, Any]:
    import secrets

    folder_id = "F-" + secrets.token_hex(3).upper()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO folders (id, title, acl, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (folder_id, title, acl, created_by, utc_now().isoformat()),
        )
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return dict(row)


def get_folder(folder_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return dict(row) if row else None


def count_folder_docs(folder_id: str) -> int:
    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM docs WHERE folder_id = ?", (folder_id,)).fetchone()
    return int(row["n"]) if row else 0


def update_folder(folder_id: str, *, title: str | None = None, acl: str | None = None) -> dict[str, Any] | None:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if acl is not None:
        fields.append("acl = ?")
        values.append(acl)
    if not fields:
        return get_folder(folder_id)
    values.append(folder_id)
    with db_conn() as conn:
        conn.execute(f"UPDATE folders SET {', '.join(fields)} WHERE id = ?", tuple(values))
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
    return dict(row) if row else None


def delete_folder(folder_id: str) -> bool:
    with db_conn() as conn:
        cursor = conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        deleted = cursor.rowcount
    return deleted > 0


def create_doc(
    *,
    title: str,
    text: str,
    acl: str,
    folder_id: str,
    source_type: str,
    created_by: str,
    date: str | None = None,
) -> dict[str, Any]:
    import secrets

    stamp = date or datetime.now().date().isoformat()
    with db_conn() as conn:
        doc_id = "U-" + secrets.token_hex(3).upper()
        conn.execute(
            """
            INSERT INTO docs
                (id, title, date, acl, text, folder_id, source_type, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                title,
                stamp,
                acl,
                text,
                folder_id,
                source_type,
                created_by,
                utc_now().isoformat(),
            ),
        )
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return dict(row)


def update_doc(
    doc_id: str,
    *,
    title: str | None = None,
    text: str | None = None,
    folder_id: str | None = None,
    acl: str | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if text is not None:
        fields.append("text = ?")
        values.append(text)
    if folder_id is not None:
        fields.append("folder_id = ?")
        values.append(folder_id)
    if acl is not None:
        fields.append("acl = ?")
        values.append(acl)
    if not fields:
        return get_doc(doc_id)
    values.append(doc_id)
    with db_conn() as conn:
        conn.execute(f"UPDATE docs SET {', '.join(fields)} WHERE id = ?", tuple(values))
        row = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def delete_doc(doc_id: str) -> bool:
    with db_conn() as conn:
        cursor = conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
    return cursor.rowcount > 0


def list_meeting_ai(user: dict[str, Any]) -> list[dict[str, Any]]:
    with db_conn() as conn:
        if user["role"] == "boss":
            rows = conn.execute("SELECT * FROM meeting_ai ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM meeting_ai WHERE created_by = ? ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for key in ("decisions", "tasks", "risks", "open_questions"):
            item[key] = json.loads(item[key] or "[]")
        item["protocol"] = json.loads(item.get("protocol") or "{}")
        item["feedback"] = json.loads(item.get("feedback") or "{}")
        item["used_llm"] = item["llm"] == "deepseek"
        out.append(item)
    return out


def create_meeting_tasks(
    *,
    event_id: str,
    event_title: str,
    items: list[dict[str, Any]],
    created_by: str,
    resolve_owner,
) -> dict[str, Any]:
    import hashlib
    import secrets

    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    with db_conn() as conn:
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            owner = str(item.get("owner") or "").strip()
            owner_id = resolve_owner(owner) or ""
            deadline = str(item.get("deadline") or "").strip()
            basis = str(item.get("basis") or "").strip()
            idem = hashlib.sha1(
                f"{event_id}|{title}|{owner}|{deadline}".encode("utf-8")
            ).hexdigest()
            task_id = "MT-" + secrets.token_hex(3).upper()
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO meeting_tasks
                    (id, event_id, event_title, title, owner, owner_id, deadline, basis,
                     status, created_at, created_by, idem_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)
                """,
                (
                    task_id,
                    event_id,
                    event_title,
                    title,
                    owner,
                    owner_id,
                    deadline,
                    basis,
                    utc_now().isoformat(),
                    created_by,
                    idem,
                ),
            )
            if cursor.rowcount:
                created.append(
                    {
                        "id": task_id,
                        "event_id": event_id,
                        "event_title": event_title,
                        "title": title,
                        "owner": owner,
                        "owner_id": owner_id,
                        "deadline": deadline,
                        "basis": basis,
                        "status": "new",
                        "created_by": created_by,
                    }
                )
            else:
                existing = conn.execute(
                    "SELECT id FROM meeting_tasks WHERE idem_key = ?", (idem,)
                ).fetchone()
                skipped.append(existing["id"] if existing else title)
    return {"created": created, "skipped": skipped}


def list_meeting_tasks(user: dict[str, Any]) -> list[dict[str, Any]]:
    with db_conn() as conn:
        base = """
            SELECT t.*, COALESCE(m.title, t.event_title) AS event_title
            FROM meeting_tasks t
            LEFT JOIN meeting_ai m ON m.event_id = t.event_id
        """
        if user["role"] == "boss":
            rows = conn.execute(base + " ORDER BY t.created_at DESC").fetchall()
        else:
            rows = conn.execute(
                base + " WHERE t.owner_id = ? OR t.created_by = ? ORDER BY t.created_at DESC",
                (user["id"], user["id"]),
            ).fetchall()
    return [dict(row) for row in rows]


def get_meeting_task(task_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT t.*, COALESCE(m.title, t.event_title) AS event_title
            FROM meeting_tasks t
            LEFT JOIN meeting_ai m ON m.event_id = t.event_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def update_meeting_task_status(
    task_id: str, status: str, owner_id: str | None = None
) -> dict[str, Any] | None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    if owner_id is not None:
        fields.append("owner_id = ?")
        values.append(owner_id)
    values.append(task_id)
    with db_conn() as conn:
        cursor = conn.execute(
            f"UPDATE meeting_tasks SET {', '.join(fields)} WHERE id = ?", tuple(values)
        )
        changed = cursor.rowcount
    return get_meeting_task(task_id) if changed else None


def delete_meeting_task(task_id: str) -> bool:
    with db_conn() as conn:
        cursor = conn.execute("DELETE FROM meeting_tasks WHERE id = ?", (task_id,))
        deleted = cursor.rowcount
    return deleted > 0


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
    created_by: str = "",
) -> dict[str, Any]:
    created_at = utc_now().isoformat()
    llm = "deepseek" if result.get("used_llm") else "fallback"
    protocol = result.get("protocol") or {
        "decided": result.get("decisions", []),
        "proposed": [],
        "discussed": [],
        "needs_clarification": result.get("open_questions", []),
    }
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO meeting_ai
                (event_id, created_at, title, transcript, summary, decisions, tasks,
                 risks, open_questions, protocol, stt, llm, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                created_at=excluded.created_at,
                title=excluded.title,
                transcript=excluded.transcript,
                summary=excluded.summary,
                decisions=excluded.decisions,
                tasks=excluded.tasks,
                risks=excluded.risks,
                open_questions=excluded.open_questions,
                protocol=excluded.protocol,
                stt=excluded.stt,
                llm=excluded.llm,
                edited_at='',
                feedback='{}',
                created_by=CASE
                    WHEN meeting_ai.created_by = '' THEN excluded.created_by
                    ELSE meeting_ai.created_by
                END
            """,
            (
                event_id,
                created_at,
                title,
                transcript,
                result.get("summary", ""),
                json.dumps(result.get("decisions", protocol.get("decided", [])), ensure_ascii=False),
                json.dumps(result.get("tasks", []), ensure_ascii=False),
                json.dumps(result.get("risks", []), ensure_ascii=False),
                json.dumps(result.get("open_questions", protocol.get("needs_clarification", [])), ensure_ascii=False),
                json.dumps(protocol, ensure_ascii=False),
                stt_engine,
                llm,
                created_by,
            ),
        )
    return get_meeting_ai(event_id) or {}


def update_meeting_ai(
    event_id: str,
    *,
    transcript: str | None = None,
    summary: str | None = None,
    protocol: dict[str, Any] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
    open_questions: list[str] | None = None,
    feedback: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    fields = ["edited_at = ?"]
    values: list[Any] = [utc_now().isoformat()]
    if transcript is not None:
        fields.append("transcript = ?")
        values.append(transcript)
    if summary is not None:
        fields.append("summary = ?")
        values.append(summary)
    if protocol is not None:
        fields.append("protocol = ?")
        values.append(json.dumps(protocol, ensure_ascii=False))
        decided = protocol.get("decided", [])
        fields.append("decisions = ?")
        values.append(json.dumps(decided, ensure_ascii=False))
        needs = protocol.get("needs_clarification", [])
        fields.append("open_questions = ?")
        values.append(json.dumps(needs, ensure_ascii=False))
    if tasks is not None:
        fields.append("tasks = ?")
        values.append(json.dumps(tasks, ensure_ascii=False))
    if risks is not None:
        fields.append("risks = ?")
        values.append(json.dumps(risks, ensure_ascii=False))
    if open_questions is not None:
        fields.append("open_questions = ?")
        values.append(json.dumps(open_questions, ensure_ascii=False))
    if feedback is not None:
        fields.append("feedback = ?")
        values.append(json.dumps(feedback, ensure_ascii=False))
    values.append(event_id)
    with db_conn() as conn:
        cursor = conn.execute(
            f"UPDATE meeting_ai SET {', '.join(fields)} WHERE event_id = ?", tuple(values)
        )
        changed = cursor.rowcount
    if not changed:
        return None
    return get_meeting_ai(event_id)


def delete_meeting_ai(event_id: str) -> bool:
    with db_conn() as conn:
        conn.execute("DELETE FROM meeting_tasks WHERE event_id = ?", (event_id,))
        cursor = conn.execute("DELETE FROM meeting_ai WHERE event_id = ?", (event_id,))
        deleted = cursor.rowcount
    return deleted > 0


def get_meeting_ai(event_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM meeting_ai WHERE event_id = ?", (event_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in ("decisions", "tasks", "risks", "open_questions"):
        item[key] = json.loads(item[key] or "[]")
    item["protocol"] = json.loads(item.get("protocol") or "{}")
    if not item["protocol"]:
        item["protocol"] = {
            "decided": item["decisions"],
            "proposed": [],
            "discussed": [],
            "needs_clarification": item["open_questions"],
        }
    item["feedback"] = json.loads(item.get("feedback") or "{}")
    item["used_llm"] = item["llm"] == "deepseek"
    return item
