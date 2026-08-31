@echo off
title Mammouth Defroster 9000
cd /d "%~dp0"

echo =======================================================
echo          STARTING MAMMOUTH AI MCP SERVER
echo =======================================================
echo.

echo [1/2] Activating Tailscale Funnel on Port 8000...
"C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8000 2>nul
echo.

echo [2/2] Launching FastMCP Server...
echo Public URL: https://[your-tailscale-node].ts.net/sse
echo.
echo Server is running! Press Ctrl+C in this window to stop.
echo -------------------------------------------------------

if exist "MammouthDefroster9000.exe" (
    MammouthDefroster9000.exe
) else (
    uv run server.py
)

echo.
echo Server stopped.
pause
