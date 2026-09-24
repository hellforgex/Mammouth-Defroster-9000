"""
Mammouth Defroster 9000 - Embedded Browser Module (Mammouth.ai In-App WebView2)
Hosts a native Microsoft Edge WebView2 control embedded directly into the CustomTkinter Cockpit.
Provides persistent sessions, navigation controls, and seamless MCP URL clipboard integration.
"""

import sys
import os
import ctypes
import webbrowser
import urllib.parse
from pathlib import Path
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
        edgechromium.webview_settings['ALLOW_DOWNLOADS'] = True

        user32 = ctypes.windll.user32
        HAS_WEBVIEW2 = True
    except Exception as e:
        _INIT_ERROR = str(e)


def _is_download_uri(uri: str) -> bool:
    """Detects whether a URI points to a downloadable file or export endpoint."""
    if not uri:
        return False
    lower = uri.lower().split("?")[0].split("#")[0]
    download_exts = (
        ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
        ".csv", ".tsv", ".xlsx", ".xls",
        ".json", ".jsonl", ".parquet",
        ".pdf", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
        ".txt", ".py", ".md", ".log",
        ".exe", ".msi", ".bin"
    )
    if any(lower.endswith(ext) for ext in download_exts):
        return True
    if "/download" in lower or "response-content-disposition" in lower or "export" in lower:
        return True
    return False


