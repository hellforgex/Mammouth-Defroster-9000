# Start Mammouth MCP Server and ensure Tailscale Funnel is active
Write-Host "Starting Tailscale Funnel on port 8000..." -ForegroundColor Cyan
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
uv run server.py
