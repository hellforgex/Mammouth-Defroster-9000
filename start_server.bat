@echo off
title Mammouth Defroster 9000
cd /d "%~dp0"

echo =======================================================
echo          STARTING MAMMOUTH AI MCP SERVER
echo =======================================================
echo.

REM Check if auto_tunnel is enabled in config.json (Safe by Default)
set "AUTO_TUNNEL=0"
if exist "config.json" (
    findstr /i /c:"\"auto_tunnel\": true" "config.json" >nul 2>&1
    if not errorlevel 1 set "AUTO_TUNNEL=1"
    findstr /i /c:"\"auto_tunnel\":true" "config.json" >nul 2>&1
    if not errorlevel 1 set "AUTO_TUNNEL=1"
)

if "%AUTO_TUNNEL%"=="1" (
    echo [1/2] Activating Tailscale Funnel on Port 8000 (auto_tunnel=true)...
    if exist "C:\Program Files\Tailscale\tailscale.exe" (
        "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8000
    )
    echo Public URL: https://[your-tailscale-node].ts.net/sse
) else (
    echo [1/2] Tailscale Funnel skipped (auto_tunnel=false).
    echo Server will bind to local host (127.0.0.1:8000).
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
