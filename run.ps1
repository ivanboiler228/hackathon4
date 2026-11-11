# Запуск демо: доступ с телефона по LAN-IP
$ErrorActionPreference = "Stop"
Write-Host "Сервер на 0.0.0.0:8000. Откройте http://127.0.0.1:8000/ или LAN-IP компьютера."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
