# Запуск демо: доступ с телефона по LAN-IP
$ErrorActionPreference = "Stop"
Write-Host "Сервер на 0.0.0.0:8000. Для QR используйте ваш LAN-IP, например 192.168.1.65."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
