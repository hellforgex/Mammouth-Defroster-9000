# Check config.json for auto_tunnel setting (Safe by Default)
$autoTunnel = $false
if (Test-Path "config.json") {
    try {
        $cfg = Get-Content "config.json" -Raw | ConvertFrom-Json
        if ($cfg.server.auto_tunnel -eq $true) {
            $autoTunnel = $true
        }
    } catch {}
}

if ($autoTunnel) {
    Write-Host "Starting Tailscale Funnel on port 8000 (auto_tunnel=true)..." -ForegroundColor Cyan
    & "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8000 2>$null

    # Attempt to detect dynamic Tailscale domain
    $tsDomain = $null
    try {
        $tsStatus = & "C:\Program Files\Tailscale\tailscale.exe" status --json | ConvertFrom-Json
        if ($tsStatus.Self.DNSName) {
            $tsDomain = "https://" + $tsStatus.Self.DNSName.TrimEnd('.') + "/sse"
        }
    } catch {}

    Write-Host "Starting Mammouth Defroster 9000 Server..." -ForegroundColor Green
    if ($tsDomain) {
        Write-Host "Public SSE Endpoint: $tsDomain" -ForegroundColor Yellow
    } else {
        Write-Host "Public SSE Endpoint: https://[your-tailscale-node].ts.net/sse" -ForegroundColor Yellow
    }
} else {
    Write-Host "Starting Mammouth Defroster 9000 Server..." -ForegroundColor Green
    Write-Host "Tailscale Funnel skipped (auto_tunnel=false). Server running in local loopback mode." -ForegroundColor Cyan
    Write-Host "Local SSE Endpoint: http://127.0.0.1:8000/sse" -ForegroundColor Yellow
}
uv run server.py
