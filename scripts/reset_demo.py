"""Удаляет тестовые данные демо, не трогая синтетические документы.

    python scripts\\reset_demo.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "app.db"


def main() -> None:
    if not DB.exists():
        print(f"База не найдена: {DB}")
        return
    conn = sqlite3.connect(DB)
    for table in ("meeting_tasks", "meeting_ai", "audit"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM docs WHERE created_by != ''")
    conn.execute("DELETE FROM folders WHERE created_by != ''")
    conn.commit()
    counts = {
        "meeting_ai": conn.execute("SELECT COUNT(*) FROM meeting_ai").fetchone()[0],
        "meeting_tasks": conn.execute("SELECT COUNT(*) FROM meeting_tasks").fetchone()[0],
        "custom_docs": conn.execute("SELECT COUNT(*) FROM docs WHERE created_by != ''").fetchone()[0],
        "audit": conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
    }
    conn.close()
    print("Демо-данные очищены:", counts)
    if counts["meeting_ai"] or counts["meeting_tasks"] or counts["custom_docs"] or counts["audit"]:
        print("Не всё удалилось — проверьте права на data/app.db", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
