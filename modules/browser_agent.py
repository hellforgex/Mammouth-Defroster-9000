"""
Mammouth Defroster 9000 - Playwright Browser Automation Agent Module
Provides native, high-reliability browser automation (Microsoft Edge / Chrome)
controllable via FastMCP tools for Mammouth AI and the Cockpit GUI.
Uses a thread-isolated worker pattern to ensure full thread safety across GUI and ASGI event loops.
"""

import os
import sys
import time
import io
import json
import queue
import re
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Tuple

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    from fastmcp.utilities.types import Image as FastMCPImage
except Exception:
    FastMCPImage = None

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

SCREENSHOTS_DIR = BASE_DIR / "workspace" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PROFILE_DIR = BASE_DIR / "data" / "agent_browser_profile"
DEFAULT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# JavaScript snippet that indexes all interactive elements and attaches data-mammouth-id
_INDEX_ELEMENTS_JS = """
(() => {
    const interactiveTags = ['A', 'BUTTON', 'INPUT', 'TEXTAREA', 'SELECT', 'DETAILS', 'SUMMARY'];
    const interactiveRoles = ['button', 'link', 'checkbox', 'radio', 'combobox', 'menuitem', 'tab', 'switch'];
    
    const elements = [];
    let idCounter = 1;
    // Drop ids from previous snapshots so a stale element can never be targeted by a new id
    document.querySelectorAll('[data-mammouth-id]').forEach(e => e.removeAttribute('data-mammouth-id'));
    
    function isVisible(el) {
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        if (rect.bottom < -50 || rect.top > window.innerHeight + 100) return false;
        return true;
    }

    const all = document.querySelectorAll('*');
    for (const el of all) {
        const tag = el.tagName;
        const role = el.getAttribute('role');
        const isInteractive = interactiveTags.includes(tag) || 
                              (role && interactiveRoles.includes(role)) ||
                              el.hasAttribute('onclick') ||
                              el.getAttribute('tabindex') === '0' ||
                              el.isContentEditable;
        if (!isInteractive || !isVisible(el)) continue;

        let text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
        if (text.length > 80) text = text.substring(0, 77) + '...';
        const placeholder = el.getAttribute('placeholder') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const title = el.getAttribute('title') || '';
        const name = el.getAttribute('name') || '';
        const val = (el.value || '').trim();
        const inputType = el.getAttribute('type') || (tag === 'INPUT' ? 'text' : '');
        const href = el.getAttribute('href') || '';

        let selector = '';
        if (el.id) {
            selector = '#' + CSS.escape(el.id);
        } else if (name) {
            selector = `${tag.toLowerCase()}[name="${CSS.escape(name)}"]`;
        } else if (placeholder) {
            selector = `${tag.toLowerCase()}[placeholder="${CSS.escape(placeholder)}"]`;
        } else if (ariaLabel) {
            selector = `[aria-label="${CSS.escape(ariaLabel)}"]`;
        }

        const elemId = idCounter++;
        el.setAttribute('data-mammouth-id', String(elemId));

        const rect = el.getBoundingClientRect();
        elements.push({
            id: elemId,
            tag: tag.toLowerCase(),
            type: inputType || undefined,
            text: text || ariaLabel || title || placeholder || val || '(no label)',
            placeholder: placeholder || undefined,
            href: href ? (href.length > 60 ? href.substring(0, 57) + '...' : href) : undefined,
            selector: selector || undefined,
            x: Math.round(rect.left + rect.width / 2),
            y: Math.round(rect.top + rect.height / 2)
        });
        if (elements.length >= 80) break;
    }
    return elements;
})()
"""

