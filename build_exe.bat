@echo off
title Build Mammouth Defroster 9000 EXE
cd /d "%~dp0"

echo =======================================================
echo     BUILDING MAMMOUTH DEFROSTER 9000 STANDALONE EXE
echo =======================================================
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [1/2] Installing build dependencies via uv...
    uv pip install -r requirements.txt
    echo.
    echo [2/2] Running PyInstaller...
    uv run pyinstaller --noconfirm --onedir --windowed --name "MammouthDefroster9000" --add-data "modules;modules" --collect-all customtkinter gui.py
) else (
    echo [1/2] Installing build dependencies via pip...
    pip install -r requirements.txt
    echo.
    echo [2/2] Running PyInstaller...
    pyinstaller --noconfirm --onedir --windowed --name "MammouthDefroster9000" --add-data "modules;modules" --collect-all customtkinter gui.py
)

echo.
echo =======================================================
if exist "dist\MammouthDefroster9000\MammouthDefroster9000.exe" (
    echo BUILD SUCCESSFUL!
    echo Standalone application located in: dist\MammouthDefroster9000\
) else (
    echo BUILD FAILED. Check console output above.
)
echo =======================================================
pause
