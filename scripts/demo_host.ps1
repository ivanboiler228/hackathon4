# Keeps the demo alive independently of the assistant UI.
# Started detached by scripts\start_demo_detached.ps1 (parent = WmiPrvSE),
# so closing the assistant / terminal / editor does not stop it.
#
# Loop every 10s:
#   - FastAPI on the demo port answers /health? if not, restart it.
#   - Tunnelmole supervisor process alive? if not, start it.

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
New-Item -ItemType Directory -Force -Path $Tools | Out-Null

$HostPidFile = Join-Path $Tools "demo-host.pid"
$LogFile = Join-Path $Tools "demo-host.log"
$PortFile = Join-Path $Tools "port.txt"
$ServerPidFile = Join-Path $Tools "server.pid"
$ServerOut = Join-Path $Tools "server.out.log"
$ServerErr = Join-Path $Tools "server.err.log"
$SupPidFile = Join-Path $Tools "tunnel-supervisor.pid"
$KeepTunnel = Join-Path $PSScriptRoot "keep_tunnel.ps1"

function Write-Log([string]$Text) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 1MB) {
        $tail = Get-Content $LogFile -Tail 400
        Set-Content -Path $LogFile -Value $tail -Encoding UTF8
    }
}

function Get-DemoPort {
    $port = 8001
    if (Test-Path $PortFile) {
        $stored = Get-Content $PortFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($stored -and [int]::TryParse($stored, [ref]$port) -and $port -gt 0) { return [int]$port }
    }
    return 8001
}

function Get-PythonPath {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    foreach ($candidate in @("C:\Python315\python.exe", "C:\Python313\python.exe", "C:\Python312\python.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Test-DemoHealth([int]$Port) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 3
        return ($r.StatusCode -eq 200 -and $r.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

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

function Start-DemoServer([int]$Port) {
    $old = Get-IdFromFile $ServerPidFile
    if ($old -and (Test-Alive $old)) {
        Stop-Process -Id $old -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    $python = Get-PythonPath
    if (-not $python) {
        Write-Log "python not found; cannot start the server"
        return
    }
    $p = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $ServerOut `
        -RedirectStandardError $ServerErr `
        -PassThru -WindowStyle Hidden
    Set-Content -Path $ServerPidFile -Value $p.Id -Encoding ASCII
    Write-Log "server started on port $Port (pid $($p.Id))"
}

function Start-DemoTunnel {
    $old = Get-IdFromFile $SupPidFile
    if ($old -and (Test-Alive $old)) { return }
    $p = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$KeepTunnel`"") `
        -WorkingDirectory $Root `
        -PassThru -WindowStyle Hidden
    Write-Log "tunnel supervisor started (pid $($p.Id))"
}

# Only one demo host may run at a time.
$existing = Get-IdFromFile $HostPidFile
if ($existing -and $existing -ne $PID -and (Test-Alive $existing)) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$existing" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like "*demo_host.ps1*") { exit }
}

Set-Content -Path $HostPidFile -Value $PID -Encoding ASCII
Write-Log "demo host started (pid $PID)"

$initialPort = Get-DemoPort
if (-not (Test-DemoHealth $initialPort)) { Start-DemoServer $initialPort }
Start-DemoTunnel

while ($true) {
    Start-Sleep -Seconds 10
    $port = Get-DemoPort
    if (-not (Test-DemoHealth $port)) {
        Write-Log "health check failed on 127.0.0.1:$port; restarting the server"
        Start-DemoServer $port
        Start-Sleep -Seconds 3
    }
    Start-DemoTunnel
}