# JavaScript snippet that extracts clean readable Markdown from rendered DOM
_EXTRACT_MARKDOWN_JS = """
(() => {
    function getCleanMarkdown(node) {
        if (!node) return '';
        if (node.nodeType === Node.TEXT_NODE) {
            return node.textContent.trim() ? node.textContent : '';
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return '';

        const tag = node.tagName.toLowerCase();
        if (['script', 'style', 'svg', 'noscript', 'meta', 'link'].includes(tag)) return '';

        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return '';

        let inner = Array.from(node.childNodes).map(getCleanMarkdown).filter(Boolean).join(' ');

        if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
            const level = tag[1];
            return '\\n\\n' + '#'.repeat(parseInt(level)) + ' ' + inner.trim() + '\\n\\n';
        }
        if (tag === 'p') return '\\n\\n' + inner.trim() + '\\n\\n';
        if (tag === 'li') return '\\n- ' + inner.trim();
        if (tag === 'a') {
            const href = node.getAttribute('href');
            return href && inner.trim() ? `[${inner.trim()}](${href})` : inner;
        }
        if (tag === 'button') return ` [Button: ${inner.trim()}] `;
        if (['input', 'textarea'].includes(tag)) {
            const val = node.value || node.placeholder || '';
            return ` [Input: ${val}] `;
        }
        if (['div', 'section', 'article', 'header', 'footer'].includes(tag)) {
            return inner ? '\\n' + inner + '\\n' : '';
        }
        return inner;
    }

    let md = getCleanMarkdown(document.body || document.documentElement);
    md = md.replace(/\\n\\s*\\n\\s*\\n+/g, '\\n\\n').trim();
    return md;
})()
"""


def _detect_browser_channel() -> str:
    """Detect available browser channel, preferring system Microsoft Edge on Windows."""
    if sys.platform == "win32":
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        ]
        for p in edge_paths:
            if os.path.exists(p):
                return "msedge"
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        for p in chrome_paths:
            if os.path.exists(p):
                return "chrome"
    return "msedge"



# Playwright waits must finish well before the caller gives up (call() timeout), otherwise the
# worker keeps running a command nobody waits for and every following command queues behind it.
_NAV_TIMEOUT_MS = 25000
_CALL_TIMEOUT_S = 40.0

_BLOCKED_METADATA_HOSTS = {"metadata.google.internal", "instance-data", "metadata", "metadata.azure.com"}


_MAX_BROWSER_SCREENSHOTS = 50


