"""Собирает THIRD_PARTY.md: ключевые компоненты, Python- и npm-зависимости.

    python scripts\\make_third_party.py

Лицензии берутся из метаданных установленных Python-пакетов и package-lock.json
клиента Tunnelmole. Это сводка для хакатонного ТЗ; юридически значимые тексты
лицензий лежат в самих пакетах.
"""
from __future__ import annotations

import importlib.metadata as md
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD_PARTY.md"

# Пакеты, у которых метаданные не дают нормального имени лицензии.
LICENSE_OVERRIDES = {
    "vosk": "Apache-2.0",
    "qrcode": "BSD-3-Clause",
    "itsdangerous": "BSD-3-Clause",
    "colorama": "BSD-3-Clause",
    "pillow": "MIT-CMU",
}

MAIN_COMPONENTS = [
    ("Python", "3.11+ (в демо 3.15)", "PSF-2.0", "Язык и runtime"),
    ("FastAPI", "0.162", "MIT", "HTTP API"),
    ("Starlette", "1.10", "BSD-3-Clause", "ASGI-основа FastAPI"),
    ("Uvicorn", "0.54", "BSD-3-Clause", "ASGI-сервер"),
    ("Pydantic", "2.14", "MIT", "Валидация схем API"),
    ("httpx", "0.28", "BSD-3-Clause", "HTTP-клиент к DeepSeek"),
    ("itsdangerous", "2.2", "BSD-3-Clause", "Подпись сессионной cookie"),
    ("python-dotenv", "1.2", "BSD-3-Clause", "Загрузка .env"),
    ("qrcode", "8.2", "BSD-3-Clause", "Генерация QR"),
    ("Pillow", "13.0", "MIT-CMU", "Отрисовка QR-карточки"),
    ("pypdf", "6.21", "BSD-3-Clause", "Разбор PDF"),
    ("python-multipart", "0.0.33", "Apache-2.0", "Загрузка файлов"),
    ("brotli", "1.2", "MIT", "Сжатие HTML"),
    ("Vosk", "0.3.45", "Apache-2.0", "Локальное распознавание речи"),
    ("Vosk model small-ru-0.22", "локальная модель", "Apache-2.0", "Русская STT-модель"),
    ("imageio-ffmpeg", "0.8.1", "BSD-2-Clause", "Поставка ffmpeg для конвертации аудио"),
    ("FFmpeg (binary)", "сборка imageio-ffmpeg", "LGPL-2.1+", "Конвертация webm/m4a → WAV"),
    ("Tunnelmole", "2.4.0", "MIT", "Публичный HTTPS-туннель"),
    ("Node.js", "LTS", "MIT", "Runtime для Tunnelmole"),
    ("DeepSeek API", "deepseek-chat", "Коммерческие условия", "Внешняя LLM; данные — КНР"),
    ("Material Design Icons", "встроенные SVG-пути", "Apache-2.0", "Иконки интерфейса"),
    ("Inter, Anonymous Pro", "woff2, self-hosted", "SIL OFL 1.1", "Шрифты интерфейса"),
    ("Синтетические документы", "21 + 8 образцов", "Созданы командой", "Демо-данные"),
    ("PDF ТЗ заказчика", "2 файла", "Материалы заказчика", "Документация хакатона"),
]


def python_license(dist: md.Distribution) -> str:
    meta = dist.metadata
    value = meta.get("License-Expression") or meta.get("License") or ""
    if not value:
        classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
        value = "; ".join(classifiers)
    value = " ".join(str(value).split()) or "см. пакет"
    return value[:120]


def collect_python() -> list[tuple[str, str, str]]:
    requirements = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[ ]", line, maxsplit=1)[0].strip()
        if name:
            requirements.append(name)

    seen: dict[str, tuple[str, str, str]] = {}
    queue = list(requirements)
    while queue:
        name = queue.pop(0)
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        license_name = LICENSE_OVERRIDES.get(key, python_license(dist))
        seen[key] = (dist.metadata.get("Name") or name, dist.version, license_name)
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            dep = re.split(r"[<>=!~;\[ ]", req, maxsplit=1)[0].strip()
            if dep:
                queue.append(dep)

    # Pillow ставится extras-ом qrcode[pil] и не всегда виден в Requires-Dist.
    try:
        pillow = md.distribution("pillow")
        seen["pillow"] = ("Pillow", pillow.version, LICENSE_OVERRIDES["pillow"])
    except md.PackageNotFoundError:
        pass

    return sorted(seen.values(), key=lambda item: item[0].lower())


