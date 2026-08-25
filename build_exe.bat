@echo off
title Build Mammouth Control Center EXE
cd /d "%~dp0"

echo =======================================================
echo     BUILDING MAMMOUTH CONTROL CENTER STANDALONE EXE
echo =======================================================
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [1/2] Installing build dependencies via uv...
    uv pip install -r requirements.txt
    echo.
    echo [2/2] Running PyInstaller...
    uv run pyinstaller --noconfirm --onedir --windowed --name "MammouthControlCenter" --add-data "modules;modules" --collect-all customtkinter gui.py
) else (
    echo [1/2] Installing build dependencies via pip...
    pip install -r requirements.txt
    echo.
    echo [2/2] Running PyInstaller...
    pyinstaller --noconfirm --onedir --windowed --name "MammouthControlCenter" --add-data "modules;modules" --collect-all customtkinter gui.py
)

echo.
echo =======================================================
if exist "dist\MammouthControlCenter\MammouthControlCenter.exe" (
    echo BUILD SUCCESSFUL!
    echo Standalone application located in: dist\MammouthControlCenter\
) else (
    echo BUILD FAILED. Check console output above.
)
echo =======================================================
pause
