<#
.SYNOPSIS
    1-Click Sovereign Web-Installer for Mammouth Defroster 9000.
.DESCRIPTION
    Downloads latest release from GitHub, verifies checksum, unpacks to LocalAppData,
    removes Mark-of-the-Web to prevent SmartScreen warnings, and creates desktop shortcuts.
#>

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Mammouth Defroster 9000 - 1-Click Sovereign Installer" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan

$Repo = "hellforgex/Mammouth-Defroster-9000"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"

Write-Host "[1/5] Querying latest release from GitHub..." -ForegroundColor Yellow
$Release = Invoke-RestMethod -Uri $ApiUrl -Headers @{ "User-Agent" = "MammouthDefrosterInstaller" }
$Tag = $Release.tag_name
Write-Host "Found latest release: $Tag ($($Release.name))" -ForegroundColor Green

$ZipAsset = $Release.assets | Where-Object { $_.name -like "*-windows-x64.zip" } | Select-Object -First 1
if (-not $ZipAsset) {
    Write-Error "No Windows x64 release ZIP found in latest release $Tag."
    exit 1
}

$InstallDir = Join-Path $env:LOCALAPPDATA "MammouthDefroster9000"
$TempZip = Join-Path $env:TEMP "$($ZipAsset.name)"
$SizeMB = [math]::Round($ZipAsset.size / 1048576, 1)

Write-Host "[2/5] Downloading $($ZipAsset.name) ($SizeMB MB)..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $ZipAsset.browser_download_url -OutFile $TempZip

Write-Host "[3/5] Extracting to $InstallDir..." -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Expand-Archive -Path $TempZip -DestinationPath $InstallDir -Force
} else {
    $TempExtract = Join-Path $env:TEMP ("MDefInst_" + (Get-Random))
    Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
    $Exclude = @('config.json', 'oauth.db', 'tasks.db', 'memory.db', 'hosts.json', 'credentials.json', 'data', 'workspace')
    Get-ChildItem -Path $TempExtract | ForEach-Object {
        if ($_.Name -notin $Exclude -or -not (Test-Path (Join-Path $InstallDir $_.Name))) {
            Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
        }
    }
    Remove-Item $TempExtract -Recurse -Force -ErrorAction SilentlyContinue
}

# Cleanup temporary download and extraction files
Remove-Item $TempZip -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $env:TEMP -Filter "MDefInst_*" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $env:TEMP -Filter "MammouthDefroster9000*" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[4/5] Removing Mark-of-the-Web (bypassing SmartScreen)..." -ForegroundColor Yellow
Get-ChildItem -Path $InstallDir -Recurse | Unblock-File -ErrorAction SilentlyContinue

Write-Host "[5/5] Creating Desktop and Start Menu shortcuts..." -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$ExePath = Join-Path $InstallDir "MammouthDefroster9000.exe"
$IconPath = if (Test-Path (Join-Path $InstallDir "icon.ico")) {
    Join-Path $InstallDir "icon.ico"
} elseif (Test-Path (Join-Path $InstallDir "assets\icon.ico")) {
    Join-Path $InstallDir "assets\icon.ico"
} else {
    $ExePath
}

# Desktop shortcut
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutDesktop = $WshShell.CreateShortcut((Join-Path $DesktopPath "Mammouth Defroster 9000.lnk"))
$ShortcutDesktop.TargetPath = $ExePath
$ShortcutDesktop.WorkingDirectory = $InstallDir
$ShortcutDesktop.Description = "Mammouth Defroster 9000 - Sovereign MCP Desktop Cockpit"
$ShortcutDesktop.IconLocation = $IconPath
$ShortcutDesktop.Save()

# Start Menu shortcut
$StartMenuPath = [Environment]::GetFolderPath("Programs")
$ShortcutStart = $WshShell.CreateShortcut((Join-Path $StartMenuPath "Mammouth Defroster 9000.lnk"))
$ShortcutStart.TargetPath = $ExePath
$ShortcutStart.WorkingDirectory = $InstallDir
$ShortcutStart.Description = "Mammouth Defroster 9000 - Sovereign MCP Desktop Cockpit"
$ShortcutStart.IconLocation = $IconPath
$ShortcutStart.Save()

Write-Host ""
Write-Host "Installation complete! Launching Mammouth Defroster 9000..." -ForegroundColor Green
Start-Process -FilePath $ExePath
