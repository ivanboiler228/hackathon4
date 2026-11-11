"""Простой поиск по документам с серверной фильтрацией по ACL.

Для хакатонного прототипа используем keyword-scoring, а не векторную БД.
Важно: фильтрация по роли выполняется до ранжирования, в SQL.
"""
from __future__ import annotations

import re
from typing import Any

from . import db

DOC_ID_RE = re.compile(r"\bD[-\s]?(\d{1,2})\b", re.IGNORECASE)
SPLIT_RE = re.compile(r"[^а-яёa-z0-9]+", re.IGNORECASE)


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def tokens(text: str) -> list[str]:
    return [t for t in SPLIT_RE.split(normalize(text)) if len(t) >= 4]


def stems(text: str) -> set[str]:
    return {t[:5] for t in tokens(text)}


def score_doc(query: str, doc: dict[str, Any]) -> int:
    q_stems = stems(query)
    if not q_stems:
        return 0
    title = normalize(doc.get("title", ""))
    body = normalize(doc.get("text", ""))
    score = 0
    for stem in q_stems:
        if stem in title:
            score += 3
        if stem in body:
            score += 1
    # Точное вхождение исходной строки — сильный сигнал.
    if normalize(query).strip() and normalize(query).strip() in body:
        score += 4
    return score


def can_access(doc: dict[str, Any], acls: list[str]) -> bool:
    return doc.get("acl") == "all" or doc.get("acl") in acls


def search(query: str, acls: list[str], limit: int = 4) -> list[dict[str, Any]]:
    allowed = db.list_docs(acls)
    ranked = []
    for doc in allowed:
        score = score_doc(query, doc)
        if score > 0:
            ranked.append((score, doc))
    ranked.sort(key=lambda item: -item[0])
    if not ranked:
        return []
    cutoff = max(1, ranked[0][0] * 0.55)
    return [doc for score, doc in ranked if score >= cutoff][:limit]


def explicit_doc(query: str) -> dict[str, Any] | None:
    match = DOC_ID_RE.search(query)
    if not match:
        return None
    doc_id = f"D-{int(match.group(1)):02d}"
    return db.get_doc(doc_id)


def search_json(query: str, docs: list[dict[str, Any]], acls: list[str], limit: int = 4) -> list[dict[str, Any]]:
    """Версия для unit-тестов без SQLite."""
    allowed = [d for d in docs if can_access(d, acls)]
    ranked = [(score_doc(query, d), d) for d in allowed]
    ranked = [(s, d) for s, d in ranked if s > 0]
    ranked.sort(key=lambda item: -item[0])
    if not ranked:
        return []
    cutoff = max(1, ranked[0][0] * 0.55)
    return [d for score, d in ranked if score >= cutoff][:limit]
