# Останавливает туннель, запущенный scripts\start_public_tunnel.ps1
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "tools\tunnel.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "PID туннеля не найден."
    return
}

$TunnelPid = Get-Content $PidFile | Select-Object -First 1
if ($TunnelPid) {
    Stop-Process -Id ([int]$TunnelPid) -Force -ErrorAction SilentlyContinue
    Write-Host "Туннель остановлен (PID $TunnelPid)."
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
