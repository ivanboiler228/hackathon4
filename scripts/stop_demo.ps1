# Stops the detached demo: host, tunnel supervisor, tunnel client and server.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"

function Get-IdFromFile([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $raw = Get-Content $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsed = 0
    if ($raw -and [int]::TryParse($raw, [ref]$parsed)) { return [int]$parsed }
    return 0
}

function Stop-PidFile([string]$Path, [string]$Label) {
    $id = Get-IdFromFile $Path
    if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host ("stopped {0} (pid {1})" -f $Label, $id)
    }
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

Stop-PidFile (Join-Path $Tools "demo-host.pid") "demo host"
Stop-PidFile (Join-Path $Tools "tunnel-supervisor.pid") "tunnel supervisor"
Stop-PidFile (Join-Path $Tools "server.pid") "demo server"

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -like "*tunnelmole*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host ("stopped tunnel client (pid {0})" -f $_.ProcessId)
    }

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "powershell.exe" -and $_.CommandLine -like "*demo_host.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*uvicorn app.main:app*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host ("stopped uvicorn (pid {0})" -f $_.ProcessId)
    }

Write-Host "demo stopped"
