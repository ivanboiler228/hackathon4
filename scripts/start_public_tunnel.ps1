# Starts the supervised public HTTPS tunnel.
# The actual reconnect/health logic lives in keep_tunnel.ps1 so there is
# exactly one supervisor and one source of truth for the public URL.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "keep_tunnel.ps1")
