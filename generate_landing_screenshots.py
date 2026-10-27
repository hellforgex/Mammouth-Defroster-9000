"""Generate high-resolution, privacy-safe official screenshots for Mammouth Defroster 9000 v0.7.0."""

import sys
import os
import time
import ctypes
import ctypes.wintypes
from pathlib import Path
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
if hdesk:
    user32.SetThreadDesktop(hdesk)

import customtkinter as ctk
import gui

ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def capture_window_hwnd(hwnd: int, output_path: Path):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbm = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    # PW_RENDERFULLCONTENT = 2
    user32.PrintWindow(hwnd, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.wintypes.DWORD),
            ("biWidth", ctypes.wintypes.LONG),
            ("biHeight", ctypes.wintypes.LONG),
            ("biPlanes", ctypes.wintypes.WORD),
            ("biBitCount", ctypes.wintypes.WORD),
            ("biCompression", ctypes.wintypes.DWORD),
            ("biSizeImage", ctypes.wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.wintypes.LONG),
            ("biYPelsPerMeter", ctypes.wintypes.LONG),
            ("biClrUsed", ctypes.wintypes.DWORD),
            ("biClrImportant", ctypes.wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)
    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    im.save(str(output_path), optimize=True)
    print(f"Captured {output_path.name}: {im.size}")

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)


def render_screenshot(appearance_mode: str, tab_key: str, output_file: str, customize_fn=None):
    ctk.set_appearance_mode(appearance_mode)
    ctk.set_default_color_theme("dark-blue")

    app = gui.MammouthControlCenter()
    app.title(f"Mammouth Defroster 9000 🦣❄️🔥 ({gui.APP_VERSION})")
    app.geometry("1330x925+60+30")

    if appearance_mode == "Light":
        app._on_theme_changed("Light")
        if hasattr(app, "theme_menu"):
            app.theme_menu.set("Light")

    time.sleep(0.9)
    app.update_idletasks()
    app.update()

    app._select_nav_tab(tab_key)

    if customize_fn:
        customize_fn(app)

    app.update_idletasks()
    app.update()
    time.sleep(0.5)

    hwnd = int(app.wm_frame(), 16)
    capture_window_hwnd(hwnd, ASSETS_DIR / output_file)

    if appearance_mode == "Light":
        cfg = gui.load_config()
        cfg["server"]["appearance_mode"] = "Dark"
        gui.save_config(cfg)

    app.destroy()
    time.sleep(0.4)


