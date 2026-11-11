"""Генерирует один QR для входа жюри в демо.

Пример:
    python scripts/make_qr.py
    python scripts/make_qr.py --url http://192.168.1.65:8000/
"""
from __future__ import annotations

import argparse
from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://192.168.1.65:8000/", help="Адрес приложения")
    parser.add_argument("--out", default="qr/jury.png", help="Путь к PNG")
    args = parser.parse_args()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    img = qrcode.make(args.url)
    img.save(out)
    print(f"QR: {out}")
    print(f"URL: {args.url}")


if __name__ == "__main__":
    main()
