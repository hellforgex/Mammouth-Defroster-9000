@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Mammouth Defroster 9000 - Production Build Script
echo ===================================================

REM 0. Ensure existing processes are closed
taskkill /F /IM MammouthDefroster9000.exe 2>nul
taskkill /F /IM MammouthDefroster9000-server.exe 2>nul
timeout /t 1 /nobreak >nul

REM 1. Clean previous build artifacts
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"

REM 2. Ensure virtualenv or system python is available
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

REM 3. Build standalone GUI & Server executables using spec file
echo Building PyInstaller binaries with dual targets (GUI + Console Server)...
%PYTHON_EXE% -m PyInstaller --noconfirm MammouthDefroster9000.spec

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed!
    exit /b %ERRORLEVEL%
)

REM 4. Release hygiene: Ensure NO secrets or personal credentials in bundle
echo Scrubbing bundle configurations and credentials...
if exist "dist\MammouthDefroster9000\_internal\config.json" (
    del /f /q "dist\MammouthDefroster9000\_internal\config.json"
)
if exist "dist\MammouthDefroster9000\_internal\mcpserv\config.json" (
    del /f /q "dist\MammouthDefroster9000\_internal\mcpserv\config.json"
)
if exist "dist\MammouthDefroster9000\credentials.json" del /f /q "dist\MammouthDefroster9000\credentials.json"
if exist "dist\MammouthDefroster9000\gdrive_token.json" del /f /q "dist\MammouthDefroster9000\gdrive_token.json"
if exist "dist\MammouthDefroster9000\service_account.json" del /f /q "dist\MammouthDefroster9000\service_account.json"
if exist "dist\MammouthDefroster9000\storage_state.json" del /f /q "dist\MammouthDefroster9000\storage_state.json"

REM Copy sanitized configs and examples
if not exist "dist\MammouthDefroster9000\assets" mkdir "dist\MammouthDefroster9000\assets"
copy "assets\*" "dist\MammouthDefroster9000\assets\" /Y
copy "config.example.json" "dist\MammouthDefroster9000\config.json" /Y
copy "config.example.json" "dist\MammouthDefroster9000\config.example.json" /Y
copy "hosts.example.json" "dist\MammouthDefroster9000\hosts.example.json" /Y
if exist "credentials.example.json" copy "credentials.example.json" "dist\MammouthDefroster9000\credentials.example.json" /Y
copy "start_server.bat" "dist\MammouthDefroster9000\start_server.bat" /Y
copy "start_gui.bat" "dist\MammouthDefroster9000\start_gui.bat" /Y
if exist "stop_server.bat" copy "stop_server.bat" "dist\MammouthDefroster9000\stop_server.bat" /Y
if exist "start_server.ps1" copy "start_server.ps1" "dist\MammouthDefroster9000\start_server.ps1" /Y
copy "SECURITY.md" "dist\MammouthDefroster9000\SECURITY.md" /Y
copy "CHANGELOG.md" "dist\MammouthDefroster9000\CHANGELOG.md" /Y
copy "README.md" "dist\MammouthDefroster9000\README.md" /Y
if exist "RELEASE_NOTES.md" copy "RELEASE_NOTES.md" "dist\MammouthDefroster9000\" /Y
if exist "LICENSE" copy "LICENSE" "dist\MammouthDefroster9000\LICENSE" /Y
copy "install.ps1" "dist\MammouthDefroster9000\" /Y
if exist "cloudflared.exe" copy "cloudflared.exe" "dist\MammouthDefroster9000\" /Y

echo ===================================================
echo   Packaging release ZIP: MammouthDefroster9000-v0.5.1-windows-x64.zip
echo ===================================================
powershell -Command "Compress-Archive -Path 'dist\MammouthDefroster9000\*' -DestinationPath '..\MammouthDefroster9000-v0.5.1-windows-x64.zip' -Force"
%PYTHON_EXE% -c "import hashlib; h = hashlib.sha256(open('..\MammouthDefroster9000-v0.5.1-windows-x64.zip', 'rb').read()).hexdigest().lower(); open('..\MammouthDefroster9000-v0.5.1-windows-x64.zip.sha256', 'w').write(h + '\n')"

echo ===================================================
echo   Syncing to unpacked test directory: ..\MammouthDefroster9000-v0.5.1
echo ===================================================
if not exist "..\MammouthDefroster9000-v0.5.1" mkdir "..\MammouthDefroster9000-v0.5.1"
robocopy "dist\MammouthDefroster9000" "..\MammouthDefroster9000-v0.5.1" /E /NP /NFL /NDL /R:0 /W:0 /XF config.json oauth.db tasks.db memory.db hosts.json credentials.json /XD data workspace

if not exist "..\releases" mkdir "..\releases"
copy "..\MammouthDefroster9000-v0.5.1-windows-x64.zip" "..\releases\" /Y
copy "..\MammouthDefroster9000-v0.5.1-windows-x64.zip.sha256" "..\releases\" /Y

echo ===================================================
echo   Build completed successfully! Output: dist\MammouthDefroster9000
echo ===================================================
