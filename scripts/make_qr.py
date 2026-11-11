"""Генерация одноразовых QR-кодов для входа на демо.

Пример:
    python scripts/make_qr.py --base-url http://192.168.1.10:8000
"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime, timedelta
from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=settings.public_base_url)
    parser.add_argument("--ttl", type=int, default=24 * 3600, help="Срок жизни QR в секундах")
    parser.add_argument("--user", default="", help="Только один user_id (например, anna)")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    if "127.0.0.1" in base or "localhost" in base:
        print("Внимание: QR с localhost не откроется с телефона. Для телефона укажите LAN-IP.")

    db.init_db()
    out_dir = ROOT / "qr"
    out_dir.mkdir(exist_ok=True)
    users = db.list_users()
    if args.user:
        users = [u for u in users if u["id"] == args.user]
        if not users:
            raise SystemExit(f"Пользователь {args.user} не найден")
    else:
        db.clear_qr_tokens()

    expires = datetime.now() + timedelta(seconds=args.ttl)
    lines = [f"Сгенерировано: {datetime.now().isoformat(timespec='seconds')}", f"Истекает: {expires.isoformat(timespec='seconds')}", ""]
    cards = []
    print(f"QR каталог: {out_dir}")
    for user in users:
        code = db.create_qr_token(user["id"], ttl_seconds=args.ttl)
        url = f"{base}/auth/qr?code={code}"
        path = out_dir / f"{user['id']}.png"
        img = qrcode.make(url)
        img.save(path)
        line = f"{user['id']:8} {user['name']:20} {user['role_label']:26} {url}"
        print(line)
        lines.append(line)
        cards.append(
            f"<article><img src='{user['id']}.png' alt='QR {html.escape(user['name'])}'>"
            f"<h2>{html.escape(user['name'])}</h2>"
            f"<p>{html.escape(user['role_label'])} · {html.escape(user['dept'])}</p></article>"
        )

    (out_dir / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "index.html").write_text(
        """<!doctype html><html lang="ru"><meta charset="utf-8"><title>QR для демо</title>
<style>body{font-family:system-ui,sans-serif;background:#eef3ee;color:#1d1d1f;padding:24px}
h1{font-size:24px}main{display:flex;flex-wrap:wrap;gap:18px}article{background:#fff;border-radius:18px;
padding:14px;box-shadow:0 6px 24px rgba(0,0,0,.08);text-align:center;width:240px}
img{width:210px;height:210px}h2{font-size:15px;margin:8px 0 2px}p{font-size:12px;color:#666;margin:0}
.warn{background:#fff4e5;border:1px solid #f0d3a8;border-radius:12px;padding:10px 14px;margin:14px 0;font-size:13px}</style>
<body><h1>QR-коды для демо</h1><div class="warn">Одноразовые ссылки. Не показывайте QR директора всем подряд.
После первого сканирования ссылка перестаёт работать — перегенерируйте скриптом.</div>
<main>""" + "".join(cards) + "</main></body></html>",
        encoding="utf-8",
    )
    print(f"Откройте: {out_dir / 'index.html'}")
    print("\nQR одноразовые: после первого сканирования ссылка перестаёт работать.")


if __name__ == "__main__":
    main()
