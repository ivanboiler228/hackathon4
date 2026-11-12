"""Генерирует QR для жюри: обычный или брендированную карточку.

Примеры:
    python scripts\\make_qr.py --url http://192.168.1.65:8000/
    python scripts\\make_qr.py --url https://example.lhr.life/ --plain
"""
from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H

ROOT = Path(__file__).resolve().parent.parent


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf", "arialbd.ttf"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _qr_image(url: str) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#111111", back_color="white").convert("RGB")
    return image.resize((720, 720), Image.Resampling.NEAREST)


def make_plain(url: str, out: Path) -> None:
    _qr_image(url).save(out)


def make_card(url: str, out: Path) -> None:
    width, height = 1000, 1180
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        (24, 24, width - 24, height - 24),
        radius=44,
        outline="#e6e6ea",
        width=3,
    )

    title_font = _font(56, bold=True)
    subtitle_font = _font(30)
    hint_font = _font(30)
    url_font = _font(21)

    draw.text((60, 58), "ФОТОПРИНТ", font=title_font, fill="#1d1d1f")
    draw.text((60, 126), "AI-ассистент руководителя", font=subtitle_font, fill="#5f6368")

    qr = _qr_image(url)
    canvas.paste(qr, ((width - qr.width) // 2, 210))

    draw.text((width // 2, 982), "Наведите камеру телефона", font=hint_font, fill="#1d1d1f", anchor="mm")
    display_url = url.split("?")[0].replace("https://", "").replace("http://", "").rstrip("/")
    draw.text((width // 2, 1032), display_url, font=url_font, fill="#7a7f87", anchor="mm")
    draw.text(
        (width // 2, 1084),
        "Открыть рабочее место руководителя",
        font=_font(22),
        fill="#9aa0a6",
        anchor="mm",
    )
    canvas.save(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://192.168.1.65:8000/", help="Адрес приложения")
    parser.add_argument("--out", default="qr/jury.png", help="Путь к PNG")
    parser.add_argument("--plain", action="store_true", help="Только QR без карточки")
    args = parser.parse_args()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    url = args.url.strip()
    if not url.endswith("/"):
        url += "/"

    if args.plain:
        make_plain(url, out)
    else:
        make_card(url, out)

    print(f"QR: {out}")
    print(f"URL: {url}")


if __name__ == "__main__":
    main()
