# Публичная HTTPS-ссылка без одной Wi-Fi сети.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\start_public_tunnel.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$PidFile = Join-Path $Tools "tunnel.pid"
$UrlFile = Join-Path $Tools "public-url.txt"
$OutLog = Join-Path $Tools "tunnel.out.log"
$ErrLog = Join-Path $Tools "tunnel.err.log"

New-Item -ItemType Directory -Force -Path $Tools | Out-Null
Remove-Item $OutLog, $ErrLog -ErrorAction SilentlyContinue

if (Test-Path $PidFile) {
    $OldPid = Get-Content $PidFile | Select-Object -First 1
    if ($OldPid -and (Get-Process -Id ([int]$OldPid) -ErrorAction SilentlyContinue)) {
        Stop-Process -Id ([int]$OldPid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

$Ssh = Get-Command ssh -ErrorAction SilentlyContinue
if (-not $Ssh) {
    throw "Не найден ssh. Включите OpenSSH Client в Windows: Settings -> Optional Features."
}

$Args = @(
    "-R", "80:127.0.0.1:8000",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ExitOnForwardFailure=yes",
    "nokey@localhost.run"
)

$Process = Start-Process -FilePath $Ssh.Source -ArgumentList $Args `
    -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
    -PassThru -WindowStyle Hidden
Set-Content -Path $PidFile -Value $Process.Id

$Url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    foreach ($Log in @($OutLog, $ErrLog)) {
        if (Test-Path $Log) {
            $Match = Select-String -Path $Log -Pattern 'https://[a-z0-9]+\.lhr\.life' -AllMatches |
                Select-Object -First 1
            if ($Match) { $Url = $Match.Matches[0].Value; break }
        }
    }
    if ($Url) { break }
    $Process.Refresh()
    if ($Process.HasExited) { break }
}

if (-not $Url) {
    Write-Host "Не удалось получить публичный URL. Логи:" -ForegroundColor Red
    if (Test-Path $OutLog) { Get-Content $OutLog -Tail 30 }
    if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 30 }
    throw "Туннель не поднялся."
}

$Url = $Url.TrimEnd("/") + "/"
Set-Content -Path $UrlFile -Value $Url
python "$Root\scripts\make_qr.py" --url $Url

Write-Host ""
Write-Host "Публичная ссылка: $Url" -ForegroundColor Green
Write-Host "QR обновлён: qr\jury.png" -ForegroundColor Green
Write-Host "Ноутбук и эта вкладка должны оставаться включёнными. Ctrl+C — остановить." -ForegroundColor Yellow
Write-Host ""

Wait-Process -Id $Process.Id
