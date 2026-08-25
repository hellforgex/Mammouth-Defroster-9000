@echo off
title Build Mammouth Defroster 9000 EXE
cd /d "%~dp0"

echo =======================================================
echo     BUILDING MAMMOUTH DEFROSTER 9000 STANDALONE EXE
echo =======================================================
echo.

where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [1/3] Installing build dependencies via uv...
    uv pip install -r requirements.txt
    echo.
    echo [2/3] Running PyInstaller...
    uv run pyinstaller --noconfirm --onedir --windowed --name "MammouthDefroster9000" ^
        --icon "assets\icon.ico" ^
        --add-data "assets;assets" ^
        --add-data "modules;modules" ^
        --add-data "config.example.json;." ^
        --add-data "hosts.example.json;." ^
        --collect-all customtkinter ^
        --collect-all PIL ^
        --collect-all fastmcp ^
        --collect-all uvicorn ^
        --collect-all starlette ^
        --hidden-import server ^
        --hidden-import config ^
        --hidden-import modules.file_ops ^
        --hidden-import modules.memory ^
        --hidden-import modules.putty_ssh ^
        --hidden-import modules.shell_processes ^
        --hidden-import modules.system_monitor ^
        --hidden-import modules.tasks_kanban ^
        --hidden-import modules.web_tools ^
        gui.py
) else (
    echo [1/3] Installing build dependencies via pip...
    pip install -r requirements.txt
    echo.
    echo [2/3] Running PyInstaller...
    pyinstaller --noconfirm --onedir --windowed --name "MammouthDefroster9000" ^
        --icon "assets\icon.ico" ^
        --add-data "assets;assets" ^
        --add-data "modules;modules" ^
        --add-data "config.example.json;." ^
        --add-data "hosts.example.json;." ^
        --collect-all customtkinter ^
        --collect-all PIL ^
        --collect-all fastmcp ^
        --collect-all uvicorn ^
        --collect-all starlette ^
        --hidden-import server ^
        --hidden-import config ^
        --hidden-import modules.file_ops ^
        --hidden-import modules.memory ^
        --hidden-import modules.putty_ssh ^
        --hidden-import modules.shell_processes ^
        --hidden-import modules.system_monitor ^
        --hidden-import modules.tasks_kanban ^
        --hidden-import modules.web_tools ^
        gui.py
)

echo.
echo [3/3] Copying runtime templates to distribution...
if exist "dist\MammouthDefroster9000" (
    if not exist "dist\MammouthDefroster9000\assets" mkdir "dist\MammouthDefroster9000\assets"
    copy /y "assets\*" "dist\MammouthDefroster9000\assets\" >nul 2>nul
    copy /y "config.example.json" "dist\MammouthDefroster9000\" >nul 2>nul
    copy /y "hosts.example.json" "dist\MammouthDefroster9000\" >nul 2>nul
    copy /y "README.md" "dist\MammouthDefroster9000\" >nul 2>nul
    copy /y "LICENSE" "dist\MammouthDefroster9000\" >nul 2>nul
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
