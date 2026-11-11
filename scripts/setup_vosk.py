"""Скачивает русскую модель Vosk для локальной расшифровки.

Примеры:
    python scripts\\setup_vosk.py
    python scripts\\setup_vosk.py vosk-model-ru-0.42
"""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
DEFAULT_NAME = "vosk-model-small-ru-0.22"


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NAME
    url = f"https://alphacephei.com/vosk/models/{name}.zip"
    MODELS.mkdir(exist_ok=True)
    target = MODELS / name
    if (target / "am" / "final.mdl").exists():
        print(f"Модель уже есть: {target}")
        return
    archive = MODELS / f"{name}.zip"
    print(f"Скачиваю {url} …")
    urllib.request.urlretrieve(url, archive)
    print("Распаковываю…")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(MODELS)
    archive.unlink(missing_ok=True)
    if not (target / "am" / "final.mdl").exists():
        print("Не удалось найти файлы модели после распаковки", file=sys.stderr)
        raise SystemExit(1)
    print(f"Готово: {target}")


if __name__ == "__main__":
    main()
