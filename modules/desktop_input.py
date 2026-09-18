import os
import sys
import time
from typing import Dict, Any, Optional, List

# Try importing pyautogui if available, with failsafe disabled for server stability
try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None

# Native Win32 API setup
if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
else:
    user32 = None

# Mouse Flags
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

# Keyboard Flags
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Virtual Key Codes
VK_MAP = {
    "backspace": 0x08, "tab": 0x09, "clear": 0x0C, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12, "menu": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B
}
# Populate alphanumeric VK codes
for i in range(10):
    VK_MAP[str(i)] = 0x30 + i
for c in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[c] = 0x41 + (ord(c) - ord('a'))


def _get_screen_bounds() -> tuple:
    if user32:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return w, h
    elif pyautogui:
        sz = pyautogui.size()
        return sz.width, sz.height
    return 1920, 1080


def desktop_get_screen_info() -> Dict[str, Any]:
    """Get primary screen resolution and current mouse cursor coordinates."""
    w, h = _get_screen_bounds()
    cur_x, cur_y = 0, 0
    if user32:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cur_x, cur_y = pt.x, pt.y
    elif pyautogui:
        pos = pyautogui.position()
        cur_x, cur_y = pos.x, pos.y

    return {
        "width": w,
        "height": h,
        "cursor_x": cur_x,
        "cursor_y": cur_y
    }


__all__ = [
    "desktop_get_screen_info",
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    "mouse_scroll",
    "mouse_get_position",
    "keyboard_type",
    "keyboard_press",
    "keyboard_hotkey",
]


def _win32_interpolate_move(from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.2):
    """Smoothly interpolate mouse cursor movement using native Win32 SetCursorPos."""
    d = max(0.01, min(float(duration), 3.0))
    steps = max(5, int(d * 60))
    step_delay = d / steps
    for i in range(1, steps + 1):
        t = i / steps
        cur_x = int(from_x + (to_x - from_x) * t)
        cur_y = int(from_y + (to_y - from_y) * t)
        user32.SetCursorPos(cur_x, cur_y)
        time.sleep(step_delay)
    user32.SetCursorPos(to_x, to_y)


