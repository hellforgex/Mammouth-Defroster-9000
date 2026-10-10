import os
import sys
import io
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from PIL import Image as PILImage, ImageGrab
except ImportError:
    PILImage = None
    ImageGrab = None

try:
    import mss
    import mss.tools
except ImportError:
    mss = None

try:
    from fastmcp.utilities.types import Image as FastMCPImage
except Exception:
    FastMCPImage = None

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

WORKSPACE_DIR = BASE_DIR / "workspace" / "screenshots"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

def _cleanup_old_screenshots(max_keep: int = 25, max_age_hours: int = 24):
    """Keep only the most recent screenshots and clean up files older than max_age_hours."""
    try:
        if not WORKSPACE_DIR.exists():
            return
        now_ts = time.time()
        files = sorted(
            [f for f in WORKSPACE_DIR.glob("*.png") if f.is_file()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        for f in files:
            if now_ts - f.stat().st_mtime > max_age_hours * 3600:
                try:
                    f.unlink()
                except Exception:
                    pass

        # Newest first, so only the oldest files beyond max_keep are deleted
        remaining = sorted(
            [f for f in WORKSPACE_DIR.glob("*.png") if f.is_file()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if len(remaining) > max_keep:
            for old_file in remaining[max_keep:]:
                try:
                    old_file.unlink()
                except Exception:
                    pass
    except Exception:
        pass

def screen_list_monitors() -> List[Dict[str, Any]]:
    """List all detected monitors, their screen resolutions, and primary display status."""
    monitors_info = []
    if mss is not None:
        try:
            with mss.mss() as sct:
                for idx, m in enumerate(sct.monitors):
                    if idx == 0:
                        # 0 is the entire combined virtual screen
                        continue
                    monitors_info.append({
                        "monitor_index": idx,
                        "width": m.get("width"),
                        "height": m.get("height"),
                        "left": m.get("left"),
                        "top": m.get("top"),
                        "is_primary": bool(m.get("is_primary", idx == 1)),
                        "name": m.get("name", f"Monitor {idx}")
                    })
                if monitors_info:
                    return monitors_info
        except Exception:
            pass

    return [{
        "monitor_index": 1,
        "is_primary": True,
        "name": "Default Primary Display",
        "description": "Standard Windows Display"
    }]

_last_screen_capture_time = 0.0
_user_consent_granted: bool = False
_consent_mode: str = "none"  # "none", "once", "always"
_consent_prompt_callback = None


def set_consent_prompt_callback(callback):
    """Register an interactive UI callback (e.g. Tkinter modal dialog) for user consent."""
    global _consent_prompt_callback
    _consent_prompt_callback = callback


def screen_grant_consent(duration: str = "once") -> Dict[str, Any]:
    """Grant explicit user consent for desktop screenshot capture.
    
    Args:
        duration: 'once' for single-shot capture or 'always' for persistent session consent.
    """
    global _user_consent_granted, _consent_mode
    _user_consent_granted = True
    _consent_mode = duration if duration in ("once", "always") else "once"
    return {
        "status": "success",
        "consent_mode": _consent_mode,
        "message": f"Desktop screen capture consent granted ({_consent_mode})."
    }


def screen_revoke_consent() -> Dict[str, Any]:
    """Revoke desktop screenshot consent."""
    global _user_consent_granted, _consent_mode
    _user_consent_granted = False
    _consent_mode = "none"
    return {"status": "success", "consent_mode": "none", "message": "Consent revoked."}


def _is_consent_required() -> bool:
    try:
        from config import load_config
        cfg = load_config()
        return bool(cfg.get("modules", {}).get("screen_capture", {}).get("require_consent", True))
    except Exception:
        return True


def _check_screen_capture_rate_limit(min_interval: float = 0.5):
    """M-07: Rate limit screen captures to prevent abusive screen scraping."""
    global _last_screen_capture_time
    now = time.time()
    if now - _last_screen_capture_time < min_interval:
        time.sleep(min_interval - (now - _last_screen_capture_time))
    _last_screen_capture_time = time.time()


def screen_capture(
    monitor: int = 1,
    max_width: Optional[int] = 1920,
    quality: int = 85,
    save_to_workspace: bool = True
) -> Any:
    """Capture a high-resolution screenshot of any connected display or full desktop.
    
    Args:
        monitor: 1 for Primary Monitor, 2+ for Secondary, 0 for all combined screens.
        max_width: Scale down image width to conserve LLM vision tokens (e.g. 1920, 1280, default 1920).
        quality: Image compression quality (1-100, default 85).
        save_to_workspace: Whether to save PNG copy in ./workspace/screenshots/ (default True).
    """
    return _screen_capture_impl(monitor, max_width, quality, save_to_workspace, local_ui=False)


def screen_capture_local(
    monitor: int = 1,
    max_width: Optional[int] = 1920,
    quality: int = 85,
    save_to_workspace: bool = True
) -> Any:
    """Screenshot initiated by the human in the desktop GUI (button / hotkey).

    The click itself is the consent, so the gate is skipped for this one capture WITHOUT
    changing the global consent state that governs MCP clients. Not registered as an MCP tool.
    """
    return _screen_capture_impl(monitor, max_width, quality, save_to_workspace, local_ui=True)


def _screen_capture_impl(monitor: int, max_width: Optional[int], quality: int, save_to_workspace: bool, local_ui: bool) -> Any:
    global _user_consent_granted, _consent_mode

    # M-07: Consent-Gate Check (skipped only for captures the human triggered in the GUI)
    if not local_ui and _is_consent_required() and not _user_consent_granted:
        # If an interactive UI callback is registered (e.g. desktop cockpit GUI), prompt the user directly
        if _consent_prompt_callback is not None:
            try:
                prompt_res = _consent_prompt_callback()
                if prompt_res in ("always", "once"):
                    _user_consent_granted = True
                    _consent_mode = prompt_res
                elif prompt_res == "denied":
                    return {
                        "status": "denied",
                        "message": "Desktop screen capture was explicitly denied by the user."
                    }
            except Exception:
                pass

        if not _user_consent_granted:
            return {
                "status": "consent_required",
                "message": "Desktop screen capture requires explicit user consent. Please ask the user to allow it in the Defroster desktop UI."
            }

    # Consume single-use consent
    if not local_ui and _consent_mode == "once":
        _user_consent_granted = False
        _consent_mode = "none"

    _check_screen_capture_rate_limit()
    if PILImage is None and mss is None:
        return {
            "error": "Pillow and MSS packages are required for Desktop Vision. Install with: pip install mss pillow"
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_mon{monitor}_{timestamp}.png"
    filepath = WORKSPACE_DIR / filename
    
    pil_image = None
    
    # Method 1: Try MSS (fast & multi-monitor accurate)
    if mss is not None:
        try:
            with mss.mss() as sct:
                target_mon = sct.monitors[min(monitor, len(sct.monitors) - 1)]
                sct_img = sct.grab(target_mon)
                pil_image = PILImage.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            pil_image = None

    # Method 2: Try PIL ImageGrab fallback
    if pil_image is None and ImageGrab is not None:
        try:
            pil_image = ImageGrab.grab(all_screens=(monitor == 0))
        except Exception:
            pil_image = None

    if pil_image is None:
        return {
            "error": "Failed to capture screen. Ensure display permissions and Pillow/MSS dependencies are installed."
        }

    original_size = pil_image.size
    
    # Optional downscaling to conserve vision LLM tokens
    if max_width is not None:
        effective_max_w = max(320, min(int(max_width), 7680))
        if pil_image.width > effective_max_w:
            ratio = effective_max_w / float(pil_image.width)
            new_height = int(float(pil_image.height) * ratio)
            resample_filter = getattr(PILImage, "Resampling", getattr(PILImage, "ANTIALIAS", None))
            resample_mode = getattr(resample_filter, "LANCZOS", PILImage.LANCZOS if hasattr(PILImage, "LANCZOS") else 1)
            pil_image = pil_image.resize((effective_max_w, new_height), resample_mode)

    # Save to disk if requested with automatic retention policy
    saved_path_str = ""
    if save_to_workspace:
        try:
            pil_image.save(str(filepath), format="PNG", optimize=True)
            saved_path_str = str(filepath)
            _cleanup_old_screenshots(max_keep=25)
        except Exception as e:
            saved_path_str = f"Error saving to disk: {e}"

    # Convert to bytes for FastMCP Image response
    img_byte_arr = io.BytesIO()
    if quality < 100:
        pil_image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
        mime_type = "image/jpeg"
        img_format = "jpeg"
    else:
        pil_image.save(img_byte_arr, format="PNG", optimize=True)
        mime_type = "image/png"
        img_format = "png"
        
    img_bytes = img_byte_arr.getvalue()

    if FastMCPImage is not None:
        try:
            return FastMCPImage(data=img_bytes, format=img_format)
        except Exception:
            pass

    import base64
    b64_str = base64.b64encode(img_bytes).decode("utf-8")
    return {
        "status": "success",
        "monitor": monitor,
        "original_resolution": f"{original_size[0]}x{original_size[1]}",
        "current_resolution": f"{pil_image.width}x{pil_image.height}",
        "saved_path": saved_path_str,
        "format": img_format,
        "mime_type": mime_type,
        "base64_preview": f"data:{mime_type};base64,{b64_str[:100]}... [total {len(b64_str)} chars]"
    }


def copy_image_to_clipboard(image_or_path) -> bool:
    """Copies an image (file path or PIL Image object) to the Windows clipboard as CF_DIB with retries."""
    if os.name != "nt":
        return False
    try:
        from PIL import Image
        import win32clipboard, io, time
        if isinstance(image_or_path, (str, Path)):
            img = Image.open(str(image_or_path))
        else:
            img = image_or_path
        
        output = io.BytesIO()
        img.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]  # 14-byte BMP header stripped for CF_DIB
        output.close()
        
        for _ in range(5):
            opened = False
            try:
                win32clipboard.OpenClipboard()
                opened = True
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                return True
            except Exception:
                time.sleep(0.06)
            finally:
                if opened:
                    try:
                        win32clipboard.CloseClipboard()
                    except Exception:
                        pass
        return False
    except Exception:
        return False



def launch_windows_snipping_tool() -> bool:
    """Launches the native Windows Screen Clip / Snipping Tool overlay (Win+Shift+S)."""
    if os.name != "nt":
        return False
    try:
        import subprocess
        subprocess.Popen(["cmd.exe", "/c", "start", "ms-screenclip:"], shell=False)
        return True
    except Exception:
        return False


def get_clipboard_image():
    """Retrieves an image from the Windows clipboard if present, else None."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is not None and hasattr(img, "save"):
            return img
    except Exception:
        pass
    return None


def save_clipboard_image(dest_path: Optional[str] = None) -> Optional[str]:
    """Saves the current clipboard image to workspace/screenshots/ and returns the path."""
    img = get_clipboard_image()
    if img is None:
        return None
    try:
        if not dest_path:
            filename = f"snip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            dest_file = WORKSPACE_DIR / filename
        else:
            dest_file = Path(dest_path)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(dest_file), format="PNG", optimize=True)
        _cleanup_old_screenshots(max_keep=25)
        return str(dest_file)
    except Exception:
        return None


def get_foreground_window_info() -> Dict[str, Any]:
    """Inspect the active foreground window on Windows using Win32 API.
    
    Returns:
        dict: {
            "hwnd": int,
            "title": str,
            "process_id": int,
            "process_name": str,
            "rect": {"left": int, "top": int, "right": int, "bottom": int, "width": int, "height": int}
        }
    """
    if sys.platform != "win32":
        return {
            "hwnd": 0,
            "title": "Desktop / Display",
            "process_id": 0,
            "process_name": "",
            "rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080}
        }

    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {
                "hwnd": 0,
                "title": "Desktop / Full Screen",
                "process_id": 0,
                "process_name": "explorer.exe",
                "rect": {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}
            }

        # Window title
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value

        # Process ID & Name
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_id = pid.value
        proc_name = ""
        if proc_id:
            try:
                import psutil
                proc = psutil.Process(proc_id)
                proc_name = proc.name()
            except Exception:
                proc_name = ""

        # Window Rect (Try DwmGetWindowAttribute with DWMWA_EXTENDED_FRAME_BOUNDS = 9 for clean borderless rect)
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        rect_found = False
        try:
            dwmapi = ctypes.windll.dwmapi
            hr = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            if hr == 0:
                rect_found = True
        except Exception:
            pass

        if not rect_found:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

        is_minimized = bool(user32.IsIconic(hwnd)) or (rect.left <= -10000)
        width = 0 if is_minimized else max(0, rect.right - rect.left)
        height = 0 if is_minimized else max(0, rect.bottom - rect.top)

        return {
            "hwnd": int(hwnd),
            "title": title or "Untitled Window",
            "process_id": int(proc_id),
            "process_name": proc_name,
            "is_minimized": is_minimized,
            "rect": {
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
                "width": int(width),
                "height": int(height)
            }
        }
    except Exception as e:
        return {
            "hwnd": 0,
            "title": f"Unknown (Error: {e})",
            "process_id": 0,
            "process_name": "",
            "rect": {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}
        }


def screen_capture_active_window(
    save_to_workspace: bool = True,
    include_metadata: bool = True,
    max_width: Optional[int] = 1920,
    quality: int = 85
) -> Any:
    """Capture a screenshot of the currently active foreground window on Windows with metadata.

    Args:
        save_to_workspace: Whether to save PNG copy in ./workspace/screenshots/ (default True).
        include_metadata: Whether to return window title, process name, and geometry metadata (default True).
        max_width: Scale down image width to conserve vision LLM tokens (default 1920).
        quality: Image compression quality (1-100, default 85).
    """
    return _screen_capture_active_window_impl(
        save_to_workspace=save_to_workspace,
        include_metadata=include_metadata,
        max_width=max_width,
        quality=quality,
        local_ui=False
    )


def screen_capture_active_window_local(
    save_to_workspace: bool = True,
    include_metadata: bool = True,
    max_width: Optional[int] = 1920,
    quality: int = 85
) -> Any:
    """Active window capture initiated locally from desktop GUI / hotkey (bypasses MCP consent gate)."""
    return _screen_capture_active_window_impl(
        save_to_workspace=save_to_workspace,
        include_metadata=include_metadata,
        max_width=max_width,
        quality=quality,
        local_ui=True
    )


def _screen_capture_active_window_impl(
    save_to_workspace: bool,
    include_metadata: bool,
    max_width: Optional[int],
    quality: int,
    local_ui: bool
) -> Any:
    global _user_consent_granted, _consent_mode

    # M-07: Consent-Gate Check (skipped only for captures triggered in local GUI / hotkey)
    if not local_ui and _is_consent_required() and not _user_consent_granted:
        if _consent_prompt_callback is not None:
            try:
                prompt_res = _consent_prompt_callback()
                if prompt_res in ("always", "once"):
                    _user_consent_granted = True
                    _consent_mode = prompt_res
                elif prompt_res == "denied":
                    return {
                        "status": "denied",
                        "message": "Desktop screen capture was explicitly denied by the user."
                    }
            except Exception:
                pass

        if not _user_consent_granted:
            return {
                "status": "consent_required",
                "message": "Desktop screen capture requires explicit user consent. Please ask the user to allow it in the Defroster desktop UI."
            }

    # Consume single-use consent
    if not local_ui and _consent_mode == "once":
        _user_consent_granted = False
        _consent_mode = "none"

    _check_screen_capture_rate_limit()

    if PILImage is None and mss is None:
        return {
            "error": "Pillow and MSS packages are required for Desktop Vision. Install with: pip install mss pillow"
        }

    # Get active foreground window info
    win_info = get_foreground_window_info()
    rect = win_info.get("rect", {})
    w = rect.get("width", 0)
    h = rect.get("height", 0)

    pil_image = None

    # Attempt capturing window bounding box if dimensions valid and window is on-screen
    if w > 10 and h > 10 and rect.get("left", 0) > -10000 and rect.get("top", 0) > -10000 and not win_info.get("is_minimized", False):
        # Method 1: MSS
        if mss is not None:
            try:
                with mss.mss() as sct:
                    monitor_bbox = {
                        "left": rect["left"],
                        "top": rect["top"],
                        "width": rect["width"],
                        "height": rect["height"]
                    }
                    sct_img = sct.grab(monitor_bbox)
                    pil_image = PILImage.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception:
                pil_image = None

        # Method 2: PIL ImageGrab
        if pil_image is None and ImageGrab is not None:
            try:
                bbox = (rect["left"], rect["top"], rect["right"], rect["bottom"])
                pil_image = ImageGrab.grab(bbox=bbox, all_screens=True)
            except Exception:
                pil_image = None

    # Fallback if window capture was unavailable: capture primary screen
    if pil_image is None:
        if mss is not None:
            try:
                with mss.mss() as sct:
                    target_mon = sct.monitors[min(1, len(sct.monitors) - 1)]
                    sct_img = sct.grab(target_mon)
                    pil_image = PILImage.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception:
                pil_image = None

        if pil_image is None and ImageGrab is not None:
            try:
                pil_image = ImageGrab.grab(all_screens=False)
            except Exception:
                pil_image = None

    if pil_image is None:
        return {
            "error": "Failed to capture window or screen. Ensure display permissions and dependencies."
        }

    original_size = pil_image.size

    # Optional downscaling
    if max_width is not None:
        effective_max_w = max(320, min(int(max_width), 7680))
        if pil_image.width > effective_max_w:
            ratio = effective_max_w / float(pil_image.width)
            new_height = int(float(pil_image.height) * ratio)
            resample_filter = getattr(PILImage, "Resampling", getattr(PILImage, "ANTIALIAS", None))
            resample_mode = getattr(resample_filter, "LANCZOS", PILImage.LANCZOS if hasattr(PILImage, "LANCZOS") else 1)
            pil_image = pil_image.resize((effective_max_w, new_height), resample_mode)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_proc = "".join(c for c in win_info.get("process_name", "app") if c.isalnum() or c in ("-", "_")) or "window"
    filename = f"window_{clean_proc}_{timestamp}.png"
    filepath = WORKSPACE_DIR / filename

    saved_path_str = ""
    if save_to_workspace:
        try:
            pil_image.save(str(filepath), format="PNG", optimize=True)
            saved_path_str = str(filepath)
            _cleanup_old_screenshots(max_keep=25)
        except Exception as e:
            saved_path_str = f"Error saving to disk: {e}"

    # Convert to bytes
    img_byte_arr = io.BytesIO()
    if quality < 100:
        pil_image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
        mime_type = "image/jpeg"
        img_format = "jpeg"
    else:
        pil_image.save(img_byte_arr, format="PNG", optimize=True)
        mime_type = "image/png"
        img_format = "png"

    img_bytes = img_byte_arr.getvalue()

    if not include_metadata and FastMCPImage is not None:
        try:
            return FastMCPImage(data=img_bytes, format=img_format)
        except Exception:
            pass

    import base64
    b64_str = base64.b64encode(img_bytes).decode("utf-8")
    return {
        "status": "success",
        "window_title": win_info.get("title", ""),
        "process_name": win_info.get("process_name", ""),
        "process_id": win_info.get("process_id", 0),
        "hwnd": win_info.get("hwnd", 0),
        "window_rect": win_info.get("rect", {}),
        "original_resolution": f"{original_size[0]}x{original_size[1]}",
        "current_resolution": f"{pil_image.width}x{pil_image.height}",
        "saved_path": saved_path_str,
        "format": img_format,
        "mime_type": mime_type,
        "base64_preview": f"data:{mime_type};base64,{b64_str[:100]}... [total {len(b64_str)} chars]"
    }



