@echo off
title Mammouth Defroster 9000
cd /d "%~dp0"

echo =======================================================
echo          STARTING MAMMOUTH AI MCP SERVER
echo =======================================================
echo.

set TUNNEL_PORT=
for /f "tokens=*" %%A in ('powershell -NoProfile -Command "try { $c = Get-Content 'config.json' -Raw | ConvertFrom-Json; if ($c.server.auto_tunnel -and $c.server.tunnel_mode -eq 'Tailscale Funnel') { Write-Output $c.server.port } } catch {}"') do set TUNNEL_PORT=%%A

if defined TUNNEL_PORT (
    echo [1/2] Activating Tailscale Funnel on Port %TUNNEL_PORT% (auto_tunnel=true)...
    if exist "C:\Program Files\Tailscale\tailscale.exe" (
        "C:\Program Files\Tailscale\tailscale.exe" funnel --bg %TUNNEL_PORT%
    )
    echo Public URL: https://[your-tailscale-node].ts.net/sse
) else (
    echo [1/2] Public tunnel inactive (auto_tunnel=false). Local access only.
)
echo.

echo [2/2] Launching FastMCP Server...
echo Server is running! Press Ctrl+C in this window to stop.
echo -------------------------------------------------------

if exist "MammouthDefroster9000-server.exe" (
    MammouthDefroster9000-server.exe
) else if exist "MammouthDefroster9000.exe" (
    MammouthDefroster9000.exe --server-only
) else (
    uv run server.py
)

echo.
echo Server stopped.
pause
