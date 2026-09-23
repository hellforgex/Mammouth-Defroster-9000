"""
Mammouth Defroster 9000 - Embedded Browser Module (Mammouth.ai In-App WebView2)
Hosts a native Microsoft Edge WebView2 control embedded directly into the CustomTkinter Cockpit.
Provides persistent sessions, navigation controls, and seamless MCP URL clipboard integration.
"""

import sys
import os
import ctypes
import webbrowser
from typing import Optional, Callable, Any
import customtkinter as ctk
import pyperclip

HAS_WEBVIEW2 = False
_INIT_ERROR = ""

if sys.platform == "win32":
    try:
        import clr
        clr.AddReference("System.Threading")
        clr.AddReference("System.Windows.Forms")
        from System.Threading import Thread, ApartmentState
        try:
            Thread.CurrentThread.SetApartmentState(ApartmentState.STA)
        except Exception:
            pass
        from System.Windows.Forms import Control
        from webview.window import Window
        from webview.platforms import edgechromium
        from webview.platforms.edgechromium import EdgeChrome

        # Disable private mode to persist cookies, user login, and local storage in profile_dir
        edgechromium._state['private_mode'] = False
        edgechromium.webview_settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False

        user32 = ctypes.windll.user32
        HAS_WEBVIEW2 = True
    except Exception as e:
        _INIT_ERROR = str(e)


