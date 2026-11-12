# Starts the demo server + public HTTPS tunnel fully detached from the assistant.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_demo_detached.ps1
#
# After this, you may close the assistant, terminal or editor: the demo keeps
# running until you run scripts\stop_demo.ps1, log off or reboot.
#
# Optional: -Port 8000 / -Port 8010 to force a port, -NoRestart to keep an
# already healthy server on the requested port (otherwise a detached one is used).

param(
    [int]$Port = 0,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
New-Item -ItemType Directory -Force -Path $Tools | Out-Null

$HostScript = Join-Path $PSScriptRoot "demo_host.ps1"
$HostPidFile = Join-Path $Tools "demo-host.pid"
$SupPidFile = Join-Path $Tools "tunnel-supervisor.pid"
$ServerPidFile = Join-Path $Tools "server.pid"
$PortFile = Join-Path $Tools "port.txt"
$UrlFile = Join-Path $Tools "public-url.txt"

function Get-IdFromFile([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $raw = Get-Content $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsed = 0
    if ($raw -and [int]::TryParse($raw, [ref]$parsed)) { return [int]$parsed }
    return 0
}

function Test-Alive([int]$Id) {
    if (-not $Id -or $Id -le 0) { return $false }
    return [bool](Get-Process -Id $Id -ErrorAction SilentlyContinue)
}

function Test-Health([string]$BaseUrl) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing ($BaseUrl.TrimEnd("/") + "/health") -TimeoutSec 8
        return ($r.StatusCode -eq 200 -and $r.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

function Test-LocalHealth([int]$Candidate) {
    if (-not $Candidate -or $Candidate -le 0) { return $false }
    return (Test-Health ("http://127.0.0.1:{0}" -f $Candidate))
}

function Stop-PidFile([string]$Path, [string]$Label) {
    $id = Get-IdFromFile $Path
    if ($id -and (Test-Alive $id)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host ("stopped {0} (pid {1})" -f $Label, $id)
    }
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

if ($NoRestart) {
    $target = if ($Port -gt 0) { $Port } else { 8001 }
    if (Test-LocalHealth $target) {
        Write-Host ("server already healthy on port {0}; nothing to do" -f $target) -ForegroundColor Green
        if (Test-Path $UrlFile) {
            Write-Host ("public URL: {0}" -f ((Get-Content $UrlFile | Select-Object -First 1).Trim()))
        }
        exit 0
    }
}

$OldUrl = ""
if (Test-Path $UrlFile) {
    $OldUrl = (Get-Content $UrlFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    Write-Host ("previous public URL was: {0}" -f $OldUrl)
}

Write-Host "stopping instances that belong to the assistant..." -ForegroundColor Cyan
Stop-PidFile $HostPidFile "demo host"
Stop-PidFile $SupPidFile "tunnel supervisor"
Stop-PidFile $ServerPidFile "demo server"

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -like "*tunnelmole*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*uvicorn app.main:app*" -and $_.ProcessId -ne $PID } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host ("stopped uvicorn (pid {0})" -f $_.ProcessId)
    }

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "powershell.exe" -and $_.CommandLine -like "*keep_tunnel.ps1*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Seconds 2

$chosenPort = 8001
if (Test-Path $PortFile) {
    $rawPort = Get-Content $PortFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsedPort = 0
    if ($rawPort -and [int]::TryParse($rawPort, [ref]$parsedPort) -and $parsedPort -gt 0) { $chosenPort = $parsedPort }
}
if ($Port -gt 0) { $chosenPort = $Port }
$Port = $chosenPort
Set-Content -Path $PortFile -Value $Port -Encoding ASCII

Write-Host "starting detached demo host..." -ForegroundColor Cyan
$commandLine = 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $HostScript + '"'
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $commandLine
    CurrentDirectory = $Root
}
if ($result.ReturnValue -ne 0) {
    throw ("failed to start the detached host (Win32_Process.Create returned {0})" -f $result.ReturnValue)
}

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 700
    if (Test-LocalHealth $Port) {
        $ready = $true
        break
    }
}
if (-not $ready) {
    Write-Host "server did not become healthy; last log lines:" -ForegroundColor Red
    foreach ($log in @((Join-Path $Tools "demo-host.log"), (Join-Path $Tools "server.err.log"))) {
        if (Test-Path $log) { Get-Content $log -Tail 20 }
    }
    throw "detached demo server failed to start"
}
Write-Host ("server is up on port {0}" -f $Port) -ForegroundColor Green

Write-Host "waiting for a fresh public URL (the old one stops working)..." -ForegroundColor Cyan
$newUrl = ""
for ($i = 0; $i -lt 150; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $UrlFile) {
        $candidate = (Get-Content $UrlFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($candidate -and (Test-Health $candidate)) {
            $newUrl = $candidate
            break
        }
    }
}
if (-not $newUrl) {
    throw "tunnel did not publish a healthy URL; check tools\tunnel.log"
}

Write-Host ""
Write-Host ("PUBLIC URL: {0}" -f $newUrl) -ForegroundColor Green
Write-Host ("QR:         {0}" -f (Join-Path $Root "qr\jury.png")) -ForegroundColor Green
Write-Host "The demo keeps running after you close the assistant."
Write-Host "Stop it with: powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1"