def _prune_browser_screenshots() -> None:
    """Keep only the newest _MAX_BROWSER_SCREENSHOTS automation screenshots on disk."""
    try:
        files = sorted(SCREENSHOTS_DIR.glob("browser_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[_MAX_BROWSER_SCREENSHOTS:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _check_navigation_url(url: str) -> str:
    """Normalize and validate a navigation target for the automated browser.

    - Only http(s) and about:blank: file:// would let a page read arbitrary local files
      (bypassing the file_ops sandbox), other schemes (chrome:, edge:, data:, javascript:) are not needed.
    - Cloud metadata endpoints / link-local addresses are blocked in every notation
      (e.g. 2852039166 or 0xA9FEA9FE for 169.254.169.254). Loopback and LAN stay allowed on purpose
      so local dev servers (localhost:3000 …) can still be tested.
    """
    target_url = str(url or "").strip()
    if not target_url:
        raise ValueError("URL cannot be empty.")
    lower = target_url.lower()
    if lower == "about:blank":
        return target_url
    if "://" not in lower and not lower.startswith(("about:", "file:", "data:", "javascript:", "chrome:", "edge:", "view-source:")):
        target_url = "https://" + target_url
        lower = target_url.lower()
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme not in ("http", "https"):
        raise PermissionError(f"Navigation Shield: scheme '{parsed.scheme}:' is not allowed (only http, https and about:blank).")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError(f"Invalid URL: '{url}'")
    if host in _BLOCKED_METADATA_HOSTS:
        raise PermissionError(f"SSRF Shield: Navigation to '{host}' is prohibited.")
    ip = None
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Browsers also accept integer / hex / octal IPv4 forms
        try:
            import ipaddress, socket as _socket
            ip = ipaddress.ip_address(_socket.inet_aton(host))
        except Exception:
            ip = None
    if ip is not None and (ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise PermissionError(f"SSRF Shield: Navigation to '{host}' ({ip}) is prohibited.")
    return target_url

class _BrowserWorker:
    """Dedicated background thread managing Playwright instance and command execution."""

    def __init__(self):
        self.cmd_queue: queue.Queue = queue.Queue()
        self.thread: Optional[threading.Thread] = None
        self.pw = None
        self.context = None
        self.active_page = None
        self.is_running = False
        self._lock = threading.Lock()
        self.config: Dict[str, Any] = {
            "channel": _detect_browser_channel(),
            "headless": False,
            "viewport_width": 1280,
            "viewport_height": 800,
            "timeout_seconds": 30,
            "user_data_dir": str(DEFAULT_PROFILE_DIR)
        }

    def start(self, config_override: Optional[Dict[str, Any]] = None):
        with self._lock:
            if config_override:
                self.config.update(config_override)
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._worker_loop, name="MammouthBrowserWorker", daemon=True)
            self.thread.start()

    def call(self, cmd: str, timeout: float = _CALL_TIMEOUT_S, **kwargs) -> Any:
        if not self.thread or not self.thread.is_alive():
            self.start()
        resp_q: queue.Queue = queue.Queue()
        deadline = time.monotonic() + timeout
        self.cmd_queue.put((cmd, kwargs, resp_q, deadline))
        try:
            success, result = resp_q.get(timeout=timeout)
            if not success:
                if isinstance(result, Exception):
                    raise result
                raise RuntimeError(str(result))
            return result
        except queue.Empty:
            raise TimeoutError(f"Browser operation '{cmd}' timed out after {timeout} seconds.")

    def _worker_loop(self):
        """Worker loop executing all Playwright operations on this dedicated thread."""
        from playwright.sync_api import sync_playwright

        try:
            self.pw = sync_playwright().start()
        except Exception as e:
            # Propagate init failure to any pending calls
            while not self.cmd_queue.empty():
                item = self.cmd_queue.get_nowait()
                item[2].put((False, e))
            return

        while True:
            try:
                item = self.cmd_queue.get()
            except Exception:
                break
            cmd, kwargs, resp_q = item[0], item[1], item[2]
            deadline = item[3] if len(item) > 3 else None
            if deadline is not None and cmd != "stop" and time.monotonic() > deadline:
                # Caller already received a TimeoutError: don't run a command nobody waits for
                continue

            if cmd == "stop":
                try:
                    self._do_close()
                    resp_q.put((True, {"status": "closed"}))
                except Exception as e:
                    resp_q.put((False, e))
                finally:
                    if self.pw:
                        try:
                            self.pw.stop()
                        except Exception:
                            pass
                        self.pw = None
                    self.is_running = False
                break

            try:
                self._ensure_browser()
                handler = getattr(self, f"_cmd_{cmd}", None)
                if not handler:
                    raise ValueError(f"Unknown browser command: {cmd}")
                res = handler(**kwargs)
                resp_q.put((True, res))
            except Exception as e:
                resp_q.put((False, e))

    def _on_context_closed(self, *_args):
        # User closed the browser window manually: forget the dead context so the next command relaunches
        self.context = None
        self.active_page = None
        self.is_running = False

    def _ensure_browser(self):
        """Ensure persistent context and active page exist."""
        if self.context and self.is_running:
            # Check if active page is still alive
            if self.active_page and self.active_page.is_closed():
                pages = self.context.pages
                self.active_page = pages[0] if pages else self.context.new_page()
            return

        profile_dir = Path(self.config.get("user_data_dir", str(DEFAULT_PROFILE_DIR))).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        channel = self.config.get("channel", "msedge")
        headless = bool(self.config.get("headless", False))
        vw = int(self.config.get("viewport_width", 1280))
        vh = int(self.config.get("viewport_height", 800))

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check"
        ]

        try:
            self.context = self.pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel=channel,
                headless=headless,
                viewport={"width": vw, "height": vh},
                accept_downloads=True,
                chromium_sandbox=True,  # Playwright defaults to --no-sandbox
                args=launch_args
            )
        except Exception as e:
            # Fallback without channel if channel failed (e.g. system Edge not found)
            if channel != "chromium":
                self.context = self.pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=headless,
                    viewport={"width": vw, "height": vh},
                    accept_downloads=True,
                    chromium_sandbox=True,
                    args=launch_args
                )
            else:
                raise e

        # Attach default timeout (kept below the call() timeout, see _NAV_TIMEOUT_MS)
        timeout_ms = min(int(self.config.get("timeout_seconds", 30)) * 1000, _NAV_TIMEOUT_MS)
        self.context.set_default_timeout(timeout_ms)
        try:
            self.context.on("close", self._on_context_closed)
        except Exception:
            pass

        pages = self.context.pages
        self.active_page = pages[0] if pages else self.context.new_page()
        self.is_running = True

    def _do_close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        self.active_page = None
        self.is_running = False

    # ---- Command Handlers ----

    def _cmd_navigate(self, url: str, wait_until: str = "load") -> Dict[str, Any]:
        target_url = _check_navigation_url(url)
        self.active_page.goto(target_url, wait_until=wait_until, timeout=_NAV_TIMEOUT_MS)
        return {
            "status": "success",
            "url": self.active_page.url,
            "title": self.active_page.title()
        }

    def _cmd_snapshot(self, include_screenshot: bool = True, max_elements: int = 60, full_page: bool = False) -> Dict[str, Any]:
        title = self.active_page.title()
        url = self.active_page.url

        # Extract indexed interactive elements
        elements = self.active_page.evaluate(_INDEX_ELEMENTS_JS)
        if len(elements) > max_elements:
            elements = elements[:max_elements]

        # Extract clean text summary (first 3000 chars)
        page_text = self.active_page.evaluate(_EXTRACT_MARKDOWN_JS)
        text_preview = page_text[:2500] + ("..." if len(page_text) > 2500 else "")

        saved_path = ""
        screenshot_bytes = None

        if include_screenshot:
            screenshot_bytes = self.active_page.screenshot(full_page=full_page, type="png")
            # Millisecond timestamp: two snapshots in the same second no longer overwrite each other
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"browser_{timestamp}.png"
            filepath = SCREENSHOTS_DIR / filename
            try:
                filepath.write_bytes(screenshot_bytes)
                saved_path = str(filepath)
                _prune_browser_screenshots()
            except Exception:
                pass

        return {
            "status": "success",
            "title": title,
            "url": url,
            "interactive_elements": elements,
            "element_count": len(elements),
            "text_preview": text_preview,
            "screenshot_path": saved_path,
            "screenshot_bytes": screenshot_bytes,
            # The full image is returned separately; encoding all of it to base64 just to show 120 chars was wasted work
            "base64_preview": f"[PNG {len(screenshot_bytes)} bytes, see screenshot_path]" if screenshot_bytes else ""
        }

    def _resolve_target(self, target: str):
        target_str = str(target).strip()
        # 1. Numeric ID from snapshot
        if target_str.isdigit() or (target_str.startswith("#") and target_str[1:].isdigit()):
            num = target_str.lstrip("#")
            loc = self.active_page.locator(f'[data-mammouth-id="{num}"]')
            if loc.count() > 0:
                return loc.first

        # 2. Coordinate format: "x,y" or "coords:x,y"
        if "," in target_str and not any(c in target_str for c in ("#", ".", "[", ">")):
            raw = target_str.replace("coords:", "").strip()
            parts = raw.split(",")
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                return (int(parts[0].strip()), int(parts[1].strip()))

        # 3. Standard CSS / XPath locator
        try:
            loc = self.active_page.locator(target_str)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

        # 4. Text-based lookup
        try:
            loc = self.active_page.get_by_text(target_str, exact=False)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

        # 5. Role or placeholder fallback
        try:
            loc = self.active_page.get_by_placeholder(target_str)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

        raise ValueError(f"Could not find element matching target '{target}'. Use browser_snapshot() to inspect available elements.")

    def _cmd_click(self, target: str, button: str = "left", double_click: bool = False) -> Dict[str, Any]:
        resolved = self._resolve_target(target)
        if isinstance(resolved, tuple):
            x, y = resolved
            if double_click:
                self.active_page.mouse.dblclick(x, y, button=button)
            else:
                self.active_page.mouse.click(x, y, button=button)
        else:
            resolved.scroll_into_view_if_needed(timeout=5000)
            if double_click:
                resolved.dblclick(button=button, timeout=10000)
            else:
                resolved.click(button=button, timeout=10000)

        # Allow SPA transitions to settle briefly
        time.sleep(0.3)
        return {
            "status": "success",
            "action": "double_click" if double_click else "click",
            "target": str(target),
            "current_url": self.active_page.url,
            "title": self.active_page.title()
        }

    def _cmd_fill(self, target: str, text: str, press_enter: bool = False) -> Dict[str, Any]:
        resolved = self._resolve_target(target)
        if isinstance(resolved, tuple):
            raise ValueError("Cannot fill text into pixel coordinates; target must be an element ID or selector.")

        resolved.scroll_into_view_if_needed(timeout=5000)
        resolved.fill(text, timeout=10000)
        if press_enter:
            resolved.press("Enter", timeout=5000)
            time.sleep(0.3)

        return {
            "status": "success",
            "target": str(target),
            "text_length": len(text),
            "pressed_enter": press_enter,
            "current_url": self.active_page.url
        }

    def _cmd_press_key(self, key: str) -> Dict[str, Any]:
        self.active_page.keyboard.press(key)
        time.sleep(0.2)
        return {"status": "success", "key": key}

    def _cmd_hover(self, target: str) -> Dict[str, Any]:
        resolved = self._resolve_target(target)
        if isinstance(resolved, tuple):
            x, y = resolved
            self.active_page.mouse.move(x, y)
        else:
            resolved.scroll_into_view_if_needed(timeout=5000)
            resolved.hover(timeout=10000)
        return {"status": "success", "target": str(target)}

    def _cmd_scroll(self, direction: str = "down", amount: int = 500, target: str = "") -> Dict[str, Any]:
        if target:
            resolved = self._resolve_target(target)
            if not isinstance(resolved, tuple):
                resolved.scroll_into_view_if_needed(timeout=5000)
                return {"status": "success", "target": str(target), "action": "scrolled_into_view"}

        delta_y = amount if direction == "down" else -amount
        self.active_page.mouse.wheel(0, delta_y)
        time.sleep(0.2)
        return {"status": "success", "direction": direction, "amount": amount}

    def _cmd_get_content(self, format: str = "markdown", max_length: int = 30000) -> str:
        if format == "html":
            content = self.active_page.content()
        else:
            content = self.active_page.evaluate(_EXTRACT_MARKDOWN_JS)

        if len(content) > max_length:
            return content[:max_length] + f"\n\n[... Truncated, total length is {len(content)} characters ...]"
        return content if content else "(Page returned empty content)"

    def _cmd_screenshot(self, full_page: bool = False) -> Tuple[bytes, str]:
        screenshot_bytes = self.active_page.screenshot(full_page=full_page, type="png")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"browser_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        try:
            filepath.write_bytes(screenshot_bytes)
            path_str = str(filepath)
        except Exception:
            path_str = ""
        return screenshot_bytes, path_str

    def _cmd_evaluate(self, script: str) -> Any:
        res = self.active_page.evaluate(script)
        return {"status": "success", "result": res}

    def _cmd_tabs(self, action: str = "list", tab_index: int = -1, url: str = "") -> Dict[str, Any]:
        pages = self.context.pages
        if action == "list":
            tabs_list = []
            for idx, p in enumerate(pages):
                tabs_list.append({
                    "index": idx,
                    "title": p.title(),
                    "url": p.url,
                    "active": (p == self.active_page)
                })
            return {"status": "success", "tabs": tabs_list, "count": len(pages)}

        if action == "create":
            new_p = self.context.new_page()
            if url:
                target_url = _check_navigation_url(url)
                new_p.goto(target_url, timeout=_NAV_TIMEOUT_MS)
            self.active_page = new_p
            return {"status": "success", "action": "created", "index": len(self.context.pages) - 1, "url": new_p.url}

        if action == "switch":
            if 0 <= tab_index < len(pages):
                self.active_page = pages[tab_index]
                self.active_page.bring_to_front()
                return {"status": "success", "action": "switched", "index": tab_index, "url": self.active_page.url}
            raise IndexError(f"Tab index {tab_index} out of range (0-{len(pages)-1}).")

        if action == "close":
            target_idx = tab_index if tab_index >= 0 else pages.index(self.active_page)
            if 0 <= target_idx < len(pages):
                page_to_close = pages[target_idx]
                page_to_close.close()
                remaining = self.context.pages
                self.active_page = remaining[0] if remaining else self.context.new_page()
                return {"status": "success", "action": "closed", "remaining_tabs": len(remaining)}
            raise IndexError(f"Tab index {target_idx} out of range.")

        raise ValueError(f"Unknown tabs action: {action}. Supported: 'list', 'create', 'switch', 'close'.")

    def _cmd_status(self) -> Dict[str, Any]:
        if not self.is_running or not self.context:
            return {
                "running": False,
                "channel": self.config.get("channel", "msedge"),
                "headless": bool(self.config.get("headless", False)),
                "active_url": "",
                "active_title": "",
                "tabs_count": 0,
                "profile_dir": self.config.get("user_data_dir", str(DEFAULT_PROFILE_DIR))
            }
        return {
            "running": True,
            "channel": self.config.get("channel", "msedge"),
            "headless": bool(self.config.get("headless", False)),
            "active_url": self.active_page.url if self.active_page else "",
            "active_title": self.active_page.title() if self.active_page else "",
            "tabs_count": len(self.context.pages) if self.context else 0,
            "profile_dir": self.config.get("user_data_dir", str(DEFAULT_PROFILE_DIR))
        }