def mouse_move(x: int, y: int, smooth: bool = False, duration: float = 0.2) -> Dict[str, Any]:
    """Move the mouse cursor to the specified desktop coordinates.
    
    Args:
        x: Target X coordinate in pixels (0 is left edge).
        y: Target Y coordinate in pixels (0 is top edge).
        smooth: Whether to smoothly interpolate movement (default False for instant response).
        duration: Movement duration if smooth is enabled (default 0.2s).
    """
    w, h = _get_screen_bounds()
    target_x = max(0, min(int(x), w - 1))
    target_y = max(0, min(int(y), h - 1))

    if user32:
        if smooth and float(duration) > 0.0:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            _win32_interpolate_move(pt.x, pt.y, target_x, target_y, duration)
        else:
            user32.SetCursorPos(target_x, target_y)
        return {"status": "success", "cursor_x": target_x, "cursor_y": target_y}
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            d = max(0.0, min(float(duration), 2.0)) if smooth else 0.0
            pyautogui.moveTo(target_x, target_y, duration=d)
            pos = pyautogui.position()
            return {"status": "success", "cursor_x": pos.x, "cursor_y": pos.y}
        except Exception as e:
            return {"status": "error", "error": f"Failed to move mouse: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}


def mouse_click(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1
) -> Dict[str, Any]:
    """Click the mouse button at current position or specified coordinates.
    
    Args:
        x: Optional target X coordinate.
        y: Optional target Y coordinate.
        button: 'left', 'right', or 'middle' (default 'left').
        clicks: Number of clicks (1 for single click, 2 for double click, default 1).
        interval: Interval between clicks in seconds (default 0.1s).
    """
    clean_btn = str(button).lower().strip()
    clean_clicks = max(1, min(int(clicks), 5))

    if x is not None and y is not None:
        mouse_move(x, y)

    if user32:
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        if clean_btn == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif clean_btn == "middle":
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

        for i in range(clean_clicks):
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            if i < clean_clicks - 1:
                time.sleep(max(0.02, min(float(interval), 1.0)))

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return {
            "status": "success",
            "button": clean_btn,
            "clicks": clean_clicks,
            "cursor_x": pt.x,
            "cursor_y": pt.y
        }
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.click(button=clean_btn, clicks=clean_clicks, interval=float(interval))
            return {"status": "success", "button": clean_btn, "clicks": clean_clicks}
        except Exception as e:
            return {"status": "error", "error": f"Failed to click mouse: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}


def mouse_drag(
    start_x: Optional[int] = None,
    start_y: Optional[int] = None,
    end_x: Optional[int] = None,
    end_y: Optional[int] = None,
    button: str = "left",
    duration: float = 0.5,
    x: Optional[int] = None,
    y: Optional[int] = None
) -> Dict[str, Any]:
    """Drag the mouse from a starting position to an ending position with a button held down.
    
    If start coordinates are omitted, drags from the current mouse position.
    Can also accept 'x' and 'y' as aliases for 'end_x' and 'end_y'.
    If only two positional coordinates are provided (start_x, start_y), they are treated as target (end_x, end_y).
    
    Args:
        start_x: Starting X coordinate in pixels (optional, defaults to current position).
        start_y: Starting Y coordinate in pixels (optional, defaults to current position).
        end_x: Target ending X coordinate in pixels.
        end_y: Target ending Y coordinate in pixels.
        button: Mouse button to hold ('left', 'right', or 'middle', default 'left').
        duration: Duration of drag movement in seconds (default 0.5s).
        x: Optional alias for end_x.
        y: Optional alias for end_y.
    """
    w, h = _get_screen_bounds()
    cur_pos = mouse_get_position()
    cur_x, cur_y = cur_pos.get("x", 0), cur_pos.get("y", 0)

    # Determine destination coordinates
    target_x = end_x if end_x is not None else x
    target_y = end_y if end_y is not None else y

    if target_x is None and target_y is None and start_x is not None and start_y is not None:
        from_x, from_y = cur_x, cur_y
        to_x, to_y = start_x, start_y
    else:
        from_x = cur_x if start_x is None else start_x
        from_y = cur_y if start_y is None else start_y
        to_x = from_x if target_x is None else target_x
        to_y = from_y if target_y is None else target_y

    from_x = max(0, min(int(from_x), w - 1))
    from_y = max(0, min(int(from_y), h - 1))
    to_x = max(0, min(int(to_x), w - 1))
    to_y = max(0, min(int(to_y), h - 1))

    clean_btn = str(button).lower().strip()
    d = max(0.05, min(float(duration), 5.0))

    if user32:
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        if clean_btn == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif clean_btn == "middle":
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

        # Move to starting point
        user32.SetCursorPos(from_x, from_y)
        time.sleep(0.02)

        # Press down button
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.02)

        # Smooth drag interpolation
        steps = max(10, int(d * 60))
        step_sleep = d / steps
        for i in range(1, steps + 1):
            t = i / steps
            cx = int(from_x + (to_x - from_x) * t)
            cy = int(from_y + (to_y - from_y) * t)
            user32.SetCursorPos(cx, cy)
            time.sleep(step_sleep)

        user32.SetCursorPos(to_x, to_y)
        time.sleep(0.02)

        # Release mouse button
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        time.sleep(0.02)

        return {
            "status": "success",
            "button": clean_btn,
            "start_x": from_x,
            "start_y": from_y,
            "end_x": to_x,
            "end_y": to_y,
            "duration": d
        }
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.moveTo(from_x, from_y)
            pyautogui.dragTo(to_x, to_y, duration=d, button=clean_btn)
            return {
                "status": "success",
                "button": clean_btn,
                "start_x": from_x,
                "start_y": from_y,
                "end_x": to_x,
                "end_y": to_y,
                "duration": d
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to drag mouse: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}


def mouse_scroll(clicks: int) -> Dict[str, Any]:
    """Scroll the mouse wheel up or down at the current cursor position.
    
    Args:
        clicks: Amount to scroll. Positive integer scrolls UP, negative integer scrolls DOWN (e.g. -5 to scroll down a page).
    """
    clean_clicks = max(-5000, min(int(clicks), 5000))
    if user32:
        # Standard Windows wheel delta is 120 per click notch
        wheel_delta = clean_clicks * 120
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)
        return {
            "status": "success",
            "scroll_amount": clean_clicks,
            "direction": "up" if clean_clicks > 0 else "down"
        }
    elif pyautogui:
        try:
            pyautogui.scroll(clean_clicks)
            return {
                "status": "success",
                "scroll_amount": clean_clicks,
                "direction": "up" if clean_clicks > 0 else "down"
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to scroll: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}


def mouse_get_position() -> Dict[str, Any]:
    """Get current mouse cursor position."""
    if user32:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return {"x": pt.x, "y": pt.y}
    elif pyautogui:
        pos = pyautogui.position()
        return {"x": pos.x, "y": pos.y}
    return {"x": 0, "y": 0}


