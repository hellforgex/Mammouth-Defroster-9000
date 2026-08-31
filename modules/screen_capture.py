import os
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

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace" / "screenshots"
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

        remaining = [f for f in WORKSPACE_DIR.glob("*.png") if f.is_file()]
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
    global _user_consent_granted, _consent_mode

    # M-07: Consent-Gate Check
    if _is_consent_required() and not _user_consent_granted:
        return {
            "status": "consent_required",
            "message": "Desktop screen capture requires explicit user consent. Please confirm via Desktop UI or call screen_grant_consent()."
        }

    # Consume single-use consent
    if _consent_mode == "once":
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