# Singleton worker instance
_WORKER = _BrowserWorker()


def init_browser_agent(config: Optional[Dict[str, Any]] = None):
    """Initialize or update browser agent configuration."""
    _WORKER.start(config)


# ---- Public MCP Tool Functions ----

def browser_navigate(url: str, wait_until: str = "load") -> Dict[str, Any]:
    """Navigate the automated browser to a specified URL.
    
    Args:
        url: The web address to load (e.g. 'https://github.com' or 'google.de').
        wait_until: Navigation wait condition ('load', 'domcontentloaded', or 'networkidle'). Default is 'load'.
    """
    try:
        return _WORKER.call("navigate", url=url, wait_until=wait_until)
    except Exception as e:
        return {"error": str(e), "url": url}


def browser_snapshot(include_screenshot: bool = True, max_elements: int = 60, full_page: bool = False) -> Dict[str, Any]:
    """Capture a comprehensive state snapshot of the active webpage.
    Returns title, current URL, a clean text summary, and a list of indexed interactive
    elements with numeric IDs (e.g. [1] button 'Login') that can be passed directly to browser_click or browser_fill.
    
    Args:
        include_screenshot: Whether to capture and save a high-res PNG screenshot.
        max_elements: Maximum number of interactive elements to list (default 60).
        full_page: Whether to take full scrollable page screenshot instead of viewport.
    """
    try:
        res = _WORKER.call("snapshot", include_screenshot=include_screenshot, max_elements=max_elements, full_page=full_page)
        # Drop raw screenshot bytes from JSON dictionary response
        res.pop("screenshot_bytes", None)
        return res
    except Exception as e:
        return {"error": str(e)}


