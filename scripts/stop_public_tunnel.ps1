# Останавливает туннель и его супервизор.
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$SupervisorPidFile = Join-Path $Tools "tunnel-supervisor.pid"
$PidFile = Join-Path $Tools "tunnel.pid"

# Сначала останавливаем супервизор, иначе он перезапустит туннель.
foreach ($file in @($SupervisorPidFile, $PidFile)) {
    if (Test-Path $file) {
        $processId = Get-Content $file | Select-Object -First 1
        if ($processId) {
            Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
            Write-Host "Остановлен процесс $processId."
        }
        Remove-Item $file -ErrorAction SilentlyContinue
    }
}

# На случай, если PID-файл потерялся: добиваем только клиент Tunnelmole.
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -like "*tunnelmole*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
