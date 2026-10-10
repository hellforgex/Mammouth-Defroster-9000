"""
Mammouth Defroster 9000 - Global Hotkey Module
Provides system-wide keyboard shortcuts (e.g. Ctrl+Shift+M, Ctrl+Shift+Space, Ctrl+Shift+K)
using native Win32 RegisterHotKey.
Runs on dedicated STA background threads with standard Windows message pumps.
Enables instant summon / toggle of the Cockpit, Multimodal Screen Copilot, and Smart Clipboard from anywhere in Windows.
"""

import sys
import ctypes
import ctypes.wintypes
import threading
import logging
from typing import Callable, Optional, Dict, Any, List

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
    "K": 0x4B,
    "C": 0x43,
    "V": 0x56,
    "SPACE": 0x20,
    " ": 0x20,
    "RETURN": 0x0D,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESCAPE": 0x1B,
    "ESC": 0x1B,
    "BACKSPACE": 0x08,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "INSERT": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    "PRIOR": 0x21,
    "PAGEUP": 0x21,
    "NEXT": 0x22,
    "PAGEDOWN": 0x22,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
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
    "PLUS": 0xBB,
    "+": 0xBB,
    "MINUS": 0xBD,
    "-": 0xBD,
}


class _HotkeyEntry:
    def __init__(
        self,
        hotkey_id: int,
        callback: Callable[[], None],
        key: str,
        modifiers: str,
        thread: threading.Thread,
        thread_id: Optional[int]
    ):
        self.hotkey_id = hotkey_id
        self.callback = callback
        self.key = key
        self.modifiers = modifiers
        self.thread = thread
        self.thread_id = thread_id


class GlobalHotkeyManager:
    """Manages background registration and message loop for Win32 global hotkeys."""

    def __init__(self):
        self._hotkeys: Dict[int, _HotkeyEntry] = {}
        self._lock = threading.RLock()

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

        # Support composite keys such as "Ctrl+Shift+Space" in a single key argument
        if "+" in key:
            parts = [p.strip() for p in key.split("+")]
            if len(parts) > 1 and parts[-1]:
                key = parts[-1]
                modifiers = "+".join(parts[:-1])

        with self._lock:
            # Unregister any existing binding for this hotkey_id
            if hotkey_id in self._hotkeys:
                self.unregister(hotkey_id=hotkey_id)

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
                if len(key_upper) == 1 and ("A" <= key_upper <= "Z" or "0" <= key_upper <= "9"):
                    vk_code = ord(key_upper)
                else:
                    vk_code = 0x4D  # Default to 'M'

            ready_event = threading.Event()
            success_flag = [False]
            thread_id_box: List[Optional[int]] = [None]

            def _listener_loop():
                try:
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    tid = kernel32.GetCurrentThreadId()
                    thread_id_box[0] = tid

                    res = user32.RegisterHotKey(0, hotkey_id, fs_modifiers, vk_code)
                    if res:
                        success_flag[0] = True
                        logger.info(f"Registered global hotkey {modifiers}+{key} (ID: {hotkey_id})")
                    else:
                        err = ctypes.GetLastError()
                        logger.warning(f"Could not register global hotkey {modifiers}+{key} (Win32 error: {err})")
                        success_flag[0] = False
                except Exception as e:
                    logger.error(f"Error initializing hotkey: {e}")
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
                        if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                            try:
                                callback()
                            except Exception as cb_err:
                                logger.error(f"Error in hotkey callback {hotkey_id}: {cb_err}")
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                except Exception as loop_err:
                    logger.warning(f"Hotkey message loop {hotkey_id} terminated: {loop_err}")
                finally:
                    try:
                        user32.UnregisterHotKey(0, hotkey_id)
                    except Exception:
                        pass
                    logger.info(f"Global hotkey unregistration complete for ID {hotkey_id}.")

            thread = threading.Thread(
                target=_listener_loop,
                name=f"GlobalHotkeyListener-{hotkey_id}",
                daemon=True
            )
            thread.start()
            ready_event.wait(timeout=2.0)

            if success_flag[0]:
                self._hotkeys[hotkey_id] = _HotkeyEntry(
                    hotkey_id=hotkey_id,
                    callback=callback,
                    key=key,
                    modifiers=modifiers,
                    thread=thread,
                    thread_id=thread_id_box[0]
                )
                return True
            return False

    def unregister(self, hotkey_id: Optional[int] = None) -> None:
        """Unregister active global hotkey(s) and terminate message loop thread cleanly."""
        with self._lock:
            if hotkey_id is not None:
                targets = [hotkey_id] if hotkey_id in self._hotkeys else []
            else:
                targets = list(self._hotkeys.keys())

            for hid in targets:
                entry = self._hotkeys.pop(hid, None)
                if not entry:
                    continue

                if sys.platform == "win32" and entry.thread_id:
                    try:
                        user32 = ctypes.windll.user32
                        user32.PostThreadMessageW(entry.thread_id, WM_QUIT, 0, 0)
                    except Exception as e:
                        logger.debug(f"Failed to post WM_QUIT for hotkey {hid}: {e}")

                if entry.thread and entry.thread.is_alive():
                    entry.thread.join(timeout=1.0)

    @property
    def is_registered(self) -> bool:
        """Check if any global hotkey is currently registered and active."""
        with self._lock:
            return len(self._hotkeys) > 0

    def is_hotkey_registered(self, hotkey_id: Optional[int] = None) -> bool:
        """Check if a specific hotkey_id (or any hotkey if None) is registered."""
        with self._lock:
            if hotkey_id is None:
                return len(self._hotkeys) > 0
            return hotkey_id in self._hotkeys

    def list_hotkeys(self) -> List[Dict[str, Any]]:
        """List all currently registered hotkeys and their specs."""
        with self._lock:
            return [
                {
                    "hotkey_id": hid,
                    "key": entry.key,
                    "modifiers": entry.modifiers,
                    "active": entry.thread.is_alive() if entry.thread else False
                }
                for hid, entry in self._hotkeys.items()
            ]


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


def unregister_global_hotkey(hotkey_id: Optional[int] = None) -> None:
    """Convenience function to unregister global hotkey (or all if hotkey_id is None)."""
    _manager.unregister(hotkey_id=hotkey_id)


def is_global_hotkey_registered(hotkey_id: Optional[int] = None) -> bool:
    """Check if global hotkey is currently registered and active."""
    return _manager.is_hotkey_registered(hotkey_id=hotkey_id)


def list_registered_hotkeys() -> List[Dict[str, Any]]:
    """List all registered hotkeys."""
    return _manager.list_hotkeys()