def keyboard_type(text: str, delay: float = 0.01) -> Dict[str, Any]:
    """Type arbitrary text into the currently active window using native Unicode events.
    
    Reliably types letters, numbers, symbols, spaces, and international Unicode characters without layout mismatch.
    
    Args:
        text: String of text to type.
        delay: Delay between keystrokes in seconds (default 0.01s).
    """
    clean_text = str(text)
    clean_delay = max(0.0, min(float(delay), 0.5))

    if user32:
        for char in clean_text:
            if char == "\r":
                continue
            if char == "\n":
                user32.keybd_event(VK_MAP.get("enter", 0x0D), 0, 0, 0)
                time.sleep(0.01)
                user32.keybd_event(VK_MAP.get("enter", 0x0D), 0, KEYEVENTF_KEYUP, 0)
            else:
                char_code = ord(char)
                user32.keybd_event(0, char_code, KEYEVENTF_UNICODE, 0)
                user32.keybd_event(0, char_code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            if clean_delay > 0:
                time.sleep(clean_delay)
        return {
            "status": "success",
            "typed_characters": len(clean_text)
        }
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.write(clean_text, interval=clean_delay)
            return {"status": "success", "typed_characters": len(clean_text)}
        except Exception as e:
            return {"status": "error", "error": f"Failed to type: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}


def keyboard_press(key: str, presses: int = 1, interval: float = 0.05) -> Dict[str, Any]:
    """Press and release a keyboard key (e.g. 'enter', 'f', 'space', 'esc', 'tab', 'backspace', 'down', 'up').
    
    Args:
        key: Key name (e.g. 'enter', 'return', 'f', 'space', 'esc', 'tab', 'backspace', 'up', 'down', 'left', 'right', 'delete').
        presses: Number of times to press the key (default 1).
        interval: Interval between repeated presses in seconds (default 0.05s).
    """
    clean_key = str(key).lower().strip()
    key_aliases = {
        "return": "enter",
        "escape": "esc",
        "del": "delete",
        "spacebar": "space",
        "back": "backspace",
        "control": "ctrl",
        "windows": "win",
        "super": "win",
        "pgup": "pageup",
        "pgdn": "pagedown",
        "prtscn": "printscreen",
        "prtsc": "printscreen"
    }
    clean_key = key_aliases.get(clean_key, clean_key)
    clean_presses = max(1, min(int(presses), 20))
    clean_interval = max(0.01, min(float(interval), 1.0))

    vk = VK_MAP.get(clean_key)
    if user32 and vk is not None:
        for i in range(clean_presses):
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            if i < clean_presses - 1:
                time.sleep(clean_interval)
        return {
            "status": "success",
            "key": clean_key,
            "presses": clean_presses
        }
    elif user32 and len(clean_key) == 1:
        # Single unicode character fallback
        for i in range(clean_presses):
            char_code = ord(clean_key)
            user32.keybd_event(0, char_code, KEYEVENTF_UNICODE, 0)
            user32.keybd_event(0, char_code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            if i < clean_presses - 1:
                time.sleep(clean_interval)
        return {"status": "success", "key": clean_key, "presses": clean_presses}
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.press(clean_key, presses=clean_presses, interval=clean_interval)
            return {"status": "success", "key": clean_key, "presses": clean_presses}
        except Exception as e:
            return {"status": "error", "error": f"Failed to press key: {e}"}

    return {"status": "error", "error": f"Unrecognized key '{key}'."}


def keyboard_hotkey(keys: str) -> Dict[str, Any]:
    """Trigger a keyboard hotkey combination (e.g. 'ctrl+t', 'ctrl+w', 'ctrl+l', 'alt+f4', 'ctrl+c', 'ctrl+v').
    
    Args:
        keys: Plus-delimited combination of keys to press together (e.g. 'ctrl+t' for new tab, 'ctrl+l' for address bar, 'ctrl+w' to close tab, 'alt+f4' to close window).
    """
    clean_combo = str(keys).lower().strip()
    if not clean_combo:
        return {"status": "error", "error": "Hotkey keys cannot be empty."}

    key_aliases = {
        "return": "enter",
        "escape": "esc",
        "del": "delete",
        "spacebar": "space",
        "back": "backspace",
        "control": "ctrl",
        "windows": "win",
        "super": "win",
        "pgup": "pageup",
        "pgdn": "pagedown",
        "prtscn": "printscreen",
        "prtsc": "printscreen"
    }

    raw_key_list = [k.strip() for k in clean_combo.split("+") if k.strip()]
    if not raw_key_list:
        return {"status": "error", "error": f"Invalid hotkey specification: '{keys}'"}

    key_list = [key_aliases.get(k, k) for k in raw_key_list]

    if user32:
        vk_list = []
        for k in key_list:
            vk = VK_MAP.get(k)
            if vk is None:
                return {"status": "error", "error": f"Unknown key in hotkey combination: '{k}'"}
            vk_list.append(vk)

        # Press down in order
        for vk in vk_list:
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.01)

        time.sleep(0.05)

        # Release in reverse order
        for vk in reversed(vk_list):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

        return {
            "status": "success",
            "hotkey": "+".join(key_list)
        }
    elif pyautogui:
        try:
            pyautogui.FAILSAFE = False
            pyautogui.hotkey(*key_list)
            return {"status": "success", "hotkey": "+".join(key_list)}
        except Exception as e:
            return {"status": "error", "error": f"Failed to trigger hotkey: {e}"}

    return {"status": "error", "error": "Native input subsystem unavailable."}
