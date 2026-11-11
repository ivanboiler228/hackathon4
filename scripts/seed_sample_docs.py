"""Загружает реальные файлы из sample_docs/ в виртуальные папки приложения.

    python scripts\\seed_sample_docs.py

Скрипт идемпотентен: повторный запуск не создаёт дубликаты по названию и папке.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import app

SAMPLES = ROOT / "sample_docs"

FILES = [
    ("01_agenda.txt", "F-REG", "all", "Повестка общей встречи (образец)", "text/plain"),
    ("02_production_shift.md", "F-PROD", "prod", "Регламент ночной смены (образец)", "text/markdown"),
    ("03_support_scripts.txt", "F-SUP", "support", "Скрипты поддержки: доставка (образец)", "text/plain"),
    ("04_marketing_ideas.md", "F-MKT", "mkt", "Идеи новогодней кампании (образец)", "text/markdown"),
    ("05_finance_note.txt", "F-FIN", "fin", "Финансовая заметка Q1 (образец)", "text/plain"),
    ("06_hr_memo.md", "F-HR", "hr", "HR: план закрытия вакансий (образец)", "text/markdown"),
    ("07_legal_checklist.txt", "F-LEGAL", "legal", "Юридический чеклист (образец)", "text/plain"),
    ("08_client_email.eml", "F-MAIL", "all", "Письмо: сроки поставки календарей", "message/rfc822"),
]


def main() -> None:
    if not SAMPLES.exists():
        print(f"Нет папки {SAMPLES}", file=sys.stderr)
        raise SystemExit(1)

    with TestClient(app) as client:
        client.get("/")
        me = client.get("/api/me").json()
        if me.get("role") != "boss":
            print("Нужен автовход директора", file=sys.stderr)
            raise SystemExit(1)

        existing = {
            (item["title"], item["folder_id"])
            for item in client.get("/api/docs").json()["items"]
        }

        created = 0
        skipped = 0
        for filename, folder, acl, title, mime in FILES:
            path = SAMPLES / filename
            if (title, folder) in existing:
                print(f"пропуск: {title}")
                skipped += 1
                continue
            if not path.exists():
                print(f"нет файла: {path}", file=sys.stderr)
                raise SystemExit(1)

            with path.open("rb") as handle:
                response = client.post(
                    "/api/docs",
                    files={"file": (path.name, handle, mime)},
                    data={"folder_id": folder, "acl": acl, "title": title},
                )
            if response.status_code != 200:
                print(f"ошибка {filename}: {response.status_code} {response.text}", file=sys.stderr)
                raise SystemExit(1)
            doc = response.json()
            print(f"загружено: {doc['id']} · {title} → {folder}")
            created += 1

        folders = client.get("/api/folders").json()["items"]
        print(f"\nСоздано: {created}, пропущено: {skipped}")
        print("Папки:")
        for folder in folders:
            print(f"  {folder['title']}: {folder['doc_count']} документ(ов)")


if __name__ == "__main__":
    main()
