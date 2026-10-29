# Mammouth Defroster 9000 - Server Startup Script
$cfgPath = Join-Path $PSScriptRoot "config.json"
$autoTunnel = $false
$tunnelMode = "Tailscale Funnel"
$port = 8000

if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        if ($cfg.server.auto_tunnel -eq $true) { $autoTunnel = $true }
        if ($cfg.server.tunnel_mode) { $tunnelMode = $cfg.server.tunnel_mode }
        if ($cfg.server.port) { $port = [int]$cfg.server.port }
    } catch {}
}

if ($autoTunnel -and ($tunnelMode -eq "Tailscale Funnel")) {
    Write-Host "Activating Tailscale Funnel on port $port (auto_tunnel=true)..." -ForegroundColor Cyan
    if (Test-Path "C:\Program Files\Tailscale\tailscale.exe") {
        & "C:\Program Files\Tailscale\tailscale.exe" funnel --bg $port
    }
    
    # Attempt to detect dynamic Tailscale domain
    $tsDomain = $null
    try {
        $tsStatus = & "C:\Program Files\Tailscale\tailscale.exe" status --json | ConvertFrom-Json
        if ($tsStatus.Self.DNSName) {
            $tsDomain = "https://" + $tsStatus.Self.DNSName.TrimEnd('.') + "/sse"
        }
    } catch {}
    
    if ($tsDomain) {
        Write-Host "Public SSE Endpoint: $tsDomain" -ForegroundColor Yellow
    } else {
        Write-Host "Public SSE Endpoint: https://[your-tailscale-node].ts.net/sse" -ForegroundColor Yellow
    }
} else {
    Write-Host "[NETWORK] Public exposure tunnel is inactive by default (auto_tunnel=false). Binding locally to port $port." -ForegroundColor Gray
}

Write-Host "Starting Mammouth Defroster 9000 Server on port $port..." -ForegroundColor Green
uv run server.py