def browser_screenshot(full_page: bool = False) -> Any:
    """Capture an image screenshot of the current browser page for visual multimodal inspection.
    
    Args:
        full_page: Whether to capture full scrollable document height (True) or current viewport (False).
    """
    try:
        screenshot_bytes, path_str = _WORKER.call("screenshot", full_page=full_page)
        if FastMCPImage is not None:
            return FastMCPImage(data=screenshot_bytes, format="png")
        import base64
        b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        return {
            "status": "success",
            "saved_path": path_str,
            "format": "png",
            "base64_preview": f"data:image/png;base64,{b64[:100]}... [total {len(b64)} chars]"
        }
    except Exception as e:
        return {"error": str(e)}


def browser_click(target: str, button: str = "left", double_click: bool = False) -> Dict[str, Any]:
    """Click on an element on the webpage.
    Target can be:
    - A numeric ID from browser_snapshot() (e.g. '1', '4', 12)
    - A CSS selector (e.g. 'button.submit-btn' or '#login')
    - Visible button/link text (e.g. 'Anmelden' or 'Search')
    - Pixel coordinates 'x,y' (e.g. '450,220')
    
    Args:
        target: Numeric ID, CSS selector, visible text, or coordinates.
        button: Mouse button ('left', 'right', 'middle'). Default is 'left'.
        double_click: Whether to perform a double-click.
    """
    try:
        return _WORKER.call("click", target=target, button=button, double_click=double_click)
    except Exception as e:
        return {"error": str(e), "target": target}


