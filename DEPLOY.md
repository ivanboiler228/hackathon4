# Деплой: облако, GitHub, Netlify

## Коротко

| Куда | Можно? | Почему |
|---|---|---|
| **Netlify** | Нет | Netlify хостит статику и serverless-функции. Здесь нужен Python-процесс, SQLite, Vosk и ffmpeg. |
| **GitHub Pages** | Нет | Это только статические файлы. Backend не запустится, `/api/*` не заработает. |
| **GitHub** | Да, для кода | Приватный репозиторий. Секреты и `.env` не коммитить. |
| **Render / Railway / Fly.io** | Да | Python-сервис + HTTPS + диск. Бесплатные тарифы могут засыпать и не давать постоянный диск. |
| **VPS (Timeweb, Yandex Cloud, Selectel)** | Да | Полный контроль, HTTPS через Caddy/Nginx, SQLite на диске. |
| **Cloudflare Tunnel с ноутбука** | Да, для демо | Даёт HTTPS-ссылку без покупки сервера. Ноутбук должен быть включён. |

**Календарь:** сейчас он живёт в браузере (JS-массив `EVENTS`). Если задеплоить приложение,
календарь не станет общим для всех устройств. Для общего календаря нужна серверная таблица
событий и API синхронизации — это отдельная доработка. AI-советник уже получает снимок
календаря на сервер, поэтому после деплоя он продолжит работать.

## Вариант 1. Render (быстрее всего)

1. Залейте код в **приватный** GitHub-репозиторий. `.env` и `data/*.db` не должны попасть в git.
2. В Render: **New → Web Service → Build from repository**.
3. Настройки:

```text
Runtime: Python
Build Command:
  pip install -r requirements.txt && python scripts/setup_vosk.py
Start Command:
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

4. Переменные окружения:

```dotenv
SECRET_KEY=<сгенерировать: python -c "import secrets; print(secrets.token_urlsafe(48))">
DEEPSEEK_API_KEY=<ключ>
DEEPSEEK_MODEL=deepseek-chat
VOSK_MODEL_PATH=models/vosk-model-small-ru-0.22
COOKIE_SECURE=1
SESSION_MAX_AGE=28800
RATE_LIMIT_PER_MINUTE=20
```

5. **Persistent Disk**: примонтируйте диск, например в `/var/data`, и добавьте:

```dotenv
DB_PATH=/var/data/app.db
```

Без диска SQLite и загруженные документы исчезнут после перезапуска.

6. Render выдаст HTTPS-ссылку. Микрофон на телефоне заработает, потому что HTTPS.
7. Пересоздайте QR:

```powershell
python scripts\make_qr.py --url https://ваш-сервис.onrender.com/
```

Модель Vosk скачивается на этапе сборки. Это ~50 МБ; если сборка не тянет, закоммитьте
модель в приватный репозиторий или используйте диск.

## Вариант 2. Railway / Fly.io

Логика та же: Python-сервис, `pip install -r requirements.txt`, `python scripts/setup_vosk.py`,
старт `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. В корне уже лежит `Procfile`.
Нужен постоянный volume под `DB_PATH` и HTTPS.

## Вариант 3. VPS + Caddy

```bash
sudo apt update
sudo apt install -y python3 python3-venv git caddy
git clone <private-repo> /opt/fotoprint
cd /opt/fotoprint
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/setup_vosk.py
```

`/etc/systemd/system/fotoprint.service`:

```ini
[Unit]
Description=Fotoprint AI
After=network.target

[Service]
WorkingDirectory=/opt/fotoprint
EnvironmentFile=/opt/fotoprint/.env
ExecStart=/opt/fotoprint/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/caddy/Caddyfile`:

```text
your-domain.by {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy сам получит TLS-сертификат. В `.env` поставьте `COOKIE_SECURE=1`.

## Вариант 4. Cloudflare Tunnel (демо с ноутбука)

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Получите `https://...trycloudflare.com`, пересоздайте QR на этот адрес. Ноутбук и туннель
должны работать всё время демонстрации. Для постоянного стенда лучше VPS.

### Если Cloudflare Tunnel blocked сетью

В некоторых сетях `api.trycloudflare.com` режет соединение. Тогда используйте
Tunnelmole — он работает по HTTPS, не требует аккаунта и не показывает
промежуточную страницу:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_public_tunnel.ps1
```

Скрипт:

- запускает Tunnelmole на выбранном порту (8000/8001/8010/8020);
- ждёт публичный `https://...tunnelmole.net`;
- проверяет `/health` и только потом публикует адрес;
- сам пересоздаёт `qr/jury.png` на этот адрес;
- пишет ссылку в `tools/public-url.txt`;
- держит туннель и перезапускает его при обрыве.

Остановить:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_public_tunnel.ps1
```

Важно: это временный публичный адрес. Ноутбук должен быть включён, а ссылка — действовать
на момент демонстрации. После перезапуска скрипт выдаст новый адрес и обновит QR.
У бесплатного Tunnelmole лимит на ответ около 60 секунд; LLM-вызовы ограничены
30 секундами, поэтому диалоговые ответы проходят, а очень длинную расшифровку
лучше обрабатывать на VPS.

Публичный туннель не является аутентификацией: кто угодно со ссылкой попадёт в приложение
под директором. Для хакатонного демо с синтетикой это допустимо; после защиты туннель
остановите.

## Что не отправлять в git

- `.env` с `SECRET_KEY` и `DEEPSEEK_API_KEY`;
- `data/app.db`, `*.db-wal`, `*.db-shm`;
- `models/` (модель Vosk);
- временные аудиофайлы.

`.gitignore` уже это закрывает.

## Шифрование и безопасность в облаке

- **Транспорт**: Render/VPS/Caddy дают HTTPS. Локальный `http://192.168...` — без TLS.
- **Cookie**: подписанная, HttpOnly, SameSite=Lax. За HTTPS включайте `COOKIE_SECURE=1`.
- **SQLite**: не шифруется на уровне приложения. В облаке используйте шифрование диска/volume
  (managed disk encryption) или BitLocker на ноутбуке.
- **PII**: маскируется перед внешней LLM, но в SQLite хранится исходный текст — это не шифрование.
- **Аудио**: временный WAV удаляется после расшифровки.
- **Секреты**: только в Environment Variables провайдера, не в репозитории.
- Для реальных ПДн нужны: настоящая аутентификация вместо автовхода, DPA с провайдером LLM,
  шифрование БД/KMS, ротация ключей, резервные копии и журнал доступа.

## Проверка после деплоя

```bash
curl https://ваш-домен/health
```

Должно вернуться `status: ok`, `llm_enabled: true`, модель STT. Затем откройте сайт,
проверьте вход, документы, AI-советник и запись с телефона (уже по HTTPS).
