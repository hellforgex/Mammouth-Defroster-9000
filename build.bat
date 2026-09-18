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

REM 3. Build standalone GUI & Server executables using spec file
echo Building PyInstaller binaries with dual targets (GUI + Console Server)...
python -m PyInstaller --noconfirm MammouthDefroster9000.spec

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
copy "config.example.json" "dist\MammouthDefroster9000\config.example.json" /Y
copy "hosts.example.json" "dist\MammouthDefroster9000\hosts.example.json" /Y
copy "start_server.bat" "dist\MammouthDefroster9000\start_server.bat" /Y
copy "start_gui.bat" "dist\MammouthDefroster9000\start_gui.bat" /Y
if exist "stop_server.bat" copy "stop_server.bat" "dist\MammouthDefroster9000\stop_server.bat" /Y
if exist "start_server.ps1" copy "start_server.ps1" "dist\MammouthDefroster9000\start_server.ps1" /Y
copy "SECURITY.md" "dist\MammouthDefroster9000\SECURITY.md" /Y
copy "CHANGELOG.md" "dist\MammouthDefroster9000\CHANGELOG.md" /Y
copy "README.md" "dist\MammouthDefroster9000\README.md" /Y
if exist "RELEASE_NOTES.md" copy "RELEASE_NOTES.md" "dist\MammouthDefroster9000\" /Y
if exist "LICENSE" copy "LICENSE" "dist\MammouthDefroster9000\LICENSE" /Y
if exist "cloudflared.exe" copy "cloudflared.exe" "dist\MammouthDefroster9000\" /Y

echo ===================================================
echo   Packaging release ZIP: MammouthDefroster9000-v0.2.3-windows-x64.zip
echo ===================================================
powershell -Command "Compress-Archive -Path 'dist\MammouthDefroster9000\*' -DestinationPath '..\MammouthDefroster9000-v0.2.3-windows-x64.zip' -Force"

echo ===================================================
echo   Syncing to unpacked test directory: ..\MammouthDefroster9000-v0.2.3
echo ===================================================
if not exist "..\MammouthDefroster9000-v0.2.3" mkdir "..\MammouthDefroster9000-v0.2.3"
robocopy "dist\MammouthDefroster9000" "..\MammouthDefroster9000-v0.2.3" /E /NP /NFL /NDL /R:1 /W:1 /PURGE

echo ===================================================
echo   Build completed successfully! Output: dist\MammouthDefroster9000
echo ===================================================
