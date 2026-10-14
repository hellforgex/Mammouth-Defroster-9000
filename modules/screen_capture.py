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

def get_workspace_screenshots_dir() -> Path:
    """Dynamically resolve screenshots directory inside the active workspace root."""
    try:
        from modules.shell_processes import resolve_workspace_root
        ws = Path(resolve_workspace_root())
    except Exception:
        ws = BASE_DIR / "workspace"
    out = ws / "screenshots"
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return out


WORKSPACE_DIR = get_workspace_screenshots_dir()


def _cleanup_old_screenshots(target_dir: Optional[Path] = None, max_keep: int = 25, max_age_hours: int = 24):
    """Keep only the most recent screenshots and clean up files older than max_age_hours."""
    try:
        folder = target_dir or get_workspace_screenshots_dir()
        if not folder.exists():
            return
        now_ts = time.time()
        files = sorted(
            [f for f in folder.glob("*.png") if f.is_file()],
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
            [f for f in folder.glob("*.png") if f.is_file()],
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

# Multimodal Screen Copilot tracking state
_tracked_target_hwnd: Optional[int] = None
_tracked_target_title: Optional[str] = None
_tracked_target_process: Optional[str] = None
_tracked_mode: str = "auto"  # "auto", "window", "monitor", "snip"


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
    target_dir = get_workspace_screenshots_dir()
    filepath = target_dir / filename
    
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
            _cleanup_old_screenshots(target_dir=target_dir, max_keep=25)
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
            target_dir = get_workspace_screenshots_dir()
            dest_file = target_dir / filename
        else:
            dest_file = Path(dest_path)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            target_dir = dest_file.parent
        img.save(str(dest_file), format="PNG", optimize=True)
        _cleanup_old_screenshots(target_dir=target_dir, max_keep=25)
        return str(dest_file)
    except Exception:
        return None


def get_window_info(hwnd: Optional[int] = None) -> Dict[str, Any]:
    """Inspect a window (or active foreground window if hwnd is None) on Windows using Win32 API.
    
    Returns:
        dict: {
            "hwnd": int,
            "title": str,
            "process_id": int,
            "process_name": str,
            "is_minimized": bool,
            "rect": {"left": int, "top": int, "right": int, "bottom": int, "width": int, "height": int}
        }
    """
    if sys.platform != "win32":
        return {
            "hwnd": hwnd or 0,
            "title": "Desktop / Display",
            "process_id": 0,
            "process_name": "",
            "is_minimized": False,
            "rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080}
        }

    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        target_hwnd = hwnd if hwnd is not None else user32.GetForegroundWindow()
        if not target_hwnd:
            return {
                "hwnd": 0,
                "title": "Desktop / Full Screen",
                "process_id": 0,
                "process_name": "explorer.exe",
                "is_minimized": False,
                "rect": {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}
            }

        # Window title
        length = user32.GetWindowTextLengthW(target_hwnd)
        title = ""
        if length > 0:
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(target_hwnd, title_buf, length + 1)
            title = title_buf.value

        # Process ID & Name
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(pid))
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
            hr = dwmapi.DwmGetWindowAttribute(target_hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            if hr == 0:
                rect_found = True
        except Exception:
            pass

        if not rect_found:
            user32.GetWindowRect(target_hwnd, ctypes.byref(rect))

        is_minimized = bool(user32.IsIconic(target_hwnd)) or (rect.left <= -10000)
        width = 0 if is_minimized else max(0, rect.right - rect.left)
        height = 0 if is_minimized else max(0, rect.bottom - rect.top)

        return {
            "hwnd": int(target_hwnd),
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
            "hwnd": int(hwnd or 0),
            "title": f"Unknown (Error: {e})",
            "process_id": 0,
            "process_name": "",
            "is_minimized": False,
            "rect": {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}
        }


def _ensure_dpi_awareness():
    """Ensure process is Per-Monitor DPI aware so window bounding boxes match physical screen pixels."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def is_defroster_window(hwnd: int) -> bool:
    """Check if the given HWND belongs to Mammouth Defroster 9000 or its children (WebView2)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        cur_pid = os.getpid()
        if pid.value == cur_pid:
            return True
        try:
            import psutil
            proc = psutil.Process(pid.value)
            proc_name = proc.name().lower()
            if proc_name in ("mammouthdefroster9000.exe", "mammouthdefroster9000-server.exe"):
                return True
            parent = proc.parent()
            if parent and parent.pid == cur_pid:
                return True
        except Exception:
            pass
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "mammouth defroster" in buf.value.lower():
                return True
    except Exception:
        pass
    return False


def get_topmost_external_window() -> Optional[Dict[str, Any]]:
    """Find the top-most visible, non-minimized window in Z-order that is NOT Defroster."""
    wins = screen_list_windows(include_minimized=False, include_system=False, exclude_self=True)
    return wins[0] if wins else None


def get_target_window_info(hwnd: Optional[int] = None, exclude_defroster: bool = True) -> Dict[str, Any]:
    """Resolve target window to capture: explicit target_hwnd -> tracked window -> top external window -> foreground window."""
    global _tracked_target_hwnd
    _ensure_dpi_awareness()
    if hwnd is not None:
        return get_window_info(hwnd)

    # 1. Explicit tracked window
    if _tracked_target_hwnd:
        try:
            import ctypes
            if ctypes.windll.user32.IsWindow(_tracked_target_hwnd):
                info = get_window_info(_tracked_target_hwnd)
                if not info.get("is_minimized") and info.get("rect", {}).get("width", 0) > 10:
                    return info
        except Exception:
            pass

    # 2. Inspect active foreground window
    fg_info = get_foreground_window_info()
    fg_hwnd = fg_info.get("hwnd", 0)
    if exclude_defroster and is_defroster_window(fg_hwnd):
        top_ext = get_topmost_external_window()
        if top_ext:
            return top_ext

    return fg_info


def capture_window_via_printwindow(hwnd: int) -> Optional[Any]:
    """Capture a window directly via Win32 PrintWindow (PW_RENDERFULLCONTENT).
    Works cleanly even when the target window is partially or completely obscured by other windows.
    """
    if sys.platform != "win32" or not hwnd or PILImage is None:
        return None
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        dwmapi = ctypes.windll.dwmapi

        if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
            return None

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]
        rect = RECT()
        hr = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if hr != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

        w = max(0, rect.right - rect.left)
        h = max(0, rect.bottom - rect.top)
        if w < 10 or h < 10:
            return None

        hdc_win = user32.GetWindowDC(hwnd)
        if not hdc_win:
            return None
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        if not hdc_mem:
            user32.ReleaseDC(hwnd, hdc_win)
            return None

        hbm = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        if not hbm:
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc_win)
            return None

        old_bm = gdi32.SelectObject(hdc_mem, hbm)

        # 2 = PW_RENDERFULLCONTENT (Win8.1+)
        res = user32.PrintWindow(hwnd, hdc_mem, 2)
        if not res:
            res = user32.PrintWindow(hwnd, hdc_mem, 0)

        img = None
        if res:
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.wintypes.DWORD),
                    ('biWidth', ctypes.c_long),
                    ('biHeight', ctypes.c_long),
                    ('biPlanes', ctypes.wintypes.WORD),
                    ('biBitCount', ctypes.wintypes.WORD),
                    ('biCompression', ctypes.wintypes.DWORD),
                    ('biSizeImage', ctypes.wintypes.DWORD),
                    ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long),
                    ('biClrUsed', ctypes.wintypes.DWORD),
                    ('biClrImportant', ctypes.wintypes.DWORD),
                ]
            class BITMAPINFO(ctypes.Structure):
                _fields_ = [
                    ('bmiHeader', BITMAPINFOHEADER),
                    ('bmiColors', ctypes.wintypes.DWORD * 3),
                ]

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # top-down DIB
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0

            buffer = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(hdc_mem, hbm, 0, h, buffer, ctypes.byref(bmi), 0)
            if lines:
                raw_img = PILImage.frombuffer('RGBA', (w, h), buffer, 'raw', 'BGRA', 0, 1).convert('RGB')
                extrema = raw_img.getextrema()
                if any(mx > mn for (mn, mx) in extrema):
                    img = raw_img

        gdi32.SelectObject(hdc_mem, old_bm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)
        gdi32.DeleteObject(hbm)
        return img
    except Exception:
        return None


