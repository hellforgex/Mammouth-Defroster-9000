@echo off
title Stop Mammouth MCP Server
echo Stopping Mammouth MCP Server and Tailscale Funnel...
taskkill /F /IM MammouthDefroster9000.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Mammouth MCP Server*" 2>nul
"C:\Program Files\Tailscale\tailscale.exe" funnel --https=443 off
echo.
echo Server and Funnel stopped successfully.
pause
