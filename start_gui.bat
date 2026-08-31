@echo off
title Mammouth Defroster 9000
cd /d "%~dp0"

echo Starting Mammouth Defroster 9000...

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
