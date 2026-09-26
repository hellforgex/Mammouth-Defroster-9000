"""
Mammouth Defroster 9000 - Embedded Browser Module (Mammouth.ai In-App WebView2)
Hosts a native Microsoft Edge WebView2 control embedded directly into the CustomTkinter Cockpit.
Provides persistent sessions, navigation controls, and seamless MCP URL clipboard integration.
"""

import sys
import os
import json
import ctypes
import webbrowser
import urllib.parse
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
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

        # Neutralize pywebview's crash-prone native event handlers on EdgeChrome class:
        # 1. on_script_notify expects exactly [func_name, func_param, value_id].
        #    Any other WebMessage (e.g. JSON dict from Mammouth quota or navigation)
        #    causes ValueError: not enough values to unpack, which calls logger.exception
        #    on a native thread without Python GIL, instantly terminating the process.
        def _safe_edgechrome_on_script_notify(self, sender, args):
            pass

        # 2. on_navigation_completed attempts inject_pywebview, which crashes with
        #    AttributeError: 'Window' object has no attribute 'js_api_endpoint' on custom Window instances.
        def _safe_edgechrome_on_nav_completed(self, sender, args):
            try:
                if sender and hasattr(sender, "Source"):
                    self.url = str(sender.Source)
            except Exception:
                pass

        # 3. on_download_starting creates WinForms SaveFileDialog on .NET COM thread,
        #    which disrupts GUI message pumps and crashes if Window.localization is missing.
        def _safe_edgechrome_on_download_starting(self, sender, args):
            pass

        edgechromium.EdgeChrome.on_script_notify = _safe_edgechrome_on_script_notify
        edgechromium.EdgeChrome.on_navigation_completed = _safe_edgechrome_on_nav_completed
        edgechromium.EdgeChrome.on_download_starting = _safe_edgechrome_on_download_starting

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


def _native_save_file_dialog(initial_dir: str, default_name: str, title: str = "Mammouth — Datei speichern", hwnd_owner: int = 0) -> Optional[str]:
    """Prompts the user with native Windows GetSaveFileNameW dialog.
    Pure Win32 C API: thread-safe, STA/MTA agnostic, zero COM or Tkinter message-loop side effects."""
    if os.name == "nt":
        try:
            from ctypes import wintypes

            class OPENFILENAME(ctypes.Structure):
                _fields_ = [
                    ('lStructSize', wintypes.DWORD),
                    ('hwndOwner', wintypes.HWND),
                    ('hInstance', wintypes.HINSTANCE),
                    ('lpstrFilter', wintypes.LPCWSTR),
                    ('lpstrCustomFilter', wintypes.LPWSTR),
                    ('nMaxCustFilter', wintypes.DWORD),
                    ('nFilterIndex', wintypes.DWORD),
                    ('lpstrFile', wintypes.LPWSTR),
                    ('nMaxFile', wintypes.DWORD),
                    ('lpstrFileTitle', wintypes.LPWSTR),
                    ('nMaxFileTitle', wintypes.DWORD),
                    ('lpstrInitialDir', wintypes.LPCWSTR),
                    ('lpstrTitle', wintypes.LPCWSTR),
                    ('Flags', wintypes.DWORD),
                    ('nFileOffset', wintypes.WORD),
                    ('nFileExtension', wintypes.WORD),
                    ('lpstrDefExt', wintypes.LPCWSTR),
                    ('lCustData', wintypes.LPARAM),
                    ('lpfnHook', wintypes.LPVOID),
                    ('lpTemplateName', wintypes.LPCWSTR),
                    ('pvReserved', wintypes.LPVOID),
                    ('dwReserved', wintypes.DWORD),
                    ('FlagsEx', wintypes.DWORD)
                ]

            buf = ctypes.create_unicode_buffer(1024)
            buf.value = default_name

            filter_str = "Alle Dateien (*.*)\0*.*\0\0"

            ofn = OPENFILENAME()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAME)
            ofn.hwndOwner = hwnd_owner or 0
            ofn.lpstrFilter = filter_str
            ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
            ofn.nMaxFile = 1024
            ofn.lpstrInitialDir = initial_dir
            ofn.lpstrTitle = title
            # OFN_OVERWRITEPROMPT (0x02) | OFN_PATHMUSTEXIST (0x800) | OFN_NOCHANGEDIR (0x08)
            ofn.Flags = 0x00000002 | 0x00000800 | 0x00000008

            if ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
                val = str(buf.value).strip()
                if val:
                    return os.path.normpath(val)
            return None
        except Exception:
            pass

    # Non-Windows or fallback
    try:
        import tkinter.filedialog as fd
        chosen = fd.asksaveasfilename(
            title=title,
            initialdir=initial_dir,
            initialfile=default_name
        )
        if chosen:
            return os.path.normpath(str(chosen))
        return None
    except Exception:
        return None


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