def collect_node() -> list[tuple[str, str, str]]:
    lock_path = ROOT / "tools" / "tunnelmole" / "package-lock.json"
    if not lock_path.exists():
        return []
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = data.get("packages", {})
    out = []
    for path, info in packages.items():
        if not path:
            continue
        name = path.replace("node_modules/", "").split("node_modules/")[-1]
        version = info.get("version", "")
        license_name = info.get("license")
        if not license_name:
            # busboy и streamsearch исторически без поля license в lock,
            # оба распространяются под MIT.
            license_name = "MIT" if name in {"busboy", "streamsearch"} else "см. пакет"
        out.append((name, version, str(license_name)))
    return sorted(out, key=lambda item: item[0].lower())


def md_table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def main() -> None:
    python_rows = collect_python()
    node_rows = collect_node()

    parts = [
        "# Сторонние компоненты и лицензии",
        "",
        "Прототип **«Фотопринт · AI-ассистент руководителя»**, хакатон Track 3.",
        "Документ закрывает требование **ОТ-08**: перечислены внешние библиотеки,",
        "модели, датасеты, API и заимствованные компоненты с лицензиями.",
        "",
        "> Это практическая сводка для хакатона, а не юридическое заключение.",
        "> Точные тексты лицензий лежат в самих пакетах (`*.dist-info`, `node_modules/*/LICENSE`).",
        "",
        "## 1. Ключевые компоненты",
        "",
        md_table(MAIN_COMPONENTS, ("Компонент", "Версия / поставка", "Лицензия", "Назначение")),
        "",
        "### Данные, модели и API",
        "",
        "- **Синтетические документы и расшифровки** созданы командой для хакатона;",
        "  реальные персональные данные не используются.",
        "- **8 образцов** в `sample_docs/` созданы командой; внешние датасеты не заимствовались.",
        "- **Vosk-модель** `vosk-model-small-ru-0.22` — Apache-2.0 (проект Vosk).",
        "- **DeepSeek API** — коммерческие условия провайдера; модель `deepseek-chat`,",
        "  обработка в КНР; наружу уходит только маскированный текст.",
        "- **PDF ТЗ** — материалы заказчика (ООО «Фотопринт»), используются как документация",
        "  хакатона, не входят в runtime приложения.",
        "- **Иконки** — встроенные SVG-пути; набор соответствует Material Design Icons (Apache-2.0).",
        "- **Шрифты** — Inter и Anonymous Pro, SIL OFL 1.1; файлы лежат локально",
        "  в `static/fonts`, внешний Google CDN не используется.",
        "",
        "## 2. Python-зависимости",
        "",
        f"Всего: **{len(python_rows)}** пакетов (включая транзитивные и dev/test).",
        "",
        md_table(python_rows, ("Пакет", "Версия", "Лицензия")),
        "",
        "## 3. Node.js / Tunnelmole",
        "",
        f"Всего: **{len(node_rows)}** npm-пакетов в клиенте Tunnelmole.",
        "Сам Tunnelmole — MIT. Большинство транзитивных пакетов — MIT; ниже полный список.",
        "",
        "<details>",
        "<summary>Полный список npm-пакетов и лицензий</summary>",
        "",
        md_table(node_rows, ("Пакет", "Версия", "Лицензия")),
        "",
        "</details>",
        "",
        "## 4. Оговорки",
        "",
        "- Лицензии взяты из метаданных Python-пакетов и `package-lock.json`.",
        "- Транзитивные зависимости могут иметь собственные условия; их тексты сохраняются",
        "  в пакетах и `node_modules`.",
        "- FFmpeg поставляется сборкой `imageio-ffmpeg`; точная конфигурация сборки определяет",
        "  LGPL/GPL-условия. Для пилота нужно проверить конкретный бинарник.",
        "- DeepSeek API не является open-source компонентом; действуют условия провайдера.",
        "- При замене дизайна/шрифтов/иконок обновить этот файл.",
        "",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"{OUT.name}: {len(python_rows)} python, {len(node_rows)} npm")


if __name__ == "__main__":
    main()
