# Запускает сервер (если ещё не запущен) и публичный HTTPS-туннель.
# Использование: powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
# Если 8000 занят другим приложением, берётся 8001/8010/8020.
param([int]$Port = 0)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$ServerPidFile = Join-Path $Tools "server.pid"
$ServerOut = Join-Path $Tools "server.out.log"
$ServerErr = Join-Path $Tools "server.err.log"
$PortFile = Join-Path $Tools "port.txt"

New-Item -ItemType Directory -Force -Path $Tools | Out-Null

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { throw "Не найден python. Установите Python и зависимости из requirements.txt." }

function Test-OurApp([int]$Candidate) {
    try {
        $Response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Candidate/health" -TimeoutSec 2
        return ($Response.StatusCode -eq 200 -and $Response.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

$Candidates = if ($Port -gt 0) { @($Port) } else { @(8000, 8001, 8010, 8020) }
$ChosenPort = $null
foreach ($Candidate in $Candidates) {
    if (Test-OurApp $Candidate) {
        $ChosenPort = $Candidate
        break
    }
    $Listener = Get-NetTCPConnection -LocalPort $Candidate -State Listen -ErrorAction SilentlyContinue
    if (-not $Listener) {
        $ChosenPort = $Candidate
        break
    }
    Write-Host "Порт $Candidate занят другим приложением, пробую следующий..." -ForegroundColor Yellow
}

if (-not $ChosenPort) {
    throw "Нет свободного порта. Освободите 8000 или запустите с -Port <номер>."
}
Set-Content -Path $PortFile -Value $ChosenPort

if (-not (Test-OurApp $ChosenPort)) {
    Write-Host "Запускаю FastAPI на 0.0.0.0:$ChosenPort..." -ForegroundColor Cyan
    $Process = Start-Process -FilePath $Python.Source `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$ChosenPort") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $ServerOut `
        -RedirectStandardError $ServerErr `
        -PassThru -WindowStyle Hidden
    Set-Content -Path $ServerPidFile -Value $Process.Id
}

$Ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-OurApp $ChosenPort) {
        $Ready = $true
        break
    }
}
if (-not $Ready) {
    Write-Host "Сервер не ответил. Логи:" -ForegroundColor Red
    if (Test-Path $ServerOut) { Get-Content $ServerOut -Tail 30 }
    if (Test-Path $ServerErr) { Get-Content $ServerErr -Tail 30 }
    throw "FastAPI не запустился."
}

Write-Host "Сервер готов: http://127.0.0.1:$ChosenPort" -ForegroundColor Green
try {
    Write-Host "Загружаю образцы документов..." -ForegroundColor Cyan
    & $Python.Source (Join-Path $Root "scripts\seed_sample_docs.py")
} catch {
    Write-Host "Образцы документов не загрузились, продолжаю запуск." -ForegroundColor Yellow
}
& (Join-Path $PSScriptRoot "keep_tunnel.ps1")