def screen_set_tracked_window(target: Any) -> Dict[str, Any]:
    """Set the target application or window to track for screenshots.

    Args:
        target: HWND integer, or process/title search query (e.g. 'code.exe', 'Chrome', 'Notepad'),
                or 'auto' to automatically track the most active external window,
                or 'monitor' to capture the entire desktop display,
                or 'snip' to use the interactive snipping tool.
    """
    global _tracked_target_hwnd, _tracked_target_title, _tracked_target_process, _tracked_mode
    query_str = str(target).strip()
    if query_str.lower() in ("auto", "none", "0"):
        _tracked_target_hwnd = None
        _tracked_target_title = None
        _tracked_target_process = None
        _tracked_mode = "auto"
        return {"status": "success", "mode": "auto", "message": "Tracking set to Auto (Active non-Defroster window)."}

    if query_str.lower() in ("monitor", "screen", "fullscreen", "1"):
        _tracked_target_hwnd = None
        _tracked_target_title = None
        _tracked_target_process = None
        _tracked_mode = "monitor"
        return {"status": "success", "mode": "monitor", "message": "Tracking set to Full Desktop Monitor."}

    if query_str.lower() in ("snip", "snipping", "clip"):
        _tracked_target_hwnd = None
        _tracked_target_title = None
        _tracked_target_process = None
        _tracked_mode = "snip"
        return {"status": "success", "mode": "snip", "message": "Tracking set to Interactive Snipping Tool."}

    target_hwnd = None
    if isinstance(target, int):
        target_hwnd = target
    elif query_str.isdigit():
        target_hwnd = int(query_str)
    else:
        wins = screen_list_windows(include_minimized=True, include_system=False, exclude_self=True)
        q = query_str.lower()
        matched = None
        for w in wins:
            if q in w.get("process_name", "").lower() or q in w.get("title", "").lower():
                matched = w
                break
        if matched:
            target_hwnd = matched["hwnd"]

    if target_hwnd:
        info = get_window_info(target_hwnd)
        _tracked_target_hwnd = target_hwnd
        _tracked_target_title = info.get("title", "")
        _tracked_target_process = info.get("process_name", "")
        _tracked_mode = "window"
        return {
            "status": "success",
            "mode": "window",
            "hwnd": target_hwnd,
            "title": _tracked_target_title,
            "process_name": _tracked_target_process,
            "message": f"Now tracking '{_tracked_target_title}' ({_tracked_target_process})."
        }

    return {
        "status": "error",
        "message": f"Window '{target}' not found among open applications."
    }


