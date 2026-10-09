"""
Mammouth Defroster 9000 - Auto-Updater Module
Checks GitHub Releases for updates, verifies SHA256 checksums, and performs
clean Windows process handoff via detached update runner.
"""

import os
import sys
import hashlib
import tempfile
import subprocess
from typing import Optional, Dict, Any, Tuple, Callable
import httpx
from packaging import version

GITHUB_REPO = "hellforgex/Mammouth-Defroster-9000"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def check_for_update(current_version: str) -> Optional[Dict[str, Any]]:
    """Check GitHub Releases for newer version of Mammouth Defroster 9000."""
    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MammouthDefroster9000-Updater/{current_version}"
        }
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(RELEASES_API_URL, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()

        tag = data.get("tag_name", "").strip()
        if not tag:
            return None

        # Compare semantic versions
        clean_current = current_version.lstrip("v").strip()
        clean_tag = tag.lstrip("v").strip()
        if version.parse(clean_tag) <= version.parse(clean_current):
            return None  # Current version is up to date

        # Locate zip asset and sha256 asset
        assets = data.get("assets", [])
        zip_url = ""
        zip_name = ""
        zip_size = 0
        sha256_url = ""

        for a in assets:
            name = a.get("name", "")
            if name.endswith("-windows-x64.zip"):
                zip_url = a.get("browser_download_url", "")
                zip_name = name
                zip_size = a.get("size", 0)
            elif name.endswith(".zip.sha256"):
                sha256_url = a.get("browser_download_url", "")

        if not zip_url or not sha256_url:
            return None

        return {
            "version": tag,
            "name": data.get("name", tag),
            "body": data.get("body", ""),
            "published_at": data.get("published_at", ""),
            "zip_url": zip_url,
            "zip_name": zip_name,
            "zip_size": zip_size,
            "sha256_url": sha256_url,
            "html_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}")
        }
    except Exception:
        return None


def download_and_verify_update(
    update_info: Dict[str, Any],
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> Tuple[bool, str]:
    """Download update ZIP and verify SHA256 checksum against GitHub release asset.
    Returns (True, downloaded_zip_path) or (False, error_message).
    """
    try:
        update_dir = os.path.join(tempfile.gettempdir(), "MammouthDefroster9000_Update")
        os.makedirs(update_dir, exist_ok=True)
        zip_path = os.path.join(update_dir, update_info.get("zip_name", "update.zip"))

        if progress_cb:
            progress_cb(0.1, "Connecting to GitHub download servers...")

        # 1. Download SHA256 checksum asset (MANDATORY for integrity verification)
        expected_sha256 = ""
        sha256_url = update_info.get("sha256_url", "")
        if not sha256_url:
            return False, "Security Error: Missing SHA256 checksum URL in release metadata! Cannot verify package."

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(sha256_url)
            if resp.status_code != 200:
                return False, f"Failed to download SHA256 checksum asset (HTTP {resp.status_code})"
            parts = resp.text.strip().split()
            if parts:
                expected_sha256 = parts[0].strip().lower()

        if not expected_sha256 or len(expected_sha256) != 64:
            return False, f"Security Error: Malformed or missing SHA256 checksum asset!"

        # 2. Download ZIP asset with streaming progress
        zip_url = update_info.get("zip_url", "")
        total_size = update_info.get("zip_size", 0)

        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            with client.stream("GET", zip_url) as stream:
                if stream.status_code != 200:
                    return False, f"Failed to download update package (HTTP {stream.status_code})"

                downloaded = 0
                hasher = hashlib.sha256()

                with open(zip_path, "wb") as f:
                    for chunk in stream.iter_bytes(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)
                            if progress_cb and total_size > 0:
                                pct = min(0.90, 0.10 + (downloaded / total_size) * 0.80)
                                progress_cb(pct, f"Downloading update ({downloaded // (1024 * 1024)}MB / {total_size // (1024 * 1024)}MB)...")

        # 3. Verify SHA256 integrity (Hard fail on any discrepancy)
        calculated_sha256 = hasher.hexdigest().lower()
        if calculated_sha256 != expected_sha256:
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return False, f"Security Error: SHA256 Checksum mismatch! Expected {expected_sha256}, got {calculated_sha256}"

        if progress_cb:
            progress_cb(1.0, "Update package verified successfully! Ready to apply.")

        return True, zip_path
    except Exception as e:
        return False, str(e)


def apply_update_and_restart(zip_path: str, target_dir: str, current_pid: int) -> bool:
    """Spawn detached Windows batch script to wait for app exit, extract update and relaunch."""
    try:
        update_dir = os.path.dirname(zip_path)
        batch_script = os.path.join(update_dir, "apply_update.bat")

        script_content = """@echo off
title Mammouth Defroster 9000 - Auto-Updater
echo ========================================================
echo   Mammouth Defroster 9000 - Applying Update...
echo ========================================================
timeout /t 2 /nobreak >nul

:wait_loop
tasklist /fi "PID eq %1" 2>nul | findstr /i "%1" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

echo Extracting update package...
powershell -NoProfile -Command "$tmp = Join-Path $env:TEMP ('MDefUpd_' + (Get-Random)); Expand-Archive -LiteralPath $env:MDEF_UPDATE_ZIP -DestinationPath $tmp -Force; Get-ChildItem -Path $tmp -Recurse | Unblock-File; $exclude = @('config.json', 'oauth.db', 'tasks.db', 'memory.db', 'hosts.json', 'credentials.json', 'data', 'workspace'); Get-ChildItem -Path $tmp | ForEach-Object { if ($_.Name -notin $exclude -or -not (Test-Path -LiteralPath (Join-Path $env:MDEF_TARGET_DIR $_.Name))) { Copy-Item -LiteralPath $_.FullName -Destination $env:MDEF_TARGET_DIR -Recurse -Force } }; Remove-Item $tmp -Recurse -Force"

echo Launching updated Mammouth Defroster 9000...
start "" "%~2\\MammouthDefroster9000.exe"

echo Cleaning up temporary update files and reclaiming disk space...
del "%~3" 2>nul
powershell -NoProfile -Command "Get-ChildItem -Path $env:TEMP -Filter 'MDefUpd_*' -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" 2>nul
cd /d "%TEMP%"
start /b "" cmd /c "timeout /t 2 /nobreak >nul & rmdir /s /q \"%~dp0\" 2>nul"
exit
"""
        with open(batch_script, "w", encoding="utf-8") as f:
            f.write(script_content)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        # Paths reach PowerShell via environment variables so that quotes or
        # apostrophes in folder names cannot break out of the command string.
        child_env = os.environ.copy()
        child_env["MDEF_TARGET_DIR"] = str(target_dir)
        child_env["MDEF_UPDATE_ZIP"] = str(zip_path)

        subprocess.Popen(
            ["cmd.exe", "/c", batch_script, str(current_pid), target_dir, zip_path],
            creationflags=creationflags,
            env=child_env,
            close_fds=True
        )
        return True
    except Exception:
        return False
