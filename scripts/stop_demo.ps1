# Останавливает сервер и туннель, запущенные scripts\start_demo.ps1
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"

$TunnelPidFile = Join-Path $Tools "tunnel.pid"
if (Test-Path $TunnelPidFile) {
    $TunnelPid = Get-Content $TunnelPidFile | Select-Object -First 1
    if ($TunnelPid) {
        Stop-Process -Id ([int]$TunnelPid) -Force -ErrorAction SilentlyContinue
        Write-Host "Туннель остановлен (PID $TunnelPid)."
    }
    Remove-Item $TunnelPidFile -ErrorAction SilentlyContinue
}

$ServerPidFile = Join-Path $Tools "server.pid"
if (Test-Path $ServerPidFile) {
    $ServerPid = Get-Content $ServerPidFile | Select-Object -First 1
    if ($ServerPid) {
        Stop-Process -Id ([int]$ServerPid) -Force -ErrorAction SilentlyContinue
        Write-Host "Сервер остановлен (PID $ServerPid)."
    }
    Remove-Item $ServerPidFile -ErrorAction SilentlyContinue
}