def screen_get_tracked_window() -> Dict[str, Any]:
    """Get the currently tracked target window or tracking mode."""
    global _tracked_target_hwnd, _tracked_target_title, _tracked_target_process, _tracked_mode
    if _tracked_target_hwnd:
        is_valid = True
        is_min = False
        cur_title = _tracked_target_title
        cur_proc = _tracked_target_process
        if sys.platform == "win32":
            try:
                import ctypes
                is_valid = bool(ctypes.windll.user32.IsWindow(_tracked_target_hwnd))
                if is_valid:
                    cur = get_window_info(_tracked_target_hwnd)
                    cur_title = cur.get("title", _tracked_target_title)
                    cur_proc = cur.get("process_name", _tracked_target_process)
                    is_min = cur.get("is_minimized", False)
            except Exception:
                pass
        return {
            "mode": "window",
            "hwnd": _tracked_target_hwnd,
            "title": cur_title,
            "process_name": cur_proc,
            "is_minimized": is_min,
            "is_valid": is_valid
        }
    return {
        "mode": _tracked_mode,
        "hwnd": None,
        "title": None,
        "process_name": None,
        "is_valid": False
    }


def get_foreground_window_info() -> Dict[str, Any]:
    """Inspect the active foreground window on Windows using Win32 API."""
    return get_window_info(None)


