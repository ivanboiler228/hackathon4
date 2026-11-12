# Supervised public HTTPS tunnel for the demo (Tunnelmole, no account needed).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\keep_tunnel.ps1
# Keeps the tunnel alive, publishes only healthy URLs and regenerates
# qr\jury.png whenever the public address changes.
$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$PortFile = Join-Path $Tools "port.txt"
$UrlFile = Join-Path $Tools "public-url.txt"
$PidFile = Join-Path $Tools "tunnel.pid"
$OutLog = Join-Path $Tools "tunnel.out.log"
$ErrLog = Join-Path $Tools "tunnel.err.log"
$SupervisorLog = Join-Path $Tools "tunnel.log"
$SupervisorPidFile = Join-Path $Tools "tunnel-supervisor.pid"
$TmRoot = Join-Path $Tools "tunnelmole"
$TmScript = Join-Path $TmRoot "node_modules\tunnelmole\dist\bin\tunnelmole.js"

New-Item -ItemType Directory -Force -Path $Tools | Out-Null

# Only one supervisor and one Tunnelmole client may run at a time.
if (Test-Path $SupervisorPidFile) {
    $oldSupervisor = Get-Content $SupervisorPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldSupervisor -and [int]$oldSupervisor -ne $PID) {
        Stop-Process -Id ([int]$oldSupervisor) -Force -ErrorAction SilentlyContinue
    }
}
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -like "*tunnelmole*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Set-Content -Path $SupervisorPidFile -Value $PID -Encoding ASCII

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    Add-Content -Path $SupervisorLog -Value $line -Encoding UTF8
    Write-Host $line
    if ((Test-Path $SupervisorLog) -and ((Get-Item $SupervisorLog).Length -gt 1MB)) {
        $tail = Get-Content $SupervisorLog -Tail 500
        Set-Content -Path $SupervisorLog -Value $tail -Encoding UTF8
    }
}

function Get-AppPort {
    $port = 8001
    if (Test-Path $PortFile) {
        $stored = Get-Content $PortFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($stored -and [int]::TryParse($stored, [ref]$port)) { return [int]$port }
    }
    return 8001
}

function Ensure-Tunnelmole {
    if (Test-Path $TmScript) { return }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { throw "Node.js/npm not found. Install Node.js or put a prebuilt Tunnelmole client into tools\tunnelmole." }
    Write-Log "installing Tunnelmole client into tools\tunnelmole"
    & $npm.Source install --prefix $TmRoot --no-audit --no-fund tunnelmole@latest | Out-Null
    if (-not (Test-Path $TmScript)) { throw "Tunnelmole client was not installed." }
}

function Test-Health([string]$BaseUrl, [int]$TimeoutSec = 20) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing ($BaseUrl.TrimEnd("/") + "/health") -TimeoutSec $TimeoutSec
        return ($response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

function Test-LocalHealth([int]$Port) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:$Port/health") -TimeoutSec 4
        return ($response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

function Find-PublicUrl([System.Diagnostics.Process]$Process, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        foreach ($log in @($OutLog, $ErrLog)) {
            if (Test-Path $log) {
                $match = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.tunnelmole\.net' -AllMatches |
                    Select-Object -First 1
                if ($match) { return $match.Matches[0].Value }
            }
        }
        $Process.Refresh()
        if ($Process.HasExited) { return $null }
    }
    return $null
}

function Publish-Url([string]$BaseUrl) {
    $BaseUrl = $BaseUrl.TrimEnd("/") + "/"
    Set-Content -Path $UrlFile -Value $BaseUrl -Encoding ASCII
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source (Join-Path $Root "scripts\make_qr.py") --url $BaseUrl | Out-Null
    }
    Write-Log "PUBLIC URL: $BaseUrl"
    Write-Host ""
    Write-Host "Публичная ссылка: $BaseUrl" -ForegroundColor Green
    Write-Host "QR сохранён:      qr\jury.png" -ForegroundColor Green
    Write-Host ""
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js not found. Install Node.js LTS and retry." }
Ensure-Tunnelmole

$restarts = 0
while ($true) {
    $port = Get-AppPort
    Remove-Item $OutLog, $ErrLog, $PidFile -ErrorAction SilentlyContinue

    Write-Log "starting Tunnelmole tunnel to 127.0.0.1:$port"
    $process = Start-Process -FilePath $node.Source -ArgumentList @($TmScript, "$port") `
        -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
        -PassThru -WindowStyle Hidden
    Set-Content -Path $PidFile -Value $process.Id -Encoding ASCII

    $url = Find-PublicUrl $process
    if (-not $url) {
        Write-Log "tunnel did not return a URL; restarting"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        continue
    }

    $healthy = $false
    for ($i = 0; $i -lt 10; $i++) {
        if (Test-Health $url 15) { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        Write-Log "URL $url is not healthy yet; restarting"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        continue
    }

    Publish-Url $url
    Write-Log "warming up the public route"
    for ($i = 0; $i -lt 3; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing ($url.TrimEnd("/") + "/health") -TimeoutSec 20 | Out-Null
        } catch { }
    }
    try {
        Invoke-WebRequest -UseBasicParsing ($url.TrimEnd("/") + "/") -Headers @{ "Accept-Encoding" = "gzip" } -TimeoutSec 30 | Out-Null
    } catch { }
    Write-Log "public route is warm"
    $restarts = 0
    $fails = 0

    while ($true) {
        Start-Sleep -Seconds 12
        $process.Refresh()
        if ($process.HasExited) {
            Write-Log "tunnel process exited; reconnecting"
            break
        }
        if (Test-Health $url 12) {
            $fails = 0
        } else {
            $fails++
            Write-Log "health check failed ($fails/3)"
            if ($fails -ge 3) {
                if (Test-LocalHealth $port) {
                    Write-Log "tunnel is unhealthy; reconnecting"
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    break
                }
                Write-Log "local server is down; keeping the tunnel and waiting"
                $fails = 0
            }
        }
    }

    Remove-Item $PidFile -ErrorAction SilentlyContinue
    $restarts++
    if ($restarts -gt 20) {
        Write-Log "too many restarts in a row; cooling down for 30 seconds"
        Start-Sleep -Seconds 30
        $restarts = 0
    } else {
        Start-Sleep -Seconds 3
    }
}