def _is_trusted_browser_origin(uri: str) -> bool:
    """Verifies if the requested URI originates from trusted domains (Mammouth.ai, localhost, 127.0.0.1)."""
    if not uri:
        return False
    try:
        parsed = urllib.parse.urlparse(uri)
        domain = (parsed.hostname or "").lower()
        if not domain:
            # Allow blob/data schemes if needed
            return uri.lower().startswith("blob:") or uri.lower().startswith("data:")
        trusted_domains = ("mammouth.ai", "localhost", "127.0.0.1")
        return any(domain == td or domain.endswith("." + td) for td in trusted_domains)
    except Exception:
        return False


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
        # 1. Sleek, Borderless Navigation Bar (Blends seamlessly with the Cockpit theme)
        self.toolbar = ctk.CTkFrame(
            self,
            height=32,
            corner_radius=0,
            fg_color=("#FFFFFF", "#202124"),
            border_width=0
        )
        self.toolbar.pack(fill="x", padx=0, pady=0)

        # Nav Buttons: Back, Forward, Reload, Home
        btn_nav_box = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        btn_nav_box.pack(side="left", padx=8, pady=3)

        self.btn_back = ctk.CTkButton(
            btn_nav_box,
            text="◀",
            width=28,
            height=24,
            corner_radius=4,
            fg_color=("#F1F5F9", "#2F2F33"),
            hover_color=("#E2E8F0", "#38393F"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=10, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#3E4048"),
            command=self.go_back
        )
        self.btn_back.pack(side="left", padx=2)

        self.btn_forward = ctk.CTkButton(
            btn_nav_box,
            text="▶",
            width=28,
            height=24,
            corner_radius=4,
            fg_color=("#F1F5F9", "#2F2F33"),
            hover_color=("#E2E8F0", "#38393F"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=10, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#3E4048"),
            command=self.go_forward
        )
        self.btn_forward.pack(side="left", padx=2)

        self.btn_reload = ctk.CTkButton(
            btn_nav_box,
            text="🔄",
            width=28,
            height=24,
            corner_radius=4,
            fg_color=("#F1F5F9", "#2F2F33"),
            hover_color=("#E2E8F0", "#38393F"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11),
            border_width=1,
            border_color=("#CBD5E1", "#3E4048"),
            command=self.reload
        )
        self.btn_reload.pack(side="left", padx=2)

        self.btn_home = ctk.CTkButton(
            btn_nav_box,
            text="🏠",
            width=28,
            height=24,
            corner_radius=4,
            fg_color=("#F1F5F9", "#2F2F33"),
            hover_color=("#E2E8F0", "#38393F"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11),
            border_width=1,
            border_color=("#CBD5E1", "#3E4048"),
            command=self.go_home
        )
        self.btn_home.pack(side="left", padx=2)

        # Download status feedback label
        self.lbl_download_status = ctk.CTkLabel(
            self.toolbar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10B981"
        )
        self.lbl_download_status.pack(side="left", padx=10)

        # Right Action Buttons: External Browser
        btn_action_box = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        btn_action_box.pack(side="right", padx=8, pady=3)

        # Retain btn_copy_mcp and btn_screenshot for API/test compatibility without duplicate UI packing
        self.btn_copy_mcp = ctk.CTkButton(
            btn_action_box,
            text="📋 Copy MCP URL",
            width=120,
            height=24,
            corner_radius=4,
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
            height=24,
            corner_radius=4,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._take_screenshot
        )

        self.btn_ext_browser = ctk.CTkButton(
            btn_action_box,
            text="🌐 In Browser öffnen",
            width=135,
            height=24,
            corner_radius=4,
            fg_color=("#F1F5F9", "#2F2F33"),
            hover_color=("#E2E8F0", "#38393F"),
            text_color=("#0F172A", "#FFFFFF"),
            font=ctk.CTkFont(size=11, weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#3E4048"),
            command=lambda: webbrowser.open(self.start_url)
        )
        self.btn_ext_browser.pack(side="right")

        # 2. Seamless Full-Bleed Viewport Frame for hosting Edge WebView2
        self.viewport = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=("#FFFFFF", "#202124"),
            border_width=0
        )
        self.viewport.pack(fill="both", expand=True, padx=0, pady=0)
        self.viewport.bind("<Configure>", self._on_viewport_resize)
        self.viewport.bind("<Button-1>", lambda e: self.focus_browser())

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
            # Override pywebview's default on_download_starting before it gets wired
            try:
                self.edge.on_download_starting = lambda sender, args: None
            except Exception:
                pass
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

            def _setup_core_webview2(sender, args):
                try:
                    target_wv = sender if hasattr(sender, "CoreWebView2") else self.edge.webview
                    if hasattr(target_wv, "CoreWebView2") and target_wv.CoreWebView2:
                        core = target_wv.CoreWebView2
                        # 1. Standard Edge desktop User-Agent to avoid Google/Cloudflare "disallowed_useragent" or bot challenges
                        core.Settings.UserAgent = (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
                        )
                        # 2. Enable keyboard accelerator shortcuts (Ctrl+C, Ctrl+V, Ctrl+A) and right-click context menu
                        core.Settings.AreBrowserAcceleratorKeysEnabled = True
                        core.Settings.AreDefaultContextMenusEnabled = True
                        core.Settings.IsGeneralAutofillEnabled = True
                        core.Settings.IsPasswordAutosaveEnabled = True

                        # 3. Allow clipboard, downloads, and storage permissions only for trusted origins
                        try:
                            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
                            def _on_permission(s, a):
                                try:
                                    req_uri = str(getattr(a, "Uri", "") or "")
                                    if _is_trusted_browser_origin(req_uri):
                                        a.set_State(CoreWebView2PermissionState.Allow)
                                        a.set_SavesInProfile(True)
                                    else:
                                        a.set_State(CoreWebView2PermissionState.Deny)
                                except Exception:
                                    pass
                            core.PermissionRequested += _on_permission
                        except Exception:
                            pass

                        # 4. Wire custom native download handler
                        try:
                            core.DownloadStarting -= self.edge.on_download_starting
                        except Exception:
                            pass
                        core.DownloadStarting += self._on_download_starting

                        # 5. Replace NewWindowRequested handler to support popup OAuth flows properly
                        try:
                            core.NewWindowRequested -= self.edge.on_new_window_request
                        except Exception:
                            pass
                        core.NewWindowRequested += self._on_new_window_requested
                except Exception:
                    pass

            try:
                if self.edge.webview.CoreWebView2 is not None:
                    _setup_core_webview2(self.edge.webview, None)
                else:
                    self.edge.webview.CoreWebView2InitializationCompleted += _setup_core_webview2
            except Exception:
                pass

            # Update URL pill when navigation completes and handle auto-recovery
            def _on_nav_completed(sender, args):
                try:
                    current_uri = str(self.edge.webview.Source) if hasattr(self.edge.webview, "Source") else self.start_url
                    if current_uri and hasattr(self, "lbl_url"):
                        self.after(0, lambda u=current_uri: self.lbl_url.configure(text=f"🔒 {u}") if hasattr(self, "lbl_url") else None)
                    # Automatically redirect stuck OAuth callbacks or errors back to Mammouth home
                    if "/api/auth/callback" in current_uri or "/api/mcp/oauth/callback" in current_uri or "mcp_error" in current_uri:
                        self.after(800, lambda: self.edge.load_url(self.start_url))
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

    def _on_new_window_requested(self, sender, args):
        """Handles window.open requests (e.g. Google Login, GitHub OAuth, Mammouth MCP Consent, file downloads)
        in a native popup window preserving window.opener and sharing authentication cookies."""
        try:
            uri = str(args.Uri)
            uri_lower = uri.lower()

            # Blob and data URLs are process-local and must always remain in WebView2
            is_local_protocol = uri_lower.startswith("blob:") or uri_lower.startswith("data:")

            # Detect if this is an auth flow, app navigation, or direct file download
            is_auth_or_app = (
                is_local_protocol
                or _is_download_uri(uri)
                or "mammouth.ai" in uri_lower
                or "accounts.google.com" in uri_lower
                or "github.com/login" in uri_lower
                or "appleid.apple.com" in uri_lower
                or "oauth" in uri_lower
                or "auth" in uri_lower
                or "login" in uri_lower
                or "signin" in uri_lower
                or ".ts.net" in uri_lower
                or "127.0.0.1" in uri_lower
                or "localhost" in uri_lower
            )

            if not is_auth_or_app and uri.startswith("http"):
                args.set_Handled(True)
                webbrowser.open(uri)
                return

            from System.Windows.Forms import Form, DockStyle, FormStartPosition
            from Microsoft.Web.WebView2.WinForms import WebView2

            deferral = args.GetDeferral()

            popup_form = Form()
            popup_form.Text = "Mammouth — Login & Autorisierung"
            popup_form.Width = 620
            popup_form.Height = 720
            popup_form.StartPosition = FormStartPosition.CenterScreen

            popup_wv = WebView2()
            popup_wv.Dock = DockStyle.Fill
            popup_form.Controls.Add(popup_wv)

            def _on_popup_ready(s, a):
                try:
                    if hasattr(popup_wv, "CoreWebView2") and popup_wv.CoreWebView2:
                        popup_core = popup_wv.CoreWebView2
                        popup_core.Settings.UserAgent = (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
                        )
                        # Enable copy/paste shortcuts and context menu in popup window
                        popup_core.Settings.AreBrowserAcceleratorKeysEnabled = True
                        popup_core.Settings.AreDefaultContextMenusEnabled = True
                        popup_core.Settings.IsGeneralAutofillEnabled = True
                        popup_core.Settings.IsPasswordAutosaveEnabled = True

                        # Downloads in popup window
                        popup_core.DownloadStarting += self._on_download_starting
                        def _on_popup_download_started(ds, da):
                            # A download started in the popup, close the blank popup form
                            self.after(600, lambda: popup_form.Close())
                        popup_core.DownloadStarting += _on_popup_download_started

                        try:
                            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
                            def _on_popup_permission(ps, pa):
                                try:
                                    req_uri = str(getattr(pa, "Uri", "") or "")
                                    if _is_trusted_browser_origin(req_uri):
                                        pa.set_State(CoreWebView2PermissionState.Allow)
                                    else:
                                        pa.set_State(CoreWebView2PermissionState.Deny)
                                except Exception:
                                    pass
                            popup_core.PermissionRequested += _on_popup_permission
                        except Exception:
                            pass

                        def _on_close_req(cs, ca):
                            popup_form.Close()
                        popup_core.WindowCloseRequested += _on_close_req

                    args.set_NewWindow(popup_wv.CoreWebView2)
                    deferral.Complete()
                    popup_form.Show()
                except Exception:
                    try:
                        deferral.Complete()
                    except Exception:
                        pass

            popup_wv.CoreWebView2InitializationCompleted += _on_popup_ready
            popup_wv.EnsureCoreWebView2Async(sender.Environment)

            def _on_form_closed(s, a):
                try:
                    deferral.Complete()
                except Exception:
                    pass
                try:
                    popup_wv.Dispose()
                except Exception:
                    pass
            popup_form.FormClosed += _on_form_closed

        except Exception as e:
            try:
                args.set_Handled(True)
                if hasattr(self, "edge") and self.edge:
                    self.edge.load_url(str(args.Uri))
            except Exception:
                pass

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
                self.focus_browser()

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

    def focus_and_paste(self, delay_ms: int = 200):
        """Focuses the embedded WebView2 control and simulates Ctrl+V to attach clipboard content."""
        if not HAS_WEBVIEW2 or not self.hwnd:
            return

        def _do_paste():
            try:
                import time
                # 1. Set foreground focus to the Win32 WebView2 window
                user32.SetForegroundWindow(self.hwnd)
                user32.SetFocus(self.hwnd)

                # 2. Try JavaScript focus on the chat textarea/input
                if self.edge and hasattr(self.edge, "webview"):
                    js_focus = """
                    (function() {
                        var el = document.querySelector('textarea, div[contenteditable="true"], input[type="text"]');
                        if (el) {
                            el.focus();
                            return true;
                        }
                        return false;
                    })();
                    """
                    try:
                        if hasattr(self.edge.webview, "CoreWebView2") and self.edge.webview.CoreWebView2:
                            self.edge.webview.CoreWebView2.ExecuteScriptAsync(js_focus)
                    except Exception:
                        pass

                # 3. Simulate Ctrl+V key combination via Win32 keybd_event
                VK_CONTROL = 0x11
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002

                time.sleep(0.08)
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass

        import threading
        import time
        threading.Thread(target=lambda: (time.sleep(delay_ms / 1000.0), _do_paste()), daemon=True).start()

    def focus_browser(self):
        """Brings Win32 keyboard and mouse focus to the embedded WebView2 window."""
        if self.hwnd and self.is_embedded:
            try:
                user32.SetFocus(self.hwnd)
            except Exception:
                pass

    def _show_download_notification(self, text: str, success: bool = True):
        """Displays transient download status feedback in the toolbar."""
        if hasattr(self, "lbl_download_status"):
            color = "#10B981" if success else "#EF4444"
            self.lbl_download_status.configure(text=text, text_color=color)
            self.after(6000, lambda: self.lbl_download_status.configure(text="") if hasattr(self, "lbl_download_status") else None)

    def _prompt_save_file(self, initial_dir: str, suggested_name: str) -> Optional[str]:
        """Prompts the user with native SaveFileDialog. Returns chosen file path or None if cancelled."""
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dialog = SaveFileDialog()
        dialog.Title = "Mammouth — Datei speichern"
        dialog.InitialDirectory = initial_dir
        dialog.FileName = suggested_name
        dialog.Filter = "Alle Dateien (*.*)|*.*"
        dialog.RestoreDirectory = True

        res = dialog.ShowDialog()
        if res == DialogResult.OK and dialog.FileName:
            return str(dialog.FileName)
        return None

    def _on_download_starting(self, sender, args):
        """Native download handler presenting a SaveFileDialog and tracking download state."""
        deferral = None
        try:
            deferral = args.GetDeferral()
        except Exception:
            pass

        try:
            download_op = args.DownloadOperation
            suggested_path = str(args.ResultFilePath or "")
            suggested_name = os.path.basename(suggested_path) if suggested_path else "download"
            suggested_name = "".join(c for c in suggested_name if c not in '<>:"/\\|?*').strip() or "download"

            downloads_dir = str(Path.home() / "Downloads")
            os.makedirs(downloads_dir, exist_ok=True)

            save_dest = self._prompt_save_file(downloads_dir, suggested_name)
            if save_dest:
                args.set_ResultFilePath(save_dest)
                args.set_Handled(True)

                final_name = os.path.basename(save_dest)
                self.after(0, lambda n=final_name: self._show_download_notification(f"⬇ Lade herunter: {n}...", success=True))

                def _on_state_changed(s, a):
                    try:
                        state_str = str(download_op.State)
                        if "Completed" in state_str:
                            self.after(0, lambda n=final_name: self._show_download_notification(f"✓ Gespeichert: {n}", success=True))
                        elif "Interrupted" in state_str:
                            self.after(0, lambda n=final_name: self._show_download_notification(f"⚠ Download abgebrochen: {n}", success=False))
                    except Exception:
                        pass

                download_op.StateChanged += _on_state_changed
            else:
                args.set_Cancel(True)
        except Exception:
            # Fallback in case dialog cannot be displayed: save directly to ~/Downloads
            try:
                downloads_dir = str(Path.home() / "Downloads")
                suggested_name = os.path.basename(str(args.ResultFilePath or "download"))
                suggested_name = "".join(c for c in suggested_name if c not in '<>:"/\\|?*').strip() or "download"
                fallback_path = os.path.join(downloads_dir, suggested_name)
                args.set_ResultFilePath(fallback_path)
                args.set_Handled(True)
                self.after(0, lambda n=suggested_name: self._show_download_notification(f"✓ Gespeichert unter Downloads: {n}", success=True))
            except Exception:
                pass
        finally:
            if deferral:
                try:
                    deferral.Complete()
                except Exception:
                    pass