def screen_list_windows(
    include_minimized: bool = False,
    include_system: bool = False,
    exclude_self: bool = False
) -> List[Dict[str, Any]]:
    """List all currently visible, interactive desktop windows with title, process name, and HWND.

    Filters out hidden, zero-sized, and background system windows so AI tools or users
    can target specific applications by HWND.

    Args:
        include_minimized: If True, include minimized/iconic windows (default False).
        include_system: If True, include system background shell windows like Program Manager (default False).
        exclude_self: If True, exclude Mammouth Defroster 9000 windows (default False).

    Returns:
        List of window dictionaries containing hwnd, title, process_name, process_id,
        is_foreground, is_minimized, is_self, is_tracked, and rect geometry.
    """
    if sys.platform != "win32":
        return []

    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        windows = []
        foreground_hwnd = int(user32.GetForegroundWindow() or 0)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        def enum_proc(hwnd, lparam):
            try:
                hwnd_int = int(hwnd)
                if not user32.IsWindowVisible(hwnd_int):
                    return 1

                is_minimized = bool(user32.IsIconic(hwnd_int))
                if is_minimized and not include_minimized:
                    return 1

                length = user32.GetWindowTextLengthW(hwnd_int)
                if length <= 0:
                    return 1
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd_int, buf, length + 1)
                title = buf.value.strip()
                if not title:
                    return 1

                # Filter system windows
                if not include_system and title in (
                    "Program Manager", "Windows Shell Experience Host", "Default IME",
                    "MSCTFIME UI", "TextInputHost", "WDADesktopService",
                    "DesktopWindowXamlSource", "Windows Input Experience"
                ):
                    return 1

                # Check cloaked attribute (DWMWA_CLOAKED = 14)
                cloaked = ctypes.c_int(0)
                hr = dwmapi.DwmGetWindowAttribute(hwnd_int, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if hr == 0 and cloaked.value != 0:
                    return 1

                # Check bounds
                rect = RECT()
                hr = dwmapi.DwmGetWindowAttribute(hwnd_int, 9, ctypes.byref(rect), ctypes.sizeof(rect))
                if hr != 0:
                    user32.GetWindowRect(hwnd_int, ctypes.byref(rect))

                w = max(0, rect.right - rect.left)
                h = max(0, rect.bottom - rect.top)
                if (w < 10 or h < 10 or rect.left <= -10000 or rect.top <= -10000) and not is_minimized:
                    return 1

                pid = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd_int, ctypes.byref(pid))
                proc_name = ""
                if pid.value:
                    try:
                        import psutil
                        proc_name = psutil.Process(pid.value).name()
                    except Exception:
                        pass

                if not include_system and proc_name.lower() in ("wdadesktopservice.exe", "textinputhost.exe"):
                    return 1

                is_self = is_defroster_window(hwnd_int)
                if exclude_self and is_self:
                    return 1

                windows.append({
                    "hwnd": hwnd_int,
                    "title": title,
                    "process_name": proc_name,
                    "process_id": int(pid.value),
                    "is_foreground": (hwnd_int == foreground_hwnd),
                    "is_minimized": is_minimized,
                    "is_self": is_self,
                    "is_tracked": (hwnd_int == _tracked_target_hwnd),
                    "rect": {
                        "left": int(rect.left),
                        "top": int(rect.top),
                        "right": int(rect.right),
                        "bottom": int(rect.bottom),
                        "width": int(w),
                        "height": int(h)
                    }
                })
            except Exception:
                pass
            return 1

        proc = WNDENUMPROC(enum_proc)
        h_desk = user32.OpenDesktopW("default", 0, False, 0x0100)
        enumerated = False
        if h_desk:
            try:
                user32.EnumDesktopWindows(h_desk, proc, 0)
                enumerated = True
            finally:
                user32.CloseDesktop(h_desk)

        if not enumerated or len(windows) == 0:
            user32.EnumWindows(proc, 0)

        return windows
    except Exception:
        return []


