"""
Mammouth Defroster 9000 - Global Hotkey Module
Provides system-wide keyboard shortcuts (e.g. Ctrl+Shift+M) using native Win32 RegisterHotKey.
Runs on a dedicated STA background thread with a standard Windows message pump.
Enables instant summon / toggle of the Mammouth Defroster Cockpit and Chat interface from anywhere in Windows.
"""

import sys
import ctypes
import ctypes.wintypes
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger("global_hotkey")

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Virtual Key Mapping
VK_MAPPING = {
    "M": 0x4D,
    "SPACE": 0x20,
    "RETURN": 0x0D,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESCAPE": 0x1B,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


class GlobalHotkeyManager:
    """Manages background registration and message loop for Win32 global hotkeys."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._hotkey_id = 2001
        self._is_registered = False
        self._callback: Optional[Callable[[], None]] = None
        self._lock = threading.RLock()  # re-entrant: register() calls unregister() while holding it

    def register(
        self,
        callback: Callable[[], None],
        key: str = "M",
        modifiers: str = "Ctrl+Shift",
        hotkey_id: int = 2001
    ) -> bool:
        """Register a global hotkey on Windows. Starts background listener thread."""
        if sys.platform != "win32":
            logger.info("Global hotkey is only supported on Windows.")
            return False

        with self._lock:
            if self._is_registered:
                self.unregister()

            self._callback = callback
            self._hotkey_id = hotkey_id

            # Parse modifiers
            fs_modifiers = MOD_NOREPEAT
            mod_parts = [p.strip().lower() for p in modifiers.split("+")]
            if "ctrl" in mod_parts or "control" in mod_parts:
                fs_modifiers |= MOD_CONTROL
            if "shift" in mod_parts:
                fs_modifiers |= MOD_SHIFT
            if "alt" in mod_parts:
                fs_modifiers |= MOD_ALT
            if "win" in mod_parts or "cmd" in mod_parts:
                fs_modifiers |= MOD_WIN

            # Parse VK code
            key_upper = key.strip().upper()
            vk_code = VK_MAPPING.get(key_upper)
            if vk_code is None:
                if len(key_upper) == 1 and "A" <= key_upper <= "Z":
                    vk_code = ord(key_upper)
                elif len(key_upper) == 1 and "0" <= key_upper <= "9":
                    vk_code = ord(key_upper)
                else:
                    vk_code = 0x4D  # Default to 'M'

            ready_event = threading.Event()
            success_flag = [False]

            def _listener_loop():
                try:
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    self._thread_id = kernel32.GetCurrentThreadId()

                    res = user32.RegisterHotKey(0, self._hotkey_id, fs_modifiers, vk_code)
                    if res:
                        self._is_registered = True
                        success_flag[0] = True
                        logger.info(f"Registered global hotkey {modifiers}+{key} (ID: {self._hotkey_id})")
                    else:
                        err = ctypes.GetLastError()
                        logger.warning(f"Could not register global hotkey {modifiers}+{key} (Win32 error: {err})")
                        self._is_registered = False
                        success_flag[0] = False
                except Exception as e:
                    logger.error(f"Error initializing hotkey: {e}")
                    self._is_registered = False
                    success_flag[0] = False
                finally:
                    ready_event.set()

                if not success_flag[0]:
                    return

                try:
                    msg = ctypes.wintypes.MSG()
                    while True:
                        r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                        if r <= 0:
                            break
                        if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                            if self._callback:
                                try:
                                    self._callback()
                                except Exception as cb_err:
                                    logger.error(f"Error in hotkey callback: {cb_err}")
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                except Exception as loop_err:
                    logger.warning(f"Hotkey message loop terminated: {loop_err}")
                finally:
                    try:
                        user32.UnregisterHotKey(0, self._hotkey_id)
                    except Exception:
                        pass
                    self._is_registered = False
                    self._thread_id = None
                    logger.info("Global hotkey unregistration complete.")

            self._thread = threading.Thread(target=_listener_loop, name="GlobalHotkeyListener", daemon=True)
            self._thread.start()
            ready_event.wait(timeout=2.0)
            return success_flag[0]

    def unregister(self) -> None:
        """Unregister active global hotkey and terminate message loop thread cleanly."""
        with self._lock:
            if not self._is_registered and not self._thread_id:
                return

            if sys.platform == "win32" and self._thread_id:
                try:
                    user32 = ctypes.windll.user32
                    user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
                except Exception as e:
                    logger.debug(f"Failed to post WM_QUIT: {e}")

            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)

            self._thread = None
            self._thread_id = None
            self._is_registered = False

    @property
    def is_registered(self) -> bool:
        return self._is_registered


# Global singleton instance
_manager = GlobalHotkeyManager()


def register_global_hotkey(
    callback: Callable[[], None],
    key: str = "M",
    modifiers: str = "Ctrl+Shift",
    hotkey_id: int = 2001
) -> bool:
    """Convenience function to register global hotkey with singleton manager."""
    return _manager.register(callback, key=key, modifiers=modifiers, hotkey_id=hotkey_id)


def unregister_global_hotkey() -> None:
    """Convenience function to unregister global hotkey."""
    _manager.unregister()


def is_global_hotkey_registered() -> bool:
    """Check if global hotkey is currently registered and active."""
    return _manager.is_registered
