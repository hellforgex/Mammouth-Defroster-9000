import os
import sys
import time
import json
import shutil
import subprocess
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from PIL import Image as PILImage
try:
    import pystray
    from pystray import MenuItem as item, Menu
except ImportError:
    pystray = None
    item = None
    Menu = None

try:
    import win32clipboard
    def copy_to_clipboard(text: str):
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
except ImportError:
    import subprocess
    def copy_to_clipboard(text: str):
        # Text goes through stdin so quotes in it cannot alter the command.
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$input | Out-String | ForEach-Object { Set-Clipboard -Value $_.TrimEnd() }"],
            input=text, capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

import uvicorn
from server import app, log_path
from modules.mammouth_code import launch_mammouth_terminal, get_mammouth_code_status
from modules.screen_capture import screen_capture


class DefrosterTrayApp:
    def __init__(self):
        self.port = int(os.environ.get("PORT", 8000))
        self.host = os.environ.get("HOST", "127.0.0.1")
        self.public_url = self._detect_public_url()
        self.server_thread = None
        self.uvicorn_server = None
        self.icon = None
        self.is_running = False

    def _detect_public_url(self) -> str:
        ts_bin = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
        if os.path.exists(ts_bin) or shutil.which("tailscale"):
            try:
                proc = subprocess.run([ts_bin, "status", "--json"], capture_output=True, text=True, timeout=2)
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    dns = data.get("Self", {}).get("DNSName", "").rstrip(".")
                    if dns:
                        return f"https://{dns}/sse"
            except Exception:
                pass
        return "https://[your-tailscale-node].ts.net/sse"

    def load_icon_image(self):
        # Look for icon.ico or icon.png in assets across frozen, dev, and _internal layouts
        candidates = [
            BASE_DIR / "assets" / "icon.ico",
            BASE_DIR / "_internal" / "assets" / "icon.ico",
            Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "assets" / "icon.ico",
            Path(__file__).parent / "assets" / "icon.ico",
            BASE_DIR.parent / "assets" / "icon.ico",
            BASE_DIR.parent / "src" / "assets" / "icon.ico",
            BASE_DIR / "assets" / "icon.png",
            BASE_DIR / "_internal" / "assets" / "icon.png",
            Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "assets" / "icon.png",
            Path(__file__).parent / "assets" / "icon.png",
            BASE_DIR.parent / "assets" / "icon.png",
            BASE_DIR.parent / "src" / "assets" / "icon.png",
        ]
        for icon_candidate in candidates:
            if icon_candidate.exists():
                try:
                    with PILImage.open(str(icon_candidate)) as img:
                        return img.copy()
                except Exception:
                    pass
        # Fallback: Generate a nice neon cyan/fire mammoth circle
        img = PILImage.new("RGBA", (64, 64), color=(18, 18, 24, 255))
        return img

    def start_server_thread(self):
        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="info",
            use_colors=False
        )
        server = uvicorn.Server(config)
        self.uvicorn_server = server
        self.is_running = True

        def _run():
            try:
                server.run()
            except Exception as e:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[SERVER THREAD ERROR] {e}\n")
            finally:
                # Only clear the flag if no newer server instance replaced this one.
                if self.uvicorn_server is server:
                    self.is_running = False

        self.server_thread = threading.Thread(target=_run, daemon=True)
        self.server_thread.start()

    def restart_server(self, icon=None, item=None):
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            # Wait until the old server released the port before binding again.
            self.server_thread.join(timeout=10)
        self.start_server_thread()
        if self.icon:
            try:
                self.icon.notify(f"Mammouth Defroster 9000 server restarted on port {self.port}.", "Server Restarted")
            except Exception:
                pass

    def on_copy_url(self, icon=None, item=None):
        copy_to_clipboard(self.public_url)
        if self.icon:
            try:
                self.icon.notify(f"Copied to clipboard:\n{self.public_url}", "URL Copied")
            except Exception:
                pass

    def on_open_logs(self, icon=None, item=None):
        if log_path.exists():
            os.startfile(str(log_path))
        else:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("Mammouth Defroster 9000 Log Initialized.\n")
            os.startfile(str(log_path))

    def on_open_workspace(self, icon=None, item=None):
        ws_dir = BASE_DIR.parent / "workspace"
        ws_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(ws_dir))

    def on_take_screenshot(self, icon=None, item=None):
        res = screen_capture(monitor=1, save_to_workspace=True)
        saved_path = res.get("saved_path") if isinstance(res, dict) else None
        if saved_path and os.path.exists(saved_path):
            os.startfile(saved_path)
            if self.icon:
                try:
                    self.icon.notify(f"Screenshot saved & opened:\n{Path(saved_path).name}", "Desktop Vision")
                except Exception:
                    pass

    def on_launch_mammouth_code(self, icon=None, item=None):
        res = launch_mammouth_terminal()
        if res.get("success"):
            if self.icon:
                try:
                    self.icon.notify("Launched Mammouth Code in new terminal window.", "Mammouth Code")
                except Exception:
                    pass
        else:
            if self.icon:
                try:
                    self.icon.notify(f"Launch failed: {res.get('error', 'Unknown')}", "Mammouth Code")
                except Exception:
                    pass

    def on_exit(self, icon=None, item=None):
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.icon:
            self.icon.stop()
        os._exit(0)

    def create_menu(self):
        return Menu(
            item("🦣 Mammouth Defroster 9000", None, enabled=False),
            item(f"🟢 Status: Online (Port {self.port})", None, enabled=False),
            Menu.SEPARATOR,
            item("🌐 Copy Public SSE URL", self.on_copy_url),
            item("📋 Open Server Logs", self.on_open_logs),
            item("📁 Open Workspace Folder", self.on_open_workspace),
            item("📸 Take Desktop Screenshot", self.on_take_screenshot),
            item("💻 Launch Mammouth Code", self.on_launch_mammouth_code),
            Menu.SEPARATOR,
            item("🔄 Restart Server", self.restart_server),
            item("❌ Exit Defroster 9000", self.on_exit),
        )

    def run(self):
        # 1. Start background server thread
        self.start_server_thread()

        # 2. Build Tray Icon
        image = self.load_icon_image()
        menu = self.create_menu()
        self.icon = pystray.Icon("MammouthDefroster9000", image, "Mammouth Defroster 9000 (Online)", menu)

        # 3. Notify user on startup
        try:
            self.icon.notify(
                f"Defroster 9000 is active on port {self.port}!\nRight-click icon for management menu.",
                "Mammouth Defroster 9000"
            )
        except Exception:
            pass

        # 4. Run main icon loop on main thread (blocks until icon.stop())
        self.icon.run()


if __name__ == "__main__":
    app_tray = DefrosterTrayApp()
    app_tray.run()
