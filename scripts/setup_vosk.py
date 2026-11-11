"""Скачивает небольшую русскую модель Vosk для локальной расшифровки."""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
NAME = "vosk-model-small-ru-0.22"
URL = f"https://alphacephei.com/vosk/models/{NAME}.zip"


def main() -> None:
    MODELS.mkdir(exist_ok=True)
    target = MODELS / NAME
    if (target / "am" / "final.mdl").exists():
        print(f"Модель уже есть: {target}")
        return
    archive = MODELS / f"{NAME}.zip"
    print(f"Скачиваю {URL} …")
    urllib.request.urlretrieve(URL, archive)
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
