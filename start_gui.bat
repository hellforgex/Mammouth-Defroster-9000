@echo off
title Mammouth MCP Control Center
cd /d "%~dp0"

echo Starting Mammouth MCP Control Center...

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run gui.py
) else (
    python gui.py
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo An error occurred while running the GUI.
    pause
)