class MammouthBrowserFrame(ctk.CTkFrame):
    """Modern embedded browser widget hosting Mammouth.ai inside the Cockpit."""

    def __init__(
        self,
        master,
        get_mcp_url_cb: Optional[Callable[[], str]] = None,
        start_url: str = "https://mammouth.ai",
        profile_dir: Optional[str] = None,
        screenshot_cb: Optional[Callable[[], Optional[str]]] = None,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.get_mcp_url_cb = get_mcp_url_cb
        self.start_url = start_url or "https://mammouth.ai"
        self.screenshot_cb = screenshot_cb

        # Persistent profile directory (ensures login/cookies are stored in app root, never in _internal)
        if not profile_dir:
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.profile_dir = os.path.join(base, "data", "browser_profile")
        else:
            self.profile_dir = os.path.abspath(profile_dir)

        os.makedirs(self.profile_dir, exist_ok=True)

        self.edge: Optional[Any] = None
        self.control: Optional[Any] = None
        self.hwnd: Optional[int] = None
        self.is_embedded = False
        self._is_visible = True

        self._build_ui()

    def _build_ui(self):
        # 1. Navigation & Utility Toolbar
        self.toolbar = ctk.CTkFrame(
            self,
            height=46,
            corner_radius=8,
            fg_color=("#FFFFFF", "#242428"),
            border_width=1,
            border_color=("#CBD5E1", "#38393F")
        )
        self.toolbar.pack(fill="x", padx=6, pady=(4, 6))

        # Brand / Title Label
        title_box = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        title_box.pack(side="left", padx=(10, 8), pady=6)

        ctk.CTkLabel(
            title_box,
            text="🦣 Mammouth.ai",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0F172A", "#FFFFFF")
        ).pack(side="left")

        # Nav Buttons: Back, Forward, Reload, Home
        btn_nav_box = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        btn_nav_box.pack(side="left", padx=4, pady=6)

        self.btn_back = ctk.CTkButton(
            btn_nav_box,
            text="◀",
            width=30,
            height=28,
            corner_radius=6,
            fg_color=("#F1F5F9", "#36373E"),
            hover_color=("#E2E8F0", "#42434B"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#4A4B53"),
            command=self.go_back
        )
        self.btn_back.pack(side="left", padx=2)

        self.btn_forward = ctk.CTkButton(
            btn_nav_box,
            text="▶",
            width=30,
            height=28,
            corner_radius=6,
            fg_color=("#F1F5F9", "#36373E"),
            hover_color=("#E2E8F0", "#42434B"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#4A4B53"),
            command=self.go_forward
        )
        self.btn_forward.pack(side="left", padx=2)

        self.btn_reload = ctk.CTkButton(
            btn_nav_box,
            text="🔄",
            width=30,
            height=28,
            corner_radius=6,
            fg_color=("#F1F5F9", "#36373E"),
            hover_color=("#E2E8F0", "#42434B"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=12),
            border_width=1,
            border_color=("#CBD5E1", "#4A4B53"),
            command=self.reload
        )
        self.btn_reload.pack(side="left", padx=2)

        self.btn_home = ctk.CTkButton(
            btn_nav_box,
            text="🏠",
            width=30,
            height=28,
            corner_radius=6,
            fg_color=("#F1F5F9", "#36373E"),
            hover_color=("#E2E8F0", "#42434B"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=12),
            border_width=1,
            border_color=("#CBD5E1", "#4A4B53"),
            command=self.go_home
        )
        self.btn_home.pack(side="left", padx=2)

        # Right Action Buttons: Screenshot & External Browser (URL bar removed for clean desktop look)
        btn_action_box = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        btn_action_box.pack(side="right", padx=(4, 8), pady=6)

        # Retain btn_copy_mcp for programmatic access, but do not pack into WebApp view
        self.btn_copy_mcp = ctk.CTkButton(
            btn_action_box,
            text="📋 Copy MCP URL",
            width=120,
            height=28,
            corner_radius=6,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._copy_mcp_url
        )

        self.btn_screenshot = ctk.CTkButton(
            btn_action_box,
            text="📸 Screenshot (Ctrl+V)",
            width=165,
            height=28,
            corner_radius=6,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._take_screenshot
        )
        self.btn_screenshot.pack(side="left", padx=(0, 6))

        self.btn_ext_browser = ctk.CTkButton(
            btn_action_box,
            text="🌐 In Browser öffnen",
            width=135,
            height=28,
            corner_radius=6,
            fg_color=("#F1F5F9", "#36373E"),
            hover_color=("#E2E8F0", "#42434B"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#4A4B53"),
            command=lambda: webbrowser.open(self.start_url)
        )
        self.btn_ext_browser.pack(side="left")

        # 2. Viewport Frame for hosting Edge WebView2
        self.viewport = ctk.CTkFrame(
            self,
            corner_radius=8,
            fg_color=("#FFFFFF", "#0D0E12"),
            border_width=1,
            border_color=("#CBD5E1", "#22242E")
        )
        self.viewport.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.viewport.bind("<Configure>", self._on_viewport_resize)

        if not HAS_WEBVIEW2:
            self._show_fallback_ui()

    def _show_fallback_ui(self):
        """Displays friendly fallback UI if WebView2 runtime is missing."""
        box = ctk.CTkFrame(self.viewport, fg_color="transparent")
        box.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(box, text="🌐", font=ctk.CTkFont(size=48)).pack(pady=(0, 10))
        ctk.CTkLabel(
            box,
            text="Edge WebView2 Laufzeitumgebung nicht verfügbar",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#0F172A", "#F3F4F6")
        ).pack(pady=(0, 4))

        err_msg = _INIT_ERROR or "Microsoft Edge WebView2 Runtime konnte auf diesem System nicht geladen werden."
        ctk.CTkLabel(
            box,
            text=f"{err_msg}\n\nDu kannst Mammouth.ai weiterhin problemlos im externen Browser nutzen:",
            font=ctk.CTkFont(size=12),
            text_color=("#64748B", "#94A3B8"),
            wraplength=480
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            box,
            text="🚀 Mammouth.ai im Browser öffnen",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            height=36,
            command=lambda: webbrowser.open(self.start_url)
        ).pack()

    def ensure_initialized(self):
        """Initializes and embeds the WebView2 control into the viewport."""
        if self.is_embedded or not HAS_WEBVIEW2:
            return

        try:
            self.update_idletasks()
            w = max(self.viewport.winfo_width(), 400)
            h = max(self.viewport.winfo_height(), 300)

            control = Control()
            window = Window("Mammouth", "Mammouth.ai", self.start_url)
            window.real_url = self.start_url
            self.edge = EdgeChrome(control, window, self.profile_dir)
            self.control = control
            self.hwnd = int(str(control.Handle))

            parent_hwnd = self.viewport.winfo_id()
            user32.SetParent(self.hwnd, parent_hwnd)
            user32.MoveWindow(self.hwnd, 0, 0, w, h, True)
            user32.ShowWindow(self.hwnd, 5)  # SW_SHOW

            # Explicitly load the start URL
            try:
                self.edge.load_url(self.start_url)
            except Exception:
                pass

            # Update URL pill when navigation completes (if present)
            def _on_nav_completed(sender, args):
                try:
                    current_uri = str(self.edge.webview.Source) if hasattr(self.edge.webview, "Source") else self.start_url
                    if current_uri and hasattr(self, "lbl_url"):
                        self.after(0, lambda u=current_uri: self.lbl_url.configure(text=f"🔒 {u}") if hasattr(self, "lbl_url") else None)
                except Exception:
                    pass

            try:
                self.edge.webview.NavigationCompleted += _on_nav_completed
            except Exception:
                pass

            self.is_embedded = True
        except Exception as e:
            global _INIT_ERROR
            _INIT_ERROR = str(e)
            self._show_fallback_ui()

    def _on_viewport_resize(self, event):
        """Resizes the Win32 WebView2 control to match the viewport container."""
        if self.hwnd and self.is_embedded and self._is_visible:
            user32.MoveWindow(self.hwnd, 0, 0, event.width, event.height, True)

    def set_tab_visible(self, visible: bool):
        """Controls Win32 visibility when switching between tabs."""
        self._is_visible = visible
        if self.hwnd and self.is_embedded:
            cmd = 5 if visible else 0  # SW_SHOW vs SW_HIDE
            user32.ShowWindow(self.hwnd, cmd)
            if visible:
                w = self.viewport.winfo_width()
                h = self.viewport.winfo_height()
                user32.MoveWindow(self.hwnd, 0, 0, w, h, True)

    def go_back(self):
        if self.edge and hasattr(self.edge, "webview"):
            try:
                self.edge.webview.GoBack()
            except Exception:
                pass

    def go_forward(self):
        if self.edge and hasattr(self.edge, "webview"):
            try:
                self.edge.webview.GoForward()
            except Exception:
                pass

    def reload(self):
        if self.edge and hasattr(self.edge, "webview"):
            try:
                self.edge.webview.Reload()
            except Exception:
                pass

    def go_home(self):
        if self.edge:
            try:
                self.edge.load_url(self.start_url)
            except Exception:
                pass

    def _copy_mcp_url(self):
        url = ""
        if self.get_mcp_url_cb:
            try:
                url = self.get_mcp_url_cb()
            except Exception:
                pass
        if not url:
            url = "http://127.0.0.1:8000/mcp"

        pyperclip.copy(url)
        self.btn_copy_mcp.configure(text="✓ Kopiert!", fg_color="#10B981")
        self.after(2000, lambda: self.btn_copy_mcp.configure(text="📋 Copy MCP URL", fg_color=("#059669", "#10B981")))

    def _take_screenshot(self):
        saved_path = None
        if self.screenshot_cb:
            try:
                saved_path = self.screenshot_cb()
            except Exception:
                pass
        if not saved_path:
            try:
                from modules.screen_capture import screen_capture, copy_image_to_clipboard, screen_grant_consent
                screen_grant_consent("always")
                res = screen_capture(monitor=1, save_to_workspace=True)
                if isinstance(res, dict) and res.get("saved_path"):
                    saved_path = res.get("saved_path")
                    copy_image_to_clipboard(saved_path)
            except Exception:
                pass

        if hasattr(self, "btn_screenshot"):
            self.btn_screenshot.configure(text="✓ Im Clipboard! (Ctrl+V)", fg_color="#10B981")
            self.after(2500, lambda: self.btn_screenshot.configure(text="📸 Screenshot (Ctrl+V)", fg_color=("#059669", "#10B981")))