def browser_fill(target: str, text: str, press_enter: bool = False) -> Dict[str, Any]:
    """Type or fill text into an input field or textarea.
    Target can be a numeric element ID from browser_snapshot() (e.g. '2') or a CSS selector/placeholder.
    Dispatches input and change events so reactive SPAs (React, Vue) update state properly.
    
    Args:
        target: Numeric ID, CSS selector, or placeholder of the target input.
        text: The text to enter.
        press_enter: Automatically press Enter after typing (useful for search bars). Default False.
    """
    try:
        return _WORKER.call("fill", target=target, text=text, press_enter=press_enter)
    except Exception as e:
        return {"error": str(e), "target": target}


def browser_press_key(key: str) -> Dict[str, Any]:
    """Simulate a keyboard keypress in the browser.
    
    Args:
        key: Key name such as 'Enter', 'Tab', 'Escape', 'Backspace', 'ArrowDown', 'ArrowUp', 'PageDown'.
    """
    try:
        return _WORKER.call("press_key", key=key)
    except Exception as e:
        return {"error": str(e), "key": key}


def browser_hover(target: str) -> Dict[str, Any]:
    """Hover the mouse cursor over an element (e.g. to open drop-down menus or preview tooltips).
    
    Args:
        target: Numeric element ID from browser_snapshot(), CSS selector, or visible text.
    """
    try:
        return _WORKER.call("hover", target=target)
    except Exception as e:
        return {"error": str(e), "target": target}


