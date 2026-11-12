"""Контрольный замер извлечения задач из расшифровок (критерий ТЗ 7.5).

    python scripts\\eval_meeting_tasks.py

Скрипт вызывает реальный протокол встречи (DeepSeek) на трёх синтетических
расшифровках и считает, сколько явно сформулированных поручений извлечено.
Задача = одно поручение ответственному в одной реплике; составные действия
в одной реплике считаются одной задачей.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import meeting_ai  # noqa: E402
from app.config import settings  # noqa: E402

CASES = [
    {
        "file": "night_shift_week48.txt",
        "title": "Запуск ночной смены в неделю 48",
        "expected": [
            {"name": "Подготовить график смен", "owner": "Игорь", "keywords": ["график", "смен"]},
            {
                "name": "Сверить остатки и заказать бумагу",
                "owner": "Павел",
                "keywords": ["остатк", "бумаг"],
            },
        ],
    },
    {
        "file": "sla_support_review.txt",
        "title": "Разбор SLA поддержки",
        "expected": [
            {"name": "Обновить скрипты по доставке", "owner": "Мария", "keywords": ["скрипт", "доставк"]},
            {
                "name": "Согласовать новые сроки с подрядчиком",
                "owner": "Дмитрий",
                "keywords": ["срок", "подрядчик"],
            },
        ],
    },
    {
        "file": "mobile_beta_sync.txt",
        "title": "Синк по мобильному приложению",
        "expected": [
            {"name": "Подготовить список клиентов для беты", "owner": "Мария", "keywords": ["список", "клиент"]},
        ],
    },
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


def matches(expected: dict, task: dict) -> bool:
    title = norm(task.get("title", ""))
    if not all(keyword in title for keyword in expected["keywords"]):
        return False
    owner = norm(task.get("owner", ""))
    return not expected.get("owner") or expected["owner"].lower() in owner


async def main() -> int:
    if not settings.llm_enabled:
        print("DEEPSEEK_API_KEY не задан — замер невозможен.", file=sys.stderr)
        return 2

    total_expected = 0
    total_matched = 0
    print(f"Модель: {settings.deepseek_model}\n")
    for case in CASES:
        path = ROOT / "data" / "transcripts" / case["file"]
        transcript = path.read_text(encoding="utf-8")
        result = await meeting_ai.summarize(transcript, case["title"])
        tasks = list(result.get("tasks", []))
        matched = []
        for expected in case["expected"]:
            for index, task in enumerate(tasks):
                if matches(expected, task):
                    matched.append(expected["name"])
                    tasks.pop(index)
                    break
        total_expected += len(case["expected"])
        total_matched += len(matched)
        recall = len(matched) / len(case["expected"]) * 100
        print(f"{case['file']}: {len(matched)}/{len(case['expected'])} ({recall:.0f}%)")
        for name in matched:
            print(f"  + {name}")
        for expected in case["expected"]:
            if expected["name"] not in matched:
                print(f"  - {expected['name']} (не извлечено)")

    total_recall = total_matched / total_expected * 100 if total_expected else 0
    print(f"\nИтого: {total_matched}/{total_expected} ({total_recall:.1f}%)")
    print("Порог ТЗ 7.5: не менее 80%.")
    return 0 if total_recall >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
