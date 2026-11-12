"""Собирает переносимые ZIP-архивы проекта для передачи на другой компьютер.

    python scripts\\make_dist.py

Создаёт:
    dist/fotoprint-ai-assistant.zip       — полный: код + модель Vosk + клиент Tunnelmole
    dist/fotoprint-ai-assistant-lite.zip  — лёгкий: код, модель и клиент скачиваются при первом запуске

.env, база, аудит, логи, PID-файлы и ключи туннеля в архив не попадают.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

INCLUDE_DIRS = ["app", "data", "sample_docs", "scripts", "static", "tests"]
INCLUDE_FILES = [
    "fotoprint-ai-assistant (1).html",
    "requirements.txt",
    "README.md",
    "DEPLOY.md",
    "SECURITY.md",
    "TZ_REQUIREMENTS.md",
    "THIRD_PARTY.md",
    "Procfile",
    "run.ps1",
    ".gitignore",
    ".env.example",
    "START.bat",
]
OPTIONAL_DIRS = ["models", "tools/tunnelmole"]

IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.log",
    "*.pid",
    "public-url.txt",
    "port.txt",
    "serveo_key*",
    "tunnel-supervisor.pid",
)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dst, ignore=IGNORE)


def build(mode: str) -> Path:
    stage = DIST / f"_stage_{mode}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for name in INCLUDE_DIRS:
        copy_tree(ROOT / name, stage / name)

    for name in INCLUDE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, stage / name)

    if mode == "full":
        for name in OPTIONAL_DIRS:
            copy_tree(ROOT / name, stage / name)

    start_here = (ROOT / "START_HERE.txt").read_text(encoding="utf-8")
    (stage / "START_HERE.txt").write_text(start_here, encoding="utf-8-sig")

    pdfs = sorted(ROOT.glob("*.pdf"))
    if pdfs:
        (stage / "docs").mkdir()
        for pdf in pdfs:
            shutil.copy2(pdf, stage / "docs" / pdf.name)

    qr = stage / "qr"
    qr.mkdir(exist_ok=True)
    (qr / "README.txt").write_text(
        "QR создаётся автоматически при запуске scripts\\start_demo.ps1.\n"
        "Старый QR из другого запуска не используйте.\n",
        encoding="utf-8",
    )

    zip_name = "fotoprint-ai-assistant.zip" if mode == "full" else "fotoprint-ai-assistant-lite.zip"
    zip_path = DIST / zip_name
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                archive.write(file, Path("fotoprint-ai-assistant") / file.relative_to(stage))

    shutil.rmtree(stage)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"{zip_path.name}: {size_mb:.1f} MB")
    return zip_path


def main() -> None:
    DIST.mkdir(exist_ok=True)
    build("lite")
    build("full")


if __name__ == "__main__":
    main()