def customize_dashboard_dark(app):
    if hasattr(app, "lbl_public_url"):
        app.lbl_public_url.configure(text="https://mammouth-cockpit.ts.net/sse")

    if hasattr(app, "lbl_local_url"):
        app.lbl_local_url.configure(text="http://127.0.0.1:8000/sse")

    if hasattr(app, "status_badge"):
        app.status_badge.configure(text="● ONLINE (Port 8000)", text_color="#10B981")

    if hasattr(app, "btn_toggle_server"):
        app.btn_toggle_server.configure(text="⏹ STOP SERVER", fg_color="#EF4444", hover_color="#DC2626")

    if hasattr(app, "lbl_stat_uptime"):
        app.lbl_stat_uptime.configure(text="⏱️ Uptime: 01:24:50")

    if hasattr(app, "lbl_stat_tools"):
        app.lbl_stat_tools.configure(text="⚡ 89 Tools active")

    if hasattr(app, "lbl_nav_tools"):
        app.lbl_nav_tools.configure(text="⚡ 89 Tools active")

    if hasattr(app, "lbl_stat_cpu"):
        app.lbl_stat_cpu.configure(text="💻 CPU: 3.8%")
    if hasattr(app, "bar_cpu"):
        app.bar_cpu.set(0.038)
    if hasattr(app, "lbl_stat_ram"):
        app.lbl_stat_ram.configure(text="🧠 RAM: 24.2%")
    if hasattr(app, "bar_ram"):
        app.bar_ram.set(0.242)

    if hasattr(app, "lbl_nav_cpu"):
        app.lbl_nav_cpu.configure(text="CPU: 3.8%")
    if hasattr(app, "bar_nav_cpu"):
        app.bar_nav_cpu.set(0.038)
    if hasattr(app, "lbl_nav_ram"):
        app.lbl_nav_ram.configure(text="RAM: 24.2%")
    if hasattr(app, "bar_nav_ram"):
        app.bar_nav_ram.set(0.242)

    if hasattr(app, "log_textbox"):
        app.log_textbox.configure(state="normal")
        app.log_textbox.delete("1.0", "end")
        logs = [
            "[12:00:01] Mammouth Defroster 9000 v0.7.0 initialized. Sovereign Cockpit Ready.",
            "[12:00:01] [QUICK-LAUNCHER] Global summon hotkey active: Ctrl+Shift+M (ID: 2001)",
            "[12:00:01] [COPILOT] Screen Copilot global hotkey active: Ctrl+Shift+Space (ID: 2002)",
            "[12:00:01] [SMART CLIPBOARD] Global hotkey active: Ctrl+Shift+K (ID: 2003)",
            "[12:00:02] Starting in-process FastMCP server on 127.0.0.1:8000...",
            "[12:00:02] [NETWORK] Tailscale Funnel background proxy activated.",
            "[12:00:02] Server is LIVE! Active Endpoint: https://mammouth-cockpit.ts.net/sse",
            "[12:00:02] [CAPABILITIES] 15 Defrosted Modules loaded (89 tools total exposed).",
            "[12:00:02] [SELF-TOOLING] Autonomous Skill Engine active ($0.00 local execution).",
            "[12:00:02] [SECURITY] Fail-Closed token authentication & DPAPI credentials active.",
            "[12:00:03] [INDEXER] SQLite FTS5 Workspace Indexer ready for ./workspace.",
        ]
        for l in logs:
            app.log_textbox.insert("end", l + "\n")
        app.log_textbox.configure(state="disabled")


def customize_settings_light(app):
    if hasattr(app, "theme_menu"):
        app.theme_menu.set("Light")

    if hasattr(app, "lbl_nav_tools"):
        app.lbl_nav_tools.configure(text="⚡ 89 Tools active")

    if hasattr(app, "lbl_nav_cpu"):
        app.lbl_nav_cpu.configure(text="CPU: 3.8%")
    if hasattr(app, "bar_nav_cpu"):
        app.bar_nav_cpu.set(0.038)
    if hasattr(app, "lbl_nav_ram"):
        app.lbl_nav_ram.configure(text="RAM: 24.2%")
    if hasattr(app, "bar_nav_ram"):
        app.bar_nav_ram.set(0.242)


def customize_tools_dark(app):
    if hasattr(app, "lbl_nav_tools"):
        app.lbl_nav_tools.configure(text="⚡ 89 Tools active")

    if hasattr(app, "lbl_nav_cpu"):
        app.lbl_nav_cpu.configure(text="CPU: 3.8%")
    if hasattr(app, "bar_nav_cpu"):
        app.bar_nav_cpu.set(0.038)
    if hasattr(app, "lbl_nav_ram"):
        app.lbl_nav_ram.configure(text="RAM: 24.2%")
    if hasattr(app, "bar_nav_ram"):
        app.bar_nav_ram.set(0.242)

    if hasattr(app, "scroll_skills"):
        # Scroll to show Playwright Multi-Browser controls, Vision Gate, and Local RAG
        app.scroll_skills._parent_canvas.yview_moveto(0.605)
        app.update_idletasks()
        app.update()


if __name__ == "__main__":
    print("Generating cockpit_dark.png...")
    render_screenshot("Dark", "📊 Dashboard & Live Console", "cockpit_dark.png", customize_dashboard_dark)

    print("Generating cockpit_light.png...")
    render_screenshot("Light", "⚙️ Security & Settings", "cockpit_light.png", customize_settings_light)

    print("Generating cockpit_tools.png...")
    render_screenshot("Dark", "⚡ Modular Capabilities (15 Modules)", "cockpit_tools.png", customize_tools_dark)

    print("All screenshots generated successfully!")
