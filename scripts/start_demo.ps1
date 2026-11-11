# Запускает сервер (если ещё не запущен) и публичный HTTPS-туннель.
# Использование: powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$ServerPidFile = Join-Path $Tools "server.pid"
$ServerOut = Join-Path $Tools "server.out.log"
$ServerErr = Join-Path $Tools "server.err.log"

New-Item -ItemType Directory -Force -Path $Tools | Out-Null

$Listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $Listening) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) { throw "Не найден python. Установите Python и зависимости из requirements.txt." }

    Write-Host "Запускаю FastAPI на 0.0.0.0:8000..." -ForegroundColor Cyan
    $Process = Start-Process -FilePath $Python.Source `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $ServerOut `
        -RedirectStandardError $ServerErr `
        -PassThru -WindowStyle Hidden
    Set-Content -Path $ServerPidFile -Value $Process.Id
}

$Ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $Response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($Response.StatusCode -eq 200) { $Ready = $true; break }
    } catch {
        # сервер ещё поднимается
    }
}
if (-not $Ready) {
    Write-Host "Сервер не ответил. Логи:" -ForegroundColor Red
    if (Test-Path $ServerOut) { Get-Content $ServerOut -Tail 30 }
    if (Test-Path $ServerErr) { Get-Content $ServerErr -Tail 30 }
    throw "FastAPI не запустился."
}

Write-Host "Сервер готов: http://127.0.0.1:8000" -ForegroundColor Green
& (Join-Path $PSScriptRoot "start_public_tunnel.ps1")
