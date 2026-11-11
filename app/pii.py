"""Обнаружение и маскирование ПДн перед отправкой во внешнюю LLM.

Это не «полная анонимизация», а защитный слой для демо-прототипа:
известные форматы и имена заменяются тегами, обратная подстановка
выполняется только в памяти текущего запроса.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

# Теги сделаны необычными, чтобы модель реже их ломала.
TAG_CANON = "⟦{}⟧"
TAG_RE = re.compile(r"[\[⟦【〔]\s*([A-Z]+_\d+)\s*[\]⟧】〕]")

FIRST_NAMES = {
    "александр", "алексей", "анастасия", "анна", "антон", "артём", "артем",
    "борис", "вадим", "валентина", "валерий", "василий", "вера", "виктор",
    "виктория", "виталий", "владимир", "владислав", "галина", "геннадий",
    "георгий", "григорий", "дарья", "денис", "дмитрий", "евгений", "евгения",
    "екатерина", "елена", "елизавета", "иван", "игорь", "илья", "инна",
    "ирина", "кирилл", "константин", "ксения", "леонид", "людмила", "максим",
    "марина", "мария", "михаил", "надежда", "наталья", "наталия", "никита",
    "николай", "оксана", "олег", "ольга", "павел", "пётр", "петр", "полина",
    "роман", "светлана", "сергей", "софия", "станислав", "степан", "татьяна",
    "тимофей", "ульяна", "юлия", "яна", "ярослав",
}

# Имена сотрудников из демо-базы. Их маскируем даже по одному слову:
# Vosk отдаёт расшифровку без заглавных букв и без отчеств.
EMPLOYEE_NAMES = {"анна", "иван", "игорь", "ольга", "дмитрий", "мария", "павел", "ирина"}
KNOWN_PERSON_RE = re.compile(
    r"(?<![а-яёa-z])(?:" + "|".join(sorted(EMPLOYEE_NAMES, key=len, reverse=True)) + r")(?![а-яёa-z])",
    re.IGNORECASE,
)

# Названия, которые не являются персональными данными и важны для ответов.
ORG_ALLOWLIST = {"фотопринт", "picpac", "picpac.by"}

PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+375|375|80)[\s\-()]*\d{2}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}(?!\d)"
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
IBAN_RE = re.compile(r"\bBY\d{2}[A-Z]{4}\d{4}[A-Z0-9]{16}\b", re.IGNORECASE)
CARD_RE = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
UNP_RE = re.compile(r"(?i)\bУНП\s*[:№]?\s*(\d{9})\b")
PASSPORT_RE = re.compile(r"\b(?:MP|MC|KB|HB|AB|BM)\s?\d{7}\b", re.IGNORECASE)
ORG_RE = re.compile(
    r"(?i)\b(?:ООО|ОАО|ЗАО|ОДО|УП|ЧУП|ИП)\s+[«\"']?[А-ЯЁA-Z][\w\-]+(?:\s+[А-ЯЁA-Z][\w\-]+){0,3}[»\"']?"
)
NAME_RE = re.compile(
    r"\b([А-ЯЁ][а-яё]{1,24})\s+([А-ЯЁ][а-яё]{1,28})(?:\s+([А-ЯЁ][а-яё]{1,28}))?\b"
)


class PIIError(RuntimeError):
    pass


class UnknownTagError(PIIError):
    pass


class PIILeakError(PIIError):
    pass


def _name_root(token: str) -> str:
    """Грубое отсечение падежных окончаний для проверки имени."""
    t = token.lower().replace("ё", "е")
    if t in FIRST_NAMES:
        return t
    for suffix in ("иями", "ями", "ами", "ому", "ему", "ого", "его", "ой", "ей", "ом", "ем", "ах", "ях", "ам", "ям", "у", "а", "я", "е", "ы", "и"):
        if len(t) > len(suffix) + 2 and t.endswith(suffix):
            root = t[: -len(suffix)]
            if root in FIRST_NAMES:
                return root
    return ""


def _looks_like_surname(token: str) -> bool:
    t = token.lower().replace("ё", "е")
    return any(
        t.endswith(suffix)
        for suffix in ("ов", "ев", "ин", "ын", "ский", "цкий", "ая", "яя", "ой", "енко", "ук", "юк", "ич")
    )


def _person_start(match: re.Match) -> int:
    """Возвращает номер группы, с которой начинается ФИО (1/2), или 0."""
    groups = [g for g in match.groups() if g]
    if not groups:
        return 0
    if _name_root(groups[0]):
        return 1
    if len(groups) >= 2 and _name_root(groups[1]) and _looks_like_surname(groups[0]):
        return 1
    if len(groups) >= 2 and _name_root(groups[1]):
        return 2
    return 0


def _looks_like_person(match: re.Match) -> bool:
    return _person_start(match) > 0


@dataclass
class MaskResult:
    masked: str
    mapping: dict[str, str] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)

    @property
    def has_pii(self) -> bool:
        return bool(self.mapping)

    @property
    def tags(self) -> list[str]:
        return list(self.mapping.keys())

    def preview(self, limit: int = 1600) -> str:
        return self.masked[:limit]


class PIIMasker:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self.counters: dict[str, int] = defaultdict(int)
        self.found: dict[str, int] = defaultdict(int)

    def _tag(self, kind: str, value: str) -> str:
        normalized = value.strip()
        key = f"{kind}:{normalized.casefold()}"
        if key in self.reverse:
            return self.reverse[key]
        self.counters[kind] += 1
        tag = TAG_CANON.format(f"{kind}_{self.counters[kind]}")
        self.mapping[tag] = normalized
        self.reverse[key] = tag
        self.found[kind] += 1
        return tag

    def _replace(self, kind: str, text: str, pattern: re.Pattern, repl: Callable[[re.Match], str] | None = None) -> str:
        def cb(match: re.Match) -> str:
            value = match.group(0)
            if kind == "ORG":
                low = value.casefold()
                if any(allowed in low for allowed in ORG_ALLOWLIST):
                    return value
            if repl:
                return repl(match)
            return self._tag(kind, value)

        return pattern.sub(cb, text)

    def mask(self, text: str) -> MaskResult:
        if not text:
            return MaskResult(masked="")

        masked = text
        masked = self._replace("EMAIL", masked, EMAIL_RE)
        masked = self._replace("PHONE", masked, PHONE_RE)
        masked = self._replace("IBAN", masked, IBAN_RE)
        masked = self._replace("CARD", masked, CARD_RE)

        def unp_repl(match: re.Match) -> str:
            return f"УНП {self._tag('UNP', match.group(1))}"

        masked = self._replace("UNP", masked, UNP_RE, repl=unp_repl)
        masked = self._replace("PASSPORT", masked, PASSPORT_RE)
        masked = self._replace("ORG", masked, ORG_RE)

        def name_repl(match: re.Match) -> str:
            start_group = _person_start(match)
            if not start_group:
                return match.group(0)
            if start_group == 1:
                return self._tag("PERSON", match.group(0))
            # ФИО начинается со второй группы: «Позвони Ивану Иванову».
            offset = match.start(start_group) - match.start(0)
            prefix = match.group(0)[:offset]
            value = match.group(0)[offset:]
            return prefix + self._tag("PERSON", value)

        masked = NAME_RE.sub(name_repl, masked)
        masked = KNOWN_PERSON_RE.sub(lambda m: self._tag("PERSON", m.group(0)), masked)

        # Контроль: после маскирования не должно остаться известных шаблонов.
        self.assert_clean(masked)
        return MaskResult(masked=masked, mapping=dict(self.mapping), found=dict(self.found))

    def assert_clean(self, text: str) -> None:
        checks = [
            ("phone", PHONE_RE),
            ("email", EMAIL_RE),
            ("iban", IBAN_RE),
            ("passport", PASSPORT_RE),
        ]
        for label, pattern in checks:
            if pattern.search(text):
                raise PIILeakError(f"В маскированном тексте остался шаблон: {label}")

        # Имена проверяем отдельно: не должно остаться известных ФИО.
        for match in NAME_RE.finditer(text):
            if _looks_like_person(match):
                raise PIILeakError("В маскированном тексте осталось имя")
        if KNOWN_PERSON_RE.search(text):
            raise PIILeakError("В маскированном тексте осталось имя сотрудника")

    def unmask(self, text: str) -> str:
        if not text:
            return ""
        normalized = TAG_RE.sub(lambda m: TAG_CANON.format(m.group(1)), text)
        unknown = [tag for tag in re.findall(r"⟦([A-Z]+_\d+)⟧", normalized) if TAG_CANON.format(tag) not in self.mapping]
        if unknown:
            raise UnknownTagError(f"Модель вернула неизвестные теги: {unknown}")
        for tag, value in self.mapping.items():
            normalized = normalized.replace(tag, value)
        return normalized


def mask_text(text: str) -> tuple[str, PIIMasker]:
    masker = PIIMasker()
    result = masker.mask(text)
    return result.masked, masker