def screen_capture_active_window(
    target_hwnd: Optional[int] = None,
    save_to_workspace: bool = True,
    include_metadata: bool = True,
    max_width: Optional[int] = 1920,
    quality: int = 85
) -> Any:
    """Capture a screenshot of the currently active foreground window or a specific window by target_hwnd.

    Args:
        target_hwnd: Optional HWND handle from screen_list_windows to capture a specific window (default None for active foreground window).
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
        local_ui=False,
        target_hwnd=target_hwnd
    )


def screen_capture_active_window_local(
    target_hwnd: Optional[int] = None,
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
        local_ui=True,
        target_hwnd=target_hwnd
    )


def screen_capture_window(
    target_hwnd: Optional[int] = None,
    save_to_workspace: bool = True,
    include_metadata: bool = True,
    max_width: Optional[int] = 1920,
    quality: int = 85
) -> Any:
    """Alias for screen_capture_active_window supporting specific target_hwnd targeting."""
    return screen_capture_active_window(
        target_hwnd=target_hwnd,
        save_to_workspace=save_to_workspace,
        include_metadata=include_metadata,
        max_width=max_width,
        quality=quality
    )


def _screen_capture_active_window_impl(
    save_to_workspace: bool,
    include_metadata: bool,
    max_width: Optional[int],
    quality: int,
    local_ui: bool,
    target_hwnd: Optional[int] = None
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

    # Resolve target window (or tracked window / top external non-Defroster window)
    win_info = get_target_window_info(target_hwnd, exclude_defroster=True)
    rect = win_info.get("rect", {})
    w = rect.get("width", 0)
    h = rect.get("height", 0)
    resolved_hwnd = win_info.get("hwnd")

    pil_image = None

    # Step 1: Try PrintWindow directly on target HWND (clean, silent, background-capable)
    if resolved_hwnd and not win_info.get("is_minimized", False):
        try:
            pil_image = capture_window_via_printwindow(resolved_hwnd)
        except Exception:
            pil_image = None

    # Step 2: If PrintWindow did not produce an image, bring window to top and use MSS/ImageGrab
    if pil_image is None and resolved_hwnd and sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if user32.IsIconic(resolved_hwnd):
                user32.ShowWindow(resolved_hwnd, 9)  # SW_RESTORE
                time.sleep(0.08)
            user32.BringWindowToTop(resolved_hwnd)
            user32.SetWindowPos(resolved_hwnd, 0, 0, 0, 0, 0, 0x0043)
            user32.SetForegroundWindow(resolved_hwnd)
            fore_hwnd = user32.GetForegroundWindow()
            if fore_hwnd != resolved_hwnd:
                fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
                cur_thread = user32.GetCurrentThreadId()
                if fore_thread and cur_thread and fore_thread != cur_thread:
                    user32.AttachThreadInput(cur_thread, fore_thread, True)
                    user32.SetForegroundWindow(resolved_hwnd)
                    user32.BringWindowToTop(resolved_hwnd)
                    user32.AttachThreadInput(cur_thread, fore_thread, False)
            time.sleep(0.12)
            # Re-read geometry after activation
            win_info = get_window_info(resolved_hwnd)
            rect = win_info.get("rect", {})
            w = rect.get("width", 0)
            h = rect.get("height", 0)
        except Exception:
            pass

    # Step 3: Attempt capturing window bounding box if dimensions valid and window is on-screen
    if pil_image is None and w > 10 and h > 10 and rect.get("left", 0) > -10000 and rect.get("top", 0) > -10000 and not win_info.get("is_minimized", False):
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
    target_dir = get_workspace_screenshots_dir()
    filepath = target_dir / filename

    saved_path_str = ""
    if save_to_workspace:
        try:
            pil_image.save(str(filepath), format="PNG", optimize=True)
            saved_path_str = str(filepath)
            _cleanup_old_screenshots(target_dir=target_dir, max_keep=25)
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