MAMMOUTH_BRAND_COLORS = {
    "claude": ("#E07A5F", "Claude"),
    "gpt": ("#10B981", "GPT"),
    "glm": ("#64748B", "GLM"),
    "gemini": ("#38BDF8", "Gemini"),
    "perplexity": ("#06B6D4", "Perplexity"),
    "mistral": ("#F59E0B", "Mistral"),
    "black-forest-labs": ("#8B5CF6", "FLUX"),
}

PLAN_MULTIPLIERS = {
    "starter": (1, "Starter x1"),
    "standard": (3, "Standard x3"),
    "pro": (3, "Pro x3"),
    "expert": (10, "Expert x10"),
    "advanced": (10, "Advanced x10"),
    "enterprise": (10, "Enterprise x10"),
    "free": (0, "Free"),
    "unsubscribed": (0, "Free / None"),
    "none": (0, "Free / None")
}

BASE_THRESHOLD_CENTS = 150  # GAUGE_MAX_CENTS in Mammouth.ai ($1.50 per 3h session window)


def parse_mammouth_quota_data(payload: Optional[Any]) -> Dict[str, Any]:
    """Parses raw Mammouth quota payload into standardized UI telemetry metrics."""
    if not payload or not isinstance(payload, dict):
        return {
            "is_logged_in": False,
            "plan_id": "unknown",
            "plan_label": "Nicht eingeloggt",
            "total_percent": 0.0,
            "current_spend_cents": 0.0,
            "max_spend_cents": float(BASE_THRESHOLD_CENTS),
            "brands": [],
            "timestamp": 0,
            "raw": payload or {}
        }

    current = payload.get("current")
    if not isinstance(current, dict):
        current = {}
    recent = payload.get("recent")
    if not isinstance(recent, dict):
        recent = {}

    is_logged_in = bool(payload.get("ok", False) and (current or recent))
    if not is_logged_in:
        return {
            "is_logged_in": False,
            "plan_id": "unknown",
            "plan_label": "Nicht eingeloggt",
            "total_percent": 0.0,
            "current_spend_cents": 0.0,
            "max_spend_cents": float(BASE_THRESHOLD_CENTS),
            "brands": [],
            "timestamp": payload.get("ts", 0),
            "raw": payload
        }

    plan_key = str(current.get("usagePlan") or current.get("plan") or "starter").lower().strip()
    mult, plan_label = PLAN_MULTIPLIERS.get(plan_key, (1, f"{plan_key.capitalize()} x1"))

    max_cents = float(BASE_THRESHOLD_CENTS * mult) if mult > 0 else float(BASE_THRESHOLD_CENTS)
    raw_spend = (
        current.get("currentSpendCents")
        if current.get("currentSpendCents") is not None
        else (current.get("spendCents") if current.get("spendCents") is not None else current.get("current_spend_cents", 0.0))
    )
    try:
        current_spend = float(raw_spend or 0.0)
    except (ValueError, TypeError):
        current_spend = 0.0

    if max_cents > 0:
        pct = round(min(100.0, max(0.0, (current_spend / max_cents) * 100.0)), 1)
    else:
        pct = 0.0

    raw_brands = recent.get("byBrand") or recent.get("brands") or recent.get("by_brand") or []
    brands_list = []
    if isinstance(raw_brands, list):
        for item in raw_brands:
            if isinstance(item, dict):
                b_name = str(item.get("brand") or item.get("name") or "").lower()
                raw_val = item.get("value") if item.get("value") is not None else (item.get("percent") or 0.0)
                try:
                    b_val = float(raw_val or 0.0)
                except (ValueError, TypeError):
                    b_val = 0.0
                color, label = MAMMOUTH_BRAND_COLORS.get(b_name, ("#94A3B8", b_name.upper()))
                brands_list.append({
                    "brand": b_name,
                    "label": label,
                    "value": b_val,
                    "color": color
                })

    return {
        "is_logged_in": True,
        "plan_id": plan_key,
        "plan_label": plan_label,
        "multiplier": mult,
        "total_percent": pct,
        "current_spend_cents": current_spend,
        "max_spend_cents": max_cents,
        "brands": brands_list,
        "timestamp": payload.get("ts", 0),
        "raw": payload
    }