def browser_scroll(direction: str = "down", amount: int = 500, target: str = "") -> Dict[str, Any]:
    """Scroll the webpage or scroll a specific element into view.
    
    Args:
        direction: 'down' or 'up'. Default is 'down'.
        amount: Pixels to scroll (default 500).
        target: Optional element ID or selector to scroll directly into view.
    """
    try:
        return _WORKER.call("scroll", direction=direction, amount=amount, target=target)
    except Exception as e:
        return {"error": str(e)}


def browser_get_content(format: str = "markdown", max_length: int = 30000) -> str:
    """Extract readable text or structured Markdown from the fully rendered DOM of the active page.
    Unlike static HTML scrapers, this executes client-side JavaScript before reading content.
    
    Args:
        format: 'markdown' (clean formatted text with headings and links) or 'html' (raw DOM). Default is 'markdown'.
        max_length: Maximum characters to return (default 30,000).
    """
    try:
        return _WORKER.call("get_content", format=format, max_length=max_length)
    except Exception as e:
        return f"Error extracting browser content: {e}"


def browser_evaluate(script: str) -> Any:
    """Execute arbitrary JavaScript in the context of the active webpage and return the result.
    
    Args:
        script: JavaScript expression or function body to execute (e.g. 'document.title' or 'window.innerWidth').
    """
    try:
        return _WORKER.call("evaluate", script=script)
    except Exception as e:
        return {"error": str(e)}


def browser_tabs(action: str = "list", tab_index: int = -1, url: str = "") -> Dict[str, Any]:
    """Manage browser tabs.
    
    Args:
        action: 'list' (list open tabs), 'create' (open new tab), 'switch' (select tab), 'close' (close tab).
        tab_index: Target tab index for 'switch' or 'close'.
        url: Optional URL to open when creating a new tab.
    """
    try:
        return _WORKER.call("tabs", action=action, tab_index=tab_index, url=url)
    except Exception as e:
        return {"error": str(e)}


def browser_status() -> Dict[str, Any]:
    """Get the current operational status of the automated browser agent."""
    try:
        return _WORKER.call("status")
    except Exception as e:
        return {"running": False, "error": str(e)}


def browser_close() -> Dict[str, Any]:
    """Close the automated browser session and release system resources."""
    try:
        return _WORKER.call("stop")
    except Exception as e:
        return {"error": str(e)}
