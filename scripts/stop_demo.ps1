# Останавливает сервер и туннель, запущенные scripts\start_demo.ps1
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"

$SupervisorPidFile = Join-Path $Tools "tunnel-supervisor.pid"
$TunnelPidFile = Join-Path $Tools "tunnel.pid"
foreach ($file in @($SupervisorPidFile, $TunnelPidFile)) {
    if (Test-Path $file) {
        $processId = Get-Content $file | Select-Object -First 1
        if ($processId) {
            Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
            Write-Host "Туннель остановлен (PID $processId)."
        }
        Remove-Item $file -ErrorAction SilentlyContinue
    }
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
