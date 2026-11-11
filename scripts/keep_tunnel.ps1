# Держит публичный туннель живым: если SSH отвалился, поднимает заново и обновляет QR.
# Использование: powershell -ExecutionPolicy Bypass -File scripts\keep_tunnel.ps1
$ErrorActionPreference = "Continue"

while ($true) {
    try {
        & (Join-Path $PSScriptRoot "start_public_tunnel.ps1")
    } catch {
        Write-Host "Туннель упал: $($_.Exception.Message). Перезапуск через 3 секунды..." -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 3
}