class MammouthBrowserFrame(ctk.CTkFrame):
    """Modern embedded browser widget hosting Mammouth.ai inside the Cockpit."""

    def __init__(
        self,
        master,
        get_mcp_url_cb: Optional[Callable[[], str]] = None,
        start_url: str = "https://mammouth.ai",
        profile_dir: Optional[str] = None,
        screenshot_cb: Optional[Callable[[], Optional[str]]] = None,
        quota_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.get_mcp_url_cb = get_mcp_url_cb
        self.start_url = start_url or "https://mammouth.ai"
        self.screenshot_cb = screenshot_cb
        self.quota_cb = quota_cb
        self._last_quota_data: Optional[Dict[str, Any]] = None

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
            window.localization = {
                'windows.fileFilter.allFiles': 'Alle Dateien'
            }
            self.edge = EdgeChrome(control, window, self.profile_dir)
            # Pywebview's on_download_starting is replaced with a no-op to prevent duplicate/crashed dialogs
            self.edge.on_download_starting = lambda sender, args: None
            self.edge.on_new_window_request = self._on_new_window_requested

            # Replace pywebview's fragile on_script_notify with our crash-proof _unified_web_message
            try:
                self.edge.webview.WebMessageReceived -= self.edge.on_script_notify
            except Exception:
                pass
            self.edge.webview.WebMessageReceived += self._unified_web_message

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

                        # 4. Attach native crash-proof download handler
                        try:
                            core.DownloadStarting += self._on_download_starting
                        except Exception:
                            pass
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

            # Direct file download or export endpoint: route directly to main WebView2 without opening a popup
            if _is_download_uri(uri):
                args.set_Handled(True)
                if hasattr(self, "edge") and self.edge and hasattr(self.edge, "webview") and self.edge.webview.CoreWebView2:
                    self.edge.webview.CoreWebView2.Navigate(uri)
                return

            # Detect if this is an auth flow, app navigation, or direct file download
            is_auth_or_app = (
                is_local_protocol
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
                            # The popup was opened solely to initiate a download.
                            # Hide the popup form so it doesn't linger visually,
                            # but KEEP popup_wv alive until the download completes!
                            try:
                                popup_form.Hide()
                            except Exception:
                                pass
                            try:
                                d_op = getattr(da, "DownloadOperation", None)
                                if d_op:
                                    def _on_pop_d_state(s, a):
                                        try:
                                            st = str(d_op.State)
                                            if "Completed" in st or "Interrupted" in st:
                                                self.after(1000, lambda: self._safe_close_popup(popup_form, popup_wv))
                                        except Exception:
                                            pass
                                    d_op.StateChanged += _on_pop_d_state
                                else:
                                    self.after(8000, lambda: self._safe_close_popup(popup_form, popup_wv))
                            except Exception:
                                self.after(8000, lambda: self._safe_close_popup(popup_form, popup_wv))

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

    def _unified_web_message(self, sender, args):
        """Unified message receiver handling both Mammouth quota telemetry and pywebview bridge calls without crashes."""
        try:
            raw = str(args.get_WebMessageAsJson() or "")
            if not raw:
                return

            parsed_data = None
            try:
                parsed_data = json.loads(raw)
                if isinstance(parsed_data, str) and (parsed_data.strip().startswith("{") or parsed_data.strip().startswith("[")):
                    try:
                        parsed_data = json.loads(parsed_data)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[BROWSER WEB-MESSAGE] JSON parse warning: {e}")

            # Safely handle pywebview drag-and-drop file notification
            if raw == '"FilesDropped"':
                try:
                    from webview.platforms.edgechromium import _dnd_state
                    if _dnd_state.get('num_listeners', 0) > 0:
                        add_objs = args.get_AdditionalObjects()
                        if add_objs is not None:
                            files = [
                                (os.path.basename(file.Path), file.Path)
                                for file in list(add_objs)
                                if 'CoreWebView2File' in str(type(file))
                            ]
                            _dnd_state['paths'] += files
                except Exception:
                    pass
                return

            # Passively receive mammouth_quota message if dispatched
            if isinstance(parsed_data, dict) and parsed_data.get("type") == "mammouth_quota":
                if getattr(self, "quota_cb", None) and callable(self.quota_cb):
                    payload = parsed_data.get("payload")
                    self.after(0, lambda p=payload: self.quota_cb(p))
                return

            # Safely handle pywebview RPC calls [func_name, func_param, value_id]
            if isinstance(parsed_data, (list, tuple)) and len(parsed_data) == 3:
                func_name, func_param, value_id = parsed_data
                try:
                    if isinstance(func_param, str):
                        try:
                            func_param = json.loads(func_param)
                        except Exception:
                            pass
                    if func_name == '_pywebviewAlert':
                        from System.Windows.Forms import MessageBox
                        MessageBox.Show(str(func_param))
                    elif func_name == 'console':
                        print(func_param)
                    else:
                        from webview.platforms.edgechromium import js_bridge_call
                        js_bridge_call(self.edge.pywebview_window, func_name, func_param, value_id)
                except Exception:
                    pass
                return
        except Exception:
            pass

    def request_quota_refresh(self):
        """Deprecated no-op: In-page DOM quota scraping removed for absolute stability."""
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

    def focus_and_paste(self, delay_ms: int = 250):
        """Focuses the embedded WebView2 control and simulates Ctrl+V to attach clipboard content.
        Runs safely on the UI thread to prevent COM cross-thread deadlocks, and guarantees key release."""
        if not HAS_WEBVIEW2 or not self.hwnd:
            return

        def _do_paste_ui():
            try:
                # 1. Bring top-level window to foreground
                try:
                    top_hwnd = self.winfo_toplevel().winfo_id()
                    user32.SetForegroundWindow(top_hwnd)
                except Exception:
                    pass

                # 2. Focus the WebView2 Win32 window
                if self.hwnd:
                    try:
                        user32.SetFocus(self.hwnd)
                    except Exception:
                        pass

                # 3. Focus chat textarea / input via JavaScript on the UI thread
                if self.edge and hasattr(self.edge, "webview"):
                    target_wv = self.edge.webview
                    if hasattr(target_wv, "CoreWebView2") and target_wv.CoreWebView2:
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
                            target_wv.CoreWebView2.ExecuteScriptAsync(js_focus)
                        except Exception:
                            pass

                # 4. Simulate Ctrl+V key combination with guaranteed key-up in finally
                VK_CONTROL = 0x11
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002

                try:
                    user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    user32.keybd_event(VK_V, 0, 0, 0)
                finally:
                    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass

        # Schedule execution on UI thread after delay_ms to allow tab switch/window focus
        self.after(max(50, delay_ms), _do_paste_ui)

    def focus_browser(self):
        """Brings Win32 keyboard and mouse focus to the embedded WebView2 window."""
        if self.hwnd and self.is_embedded:
            try:
                user32.SetFocus(self.hwnd)
            except Exception:
                pass

    def _safe_close_popup(self, form, wv=None):
        """Safely closes and disposes a popup window after downloads finish."""
        try:
            form.Close()
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
        owner = 0
        try:
            if hasattr(self, "winfo_toplevel"):
                top = self.winfo_toplevel()
                if hasattr(top, "winfo_id"):
                    owner = top.winfo_id()
        except Exception:
            pass
        return _native_save_file_dialog(
            initial_dir=initial_dir,
            default_name=suggested_name,
            title="Mammouth — Datei speichern",
            hwnd_owner=owner
        )

    def _on_download_starting(self, sender, args):
        """Native crash-proof download handler presenting a SaveFileDialog and tracking download state."""
        deferral = None
        try:
            deferral = args.GetDeferral()
        except Exception:
            pass

        try:
            download_op = getattr(args, "DownloadOperation", None)
            suggested_path = ""
            try:
                suggested_path = str(args.ResultFilePath or "")
            except Exception:
                pass
            suggested_name = os.path.basename(suggested_path) if suggested_path else "download"
            suggested_name = "".join(c for c in suggested_name if c not in '<>:"/\\|?*').strip() or "download"

            downloads_dir = str(Path.home() / "Downloads")
            os.makedirs(downloads_dir, exist_ok=True)

            save_dest = None
            try:
                save_dest = self._prompt_save_file(downloads_dir, suggested_name)
            except Exception:
                # Fallback to direct download in Downloads directory
                save_dest = os.path.join(downloads_dir, suggested_name)

            if save_dest:
                dest = os.path.normpath(str(save_dest))
                if hasattr(args, "set_ResultFilePath"):
                    try:
                        args.set_ResultFilePath(dest)
                    except Exception:
                        pass
                try:
                    args.ResultFilePath = dest
                except Exception:
                    pass

                if hasattr(args, "set_Handled"):
                    try:
                        args.set_Handled(True)
                    except Exception:
                        pass
                try:
                    args.Handled = True
                except Exception:
                    pass

                final_name = os.path.basename(dest)
                if hasattr(self, "_show_download_notification"):
                    self._show_download_notification(f"⬇ Lade herunter: {final_name}...", success=True)

                if download_op:
                    def _on_state_changed(s, a):
                        try:
                            state_str = str(download_op.State)
                            if "Completed" in state_str:
                                if hasattr(self, "_show_download_notification"):
                                    self._show_download_notification(f"✓ Gespeichert: {final_name}", success=True)
                            elif "Interrupted" in state_str:
                                if hasattr(self, "_show_download_notification"):
                                    self._show_download_notification(f"⚠ Download abgebrochen: {final_name}", success=False)
                        except Exception:
                            pass

                    try:
                        download_op.StateChanged += _on_state_changed
                    except Exception:
                        pass
            else:
                if hasattr(args, "set_Cancel"):
                    try:
                        args.set_Cancel(True)
                    except Exception:
                        pass
                try:
                    args.Cancel = True
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if deferral:
                try:
                    deferral.Complete()
                except Exception:
                    pass


