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
echo Building PyInstaller binary...
python -m PyInstaller --noconfirm --onedir --windowed ^
    --name "MammouthDefroster9000" ^
    --add-data "modules;modules" ^
    --add-data "config.example.json;." ^
    --hidden-import "uvicorn" ^
    --hidden-import "fastmcp" ^
    --hidden-import "starlette" ^
    --hidden-import "customtkinter" ^
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    --hidden-import "mss" ^
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

echo ===================================================
echo   Build completed successfully! Output: dist\MammouthDefroster9000
echo ===================================================
