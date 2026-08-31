@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Mammouth Defroster 9000 - Production Build Script
echo ===================================================

REM 1. Clean previous build artifacts
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"

REM 2. Ensure virtualenv or system python is available
python -m pip install --upgrade pyinstaller

REM 3. Build standalone GUI executable
echo Building PyInstaller binary with full asset collection...
python -m PyInstaller --noconfirm --onedir --windowed ^
    --name "MammouthDefroster9000" ^
    --icon "assets\icon.ico" ^
    --add-data "assets;assets" ^
    --add-data "modules;modules" ^
    --add-data "config.example.json;." ^
    --add-data "hosts.example.json;." ^
    --collect-all "customtkinter" ^
    --collect-all "PIL" ^
    --collect-all "fastmcp" ^
    --collect-all "uvicorn" ^
    --collect-all "starlette" ^
    --collect-all "mss" ^
    --hidden-import "server" ^
    --hidden-import "config" ^
    --hidden-import "pystray" ^
    gui.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed!
    exit /b %ERRORLEVEL%
)

REM 4. Release hygiene: Ensure empty api_token in bundle config
echo Scrubbing bundle configurations...
if exist "dist\MammouthDefroster9000\_internal\config.json" (
    del /f /q "dist\MammouthDefroster9000\_internal\config.json"
)
if exist "dist\MammouthDefroster9000\_internal\mcpserv\config.json" (
    del /f /q "dist\MammouthDefroster9000\_internal\mcpserv\config.json"
)

REM Copy sanitized config.example.json as initial default config.json
copy "config.example.json" "dist\MammouthDefroster9000\config.json" /Y
copy "SECURITY.md" "dist\MammouthDefroster9000\SECURITY.md" /Y
copy "CHANGELOG.md" "dist\MammouthDefroster9000\CHANGELOG.md" /Y
copy "README.md" "dist\MammouthDefroster9000\README.md" /Y
if exist "LICENSE" copy "LICENSE" "dist\MammouthDefroster9000\LICENSE" /Y

echo ===================================================
echo   Build completed successfully! Output: dist\MammouthDefroster9000
echo ===================================================
