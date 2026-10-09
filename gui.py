import os
import sys

# Ensure Windows COM ApartmentState is STA before Tkinter or WebView2 initialization
# and register explicit AppUserModelID so Windows Taskbar pins and displays the custom icon
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mammouth.defroster.9000")
    except Exception:
        pass
    try:
        import clr
        clr.AddReference("System.Threading")
        from System.Threading import Thread, ApartmentState
        Thread.CurrentThread.SetApartmentState(ApartmentState.STA)
    except Exception:
        pass

import re
import json
import time
import shutil
import socket
import logging
import queue
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable


# Ensure sys.stdout and sys.stderr are never None in frozen windowed binaries
class SafeStream:
    def __init__(self, target_path=None):
        self.target_path = target_path
    def write(self, s):
        if not s:
            return
        if self.target_path:
            try:
                with open(self.target_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(s)
            except Exception:
                pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None:
    sys.stdout = SafeStream()
if sys.stderr is None:
    sys.stderr = SafeStream()

# Add project directories to sys.path
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if (BASE_DIR / "mcpserv").exists() and str(BASE_DIR / "mcpserv") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "mcpserv"))
if (BASE_DIR / "modules").exists() and str(BASE_DIR / "modules") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "modules"))

from config import load_config, save_config, get_lan_ip, generate_secure_token, _decrypt_dpapi, CONFIG_FILE
from server import build_app, app
from modules.embedded_browser import MammouthBrowserFrame, HAS_WEBVIEW2, parse_mammouth_quota_data
from modules.updater import check_for_update, download_and_verify_update, apply_update_and_restart
from modules.task_scheduler import (
    scheduler_create_task,
    scheduler_list_tasks,
    scheduler_get_task,
    scheduler_update_task,
    scheduler_delete_task,
    scheduler_pause_task,
    scheduler_resume_task,
    scheduler_trigger_task_now,
    scheduler_get_presets,
    TaskSchedulerEngine
)


def generate_self_signed_cert(cert_path: str, key_path: str, hostname: str = "localhost") -> bool:
    """Generate self-signed SSL certificate for local LAN development."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime
        import ipaddress

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mammouth Defroster 9000 Local TLS"),
        ])
        
        alt_names = [x509.DNSName(hostname), x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            ip_obj = ipaddress.ip_address(hostname)
            alt_names.append(x509.IPAddress(ip_obj))
        except ValueError:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
            .sign(key, hashes.SHA256())
        )

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        return True
    except Exception as e:
        print(f"[TLS WARNING] Could not generate self-signed certificate: {e}")
        return False

# If spawned as dedicated server executable or with CLI / server-only flags, run headless server
is_server_binary = "server" in Path(sys.argv[0]).stem.lower()
if is_server_binary or "--server-only" in sys.argv or "--cli" in sys.argv or "--headless" in sys.argv:
    # Try attaching to Windows parent console so logs stream directly to the terminal
    if os.name == "nt":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        except Exception:
            pass

    import uvicorn

    cfg = load_config()
    server_cfg = cfg.get("server", {})
    port = int(os.environ.get("PORT", server_cfg.get("port", 8000)))
    host = os.environ.get("HOST", server_cfg.get("host", "127.0.0.1"))
    enable_tls = bool(server_cfg.get("enable_tls", False))
    cert_file = server_cfg.get("ssl_certfile")
    key_file = server_cfg.get("ssl_keyfile")

    token = server_cfg.get("api_token", "").strip()

    if server_cfg.get("enforce_auth", True) and not token:
        token = generate_secure_token()
        cfg["server"]["api_token"] = token
        save_config(cfg)

    server_app = build_app(token=token)

    if enable_tls and (not cert_file or not os.path.exists(str(cert_file))):
        default_cert = str(BASE_DIR / "cert.pem")
        default_key = str(BASE_DIR / "key.pem")
        if not os.path.exists(default_cert):
            print("[TLS] Generating self-signed TLS certificate for local network security...")
            generate_self_signed_cert(default_cert, default_key, host)
        cert_file = default_cert
        key_file = default_key

    proto = "https" if enable_tls else "http"
    print("=======================================================")
    print(f"  Mammouth Defroster 9000 FastMCP Server (CLI Mode)")
    print(f"  Listening on: {proto}://{host}:{port}/sse")
    if token:
        print(f"  Bearer Auth: ENABLED (Token: {token[:6]}...{token[-4:]})")
    else:
        print("  Bearer Auth: DISABLED")
    print("  Press Ctrl+C in this terminal to stop.")
    print("=======================================================\n")

    uvicorn_kwargs = {
        "app": server_app,
        "host": host,
        "port": port,
        "log_level": "info",
        "use_colors": False,
        "log_config": None
    }
    if enable_tls and cert_file and os.path.exists(cert_file):
        uvicorn_kwargs["ssl_certfile"] = cert_file
        uvicorn_kwargs["ssl_keyfile"] = key_file

    uvicorn.run(**uvicorn_kwargs)
    sys.exit(0)

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import sqlite3
import ipaddress
import hmac
import secrets
import urllib.parse
import httpx
import psutil
from PIL import Image as PILImage

try:
    import win32crypt
except ImportError:
    pass

from modules.putty_ssh import ssh_save_host, ssh_list_saved_hosts, ssh_open_putty_window, ssh_exec_command

# Appearance setup
INITIAL_CONFIG = load_config()
INITIAL_MODE = INITIAL_CONFIG.get("server", {}).get("appearance_mode", "Dark")
ctk.set_appearance_mode(INITIAL_MODE)
ctk.set_default_color_theme("dark-blue")

from modules.global_hotkey import register_global_hotkey, unregister_global_hotkey, is_global_hotkey_registered

# Mammouth AI Official Brand Design System & Unified Color Palette
# Derived from official Mammouth AI branding kit (https://info.mammouth.ai/docs/branding-kit/)
THEME_BG = ("#F2EBE1", "#242428")                 # Light: M-Base Ivory (#F2EBE1) | Dark: Warm Charcoal (#242428)
THEME_HEADER_BG = ("#EDE3D4", "#1E1E22")          # Header & Navigation Rail
THEME_CARD_BG = ("#FCFAF7", "#2F2F33")            # Cards and panels: Pure Ivory / Card Charcoal
THEME_CARD_BORDER = ("#DDC7AB", "#423E3A")        # Warm sandstone / subtle warm bronze borders
THEME_CARD_BORDER_HOVER = ("#C8A37C", "#5E5650")  # Border hover state
THEME_SUB_BG = ("#F8F4EE", "#27272B")             # Sub-surfaces / elevated frames
THEME_INPUT_BG = ("#FFFFFF", "#1E1E22")           # Text entries & inputs
THEME_INPUT_BORDER = ("#DDC7AB", "#423E3A")       # Input borders
THEME_BTN_SEC_BG = ("#EDE3D4", "#38363A")         # Secondary button background
THEME_BTN_SEC_HOVER = ("#DDC7AB", "#464349")      # Secondary button hover
THEME_BTN_SEC_BORDER = ("#DDC7AB", "#4E4944")     # Secondary button border
THEME_ACCENT = ("#9F6C45", "#B88557")             # Mammouth Caramel / Tusk Bronze Accent (#B88557)
THEME_ACCENT_HOVER = ("#754533", "#C8A37C")       # Mammouth Accent Hover (#C8A37C)
THEME_SUCCESS = ("#2E7D32", "#10B981")            # Success emerald
THEME_SUCCESS_HOVER = ("#1B5E20", "#059669")      # Success hover
THEME_TEXT_PRIMARY = ("#311A17", "#FCFAF7")       # Light: Deep Espresso (#311A17) | Dark: Warm Ivory (#FCFAF7)
THEME_TEXT_MUTED = ("#754533", "#A89F97")         # Muted warm stone text
THEME_CONSOLE_BG = "#19191C"                      # Rich dark warm charcoal console

HOSTS_FILE = BASE_DIR / "hosts.json"
APP_VERSION = "v0.5.1"



def find_tailscale_binary(tailscale_path: str = "") -> Optional[str]:
    """Find the Tailscale binary path across multiple standard Windows locations."""
    candidates = [
        tailscale_path,
        shutil.which("tailscale"),
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files\Tailscale\tailscale.EXE",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        os.path.expandvars(r"%PROGRAMFILES%\Tailscale\tailscale.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tailscale\tailscale.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def find_cloudflared_binary(custom_path: str = "") -> Optional[str]:
    """Find the cloudflared binary across custom config, app directories, siblings, and PATH."""
    candidates = [
        custom_path,
        str(BASE_DIR / "cloudflared.exe") if os.name == "nt" else str(BASE_DIR / "cloudflared"),
        str(BASE_DIR.parent / "cloudflared.exe") if os.name == "nt" else str(BASE_DIR.parent / "cloudflared"),
        shutil.which("cloudflared"),
        shutil.which("cloudflared.exe"),
    ]
    # Check parent directory for sibling release or extracted folders (e.g. MammouthDefroster9000-*)
    try:
        if BASE_DIR.parent.exists():
            for sibling in BASE_DIR.parent.glob("*"):
                if sibling.is_dir() and "Mammouth" in sibling.name:
                    cand = sibling / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
                    if cand.exists():
                        candidates.append(str(cand))
    except Exception:
        pass

    # Common Windows installation locations
    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\cloudflared\cloudflared.exe",
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%USERPROFILE%\cloudflared.exe"),
            os.path.expandvars(r"%USERPROFILE%\bin\cloudflared.exe"),
            os.path.expandvars(r"%USERPROFILE%\scoop\shims\cloudflared.exe"),
            os.path.expandvars(r"%ProgramData%\chocolatey\bin\cloudflared.exe"),
            r"C:\cloudflared\cloudflared.exe",
            r"C:\bin\cloudflared.exe",
        ])

    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return str(Path(c).resolve())
    return None




def get_tailscale_public_domain(tailscale_path: str = r"C:\Program Files\Tailscale\tailscale.exe") -> Optional[str]:
    """Attempt to detect the machine's Tailscale domain name robustly."""
    ts_bin = find_tailscale_binary(tailscale_path)
    if not ts_bin:
        return None
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run([ts_bin, "status", "--json"], capture_output=True, text=True, timeout=5, creationflags=flags)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            
            # 1. Check CertDomains
            cert_domains = data.get("CertDomains")
            if cert_domains and isinstance(cert_domains, list) and len(cert_domains) > 0:
                return f"https://{cert_domains[0]}"
            
            # 2. Check Self.DNSName
            self_node = data.get("Self", {})
            dns_name = self_node.get("DNSName", "").rstrip(".")
            if dns_name:
                return f"https://{dns_name}"
            
            # 3. Check MagicDNSSuffix + HostName
            magic = data.get("MagicDNSSuffix", "").rstrip(".")
            host = self_node.get("HostName", "").lower()
            if host and magic:
                return f"https://{host}.{magic}"
    except Exception:
        pass
    return None


_TS_DOMAIN_CACHE: Dict[str, Any] = {"value": None, "fetched_at": 0.0, "refreshing": False}
_TS_DOMAIN_LOCK = threading.Lock()
_TS_DOMAIN_TTL = 300.0


def get_tailscale_public_domain_cached(tailscale_path: str = "", on_update: Optional[Callable[[], None]] = None) -> Optional[str]:
    """Non-blocking variant for UI code: returns the cached domain immediately and refreshes it
    in a background thread when stale (`tailscale status` can take up to 5s)."""
    with _TS_DOMAIN_LOCK:
        value = _TS_DOMAIN_CACHE["value"]
        stale = time.time() - _TS_DOMAIN_CACHE["fetched_at"] > _TS_DOMAIN_TTL
        if not stale or _TS_DOMAIN_CACHE["refreshing"]:
            return value
        _TS_DOMAIN_CACHE["refreshing"] = True

    def _refresh():
        new_value = get_tailscale_public_domain(tailscale_path) if tailscale_path else get_tailscale_public_domain()
        with _TS_DOMAIN_LOCK:
            changed = new_value != _TS_DOMAIN_CACHE["value"]
            _TS_DOMAIN_CACHE.update(value=new_value, fetched_at=time.time(), refreshing=False)
        if changed and on_update:
            try:
                on_update()
            except Exception:
                pass

    threading.Thread(target=_refresh, daemon=True, name="TailscaleDomainRefresh").start()
    return value


_REDACT_PATTERNS = (
    (re.compile(r"mcp_at_[A-Za-z0-9_\-.=]+"), "mcp_at_[REDACTED]"),
    (re.compile(r"mcp_rt_[A-Za-z0-9_\-.=]+"), "mcp_rt_[REDACTED]"),
    (re.compile(r"\bmc_[A-Za-z0-9_\-.=]{8,}"), "mc_[REDACTED]"),
    (re.compile(r"(?i)(refresh_token|access_token|id_token|api_token|api_key|token|code)=([^&\s\"']+)"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(Authorization:\s*Bearer\s+)(\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(Bearer\s+)([A-Za-z0-9_\-.=]{12,})"), r"\1[REDACTED]"),
)


def redact_secrets(text: str) -> str:
    """Mask OAuth tokens, auth codes and Bearer headers in log output."""
    if not text:
        return text
    out = str(text)
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


class GuiLogHandler(logging.Handler):
    """Custom logging handler to route python/uvicorn logs directly to the GUI console."""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            # Redaction happens once, inside the GUI's _log
            self.callback(self.format(record))
        except Exception:
            pass


class HostDialog(ctk.CTkToplevel):
    """Modern modal dialog for adding or editing an SSH host."""
    def __init__(self, parent, host_data: Optional[Dict[str, Any]] = None, alias: str = ""):
        super().__init__(parent)
        self.title("Edit SSH Host" if alias else "Add New SSH Host")
        self.geometry("560x610")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None
        self.original_alias = alias

        # Header
        header_card = ctk.CTkFrame(self, fg_color=THEME_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=8)
        header_card.pack(fill="x", padx=20, pady=(15, 10))

        title_label = ctk.CTkLabel(header_card, text="🔑 Configure SSH Host Alias", font=ctk.CTkFont(size=18, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        title_label.pack(anchor="w", padx=15, pady=(10, 2))

        lbl_sec = ctk.CTkLabel(
            header_card,
            text="🔒 Passwords are encrypted at rest via Windows DPAPI before saving",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#059669", "#10B981")
        )
        lbl_sec.pack(anchor="w", padx=15, pady=(0, 10))

        form_frame = ctk.CTkFrame(self, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=8)
        form_frame.pack(padx=20, pady=5, fill="both", expand=True)

        # Alias
        ctk.CTkLabel(form_frame, text="Alias Name:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        self.entry_alias = ctk.CTkEntry(form_frame, placeholder_text="e.g. prod-server, vps-backup", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_alias.grid(row=0, column=1, padx=15, pady=8, sticky="ew")
        if alias:
            self.entry_alias.insert(0, alias)
            self.entry_alias.configure(state="disabled")

        # Host / IP
        ctk.CTkLabel(form_frame, text="Host / IP:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=1, column=0, padx=15, pady=8, sticky="w")
        self.entry_host = ctk.CTkEntry(form_frame, placeholder_text="e.g. 192.168.1.100 or node.example.com", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_host.grid(row=1, column=1, padx=15, pady=8, sticky="ew")

        # Port
        ctk.CTkLabel(form_frame, text="SSH Port:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=2, column=0, padx=15, pady=8, sticky="w")
        self.entry_port = ctk.CTkEntry(form_frame, placeholder_text="22", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_port.grid(row=2, column=1, padx=15, pady=8, sticky="ew")
        self.entry_port.insert(0, "22")

        # User
        ctk.CTkLabel(form_frame, text="Username:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=3, column=0, padx=15, pady=8, sticky="w")
        self.entry_user = ctk.CTkEntry(form_frame, placeholder_text="e.g. root, ubuntu, admin", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_user.grid(row=3, column=1, padx=15, pady=8, sticky="ew")
        self.entry_user.insert(0, "root")

        # Password
        ctk.CTkLabel(form_frame, text="Password:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=4, column=0, padx=15, pady=8, sticky="w")
        self.entry_pw = ctk.CTkEntry(form_frame, placeholder_text="(Optional - DPAPI Encrypted)", show="*", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_pw.grid(row=4, column=1, padx=15, pady=8, sticky="ew")
        if alias and host_data and host_data.get("password"):
            # Empty field on edit = keep the stored (DPAPI encrypted) password
            self.entry_pw.configure(placeholder_text="(leer lassen = gespeichertes Passwort behalten)")

        # Key Path
        ctk.CTkLabel(form_frame, text="Private Key:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=5, column=0, padx=15, pady=8, sticky="w")
        key_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        key_box.grid(row=5, column=1, padx=15, pady=8, sticky="ew")
        self.entry_key = ctk.CTkEntry(key_box, placeholder_text="(Recommended: .ppk or id_rsa)", width=230, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_key.pack(side="left", fill="x", expand=True, padx=(0, 5))
        btn_browse = ctk.CTkButton(
            key_box,
            text="Browse",
            width=70,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._browse_key
        )
        btn_browse.pack(side="right")

        # Description
        ctk.CTkLabel(form_frame, text="Description:", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).grid(row=6, column=0, padx=15, pady=8, sticky="w")
        self.entry_desc = ctk.CTkEntry(form_frame, placeholder_text="Short description of this server", width=310, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_desc.grid(row=6, column=1, padx=15, pady=8, sticky="ew")

        if host_data:
            self.entry_host.delete(0, "end")
            self.entry_host.insert(0, host_data.get("host", ""))
            self.entry_port.delete(0, "end")
            self.entry_port.insert(0, str(host_data.get("port", 22)))
            self.entry_user.delete(0, "end")
            self.entry_user.insert(0, host_data.get("username", "root"))
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, host_data.get("private_key_path", ""))
            self.entry_desc.delete(0, "end")
            self.entry_desc.insert(0, host_data.get("description", ""))

        # Button row
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=(15, 20), fill="x")

        btn_cancel = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            width=100,
            command=self.destroy
        )
        btn_cancel.pack(side="right", padx=(10, 0))

        btn_save = ctk.CTkButton(
            btn_frame,
            text="💾 Save Host",
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            width=130,
            command=self._on_save
        )
        btn_save.pack(side="right")

    def _browse_key(self):
        filename = filedialog.askopenfilename(
            title="Select Private Key File",
            filetypes=[("All Key Files", "*.ppk;*.pem;id_*;*"), ("PuTTY Key (*.ppk)", "*.ppk"), ("All Files", "*.*")]
        )
        if filename:
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, filename)

    def _on_save(self):
        alias = self.entry_alias.get().strip() or self.original_alias
        host = self.entry_host.get().strip()
        user = self.entry_user.get().strip()
        port_s = self.entry_port.get().strip() or "22"
        password = self.entry_pw.get()
        key_path = self.entry_key.get().strip()
        desc = self.entry_desc.get().strip()

        if not alias:
            messagebox.showerror("Validation Error", "Please provide a valid Host Alias.", parent=self)
            return
        if not host:
            messagebox.showerror("Validation Error", "Please enter a valid Host / IP address.", parent=self)
            return

        try:
            port = int(port_s)
        except ValueError:
            port = 22

        self.result = {
            "alias": alias,
            "data": {
                "host": host,
                "username": user or "root",
                "port": port,
                "password": password,
                "private_key_path": key_path,
                "description": desc
            }
        }
        self.destroy()


class SplashScreen(ctk.CTkToplevel):
    """Modern dark-themed loading screen with progress feedback displayed during application startup."""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Mammouth Defroster 9000 Loading...")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        
        width, height = 500, 280
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(fg_color="#0A0D14")

        container = ctk.CTkFrame(
            self,
            fg_color="#151B28",
            corner_radius=14,
            border_width=1,
            border_color="#283347"
        )
        container.pack(fill="both", expand=True, padx=2, pady=2)

        lbl_icon = ctk.CTkLabel(container, text="🦣❄️🔥", font=ctk.CTkFont(size=38))
        lbl_icon.pack(pady=(28, 6))

        lbl_title = ctk.CTkLabel(
            container,
            text="MAMMOUTH DEFROSTER 9000",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#FFFFFF"
        )
        lbl_title.pack(pady=(0, 2))

        lbl_sub = ctk.CTkLabel(
            container,
            text=f"Sovereign FastMCP Desktop Cockpit • {APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color="#A0A0A5"
        )
        lbl_sub.pack(pady=(0, 16))

        self.lbl_status = ctk.CTkLabel(
            container,
            text="Initializing FastMCP engine and security shield...",
            font=ctk.CTkFont(size=11),
            text_color="#10B981"
        )
        self.lbl_status.pack(pady=(0, 6))

        self.progress = ctk.CTkProgressBar(
            container,
            width=380,
            height=6,
            corner_radius=3,
            progress_color="#10B981",
            fg_color="#1E293B"
        )
        self.progress.pack(pady=(0, 16))
        self.progress.set(0.1)

        lbl_footer = ctk.CTkLabel(
            container,
            text="Engineered for Mammouth.ai • Fail-Closed Architecture",
            font=ctk.CTkFont(size=10),
            text_color="#6E7079"
        )
        lbl_footer.pack(side="bottom", pady=(0, 12))

        try:
            self.update()
        except Exception:
            pass

    def set_progress(self, val: float, message: str):
        try:
            self.progress.set(val)
            self.lbl_status.configure(text=message)
            self.update()
        except Exception:
            pass


class CTkMammouthQuotaCard(ctk.CTkFrame):
    """Native CustomTkinter Sidebar Card for Mammouth.ai Quota & Telemetry."""

    def __init__(
        self,
        master,
        on_click: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        super().__init__(
            master,
            fg_color=THEME_CARD_BG,
            border_width=1,
            border_color=THEME_CARD_BORDER,
            corner_radius=8,
            cursor="hand2" if on_click else "arrow",
            **kwargs
        )
        self.on_click = on_click
        self.on_refresh = on_refresh
        self._parsed_data: Dict[str, Any] = {}
        self._last_refresh_timestamp: float = 0.0

        self._build_ui()

    def _build_ui(self):
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(fill="x", padx=10, pady=8)

        # 1. Header row: Title + Refresh Button
        self.hdr_box = ctk.CTkFrame(self.inner, fg_color="transparent")
        self.hdr_box.pack(fill="x", pady=(0, 4))

        self.lbl_title = ctk.CTkLabel(
            self.hdr_box,
            text="🦣 Kontingent",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        )
        self.lbl_title.pack(side="left")

        self.btn_refresh = ctk.CTkButton(
            self.hdr_box,
            text="🔄",
            width=22,
            height=20,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_MUTED,
            command=self._on_refresh_clicked
        )
        self.btn_refresh.pack(side="right")

        # 2. Status Row: Plan Badge + Percentage
        self.status_box = ctk.CTkFrame(self.inner, fg_color="transparent")
        self.status_box.pack(fill="x", pady=(0, 6))

        self.badge_plan = ctk.CTkFrame(
            self.status_box,
            fg_color=THEME_BTN_SEC_HOVER,
            corner_radius=10
        )
        self.badge_plan.pack(side="left")

        self.lbl_plan = ctk.CTkLabel(
            self.badge_plan,
            text="Wird geladen...",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        )
        self.lbl_plan.pack(padx=6, pady=1)

        self.lbl_percent = ctk.CTkLabel(
            self.status_box,
            text="-- %",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#059669", "#10B981")
        )
        self.lbl_percent.pack(side="right")

        # 3. Canvas Progress Bar
        self.canvas_bar = ctk.CTkCanvas(
            self.inner,
            height=6,
            highlightthickness=0,
            bd=0
        )
        self.canvas_bar.pack(fill="x", pady=(0, 6))
        self.canvas_bar.bind("<Configure>", lambda e: self._draw_bar())

        # 4. Legend Frame for Models
        self.legend_frame = ctk.CTkFrame(self.inner, fg_color="transparent")
        self.legend_frame.pack(fill="x", pady=(0, 4))

        # 5. Footer info
        self.lbl_footer = ctk.CTkLabel(
            self.inner,
            text="⏳ 3h-Sitzungsfenster",
            font=ctk.CTkFont(size=9),
            text_color=THEME_TEXT_MUTED
        )
        self.lbl_footer.pack(anchor="w")

        # Bind click to open WebApp tab
        self._bind_click_recursive(self)

    def _bind_click_recursive(self, widget):
        if widget != self.btn_refresh and not str(widget).endswith("button"):
            try:
                widget.bind("<Button-1>", lambda e: self._on_card_clicked())
                widget.bind("<Enter>", lambda e: self.configure(border_color=THEME_BTN_SEC_BORDER))
                widget.bind("<Leave>", lambda e: self.configure(border_color=THEME_CARD_BORDER))
            except Exception:
                pass
        for child in widget.winfo_children():
            self._bind_click_recursive(child)

    def _on_card_clicked(self):
        if self.on_click:
            try:
                self.on_click()
            except Exception:
                pass

    def _on_refresh_clicked(self):
        self.btn_refresh.configure(text="⏳")
        self.after(1200, lambda: self.btn_refresh.configure(text="🔄"))
        if self.on_refresh:
            try:
                self.on_refresh()
            except Exception:
                pass

    def update_quota(self, parsed: Dict[str, Any]):
        self._parsed_data = parsed or {}
        self._last_refresh_timestamp = time.time()

        is_logged_in = parsed.get("is_logged_in", False)
        plan_label = parsed.get("plan_label", "Nicht eingeloggt")
        pct = float(parsed.get("total_percent", 0.0))

        self.lbl_plan.configure(text=plan_label)

        if not is_logged_in:
            self.lbl_percent.configure(text="-- %", text_color=THEME_TEXT_MUTED)
            self.badge_plan.configure(fg_color=THEME_BTN_SEC_BG)
            self.lbl_footer.configure(text="🔒 Zum Anmelden klicken")
        else:
            self.lbl_percent.configure(text=f"{int(round(pct))} %")
            if pct < 70.0:
                self.lbl_percent.configure(text_color=("#059669", "#10B981"))
            elif pct < 90.0:
                self.lbl_percent.configure(text_color=("#D97706", "#F59E0B"))
            else:
                self.lbl_percent.configure(text_color=("#DC2626", "#EF4444"))

            self.badge_plan.configure(fg_color=THEME_BTN_SEC_HOVER)
            self.lbl_footer.configure(text="⏳ 3h-Fenster • Gerade eben")

        # Update Legend
        for w in self.legend_frame.winfo_children():
            w.destroy()

        if not is_logged_in:
            lbl_hint = ctk.CTkLabel(
                self.legend_frame,
                text="In Mammouth.ai einloggen",
                font=ctk.CTkFont(size=10),
                text_color=THEME_TEXT_MUTED
            )
            lbl_hint.pack(anchor="w")
        else:
            brands = parsed.get("brands", [])
            if brands:
                for i in range(0, len(brands), 2):
                    row_f = ctk.CTkFrame(self.legend_frame, fg_color="transparent")
                    row_f.pack(fill="x", pady=1)

                    b1 = brands[i]
                    val_str1 = f"{int(round(b1['value']))}%" if b1['value'] >= 1 else "<1%"
                    ctk.CTkLabel(
                        row_f,
                        text=f"● {b1['label']} {val_str1}",
                        font=ctk.CTkFont(size=10),
                        text_color=b1['color']
                    ).pack(side="left", padx=(0, 6))

                    if i + 1 < len(brands):
                        b2 = brands[i + 1]
                        val_str2 = f"{int(round(b2['value']))}%" if b2['value'] >= 1 else "<1%"
                        ctk.CTkLabel(
                            row_f,
                            text=f"● {b2['label']} {val_str2}",
                            font=ctk.CTkFont(size=10),
                            text_color=b2['color']
                        ).pack(side="left")
            else:
                ctk.CTkLabel(
                    self.legend_frame,
                    text="Noch keine Aktivität",
                    font=ctk.CTkFont(size=10),
                    text_color=THEME_TEXT_MUTED
                ).pack(anchor="w")

        self._draw_bar()
        self._bind_click_recursive(self.legend_frame)

    def _draw_bar(self):
        if not hasattr(self, "canvas_bar"):
            return

        w = self.canvas_bar.winfo_width()
        if w <= 1:
            w = 195
        h = 6

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        card_bg = "#151B28" if is_dark else "#F8FAFC"
        track_bg = "#1E293B" if is_dark else "#E2E8F0"

        self.canvas_bar.configure(bg=card_bg)
        self.canvas_bar.delete("all")

        self.canvas_bar.create_rectangle(0, 0, w, h, fill=track_bg, outline="")

        if not self._parsed_data or not self._parsed_data.get("is_logged_in"):
            return

        pct = float(self._parsed_data.get("total_percent", 0.0))
        if pct <= 0:
            return

        filled_w = max(2, min(w, int(round(w * (pct / 100.0)))))
        brands = self._parsed_data.get("brands", [])

        if brands:
            total_brand_val = sum(b.get("value", 0.0) for b in brands)
            if total_brand_val <= 0:
                total_brand_val = 1.0

            curr_x = 0
            for i, b in enumerate(brands):
                b_val = b.get("value", 0.0)
                if b_val <= 0:
                    continue
                seg_w = max(2, int(round(filled_w * (b_val / total_brand_val))))
                x_end = min(filled_w, curr_x + seg_w)
                if i == len(brands) - 1:
                    x_end = filled_w

                if x_end > curr_x:
                    self.canvas_bar.create_rectangle(curr_x, 0, x_end, h, fill=b["color"], outline="")
                    curr_x = x_end
        else:
            color = "#10B981" if pct < 70 else ("#F59E0B" if pct < 90 else "#EF4444")
            self.canvas_bar.create_rectangle(0, 0, filled_w, h, fill=color, outline="")


class MammouthControlCenter(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # Hide main window during splash screen loading
        self.title(f"Mammouth Defroster 9000 🦣❄️🔥 ({APP_VERSION})")
        self.geometry("1160x840")
        self.minsize(1060, 740)
        self.configure(fg_color=THEME_BG)

        # Center main window
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            win_w, win_h = 1140, 840
            x = max(0, (screen_w - win_w) // 2)
            y = max(0, (screen_h - win_h) // 2)
            self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        except Exception:
            pass

        # Set window and taskbar icon across frozen, dev, and PyInstaller _internal directories
        icon_ico = None
        icon_png = None
        for cand in [
            BASE_DIR / "assets" / "icon.ico",
            BASE_DIR / "_internal" / "assets" / "icon.ico",
            Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "assets" / "icon.ico",
            Path(__file__).parent / "assets" / "icon.ico",
            BASE_DIR.parent / "assets" / "icon.ico",
            BASE_DIR.parent / "src" / "assets" / "icon.ico",
        ]:
            if cand.exists():
                icon_ico = cand
                break

        for cand in [
            BASE_DIR / "assets" / "icon.png",
            BASE_DIR / "_internal" / "assets" / "icon.png",
            Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "assets" / "icon.png",
            Path(__file__).parent / "assets" / "icon.png",
            BASE_DIR.parent / "assets" / "icon.png",
            BASE_DIR.parent / "src" / "assets" / "icon.png",
        ]:
            if cand.exists():
                icon_png = cand
                break

        if icon_ico:
            try:
                self.iconbitmap(str(icon_ico))
            except Exception:
                pass

        if icon_png:
            try:
                img = tk.PhotoImage(file=str(icon_png))
                self.iconphoto(True, img)
                self._icon_photo_ref = img  # Retain reference so garbage collector does not dispose it
            except Exception:
                pass
        elif icon_ico:
            try:
                pil_img = PILImage.open(str(icon_ico))
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(pil_img)
                self.iconphoto(True, photo)
                self._icon_photo_ref = photo
            except Exception:
                pass

        # Show splash loading screen
        splash = None
        try:
            splash = SplashScreen(self)
        except Exception:
            pass

        if splash:
            splash.set_progress(0.25, "Loading configuration and security credentials...")

        self.config_data = load_config()
        self.appearance_mode = self.config_data.get("server", {}).get("appearance_mode", "Dark")
        ctk.set_appearance_mode(self.appearance_mode)

        self.uvicorn_server = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_server_running = False
        self.dynamic_tunnel_url: Optional[str] = None
        self.server_start_time = None
        self.log_filter_mode = "ALL"
        self.sidebar_visible = True
        self.zen_mode_active = False
        self.task_countdown_labels: Dict[int, ctk.CTkLabel] = {}
        self.scheduler_engine = None

        if splash:
            splash.set_progress(0.50, "Setting up system logging and audit streams...")

        self._setup_logging()

        if splash:
            splash.set_progress(0.75, "Building desktop cockpit user interface...")

        self._build_ui()
        self._start_stats_timer()
        self._init_task_scheduler()
        self._init_global_hotkey()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Register interactive screen capture consent callback
        try:
            from modules.screen_capture import set_consent_prompt_callback
            set_consent_prompt_callback(self._prompt_screen_capture_consent)
        except Exception:
            pass

        if splash:
            splash.set_progress(1.0, "Ready! Starting Mammouth Defroster 9000...")

            def finish_loading():
                try:
                    splash.destroy()
                except Exception:
                    pass
                self.deiconify()
                self.lift()
                self.focus_force()
                if "--autostart" in sys.argv or self.config_data.get("server", {}).get("auto_start_server", False):
                    self.after(200, self._start_server)
                if self.config_data.get("server", {}).get("auto_check_updates", True):
                    self.after(2500, self._check_updates_async)
                if self.config_data.get("server", {}).get("start_in_web_tab", False) or self.config_data.get("embedded_browser", {}).get("zen_mode", False):
                    self.after(400, lambda: self.toggle_zen_mode(True))

            self.after(350, finish_loading)
        else:
            self.deiconify()
            if "--autostart" in sys.argv or self.config_data.get("server", {}).get("auto_start_server", False):
                self.after(200, self._start_server)
            if self.config_data.get("server", {}).get("auto_check_updates", True):
                self.after(2500, self._check_updates_async)
            if self.config_data.get("server", {}).get("start_in_web_tab", False) or self.config_data.get("embedded_browser", {}).get("zen_mode", False):
                self.after(400, lambda: self.toggle_zen_mode(True))


    def _setup_logging(self):
        # _log is thread-safe and batches inserts, so the handler can call it directly from any thread
        handler = GuiLogHandler(self._log)
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(formatter)

        # Clear any pre-existing handlers on uvicorn loggers to avoid duplicate lines
        for log_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastmcp"):
            lg = logging.getLogger(log_name)
            lg.handlers.clear()

        # Attach handler exclusively to top-level uvicorn and fastmcp
        # Child loggers (uvicorn.error, uvicorn.access) automatically propagate here
        u_logger = logging.getLogger("uvicorn")
        u_logger.setLevel(logging.INFO)
        u_logger.addHandler(handler)

        f_logger = logging.getLogger("fastmcp")
        f_logger.setLevel(logging.INFO)
        f_logger.addHandler(handler)

    def _build_ui(self):
        # 1. Top Hero Header Banner (Mammouth Deep Slate #0F172A)
        header = ctk.CTkFrame(self, height=66, corner_radius=0, fg_color=THEME_HEADER_BG, border_width=1, border_color=THEME_CARD_BORDER)
        header.pack(fill="x", side="top")

        # App Logo & Title + Collapsible Sidebar Toggle Button
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(14, 5), pady=10)

        self.btn_toggle_sidebar = ctk.CTkButton(
            title_box,
            text="◀",
            width=30,
            height=30,
            corner_radius=6,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
            border_width=1,
            border_color=THEME_CARD_BORDER,
            command=self.toggle_sidebar
        )
        self.btn_toggle_sidebar.pack(side="left", padx=(0, 8))
        
        lbl_icon = ctk.CTkLabel(title_box, text="🦣", font=ctk.CTkFont(size=26))
        lbl_icon.pack(side="left", padx=(0, 10))

        title_text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        title_text_box.pack(side="left")
        
        title_top_row = ctk.CTkFrame(title_text_box, fg_color="transparent")
        title_top_row.pack(anchor="w")
        
        lbl_title = ctk.CTkLabel(title_top_row, text="Mammouth Defroster 9000", font=ctk.CTkFont(size=16, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        lbl_title.pack(side="left", padx=(0, 8))

        # Version Pill Badge
        badge_ver = ctk.CTkFrame(title_top_row, fg_color=("#ECFDF5", "#1B2E24"), border_width=1, border_color=("#A7F3D0", "#244E38"), corner_radius=6)
        badge_ver.pack(side="left")
        ctk.CTkLabel(badge_ver, text=f" {APP_VERSION} ", font=ctk.CTkFont(size=11, weight="bold"), text_color=THEME_SUCCESS).pack(padx=4, pady=1)

        lbl_subtitle = ctk.CTkLabel(
            title_text_box,
            text="❄️ Sovereign FastMCP Desktop Cockpit & Agent Bridge",
            font=ctk.CTkFont(size=11),
            text_color=THEME_TEXT_MUTED
        )
        lbl_subtitle.pack(anchor="w")

        # Top Right Controls: Zen Mode, Screenshot, Theme, Status & Power Toggle
        right_box = ctk.CTkFrame(header, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=10)

        # Update Available Badge Button (Initially hidden)
        self.btn_update_badge = ctk.CTkButton(
            right_box,
            text="🔄 Update verfügbar",
            width=140,
            height=32,
            fg_color=("#3B82F6", "#2563EB"),
            hover_color=("#2563EB", "#1D4ED8"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._show_update_dialog
        )

        # Zen Mode / Chat-First Mode Toggle Button
        self.btn_zen_header = ctk.CTkButton(
            right_box,
            text="🧘 Zen",
            width=78,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self.toggle_zen_mode
        )
        self.btn_zen_header.pack(side="left", padx=(0, 8))

        # Quick Screenshot Button (copies image to clipboard for instant Ctrl+V into Mammouth)
        self.btn_header_screen = ctk.CTkButton(
            right_box,
            text="📸 Screenshot (Ctrl+V)",
            width=160,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._take_and_copy_screenshot_ui
        )
        self.btn_header_screen.pack(side="left", padx=(0, 8))

        # Retain self.btn_open_mammouth for API/test compatibility without redundant packing in top bar
        self.btn_open_mammouth = ctk.CTkButton(
            right_box,
            text="💬 Mammouth AI",
            width=125,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._switch_to_mammouth_tab
        )

        # Theme Switcher
        theme_box = ctk.CTkFrame(right_box, fg_color="transparent")
        theme_box.pack(side="left", padx=(0, 12))
        self.theme_menu = ctk.CTkOptionMenu(
            theme_box,
            values=["Dark", "System", "Light"],
            width=85,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=THEME_CARD_BORDER_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG,
            command=self._on_theme_changed
        )
        self.theme_menu.set(self.appearance_mode)
        self.theme_menu.pack(anchor="w")

        # Status badge frame
        status_box = ctk.CTkFrame(right_box, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=6)
        status_box.pack(side="left", padx=(0, 10))
        self.status_badge = ctk.CTkLabel(
            status_box,
            text="● Server Stopped",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#EF4444"
        )
        self.status_badge.pack(padx=10, pady=4)

        # Main Power Toggle Button
        self.btn_toggle_server = ctk.CTkButton(
            right_box,
            text="▶ START SERVER",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=THEME_SUCCESS,
            hover_color=THEME_SUCCESS_HOVER,
            text_color="#FFFFFF",
            width=135,
            height=34,
            corner_radius=6,
            command=self.toggle_server
        )
        self.btn_toggle_server.pack(side="left")

        # 2. Main Body Container (Left Nav Rail + Right Canvas)
        body_container = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body_container.pack(fill="both", expand=True)

        self._build_sidebar(body_container)

        self.content_area = ctk.CTkFrame(body_container, fg_color=THEME_BG, corner_radius=0)
        self.content_area.pack(side="left", fill="both", expand=True)

        # 3. Main Tabview (Hides segmented button in favor of Left Navigation Rail)
        self.tabview = ctk.CTkTabview(
            self.content_area,
            corner_radius=0,
            fg_color="transparent",
            segmented_button_selected_color=THEME_ACCENT,
            segmented_button_selected_hover_color=THEME_ACCENT_HOVER,
            segmented_button_unselected_color=THEME_CARD_BG,
            segmented_button_unselected_hover_color=THEME_SUB_BG,
            segmented_button_fg_color=THEME_BG,
            text_color=THEME_TEXT_PRIMARY,
            command=self._on_tab_changed
        )
        self.tabview.pack(fill="both", expand=True, padx=0, pady=0)

        self.tab_dashboard = self.tabview.add("📊 Dashboard & Live Console")
        self.tab_mammouth_code = self.tabview.add("💻 Mammouth Code CLI")
        self.tab_skills = self.tabview.add("⚡ Modular Capabilities (12 Modules)")
        self.tab_prompts = self.tabview.add("📖 Prompt-Katalog")
        self.tab_tasks = self.tabview.add("⏱️ Tasks & Automatisierung")
        self.tab_hosts = self.tabview.add("🔑 SSH Fleet & PuTTY Manager")
        self.tab_settings = self.tabview.add("⚙️ Security & Settings")
        self.tab_mammouth = self.tabview.add("💬 Mammouth AI Web")

        # Remove horizontal segmented button bar in favor of modern Left Rail (MUST be called after add)
        if hasattr(self.tabview, "_segmented_button"):
            try:
                self.tabview._segmented_button.grid_remove()
            except Exception:
                pass

        self._setup_dashboard_tab()
        self._setup_mammouth_code_tab()
        self._setup_skills_tab()
        self._setup_prompts_tab()
        self._setup_tasks_tab()
        self._setup_hosts_tab()
        self._setup_settings_tab()
        self._setup_mammouth_tab()

        self._update_nav_highlight("📊 Dashboard & Live Console")

    def _build_sidebar(self, parent):
        self.sidebar = ctk.CTkFrame(
            parent,
            width=225,
            corner_radius=0,
            fg_color=THEME_HEADER_BG,
            border_width=1,
            border_color=THEME_CARD_BORDER
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Nav Section Label
        lbl_nav = ctk.CTkLabel(
            self.sidebar,
            text="NAVIGATION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME_TEXT_MUTED
        )
        lbl_nav.pack(anchor="w", padx=16, pady=(16, 8))

        # Nav Buttons list
        self._nav_buttons = {}
        nav_items = [
            ("📊 Dashboard & Live Console", "⚡ Dashboard & Status"),
            ("💻 Mammouth Code CLI", "💻 Mammouth Code"),
            ("⚡ Modular Capabilities (12 Modules)", "🛠️ Werkzeuge (12)"),
            ("📖 Prompt-Katalog", "📖 Prompt-Katalog"),
            ("⏱️ Tasks & Automatisierung", "⏱️ Geplante Tasks"),
            ("🔑 SSH Fleet & PuTTY Manager", "🔑 SSH & PuTTY Fleet"),
            ("⚙️ Security & Settings", "⚙️ Einstellungen"),
            ("💬 Mammouth AI Web", "💬 Mammouth WebApp"),
        ]

        for tab_key, label in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {label}",
                anchor="w",
                height=38,
                corner_radius=8,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="transparent",
                hover_color=THEME_SUB_BG,
                text_color=THEME_TEXT_MUTED,
                command=lambda k=tab_key: self._select_nav_tab(k)
            )
            btn.pack(fill="x", padx=10, pady=3)
            self._nav_buttons[tab_key] = btn

        # Bottom Mini Telemetry Card
        bottom_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom_box.pack(side="bottom", fill="x", padx=10, pady=12)
        self.quota_card = None

        self.mini_card = ctk.CTkFrame(
            bottom_box,
            fg_color=THEME_CARD_BG,
            border_width=1,
            border_color=THEME_CARD_BORDER,
            corner_radius=8
        )
        self.mini_card.pack(fill="x", pady=(0, 8))

        inner_card = ctk.CTkFrame(self.mini_card, fg_color="transparent")
        inner_card.pack(fill="x", padx=10, pady=8)

        self.lbl_nav_tools = ctk.CTkLabel(
            inner_card,
            text=f"⚡ {self._count_active_tools()} Werkzeuge aktiv",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME_SUCCESS
        )
        self.lbl_nav_tools.pack(anchor="w", pady=(0, 4))

        self.lbl_nav_cpu = ctk.CTkLabel(
            inner_card,
            text="CPU: 0.0%",
            font=ctk.CTkFont(size=10),
            text_color=THEME_TEXT_MUTED
        )
        self.lbl_nav_cpu.pack(anchor="w")
        self.bar_nav_cpu = ctk.CTkProgressBar(inner_card, height=4, progress_color="#10B981", fg_color=THEME_SUB_BG)
        self.bar_nav_cpu.set(0.0)
        self.bar_nav_cpu.pack(fill="x", pady=(1, 4))

        self.lbl_nav_ram = ctk.CTkLabel(
            inner_card,
            text="RAM: 0.0%",
            font=ctk.CTkFont(size=10),
            text_color=THEME_TEXT_MUTED
        )
        self.lbl_nav_ram.pack(anchor="w")
        self.bar_nav_ram = ctk.CTkProgressBar(inner_card, height=4, progress_color="#38BDF8", fg_color=THEME_SUB_BG)
        self.bar_nav_ram.set(0.0)
        self.bar_nav_ram.pack(fill="x", pady=(1, 2))

        btn_quick_ws = ctk.CTkButton(
            bottom_box,
            text="📂 Workspace Ordner",
            anchor="center",
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._open_workspace_folder
        )
        btn_quick_ws.pack(fill="x")

    def toggle_sidebar(self):
        """Toggles sidebar visibility for a full-bleed seamless workspace."""
        if getattr(self, "sidebar_visible", True):
            if hasattr(self, "sidebar"):
                self.sidebar.pack_forget()
            self.sidebar_visible = False
            if hasattr(self, "btn_toggle_sidebar"):
                self.btn_toggle_sidebar.configure(text="☰")
        else:
            if hasattr(self, "sidebar") and hasattr(self, "content_area"):
                self.sidebar.pack(side="left", fill="y", before=self.content_area)
            self.sidebar_visible = True
            if hasattr(self, "btn_toggle_sidebar"):
                self.btn_toggle_sidebar.configure(text="◀")

    def _select_nav_tab(self, tab_key: str):
        if hasattr(self, "tabview") and hasattr(self.tabview, "set"):
            self.tabview.set(tab_key)
            if hasattr(self.tabview, "_segmented_button"):
                try:
                    self.tabview._segmented_button.grid_remove()
                except Exception:
                    pass
        self._update_nav_highlight(tab_key)
        self._on_tab_changed()

    def _update_nav_highlight(self, current_tab: str):
        if not hasattr(self, "_nav_buttons"):
            return
        for tab_key, btn in self._nav_buttons.items():
            if tab_key == current_tab:
                btn.configure(
                    fg_color=THEME_ACCENT,
                    text_color=("#FFFFFF", "#FFFFFF"),
                    border_width=1,
                    border_color=THEME_ACCENT_HOVER
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=THEME_TEXT_MUTED,
                    border_width=0
                )

    def _setup_mammouth_tab(self):
        browser_cfg = self.config_data.get("embedded_browser", {})
        start_url = browser_cfg.get("start_page", "https://mammouth.ai")
        user_data_dir = browser_cfg.get("user_data_dir", "./data/browser_profile")
        if not os.path.isabs(user_data_dir):
            user_data_dir = str(BASE_DIR / user_data_dir)

        self.mammouth_browser = MammouthBrowserFrame(
            self.tab_mammouth,
            get_mcp_url_cb=self._calculate_active_endpoint_url,
            start_url=start_url,
            profile_dir=user_data_dir,
            screenshot_cb=self._take_and_copy_screenshot,
            zen_toggle_cb=self.toggle_zen_mode
        )
        self.tab_mammouth.configure(fg_color=THEME_BG)
        self.mammouth_browser.pack(fill="both", expand=True, padx=0, pady=0)

    def toggle_zen_mode(self, enable: Optional[bool] = None):
        """Toggle Zen / Chat-First Mode: collapse navigation rail and give 100% viewport to Mammouth AI."""
        if enable is None:
            self.zen_mode_active = not self.zen_mode_active
        else:
            self.zen_mode_active = bool(enable)

        if self.zen_mode_active:
            if self.sidebar_visible:
                if hasattr(self, "sidebar"):
                    self.sidebar.pack_forget()
                self.sidebar_visible = False
                if hasattr(self, "btn_toggle_sidebar"):
                    self.btn_toggle_sidebar.configure(text="☰")
            self._select_nav_tab("💬 Mammouth AI Web")
            if hasattr(self, "btn_zen_header"):
                self.btn_zen_header.configure(
                    text="🧘 Normal",
                    fg_color=THEME_ACCENT,
                    hover_color=THEME_ACCENT_HOVER,
                    text_color="#FFFFFF",
                    border_color=THEME_ACCENT_HOVER
                )
            if hasattr(self, "mammouth_browser") and hasattr(self.mammouth_browser, "set_zen_state"):
                self.mammouth_browser.set_zen_state(True)
            self._log("[ZEN MODE] Activated Chat-First Zen Mode (Sidebar collapsed).")
        else:
            if not self.sidebar_visible:
                if hasattr(self, "sidebar") and hasattr(self, "content_area"):
                    self.sidebar.pack(side="left", fill="y", before=self.content_area)
                self.sidebar_visible = True
                if hasattr(self, "btn_toggle_sidebar"):
                    self.btn_toggle_sidebar.configure(text="◀")
            if hasattr(self, "btn_zen_header"):
                self.btn_zen_header.configure(
                    text="🧘 Zen",
                    fg_color=THEME_BTN_SEC_BG,
                    hover_color=THEME_BTN_SEC_HOVER,
                    text_color=THEME_TEXT_PRIMARY,
                    border_color=THEME_BTN_SEC_BORDER
                )
            if hasattr(self, "mammouth_browser") and hasattr(self.mammouth_browser, "set_zen_state"):
                self.mammouth_browser.set_zen_state(False)
            self._log("[ZEN MODE] Deactivated Zen Mode (Standard Cockpit layout restored).")

    def _init_global_hotkey(self):
        """Initialize global summon hotkey (default: Ctrl+Shift+M) using Win32 RegisterHotKey."""
        if not self.config_data.get("server", {}).get("global_hotkey_enabled", True):
            return
        hotkey_spec = self.config_data.get("server", {}).get("global_hotkey", "Ctrl+Shift+M")
        try:
            parts = [p.strip() for p in hotkey_spec.split("+")]
            key = parts[-1] if parts else "M"
            mods = "+".join(parts[:-1]) if len(parts) > 1 else "Ctrl+Shift"
            ok = register_global_hotkey(
                lambda: self.after(0, self._on_global_hotkey_summon),
                key=key,
                modifiers=mods
            )
            if ok:
                self._log(f"[QUICK-LAUNCHER] Global summon hotkey active: {hotkey_spec}")
            else:
                self._log(f"[QUICK-LAUNCHER] Global hotkey {hotkey_spec} not bound (may conflict or non-Windows).")
        except Exception as e:
            self._log(f"[QUICK-LAUNCHER] Hotkey registration error: {e}")

    def _on_global_hotkey_summon(self):
        """Handle global hotkey trigger: summon Cockpit to front and focus Mammouth chat prompt."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = self.winfo_id()
            top_hwnd = user32.GetParent(hwnd) or hwnd
            is_fg = (user32.GetForegroundWindow() == top_hwnd)
            is_iconified = (self.state() == "iconic")

            # If already frontmost and active: toggle minimize
            if is_fg and not is_iconified:
                self.iconify()
                return

            # Otherwise, summon window to front
            self.deiconify()
            self.lift()
            self.focus_force()
            user32.ShowWindow(top_hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(top_hwnd)

            # Auto switch to Mammouth AI tab
            self._select_nav_tab("💬 Mammouth AI Web")

            # Focus chat input
            if hasattr(self, "mammouth_browser") and hasattr(self.mammouth_browser, "focus_and_paste"):
                self.mammouth_browser.focus_and_paste(delay_ms=100)
        except Exception as ex:
            self._log(f"[QUICK-LAUNCHER] Error summoning window: {ex}")

    def _on_quota_updated(self, payload: Optional[Dict[str, Any]]):
        pass

    def _on_quota_manual_refresh(self):
        pass

    def _schedule_quota_refresh_loop(self):
        pass

    def _take_and_copy_screenshot(self) -> Optional[str]:
        try:
            # User-initiated capture: the click is the consent. Does NOT open the gate for MCP clients.
            from modules.screen_capture import screen_capture_local, copy_image_to_clipboard
            res = screen_capture_local(monitor=1, save_to_workspace=True)
            saved_p = res.get("saved_path") if isinstance(res, dict) else None
            if saved_p and os.path.exists(saved_p):
                copy_image_to_clipboard(saved_p)
                self._log(f"[VISION] Screenshot captured: {saved_p} (In Clipboard for Ctrl+V)")
                return saved_p
            else:
                self._log(f"[VISION ERROR] Screenshot capture failed: {res}")
                return None
        except Exception as e:
            self._log(f"[VISION ERROR] Screenshot error: {e}")
            return None

    def _take_and_copy_screenshot_ui(self):
        """Interactively launches Windows Snipping Tool (ms-screenclip:), intercepts clipboard capture,
        switches to Mammouth WebApp, and automatically pastes the image into the chat field."""
        if hasattr(self, "btn_header_screen"):
            self.btn_header_screen.configure(text="✂️ Bereich wählen...", fg_color="#0284C7")

        from modules.screen_capture import launch_windows_snipping_tool, copy_image_to_clipboard, WORKSPACE_DIR, _cleanup_old_screenshots
        from PIL import ImageGrab, Image as PILImage
        from datetime import datetime

        if sys.platform != "win32":
            # Fallback for non-Windows platforms
            saved = self._take_and_copy_screenshot()
            if saved and hasattr(self, "btn_header_screen"):
                self.btn_header_screen.configure(text="✓ Im Clipboard!", fg_color="#10B981")
                self.after(2500, lambda: self.btn_header_screen.configure(text="📸 Screenshot (Ctrl+V)", fg_color=THEME_BTN_SEC_BG))
            return

        # Remember the clipboard sequence number; it changes whenever anything new is copied,
        # so the watcher only has to decode the clipboard once something actually changed.
        import ctypes
        _get_clip_seq = ctypes.windll.user32.GetClipboardSequenceNumber
        initial_seq = _get_clip_seq()

        launched = launch_windows_snipping_tool()
        if not launched:
            # Fallback to standard fullscreen capture
            saved = self._take_and_copy_screenshot()
            if saved and hasattr(self, "btn_header_screen"):
                self.btn_header_screen.configure(text="✓ Im Clipboard!", fg_color="#10B981")
                self.after(2500, lambda: self.btn_header_screen.configure(text="📸 Screenshot (Ctrl+V)", fg_color=THEME_BTN_SEC_BG))
            return

        def _snip_watcher():
            start_t = time.time()
            max_wait = 30.0  # Wait up to 30s for user to snip
            new_image = None

            last_seq = initial_seq
            while time.time() - start_t < max_wait:
                time.sleep(0.35)
                try:
                    seq = _get_clip_seq()
                    if seq == last_seq:
                        continue
                    last_seq = seq
                    cur = ImageGrab.grabclipboard()
                    if isinstance(cur, PILImage.Image):
                        new_image = cur
                        break
                except Exception:
                    pass

            saved_ok = False
            dest_path = None
            if new_image is not None:
                # Save new snip to workspace
                filename = f"snip_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.png"
                dest_path = WORKSPACE_DIR / filename
                try:
                    new_image.save(str(dest_path), format="PNG", optimize=True)
                    saved_ok = True
                    _cleanup_old_screenshots(max_keep=25)
                    copy_image_to_clipboard(str(dest_path))
                except Exception as e:
                    if not saved_ok:
                        self.after(0, lambda err=e: self._log(f"[SNIP] Could not save snip: {err}"))

            if saved_ok:
                self.after(0, lambda: self._on_snip_completed(str(dest_path)))
            else:
                self.after(0, self._on_snip_cancelled)

        threading.Thread(target=_snip_watcher, daemon=True).start()

    def _on_snip_completed(self, saved_path: str):
        self._log(f"[VISION] Snip captured: {saved_path} (Ready in clipboard and focusing chat)")
        if hasattr(self, "btn_header_screen"):
            self.btn_header_screen.configure(text="✓ Im Clipboard & Chat!", fg_color="#10B981")
            self.after(3000, lambda: self.btn_header_screen.configure(text="📸 Screenshot (Ctrl+V)", fg_color=THEME_BTN_SEC_BG))

        # 1. Bring Defroster to foreground
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

        # 2. Switch to Mammouth WebApp tab
        self._switch_to_mammouth_tab()

        # 3. Focus chat input and trigger Ctrl+V paste safely on UI thread
        if hasattr(self, "mammouth_browser") and hasattr(self.mammouth_browser, "focus_and_paste"):
            self.mammouth_browser.focus_and_paste(delay_ms=300)

    def _on_snip_cancelled(self):
        if hasattr(self, "btn_header_screen"):
            self.btn_header_screen.configure(text="📸 Screenshot (Ctrl+V)", fg_color=THEME_BTN_SEC_BG)

    def _switch_to_mammouth_tab(self):
        self.tabview.set("💬 Mammouth AI Web")
        if hasattr(self.tabview, "_segmented_button"):
            try:
                self.tabview._segmented_button.grid_remove()
            except Exception:
                pass
        self._update_nav_highlight("💬 Mammouth AI Web")
        self._on_tab_changed()

    def _on_tab_changed(self):
        current = self.tabview.get()
        self._update_nav_highlight(current)
        if current == "⏱️ Tasks & Automatisierung" and hasattr(self, "_refresh_task_cards"):
            self._refresh_task_cards()
        if hasattr(self, "mammouth_browser"):
            if current == "💬 Mammouth AI Web":
                self.mammouth_browser.ensure_initialized()
                self.mammouth_browser.set_tab_visible(True)
            else:
                self.mammouth_browser.set_tab_visible(False)

    def _check_updates_async(self, manual: bool = False):
        def worker():
            try:
                update_info = check_for_update(APP_VERSION)
                if update_info:
                    self.after(0, self._on_update_found, update_info)
                elif manual:
                    self.after(0, lambda: messagebox.showinfo("Up to Date", f"Mammouth Defroster 9000 ist auf dem neuesten Stand ({APP_VERSION})!", parent=self))
            except Exception as e:
                if manual:
                    # Bind e now: Python deletes the except variable when the block ends
                    self.after(0, lambda err=e: messagebox.showwarning("Update Check", f"Update-Prüfung fehlgeschlagen: {err}", parent=self))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_update_found(self, update_info: Dict[str, Any]):
        self.available_update = update_info
        ver = update_info.get("version", "vNeu")
        self.btn_update_badge.configure(text=f"🔄 Update: {ver}")
        self.btn_update_badge.pack(side="left", padx=(0, 8))
        self._log(f"[UPDATER] Eine neuere Version ist verfügbar: {ver} (Aktuell: {APP_VERSION})")
        if hasattr(self, "update_banner") and hasattr(self, "lbl_update_banner_text") and hasattr(self, "endpoint_card"):
            self.lbl_update_banner_text.configure(
                text=f"🎉 Neues Update verfügbar: {ver} (Installiert: {APP_VERSION}) — Schneller & stabiler mit Mammouth.ai!"
            )
            self.update_banner.pack(fill="x", padx=10, pady=(10, 0), before=self.endpoint_card)

    def _show_update_dialog(self):
        if not getattr(self, "available_update", None):
            self._check_updates_async(manual=True)
            return

        upd = self.available_update
        ver = upd.get("version", "")
        name = upd.get("name", ver)
        notes = upd.get("body", "Keine Release Notes verfügbar.")
        size_mb = round(upd.get("zip_size", 0) / (1024 * 1024), 1)

        dlg = ctk.CTkToplevel(self)
        dlg.title("Update verfügbar")
        dlg.geometry("520x480")
        dlg.resizable(False, False)
        dlg.configure(fg_color=THEME_BG)
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="🎉 Neues Update verfügbar!", font=ctk.CTkFont(size=18, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(pady=(20, 4))
        ctk.CTkLabel(dlg, text=f"Version {ver} (ca. {size_mb} MB) • Aktuell installiert: {APP_VERSION}", font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8")).pack(pady=(0, 10))

        tb = ctk.CTkTextbox(dlg, width=470, height=200, corner_radius=8, font=ctk.CTkFont(size=11), fg_color=THEME_INPUT_BG, border_width=1, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        tb.pack(padx=20, pady=5)
        tb.insert("1.0", notes)
        tb.configure(state="disabled")

        lbl_progress = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"))
        lbl_progress.pack(pady=(5, 0))

        progress_bar = ctk.CTkProgressBar(dlg, width=470, progress_color="#10B981", fg_color=("#E2E8F0", "#1E293B"))
        progress_bar.set(0)

        btn_box = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_box.pack(fill="x", padx=20, pady=15)

        def start_download():
            btn_install.configure(state="disabled")
            progress_bar.pack(pady=5)

            def dl_worker():
                def prog_cb(pct, msg):
                    self.after(0, lambda: [progress_bar.set(pct), lbl_progress.configure(text=msg)])

                success, result = download_and_verify_update(upd, progress_cb=prog_cb)
                if not success:
                    self.after(0, lambda: messagebox.showerror("Update Fehler", f"Download oder Verifikation fehlgeschlagen:\n\n{result}", parent=dlg))
                    self.after(0, lambda: btn_install.configure(state="normal"))
                else:
                    self.after(0, lambda: lbl_progress.configure(text="Installiere Update & starte neu..."))
                    target_dir = str(BASE_DIR)
                    pid = os.getpid()
                    applied = apply_update_and_restart(result, target_dir, pid)
                    if applied:
                        # The updater script is already waiting for this PID: close without a cancel option
                        self.after(500, lambda: self._on_close(force=True))
                    else:
                        self.after(0, lambda: messagebox.showerror("Update Fehler", "Konnte Updater-Skript nicht starten.", parent=dlg))

            threading.Thread(target=dl_worker, daemon=True).start()

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Später",
            width=100,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=dlg.destroy
        )
        btn_cancel.pack(side="left")

        btn_install = ctk.CTkButton(
            btn_box,
            text="⬇️ Jetzt herunterladen & installieren",
            font=ctk.CTkFont(weight="bold"),
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            command=start_download
        )
        btn_install.pack(side="right")


    def _on_theme_changed(self, choice: str):
        ctk.set_appearance_mode(choice)
        self.appearance_mode = choice
        self.config_data["server"]["appearance_mode"] = choice
        save_config(self.config_data)
        self._log(f"Theme switched to: {choice} (saved to config.json)")

    # ---------------------------------------------------------
    # TAB 1: DASHBOARD & LIVE LOGS
    # ---------------------------------------------------------
    def _setup_dashboard_tab(self):
        # Update Notice Banner (packed dynamically when update is available)
        self.update_banner = ctk.CTkFrame(
            self.tab_dashboard,
            fg_color=("#ECFDF5", "#1B2E24"),
            border_width=1,
            border_color=("#10B981", "#10B981"),
            corner_radius=8
        )
        self.lbl_update_banner_text = ctk.CTkLabel(
            self.update_banner,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#065F46", "#A7F3D0")
        )
        self.lbl_update_banner_text.pack(side="left", padx=(15, 10), pady=10)

        btn_banner_dismiss = ctk.CTkButton(
            self.update_banner,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color=("#D1FAE5", "#047857"),
            text_color=("#065F46", "#A7F3D0"),
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.update_banner.pack_forget()
        )
        btn_banner_dismiss.pack(side="right", padx=(4, 10), pady=8)

        btn_banner_action = ctk.CTkButton(
            self.update_banner,
            text="⬇️ Jetzt aktualisieren",
            width=150,
            height=28,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._show_update_dialog
        )
        btn_banner_action.pack(side="right", padx=(10, 4), pady=8)

        # 1. Hero Engine & Endpoint Card
        card = ctk.CTkFrame(self.tab_dashboard, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        card.pack(fill="x", padx=15, pady=(12, 10))
        self.endpoint_card = card

        # Mode Selection Bar inside Hero Card
        mode_bar = ctk.CTkFrame(card, fg_color="transparent")
        mode_bar.pack(fill="x", padx=15, pady=(12, 8))

        ctk.CTkLabel(mode_bar, text="Exposure Mode:", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        
        tunnel_modes = ["Serveo (Public SSH Tunnel)", "Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"]
        current_mode = self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel")
        self.dash_mode_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=tunnel_modes,
            width=170,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=("#CBD5E1", "#42434B"),
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG,
            command=self._on_dash_mode_changed
        )
        self.dash_mode_menu.set(current_mode)
        self.dash_mode_menu.pack(side="left", padx=10)

        ctk.CTkLabel(mode_bar, text="Route Path:", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left", padx=(10, 5))
        paths = ["/sse", "/mcp", "/messages", "/"]
        current_path = self.config_data.get("server", {}).get("endpoint_path", "/sse")
        self.dash_path_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=paths,
            width=100,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=("#CBD5E1", "#42434B"),
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG,
            command=self._on_dash_path_changed
        )
        self.dash_path_menu.set(current_path)
        self.dash_path_menu.pack(side="left")

        # Security Status Badges
        pills_box = ctk.CTkFrame(mode_bar, fg_color="transparent")
        pills_box.pack(side="right")

        self.lbl_oauth_status = ctk.CTkLabel(
            pills_box,
            text="⚡ OAuth 2.0 Ready",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0284C7", "#38BDF8")
        )
        self.lbl_oauth_status.pack(side="left", padx=5)

        self.lbl_auth_status = ctk.CTkLabel(
            pills_box,
            text="🔐 Bearer Token Active" if self.config_data.get("server", {}).get("enforce_auth", True) else "🔓 Open / No Auth",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#059669", "#10B981") if self.config_data.get("server", {}).get("enforce_auth", True) else "#F59E0B"
        )
        self.lbl_auth_status.pack(side="left", padx=5)

        self.lbl_sandbox_status = ctk.CTkLabel(
            pills_box,
            text="🔒 Sandbox ON" if self.config_data.get("server", {}).get("enforce_workspace_sandbox", True) else "⚠️ Full Machine",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#059669", "#10B981") if self.config_data.get("server", {}).get("enforce_workspace_sandbox", True) else "#EF4444"
        )
        self.lbl_sandbox_status.pack(side="left", padx=5)

        # Primary Public Endpoint Row
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=6)
        
        self.lbl_primary_title = ctk.CTkLabel(row1, text="🌐 Public SSE URL:", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY, width=160, anchor="w")
        self.lbl_primary_title.pack(side="left")
        
        self.lbl_public_url = ctk.CTkLabel(row1, text=self._calculate_active_endpoint_url(), font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0284C7", "#38BDF8"))
        self.lbl_public_url.pack(side="left", padx=10)
        
        btn_box1 = ctk.CTkFrame(row1, fg_color="transparent")
        btn_box1.pack(side="right")
        
        btn_detect_ts = ctk.CTkButton(
            btn_box1,
            text="🔄 Detect",
            width=80,
            height=28,
            fg_color=("#ECFDF5", "#1B2E24"),
            hover_color=("#D1FAE5", "#244E38"),
            text_color=("#047857", "#10B981"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#A7F3D0", "#244E38"),
            command=self._manual_detect_url
        )
        btn_detect_ts.pack(side="left", padx=3)

        btn_copy_pub = ctk.CTkButton(
            btn_box1,
            text="📋 Copy URL",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=lambda: self._copy_to_clipboard(self.lbl_public_url.cget("text"), "Public URL")
        )
        btn_copy_pub.pack(side="left", padx=3)

        btn_copy_json = ctk.CTkButton(
            btn_box1,
            text="⚙️ MCP JSON",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._copy_mcp_client_config
        )
        btn_copy_json.pack(side="left", padx=3)

        # Localhost Endpoint Row
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(4, 6))
        
        ctk.CTkLabel(row2, text="💻 Localhost URL:", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY, width=160, anchor="w").pack(side="left")
        self.lbl_local_url = ctk.CTkLabel(row2, text=self._calculate_local_endpoint_url(), font=ctk.CTkFont(size=12), text_color=("#64748B", "#A0A0A5"))
        self.lbl_local_url.pack(side="left", padx=10)
        
        btn_box2 = ctk.CTkFrame(row2, fg_color="transparent")
        btn_box2.pack(side="right")
        
        btn_copy_loc = ctk.CTkButton(
            btn_box2,
            text="📋 Copy URL",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=lambda: self._copy_to_clipboard(self.lbl_local_url.cget("text"), "Localhost URL")
        )
        btn_copy_loc.pack(side="left", padx=3)

        # Active Bearer Token Row
        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=15, pady=(4, 12))

        self.lbl_key_title = ctk.CTkLabel(row3, text="🔑 Bearer API Key:", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY, width=160, anchor="w")
        self.lbl_key_title.pack(side="left")

        current_token = self.config_data.get("server", {}).get("api_token", "")
        self.dash_token_visible = False
        display_tok = "•" * 28 if current_token else "(No Key Generated)"
        self.lbl_dash_key = ctk.CTkLabel(
            row3,
            text=display_tok,
            font=ctk.CTkFont(size=13, weight="bold", family="Consolas" if os.name == "nt" else "Monospace"),
            text_color=("#059669", "#10B981")
        )
        self.lbl_dash_key.pack(side="left", padx=10)

        btn_box3 = ctk.CTkFrame(row3, fg_color="transparent")
        btn_box3.pack(side="right")

        self.btn_toggle_dash_key = ctk.CTkButton(
            btn_box3,
            text="👁️ Show Key",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._toggle_dash_key_visibility
        )
        self.btn_toggle_dash_key.pack(side="left", padx=3)

        btn_copy_dash_key = ctk.CTkButton(
            btn_box3,
            text="📋 Copy Key",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=lambda: self._copy_to_clipboard(self.config_data.get("server", {}).get("api_token", ""), "Bearer Key")
        )
        btn_copy_dash_key.pack(side="left", padx=3)

        # 2. Four Clean Flat Metric Tiles (Horizontal Row)
        metrics_frame = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        metrics_frame.pack(fill="x", padx=15, pady=(0, 10))

        # Tile 1: Tools
        tile1 = ctk.CTkFrame(metrics_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        tile1.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(tile1, text="WERKZEUGE", font=ctk.CTkFont(size=10, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 2))
        self.lbl_stat_tools = ctk.CTkLabel(tile1, text=f"⚡ {self._count_active_tools()} Tools aktiv", font=ctk.CTkFont(size=14, weight="bold"), text_color=("#059669", "#10B981"))
        self.lbl_stat_tools.pack(anchor="w", padx=14, pady=(0, 10))

        # Tile 2: CPU
        tile2 = ctk.CTkFrame(metrics_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        tile2.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(tile2, text="CPU AUSLASTUNG", font=ctk.CTkFont(size=10, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 2))
        self.lbl_stat_cpu = ctk.CTkLabel(tile2, text="💻 CPU: 0.0%", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        self.lbl_stat_cpu.pack(anchor="w", padx=14)
        self.bar_cpu = ctk.CTkProgressBar(tile2, height=5, progress_color="#10B981", fg_color=("#E2E8F0", "#1E293B"))
        self.bar_cpu.set(0.0)
        self.bar_cpu.pack(fill="x", padx=14, pady=(3, 10))

        # Tile 3: RAM
        tile3 = ctk.CTkFrame(metrics_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        tile3.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(tile3, text="SPEICHER (RAM)", font=ctk.CTkFont(size=10, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 2))
        self.lbl_stat_ram = ctk.CTkLabel(tile3, text="🧠 RAM: 0.0%", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        self.lbl_stat_ram.pack(anchor="w", padx=14)
        self.bar_ram = ctk.CTkProgressBar(tile3, height=5, progress_color="#38BDF8", fg_color=("#E2E8F0", "#1E293B"))
        self.bar_ram.set(0.0)
        self.bar_ram.pack(fill="x", padx=14, pady=(3, 10))

        # Tile 4: Uptime
        tile4 = ctk.CTkFrame(metrics_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        tile4.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(tile4, text="SERVER LAUFZEIT", font=ctk.CTkFont(size=10, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 2))
        self.lbl_stat_uptime = ctk.CTkLabel(tile4, text="⏱️ Uptime: 00:00:00", font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        self.lbl_stat_uptime.pack(anchor="w", padx=14, pady=(0, 10))

        # 3. Quick Action Buttons Bar
        actions_bar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        actions_bar.pack(fill="x", padx=15, pady=(0, 8))

        btn_screen = ctk.CTkButton(
            actions_bar,
            text="📸 Capture Desktop",
            width=140,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._test_screenshot
        )
        btn_screen.pack(side="left", padx=(0, 8))

        btn_mc = ctk.CTkButton(
            actions_bar,
            text="💻 Mammouth Code",
            width=150,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._launch_mammouth_code
        )
        btn_mc.pack(side="left", padx=(0, 8))

        btn_tasks = ctk.CTkButton(
            actions_bar,
            text="⏱️ Geplante Tasks",
            width=140,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=lambda: self._select_nav_tab("⏱️ Tasks & Automatisierung")
        )
        btn_tasks.pack(side="left", padx=(0, 8))

        btn_ws = ctk.CTkButton(
            actions_bar,
            text="📂 Open Workspace",
            width=140,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._open_workspace_folder
        )
        btn_ws.pack(side="left", padx=(0, 8))

        btn_export = ctk.CTkButton(
            actions_bar,
            text="💾 Save Log",
            width=100,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._export_logs
        )
        btn_export.pack(side="right", padx=(8, 0))

        btn_clear = ctk.CTkButton(
            actions_bar,
            text="🧹 Clear Logs",
            width=100,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._clear_logs
        )
        btn_clear.pack(side="right")

        # 4. Text Console with Modern Monospace Styling
        self.log_textbox = ctk.CTkTextbox(
            self.tab_dashboard,
            font=ctk.CTkFont(family="Consolas" if os.name == "nt" else "Monospace", size=12),
            wrap="word",
            fg_color=("#FFFFFF", "#1C1C1F"),
            text_color=("#0F172A", "#E2E8F0"),
            border_width=1,
            border_color=("#CBD5E1", "#323338"),
            corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self._log(f"Mammouth Defroster 9000 {APP_VERSION} initialized. Sovereign Cockpit Ready.")

    def _setup_prompts_tab(self):
        top_bar = ctk.CTkFrame(self.tab_prompts, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(12, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(
            title_box,
            text="📖 Mammouth.ai Prompt-Katalog",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Optimierte Vorlagen für Mammouth.ai. Mit 1 Klick in die Zwischenablage kopieren & im Chat abschicken.",
            font=ctk.CTkFont(size=12),
            text_color=THEME_TEXT_MUTED
        ).pack(anchor="w")

        scroll = ctk.CTkScrollableFrame(self.tab_prompts, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        prompts = [
            (
                "🖥️ Bildschirm-Inspektion & OCR",
                "Vision",
                "Lässt Mammouth deinen Bildschirm erfassen, Menüs und Fehler analysieren.",
                "Nutze das Tool screen_capture (monitor=1), erstelle einen Screenshot meines Bildschirms und analysiere die aktuell sichtbaren Fenster, Fehlermeldungen und Inhalte."
            ),
            (
                "📊 Systemdiagnose & Top-Prozesse",
                "System",
                "Ermittelt laufende Hintergrundprozesse und deren Ressourcenverbrauch.",
                "Führe mit system_get_processes eine Systemdiagnose durch und zeige mir die Top 5 Prozesse nach Arbeitsspeicher- und CPU-Verbrauch in einer übersichtlichen Tabelle an."
            ),
            (
                "📁 Workspace Projekt-Generierung",
                "Dateien",
                "Erstellt ein neues Skript oder eine Konfiguration direkt im lokalen Workspace.",
                "Erstelle mit file_write im lokalen Workspace eine neue Python-Datei 'pipeline.py'. Implementiere eine saubere Pipeline mit Fehlerbehandlung und Dokumentation."
            ),
            (
                "💻 Mammouth Code CLI Task",
                "Coding Agent",
                "Startet eine Coding-Aufgabe headless oder im interaktiven Terminal mit Mammouth Code.",
                "Starte mit mammouth_code_run_task eine Aufgabe: 'Analysiere das aktuelle Projekt und erstelle eine modular aufgebaute REST-API mit Tests'."
            ),
            (
                "☁️ Google Drive Dateisuche",
                "Cloud",
                "Durchsucht angebundene Google Drive Dokumente nach Schlüsselwörtern.",
                "Nutze gdrive_list_files mit einer Suchanfrage nach aktuellen Dokumenten und liste mir Dateinamen, Links und das letzte Änderungsdatum übersichtlich auf."
            ),
            (
                "🐧 SSH Linux Server Check",
                "Remote",
                "Führt über PuTTY/SSH gespeicherte Host-Profile Statuskommandos aus.",
                "Nutze putty_ssh_exec auf meinem gespeicherten Linux-Host, um 'uptime && df -h && free -m' auszuführen und fasse mir den Serverzustand zusammen."
            ),
        ]

        for title, category, desc, prompt_text in prompts:
            card = ctk.CTkFrame(
                scroll,
                fg_color=THEME_CARD_BG,
                border_width=1,
                border_color=THEME_CARD_BORDER,
                corner_radius=10
            )
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=12, fill="x", expand=True)

            t_row = ctk.CTkFrame(left, fg_color="transparent")
            t_row.pack(anchor="w")

            ctk.CTkLabel(
                t_row,
                text=title,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=THEME_TEXT_PRIMARY
            ).pack(side="left")

            badge = ctk.CTkFrame(
                t_row,
                fg_color=("#F1F5F9", "#1E2028"),
                border_width=1,
                border_color=THEME_CARD_BORDER,
                corner_radius=5
            )
            badge.pack(side="left", padx=8)
            ctk.CTkLabel(
                badge,
                text=f" {category} ",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#059669", "#10B981")
            ).pack(padx=3, pady=1)

            ctk.CTkLabel(
                left,
                text=desc,
                font=ctk.CTkFont(size=12),
                text_color=("#64748B", "#A0A0A5"),
                anchor="w"
            ).pack(anchor="w", pady=(2, 6))

            prompt_box = ctk.CTkFrame(
                left,
                fg_color=THEME_INPUT_BG,
                border_width=1,
                border_color=("#E2E8F0", "#323338"),
                corner_radius=6
            )
            prompt_box.pack(fill="x")

            ctk.CTkLabel(
                prompt_box,
                text=prompt_text,
                font=ctk.CTkFont(size=11, family="Consolas" if os.name == "nt" else "Monospace"),
                text_color=("#334155", "#E2E8F0"),
                wraplength=600,
                justify="left",
                anchor="w"
            ).pack(fill="x", padx=10, pady=8)

            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.pack(side="right", padx=15, pady=12)

            btn_copy = ctk.CTkButton(
                btn_box,
                text="📋 Prompt kopieren",
                width=140,
                height=32,
                fg_color=("#059669", "#10B981"),
                hover_color=("#047857", "#059669"),
                text_color="#FFFFFF",
                font=ctk.CTkFont(weight="bold"),
                command=lambda p=prompt_text: self._copy_to_clipboard(p, "Prompt")
            )
            btn_copy.pack(side="right")

    def _init_task_scheduler(self):
        """Initialize the automated task scheduler and register event callbacks."""
        self.task_countdown_labels: Dict[int, ctk.CTkLabel] = {}
        try:
            self.scheduler_engine = TaskSchedulerEngine.get_instance()
            self.scheduler_engine.register_handler("mammouth_web", self._on_trigger_mammouth_web_task)
            self.scheduler_engine.register_handler("mammouth_code", self._on_trigger_mammouth_code_task)
            self.scheduler_engine.register_handler("powershell", self._on_trigger_powershell_task)
            self.scheduler_engine.register_handler("notification", self._on_trigger_notification_task)
            self.scheduler_engine.register_listener(lambda: self.after(0, self._refresh_task_cards))
            self.after(1000, self._on_scheduler_tick)
        except Exception as e:
            self._log(f"[TASK SCHEDULER WARNING] Init failed: {e}")

    def _on_scheduler_tick(self):
        """Runs every 1 second on the Tkinter UI thread to check due tasks and update countdowns."""
        try:
            if hasattr(self, "scheduler_engine"):
                self.scheduler_engine.check_and_run_due_tasks()
            self._update_task_countdowns()
        except Exception:
            pass
        finally:
            self.after(1000, self._on_scheduler_tick)

    def _on_trigger_mammouth_web_task(self, task: Dict[str, Any]) -> str:
        """Trigger handler: Injects prompt into the embedded Mammouth AI Web chat."""
        prompt = task.get("prompt", "")
        name = task.get("name", "Task")
        runs_done = task.get("runs_done", 0) + 1
        switch_tab = bool(task.get("switch_tab", 1))
        auto_submit = bool(task.get("auto_submit", 1))

        self._log(f"[TASK SCHEDULER] ⏱️ Triggering '{name}' (Run #{runs_done}) -> Mammouth Web Chat")

        def _do_web_trigger():
            try:
                if switch_tab:
                    self._switch_to_mammouth_tab()
                if hasattr(self, "mammouth_browser") and hasattr(self.mammouth_browser, "send_chat_prompt"):
                    self.mammouth_browser.send_chat_prompt(prompt, auto_submit=auto_submit, delay_ms=350 if switch_tab else 50)
            except Exception as ex:
                self._log(f"[TASK WARNING] Web trigger error: {ex}")

        self.after(0, _do_web_trigger)
        return "Dispatched to Mammouth AI Web"

    def _on_trigger_mammouth_code_task(self, task: Dict[str, Any]) -> str:
        """Trigger handler: Runs Mammouth Code CLI headlessly."""
        prompt = task.get("prompt", "")
        name = task.get("name", "Task")
        runs_done = task.get("runs_done", 0) + 1
        self._log(f"[TASK SCHEDULER] 💻 Triggering '{name}' (Run #{runs_done}) -> Mammouth Code CLI")

        def _run():
            try:
                from modules.mammouth_code import run_mammouth_task
                res = run_mammouth_task(task_prompt=prompt, stream_output=False, timeout_seconds=180)
                status_str = "Success" if res.get("success") else f"Failed: {res.get('error', 'unknown')}"
                self._log(f"[TASK SCHEDULER] Mammouth Code Run #{runs_done} finished: {status_str}")
            except Exception as e:
                self._log(f"[TASK WARNING] Mammouth Code trigger error: {e}")

        # Runs up to 180s: never block the Tk scheduler tick with it
        threading.Thread(target=_run, daemon=True, name=f"SchedMammouthCode-{task.get('id')}").start()
        return "Started in background"

    def _on_trigger_powershell_task(self, task: Dict[str, Any]) -> str:
        """Trigger handler: Runs local PowerShell command."""
        prompt = task.get("prompt", "")
        name = task.get("name", "Task")
        runs_done = task.get("runs_done", 0) + 1
        self._log(f"[TASK SCHEDULER] ⚡ Triggering '{name}' (Run #{runs_done}) -> PowerShell")

        cfg = load_config()
        if not cfg.get("modules", {}).get("shell_processes", {}).get("enabled", False):
            self._log(f"[TASK SCHEDULER] PowerShell task '{name}' skipped: module 'shell_processes' is disabled.")
            return "Skipped: shell_processes module disabled"

        def _run():
            try:
                from modules.shell_processes import command_run
                res = command_run(command=prompt)
                self._log(f"[TASK SCHEDULER] PowerShell Run #{runs_done} finished (exit {res.get('exit_code')}).")
            except Exception as e:
                self._log(f"[TASK WARNING] PowerShell trigger error: {e}")

        threading.Thread(target=_run, daemon=True, name=f"SchedPowerShell-{task.get('id')}").start()
        return "Started in background"

    def _on_trigger_notification_task(self, task: Dict[str, Any]) -> str:
        """Trigger handler: Displays desktop alert & sound."""
        prompt = task.get("prompt", "")
        name = task.get("name", "Task")
        runs_done = task.get("runs_done", 0) + 1
        self._log(f"[TASK SCHEDULER] 🔔 Alert: '{name}' (Run #{runs_done}): {prompt[:60]}...")
        if sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        return "Notification displayed"

    def _setup_tasks_tab(self):
        """Build the Tasks & Automation UI view."""
        top_bar = ctk.CTkFrame(self.tab_tasks, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(12, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(
            title_box,
            text="⏱️ Aufgaben & Automatisierung (Task Scheduler)",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Wiederkehrende Tasks automatisch im Mammouth AI Chat, Code CLI oder System auslösen (z.B. Fußball-Livebericht alle 5 Min).",
            font=ctk.CTkFont(size=12),
            text_color=THEME_TEXT_MUTED
        ).pack(anchor="w")

        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right")

        ctk.CTkButton(
            btn_box,
            text="⚽ Livebericht (5 Min)",
            width=165,
            height=32,
            fg_color=THEME_ACCENT,
            hover_color=THEME_ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._quick_start_football_live_task
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_box,
            text="➕ Neuer Task",
            width=130,
            height=32,
            fg_color=THEME_SUCCESS,
            hover_color=THEME_SUCCESS_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=lambda: self._show_new_task_dialog()
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_box,
            text="🔄",
            width=36,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            command=self._refresh_task_cards
        ).pack(side="left")

        # KPI Metrics Row
        self.task_kpi_frame = ctk.CTkFrame(self.tab_tasks, fg_color="transparent")
        self.task_kpi_frame.pack(fill="x", padx=15, pady=(0, 10))

        # Metric 1: Running tasks
        m1 = ctk.CTkFrame(self.task_kpi_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=8)
        m1.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(m1, text="Laufende Tasks", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.lbl_task_stat_running = ctk.CTkLabel(m1, text="0 aktiv", font=ctk.CTkFont(size=16, weight="bold"), text_color=THEME_SUCCESS)
        self.lbl_task_stat_running.pack(anchor="w", padx=12, pady=(0, 8))

        # Metric 2: Next trigger
        m2 = ctk.CTkFrame(self.task_kpi_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=8)
        m2.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkLabel(m2, text="Nächster Trigger", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.lbl_task_stat_next = ctk.CTkLabel(m2, text="Kein aktiver Task", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY)
        self.lbl_task_stat_next.pack(anchor="w", padx=12, pady=(0, 8))

        # Metric 3: Total executions
        m3 = ctk.CTkFrame(self.task_kpi_frame, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=8)
        m3.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(m3, text="Ausführungen gesamt", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", padx=12, pady=(8, 0))
        self.lbl_task_stat_total = ctk.CTkLabel(m3, text="0", font=ctk.CTkFont(size=16, weight="bold"), text_color=("#9F6C45", "#C8A37C"))
        self.lbl_task_stat_total.pack(anchor="w", padx=12, pady=(0, 8))

        # Scrollable Tasks Frame
        self.tasks_scroll = ctk.CTkScrollableFrame(self.tab_tasks, fg_color="transparent")
        self.tasks_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self._refresh_task_cards()

    def _refresh_task_cards(self):
        """Re-render the list of scheduled tasks cards and update KPI stats."""
        if not hasattr(self, "tasks_scroll"):
            return

        for w in self.tasks_scroll.winfo_children():
            w.destroy()

        if not hasattr(self, "task_countdown_labels"):
            self.task_countdown_labels = {}
        else:
            self.task_countdown_labels.clear()

        tasks = scheduler_list_tasks()

        # Update KPI metrics
        active_count = len([t for t in tasks if t.get("status") == "active"])
        total_runs = sum(t.get("runs_done", 0) for t in tasks)

        if hasattr(self, "lbl_task_stat_running"):
            self.lbl_task_stat_running.configure(text=f"{active_count} aktiv")
        if hasattr(self, "lbl_task_stat_total"):
            self.lbl_task_stat_total.configure(text=str(total_runs))

        if not tasks:
            empty_card = ctk.CTkFrame(
                self.tasks_scroll,
                fg_color=THEME_CARD_BG,
                border_width=1,
                border_color=THEME_CARD_BORDER,
                corner_radius=12
            )
            empty_card.pack(fill="x", pady=25, padx=20)

            inner = ctk.CTkFrame(empty_card, fg_color="transparent")
            inner.pack(pady=35, padx=20)

            ctk.CTkLabel(inner, text="⏱️", font=ctk.CTkFont(size=44)).pack()
            ctk.CTkLabel(
                inner,
                text="Noch keine automatisierten Tasks eingerichtet",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=THEME_TEXT_PRIMARY
            ).pack(pady=(10, 4))
            ctk.CTkLabel(
                inner,
                text="Erstelle geplante Tasks, um z.B. alle 5 Minuten einen Livebericht zum Fußballspiel oder Krypto-Updates automatisch im Mammouth AI Chat auszulösen.",
                font=ctk.CTkFont(size=12),
                text_color=THEME_TEXT_MUTED,
                wraplength=550,
                justify="center"
            ).pack(pady=(0, 16))

            btn_row = ctk.CTkFrame(inner, fg_color="transparent")
            btn_row.pack()

            ctk.CTkButton(
                btn_row,
                text="⚽ Fußball-Livebericht starten (alle 5 Min)",
                fg_color=THEME_ACCENT,
                hover_color=THEME_ACCENT_HOVER,
                font=ctk.CTkFont(weight="bold"),
                height=34,
                command=self._quick_start_football_live_task
            ).pack(side="left", padx=6)

            ctk.CTkButton(
                btn_row,
                text="➕ Benutzerdefinierten Task erstellen",
                fg_color=THEME_SUCCESS,
                hover_color=THEME_SUCCESS_HOVER,
                font=ctk.CTkFont(weight="bold"),
                height=34,
                command=lambda: self._show_new_task_dialog()
            ).pack(side="left", padx=6)
            return

        for task in tasks:
            task_id = task["id"]
            name = task.get("name", "Task")
            status = task.get("status", "active")
            target = task.get("target", "mammouth_web")
            interval_sec = task.get("interval_seconds", 300)
            repeats = task.get("repeat_count", 0)
            runs_done = task.get("runs_done", 0)
            prompt = task.get("prompt", "")
            last_run = task.get("last_run", "")

            card = ctk.CTkFrame(
                self.tasks_scroll,
                fg_color=THEME_CARD_BG,
                border_width=1,
                border_color=THEME_CARD_BORDER,
                corner_radius=10
            )
            card.pack(fill="x", pady=6)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=15, pady=12)

            # Top Row: Title + Target Badge + Status Badge + Actions
            top_row = ctk.CTkFrame(inner, fg_color="transparent")
            top_row.pack(fill="x", pady=(0, 6))

            left_box = ctk.CTkFrame(top_row, fg_color="transparent")
            left_box.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(
                left_box,
                text=name,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=THEME_TEXT_PRIMARY
            ).pack(side="left")

            # Target badge
            target_labels = {
                "mammouth_web": ("💬 Mammouth AI Web", ("#F2EBE1", "#2F241D"), ("#754533", "#C8A37C")),
                "mammouth_code": ("💻 Mammouth Code", ("#EDE3D4", "#3D2B1F"), ("#9F6C45", "#B88557")),
                "powershell": ("⚡ PowerShell", ("#EFF6FF", "#1E293B"), ("#2563EB", "#60A5FA")),
                "notification": ("🔔 Benachrichtigung", ("#FFFBEB", "#382D1D"), ("#D97706", "#FBBF24"))
            }
            tgt_text, tgt_bg, tgt_fg = target_labels.get(target, ("⚙️ Target", ("#F1F5F9", "#1E2028"), ("#64748B", "#94A3B8")))

            t_badge = ctk.CTkFrame(left_box, fg_color=tgt_bg, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=5)
            t_badge.pack(side="left", padx=8)
            ctk.CTkLabel(t_badge, text=f" {tgt_text} ", font=ctk.CTkFont(size=10, weight="bold"), text_color=tgt_fg).pack(padx=3, pady=1)

            # Status badge
            status_labels = {
                "active": ("🟢 Aktiv", ("#DCFCE7", "#14532D"), ("#16A34A", "#4ADE80")),
                "paused": ("⏸️ Pausiert", ("#FEF3C7", "#713F12"), ("#D97706", "#FBBF24")),
                "completed": ("🏁 Abgeschlossen", ("#F1F5F9", "#1E2028"), ("#64748B", "#94A3B8")),
                "stopped": ("⏹️ Gestoppt", ("#FEE2E2", "#450A0A"), ("#DC2626", "#F87171"))
            }
            st_text, st_bg, st_fg = status_labels.get(status, ("•", ("#F1F5F9", "#1E2028"), ("#64748B", "#94A3B8")))

            s_badge = ctk.CTkFrame(left_box, fg_color=st_bg, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=5)
            s_badge.pack(side="left")
            ctk.CTkLabel(s_badge, text=f" {st_text} ", font=ctk.CTkFont(size=10, weight="bold"), text_color=st_fg).pack(padx=3, pady=1)

            # Right action buttons
            right_actions = ctk.CTkFrame(top_row, fg_color="transparent")
            right_actions.pack(side="right")

            # 1. Trigger Now
            btn_run_now = ctk.CTkButton(
                right_actions,
                text="⚡ Jetzt ausführen",
                width=115,
                height=28,
                fg_color=("#059669", "#10B981"),
                hover_color=("#047857", "#059669"),
                text_color="#FFFFFF",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda tid=task_id: self._trigger_task_now_ui(tid)
            )
            btn_run_now.pack(side="left", padx=(0, 6))

            # 2. Pause / Resume
            if status == "active":
                btn_pause = ctk.CTkButton(
                    right_actions,
                    text="⏸️ Pause",
                    width=85,
                    height=28,
                    fg_color=THEME_BTN_SEC_BG,
                    hover_color=THEME_BTN_SEC_HOVER,
                    text_color=THEME_TEXT_PRIMARY,
                    font=ctk.CTkFont(size=11),
                    command=lambda tid=task_id: self._pause_task_ui(tid)
                )
                btn_pause.pack(side="left", padx=(0, 6))
            else:
                btn_resume = ctk.CTkButton(
                    right_actions,
                    text="▶️ Start",
                    width=85,
                    height=28,
                    fg_color=THEME_BTN_SEC_BG,
                    hover_color=THEME_BTN_SEC_HOVER,
                    text_color=THEME_TEXT_PRIMARY,
                    font=ctk.CTkFont(size=11),
                    command=lambda tid=task_id: self._resume_task_ui(tid)
                )
                btn_resume.pack(side="left", padx=(0, 6))

            # 3. Delete
            btn_del = ctk.CTkButton(
                right_actions,
                text="🗑️",
                width=32,
                height=28,
                fg_color=("#FEE2E2", "#381E1E"),
                hover_color=("#FECACA", "#542222"),
                text_color=("#DC2626", "#F87171"),
                font=ctk.CTkFont(size=12),
                command=lambda tid=task_id: self._delete_task_ui(tid)
            )
            btn_del.pack(side="left")

            # Second Row: Interval, Runs progress, Countdown timer, Last run
            info_row = ctk.CTkFrame(inner, fg_color="transparent")
            info_row.pack(fill="x", pady=(2, 6))

            interv_min = round(interval_sec / 60, 1)
            interv_str = f"{int(interv_min)} Min" if interv_min.is_integer() else f"{interv_min} Min"

            ctk.CTkLabel(
                info_row,
                text=f"⏱️ Alle {interv_str} ({interval_sec}s)",
                font=ctk.CTkFont(size=11),
                text_color=THEME_TEXT_MUTED
            ).pack(side="left", padx=(0, 15))

            rep_str = f"🔁 Ausführung {runs_done} von {repeats}" if repeats > 0 else f"🔁 Ausführung {runs_done} (fortlaufend)"
            ctk.CTkLabel(
                info_row,
                text=rep_str,
                font=ctk.CTkFont(size=11),
                text_color=THEME_TEXT_MUTED
            ).pack(side="left", padx=(0, 15))

            lbl_cd = ctk.CTkLabel(
                info_row,
                text="⏳ Berechne...",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#4F46E5", "#818CF8")
            )
            lbl_cd.pack(side="left", padx=(0, 15))
            self.task_countdown_labels[task_id] = lbl_cd

            if last_run:
                try:
                    lr_dt = datetime.fromisoformat(last_run)
                    lr_str = lr_dt.strftime("%H:%M:%S Uhr")
                except Exception:
                    lr_str = last_run[:19]
                ctk.CTkLabel(
                    info_row,
                    text=f"Zuletzt: {lr_str}",
                    font=ctk.CTkFont(size=11),
                    text_color=THEME_TEXT_MUTED
                ).pack(side="left")

            # Third Row: Prompt Box Preview
            prompt_box = ctk.CTkFrame(
                inner,
                fg_color=THEME_INPUT_BG,
                border_width=1,
                border_color=("#E2E8F0", "#323338"),
                corner_radius=6
            )
            prompt_box.pack(fill="x")

            ctk.CTkLabel(
                prompt_box,
                text=prompt,
                font=ctk.CTkFont(size=11, family="Consolas" if os.name == "nt" else "Monospace"),
                text_color=("#334155", "#E2E8F0"),
                wraplength=640,
                justify="left",
                anchor="w"
            ).pack(fill="x", padx=10, pady=8)

        # Trigger countdown calculation immediately
        self._update_task_countdowns()

    def _update_task_countdowns(self):
        """Update live countdown labels on all rendered task cards."""
        if not hasattr(self, "task_countdown_labels") or not self.task_countdown_labels:
            return

        now_dt = datetime.now()
        earliest_next_str = None
        earliest_task_name = None

        tasks = scheduler_list_tasks()
        task_map = {t["id"]: t for t in tasks}

        for tid, lbl in list(self.task_countdown_labels.items()):
            task = task_map.get(tid)
            if not task:
                continue

            status = task.get("status", "active")
            next_run = task.get("next_run", "")

            if status == "active" and next_run:
                try:
                    nr_dt = datetime.fromisoformat(next_run)
                    diff = (nr_dt - now_dt).total_seconds()
                    if diff > 0:
                        mm = int(diff) // 60
                        ss = int(diff) % 60
                        lbl.configure(text=f"⏳ Nächster Trigger: {mm:02d}:{ss:02d} min", text_color=("#4F46E5", "#818CF8"))
                    else:
                        lbl.configure(text="⏳ Wird ausgeführt...", text_color=("#059669", "#10B981"))

                    if earliest_next_str is None or next_run < earliest_next_str:
                        earliest_next_str = next_run
                        earliest_task_name = task.get("name", "Task")
                except Exception:
                    lbl.configure(text=f"⏳ {next_run[:19]}")
            elif status == "paused":
                lbl.configure(text="⏸️ Pausiert", text_color=("#D97706", "#FBBF24"))
            elif status == "completed":
                lbl.configure(text="🏁 Abgeschlossen", text_color=THEME_TEXT_MUTED)
            elif status == "stopped":
                lbl.configure(text="⏹️ Gestoppt", text_color=("#DC2626", "#F87171"))

        if hasattr(self, "lbl_task_stat_next"):
            if earliest_next_str:
                try:
                    e_dt = datetime.fromisoformat(earliest_next_str)
                    e_diff = (e_dt - now_dt).total_seconds()
                    if e_diff > 0:
                        mm = int(e_diff) // 60
                        ss = int(e_diff) % 60
                        short_name = (earliest_task_name[:16] + "...") if len(earliest_task_name or "") > 18 else earliest_task_name
                        self.lbl_task_stat_next.configure(text=f"{mm:02d}:{ss:02d} min ({short_name})")
                    else:
                        self.lbl_task_stat_next.configure(text="Wird ausgeführt...")
                except Exception:
                    self.lbl_task_stat_next.configure(text="Geplant")
            else:
                self.lbl_task_stat_next.configure(text="Kein aktiver Task")

    def _trigger_task_now_ui(self, task_id: int):
        scheduler_trigger_task_now(task_id)
        self._refresh_task_cards()

    def _pause_task_ui(self, task_id: int):
        scheduler_pause_task(task_id)
        self._refresh_task_cards()

    def _resume_task_ui(self, task_id: int):
        scheduler_resume_task(task_id)
        self._refresh_task_cards()

    def _delete_task_ui(self, task_id: int):
        scheduler_delete_task(task_id)
        self._refresh_task_cards()

    def _quick_start_football_live_task(self):
        """1-Click shortcut: Creates and launches the 5-minute football live ticker task immediately."""
        task = scheduler_create_task(
            name="⚽ Livebericht: Fußballspiel",
            prompt="Gib mir einen ausführlichen Livebericht zum aktuellen Fußballspiel: Suche im Web nach aktuellem Spielstand, Toren, Karten, Auswechslungen und dem Spielgeschehen der letzten 5 Minuten.",
            interval_seconds=300,
            repeat_count=20,
            target="mammouth_web",
            auto_submit=True,
            switch_tab=True,
            start_immediately=True
        )
        self._log(f"[TASK SCHEDULER] ⚽ Fußball-Livebericht gestartet (ID #{task.get('id')}). Nächster Trigger in 2s, danach alle 5 Minuten.")
        self._select_nav_tab("⏱️ Tasks & Automatisierung")
        self._refresh_task_cards()

    def _show_new_task_dialog(self, preset_id: Optional[str] = None):
        """Modal dialog to configure and launch a new scheduled automated task."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Neuen automatisierten Task erstellen")
        dlg.geometry("640x580")
        dlg.resizable(False, False)
        dlg.grab_set()

        # Center dialog
        try:
            dlg.update_idletasks()
            w, h = 640, 580
            x = max(0, self.winfo_x() + (self.winfo_width() - w) // 2)
            y = max(0, self.winfo_y() + (self.winfo_height() - h) // 2)
            dlg.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        content = ctk.CTkFrame(dlg, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(
            content,
            text="⏱️ Neuer automatisierter Task",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        ).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(
            content,
            text="Definiere Name, Intervall und den Prompt, der automatisch ausgeführt werden soll.",
            font=ctk.CTkFont(size=12),
            text_color=THEME_TEXT_MUTED
        ).pack(anchor="w", pady=(0, 14))

        # Preset selector
        presets = scheduler_get_presets()
        preset_names = ["-- Vorlage wählen (optional) --"] + [p["name"] for p in presets]

        ctk.CTkLabel(content, text="Vorlage (Optional):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")

        def on_preset_selected(choice):
            for p in presets:
                if p["name"] == choice:
                    entry_name.delete(0, "end")
                    entry_name.insert(0, p["name"])

                    txt_prompt.delete("1.0", "end")
                    txt_prompt.insert("1.0", p["prompt"])

                    entry_interval.delete(0, "end")
                    entry_interval.insert(0, str(round(p["interval_seconds"] / 60, 1)))

                    entry_repeats.delete(0, "end")
                    entry_repeats.insert(0, str(p.get("repeat_count", 0)))

                    tgt_labels_rev = {
                        "mammouth_web": "💬 Mammouth AI Web Chat",
                        "mammouth_code": "💻 Mammouth Code CLI",
                        "powershell": "⚡ PowerShell",
                        "notification": "🔔 Benachrichtigung"
                    }
                    menu_target.set(tgt_labels_rev.get(p.get("target", "mammouth_web"), "💬 Mammouth AI Web Chat"))
                    break

        menu_presets = ctk.CTkOptionMenu(content, values=preset_names, command=on_preset_selected, width=600)
        menu_presets.pack(fill="x", pady=(2, 10))

        # Task Name
        ctk.CTkLabel(content, text="Name des Tasks:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        entry_name = ctk.CTkEntry(content, placeholder_text="z.B. ⚽ Livebericht Fußballspiel", width=600)
        entry_name.pack(fill="x", pady=(2, 10))

        # Action Prompt
        ctk.CTkLabel(content, text="Prompt / Befehl (wird bei jedem Trigger übergeben):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        txt_prompt = ctk.CTkTextbox(content, height=110, font=ctk.CTkFont(size=12))
        txt_prompt.pack(fill="x", pady=(2, 10))

        # Timing grid: Interval + Repeats + Target
        grid_frame = ctk.CTkFrame(content, fg_color="transparent")
        grid_frame.pack(fill="x", pady=(0, 10))

        # Col 1: Interval in minutes
        col1 = ctk.CTkFrame(grid_frame, fg_color="transparent")
        col1.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(col1, text="Intervall (Minuten):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        entry_interval = ctk.CTkEntry(col1)
        entry_interval.insert(0, "5.0")
        entry_interval.pack(fill="x", pady=(2, 0))

        # Col 2: Max Repeats (0 = infinite)
        col2 = ctk.CTkFrame(grid_frame, fg_color="transparent")
        col2.pack(side="left", fill="x", expand=True, padx=3)
        ctk.CTkLabel(col2, text="Wiederholungen (0 = Dauerhaft):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        entry_repeats = ctk.CTkEntry(col2)
        entry_repeats.insert(0, "20")
        entry_repeats.pack(fill="x", pady=(2, 0))

        # Col 3: Target
        col3 = ctk.CTkFrame(grid_frame, fg_color="transparent")
        col3.pack(side="left", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(col3, text="Ausführungsziel:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        target_options = [
            "💬 Mammouth AI Web Chat",
            "💻 Mammouth Code CLI",
            "⚡ PowerShell",
            "🔔 Benachrichtigung"
        ]
        menu_target = ctk.CTkOptionMenu(col3, values=target_options)
        menu_target.pack(fill="x", pady=(2, 0))

        # Checkbox: Start immediately
        chk_immediate_var = ctk.BooleanVar(value=True)
        chk_immediate = ctk.CTkCheckBox(
            content,
            text="Ersten Bericht sofort anfordern (nach 2 Sekunden, danach im Intervall)",
            variable=chk_immediate_var,
            font=ctk.CTkFont(size=12)
        )
        chk_immediate.pack(anchor="w", pady=(4, 16))

        # Apply preset if one was requested
        if preset_id:
            for p in presets:
                if p["id"] == preset_id:
                    menu_presets.set(p["name"])
                    on_preset_selected(p["name"])
                    break
        else:
            # Default to football live ticker as example!
            menu_presets.set(presets[0]["name"])
            on_preset_selected(presets[0]["name"])

        # Bottom Buttons
        btn_box = ctk.CTkFrame(content, fg_color="transparent")
        btn_box.pack(fill="x")

        def submit():
            name = entry_name.get().strip()
            prompt = txt_prompt.get("1.0", "end").strip()
            if not name:
                messagebox.showerror("Fehler", "Bitte gib einen Namen für den Task ein.", parent=dlg)
                return
            if not prompt:
                messagebox.showerror("Fehler", "Bitte gib einen Prompt ein.", parent=dlg)
                return

            try:
                interv_m = float(entry_interval.get().replace(",", "."))
                interv_sec = max(10, int(interv_m * 60))
            except ValueError:
                interv_sec = 300

            try:
                repeats = max(0, int(entry_repeats.get()))
            except ValueError:
                repeats = 0

            tgt_map = {
                "💬 Mammouth AI Web Chat": "mammouth_web",
                "💻 Mammouth Code CLI": "mammouth_code",
                "⚡ PowerShell": "powershell",
                "🔔 Benachrichtigung": "notification"
            }
            target_str = tgt_map.get(menu_target.get(), "mammouth_web")

            task = scheduler_create_task(
                name=name,
                prompt=prompt,
                interval_seconds=interv_sec,
                repeat_count=repeats,
                target=target_str,
                auto_submit=True,
                switch_tab=True,
                start_immediately=chk_immediate_var.get()
            )

            self._log(f"[TASK SCHEDULER] ✅ Neuer Task erstellt: '{name}' (Intervall: {interv_sec}s).")
            dlg.destroy()
            self._refresh_task_cards()

        ctk.CTkButton(
            btn_box,
            text="Abbrechen",
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            width=100,
            height=34,
            command=dlg.destroy
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_box,
            text="✅ Task erstellen & starten",
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            width=200,
            height=34,
            command=submit
        ).pack(side="right")

    def _count_active_tools(self) -> int:
        mods = self.config_data.get("modules", {})
        counts = {
            "memory": 5,
            "tasks_kanban": 4,
            "task_scheduler": 5,
            "file_ops": 6,
            "shell_processes": 8,
            "putty_ssh": 6,
            "system_monitor": 4,
            "web_tools": 2,
            "screen_capture": 4,
            "mammouth_code": 5,
            "desktop_input": 9,
            "google_drive": 11,
            "browser_agent": 12
        }
        total = 0
        for k, v in mods.items():
            if v.get("enabled", True):
                total += counts.get(k, 1)
        return total

    def _copy_mcp_client_config(self):
        url = self._calculate_active_endpoint_url()
        token = self.config_data.get("server", {}).get("api_token", "")
        cfg_snippet = {
            "mcpServers": {
                "MammouthDefroster9000": {
                    "url": url,
                    "headers": {
                        "Authorization": f"Bearer {token}"
                    }
                }
            }
        }
        json_str = json.dumps(cfg_snippet, indent=2)
        self.clipboard_clear()
        self.clipboard_append(json_str)
        self._log("[CLIPBOARD] Copied MCP JSON configuration snippet.")
        messagebox.showinfo("MCP JSON Config Copied", f"Copied MCP client configuration snippet to clipboard:\n\n{json_str}", parent=self)

    def _export_logs(self):
        f = filedialog.asksaveasfilename(
            title="Save Console Log",
            defaultextension=".txt",
            filetypes=[("Text Files (*.txt)", "*.txt"), ("All Files (*.*)", "*.*")]
        )
        if f:
            content = self.log_textbox.get("1.0", "end")
            Path(f).write_text(content, encoding="utf-8")
            self._log(f"[LOG] Exported console logs to: {f}")
            messagebox.showinfo("Log Saved", f"Successfully exported logs to:\n\n{f}", parent=self)

    def _open_workspace_folder(self):
        ws = (BASE_DIR / "workspace").resolve()
        ws.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(ws))
            self._log(f"[EXPLORER] Opened workspace directory: {ws}")
        except Exception as e:
            self._log(f"[ERROR] Could not open workspace: {e}")

    def _start_stats_timer(self):
        def update_stats():
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                if hasattr(self, "lbl_stat_cpu"):
                    self.lbl_stat_cpu.configure(text=f"💻 CPU: {cpu:.1f}%")
                if hasattr(self, "lbl_stat_ram"):
                    self.lbl_stat_ram.configure(text=f"🧠 RAM: {ram:.1f}%")
                if hasattr(self, "bar_cpu"):
                    self.bar_cpu.set(cpu / 100.0)
                if hasattr(self, "bar_ram"):
                    self.bar_ram.set(ram / 100.0)

                if hasattr(self, "lbl_nav_cpu"):
                    self.lbl_nav_cpu.configure(text=f"CPU: {cpu:.1f}%")
                if hasattr(self, "lbl_nav_ram"):
                    self.lbl_nav_ram.configure(text=f"RAM: {ram:.1f}%")
                if hasattr(self, "bar_nav_cpu"):
                    self.bar_nav_cpu.set(cpu / 100.0)
                if hasattr(self, "bar_nav_ram"):
                    self.bar_nav_ram.set(ram / 100.0)

                active_cnt = self._count_active_tools()
                if hasattr(self, "lbl_stat_tools"):
                    self.lbl_stat_tools.configure(text=f"⚡ {active_cnt} Tools aktiv")
                if hasattr(self, "lbl_nav_tools"):
                    self.lbl_nav_tools.configure(text=f"⚡ {active_cnt} Werkzeuge aktiv")

                if self.is_server_running and self.server_start_time:
                    elapsed = int(time.time() - self.server_start_time)
                    hrs, rem = divmod(elapsed, 3600)
                    mins, secs = divmod(rem, 60)
                    self.lbl_stat_uptime.configure(text=f"⏱️ Uptime: {hrs:02d}:{mins:02d}:{secs:02d}")
                else:
                    self.lbl_stat_uptime.configure(text="⏱️ Uptime: 00:00:00")
            except Exception:
                pass
            self.after(2000, update_stats)

        self.after(1000, update_stats)

    def _test_screenshot(self):
        try:
            # Test button is a local, user-initiated capture: no consent dialog and no global grant
            from modules.screen_capture import screen_capture_local
            res = screen_capture_local(monitor=1, save_to_workspace=True)

            saved_p = res.get("saved_path") if isinstance(res, dict) else None
            if saved_p and os.path.exists(saved_p):
                self._log(f"[VISION] Screenshot captured successfully: {saved_p}")
                os.startfile(saved_p)
            else:
                self._log(f"[VISION] Screenshot result: {res}")
        except Exception as e:
            self._log(f"[VISION ERROR] {e}")

    def _launch_mammouth_code(self):
        try:
            from modules.mammouth_code import launch_mammouth_terminal, get_mammouth_code_status
            st = get_mammouth_code_status()
            if not st.get("installed"):
                self._select_nav_tab("💻 Mammouth Code CLI")
                self._log("[MAMMOUTH CODE] CLI is not installed. Opened Mammouth Code tab for installation.")
                messagebox.showinfo("Mammouth Code Not Installed", "Mammouth Code CLI is not installed yet.\n\nPlease click 'Install Mammouth Code' in the Mammouth Code tab to set it up automatically.", parent=self)
                return

            res = launch_mammouth_terminal()
            if res.get("success"):
                term = res.get("terminal", "Terminal")
                ws = res.get("workspace", "")
                self._log(f"[MAMMOUTH CODE] 💻 Launched interactive session via {term} in '{ws}'")
            else:
                self._log(f"[MAMMOUTH CODE ERROR] {res.get('error')}")
                messagebox.showerror("Launch Error", f"Could not launch Mammouth Code:\n\n{res.get('error')}", parent=self)
        except Exception as e:
            self._log(f"[MAMMOUTH CODE ERROR] {e}")

    def _on_dash_mode_changed(self, choice: str):
        self.config_data["server"]["tunnel_mode"] = choice
        self.opt_tunnel_mode.set(choice)
        save_config(self.config_data)
        if self.is_server_running:
            port = self.config_data.get("server", {}).get("port", 8000)
            # Close whatever tunnel was exposing the port before, otherwise it stays public
            self._stop_all_tunnels()
            self._start_tunnel_for_mode(choice, port)
        self._refresh_all_endpoint_labels()
        self._log(f"Switched exposure tunnel mode to: {choice}")

    def _on_dash_path_changed(self, choice: str):
        self.config_data["server"]["endpoint_path"] = choice
        self.opt_endpoint_path.set(choice)
        save_config(self.config_data)
        self._refresh_all_endpoint_labels()
        self._log(f"Switched endpoint route path to: {choice}")

    def _calculate_active_endpoint_url(self) -> str:
        cfg = self.config_data.get("server", {})
        mode = cfg.get("tunnel_mode", "Tailscale Funnel")
        path = cfg.get("endpoint_path", "/sse")

        if mode == "Tailscale Funnel":
            ts_domain = get_tailscale_public_domain_cached(
                cfg.get("tailscale_path", ""),
                on_update=lambda: self.after(0, self._refresh_all_endpoint_labels)
            )
            if ts_domain:
                return f"{ts_domain}{path}"
            return f"https://[your-tailscale-node].ts.net{path}"

        elif mode == "Serveo (Public SSH Tunnel)":
            if self.__dict__.get("serveo_url", None):
                return f"{self.serveo_url.rstrip('/')}{path}"
            return f"https://[random].serveousercontent.com{path} (Starting...)"

        elif mode == "Cloudflare Tunnel":
            if self.dynamic_tunnel_url:
                return f"{self.dynamic_tunnel_url.rstrip('/')}{path}"
            custom_cf = cfg.get("cloudflare_custom_url", "").strip()
            if custom_cf:
                return f"{custom_cf.rstrip('/')}{path}"
            if self.is_server_running and self.__dict__.get("cf_proc", None):
                return f"https://[connecting].trycloudflare.com{path} (Starting...)"
            return f"https://[your-app].trycloudflare.com{path}"

        elif mode == "ngrok":
            if self.dynamic_tunnel_url:
                return f"{self.dynamic_tunnel_url.rstrip('/')}{path}"
            custom_ng = cfg.get("ngrok_custom_url", "").strip()
            if custom_ng:
                return f"{custom_ng.rstrip('/')}{path}"
            return f"https://[your-ngrok-id].ngrok-free.app{path}"

        elif mode == "Direct / LAN IP":
            lan_ip = get_lan_ip()
            port = cfg.get("port", 8000)
            return f"http://{lan_ip}:{port}{path}"

        elif mode == "Custom Domain":
            custom_url = cfg.get("custom_public_url", "").strip()
            if custom_url:
                return f"{custom_url.rstrip('/')}{path}"
            return f"https://mcp.yourdomain.com{path}"

        port = cfg.get("port", 8000)
        return f"http://127.0.0.1:{port}{path}"

    def _calculate_local_endpoint_url(self) -> str:
        cfg = self.config_data.get("server", {})
        port = cfg.get("port", 8000)
        path = cfg.get("endpoint_path", "/sse")
        return f"http://127.0.0.1:{port}{path}"

    def _refresh_all_endpoint_labels(self):
        self.lbl_public_url.configure(text=self._calculate_active_endpoint_url())
        self.lbl_local_url.configure(text=self._calculate_local_endpoint_url())
        if hasattr(self, "lbl_dash_key"):
            cur_tok = self.config_data.get("server", {}).get("api_token", "")
            if getattr(self, "dash_token_visible", False):
                self.lbl_dash_key.configure(text=cur_tok if cur_tok else "(No Key Generated)")
            else:
                self.lbl_dash_key.configure(text="•" * 28 if cur_tok else "(No Key Generated)")

    def _toggle_dash_key_visibility(self):
        self.dash_token_visible = not getattr(self, "dash_token_visible", False)
        cur_tok = self.config_data.get("server", {}).get("api_token", "")
        if self.dash_token_visible:
            self.lbl_dash_key.configure(text=cur_tok if cur_tok else "(No Key Generated)")
            self.btn_toggle_dash_key.configure(text="🔒 Hide Key")
        else:
            self.lbl_dash_key.configure(text="•" * 28 if cur_tok else "(No Key Generated)")
            self.btn_toggle_dash_key.configure(text="👁️ Show Key")

    def _manual_detect_url(self):
        cfg = self.config_data.get("server", {})
        mode = cfg.get("tunnel_mode", "Tailscale Funnel")
        
        if mode == "Tailscale Funnel":
            self._log("[DISCOVERY] Querying local Tailscale daemon for domain name...")
            domain = get_tailscale_public_domain(cfg.get("tailscale_path", ""))
            if domain:
                self._log(f"[DISCOVERY] Successfully detected Tailscale domain: {domain}")
                self._refresh_all_endpoint_labels()
                messagebox.showinfo("Tailscale Discovered", f"Successfully detected your Tailscale domain:\n\n{domain}", parent=self)
            else:
                self._log("[DISCOVERY WARNING] Could not detect active Tailscale domain.")
                messagebox.showwarning("Tailscale Not Found", "Could not detect active Tailscale node.\n\nMake sure Tailscale is running and connected.", parent=self)
        
        elif mode == "Cloudflare Tunnel":
            url = self.__dict__.get("dynamic_tunnel_url", None)
            if url:
                self._refresh_all_endpoint_labels()
                messagebox.showinfo("Cloudflare Tunnel Discovered", f"Cloudflare Tunnel is active:\n\n{url}", parent=self)
            elif self.is_server_running:
                cf_bin = find_cloudflared_binary(cfg.get("cloudflared_path", ""))
                if not cf_bin:
                    messagebox.showwarning("cloudflared Not Found", "Could not locate cloudflared binary.\n\nPlease place cloudflared.exe in the app directory or ensure it is on PATH.", parent=self)
                else:
                    self._log(f"[DISCOVERY] Found cloudflared at: {cf_bin}. Connecting Cloudflare tunnel now...")
                    port = cfg.get("port", 8000)
                    self._start_cloudflare_tunnel(port)
                    messagebox.showinfo("Cloudflare Tunnel Starting", f"Located cloudflared at:\n{cf_bin}\n\nConnecting quick tunnel in the background. The Public URL will update automatically once established.", parent=self)
            else:
                cf_bin = find_cloudflared_binary(cfg.get("cloudflared_path", ""))
                status = f"cloudflared found at:\n{cf_bin}" if cf_bin else "cloudflared.exe not found on system."
                messagebox.showinfo("Cloudflare Tunnel", f"{status}\n\nClick '▶ START SERVER' on the left to start the server and connect the Cloudflare tunnel.", parent=self)

        elif mode in ("Serveo (Public SSH Tunnel)", "ngrok"):
            url = self.__dict__.get("dynamic_tunnel_url", None)
            if url:
                self._refresh_all_endpoint_labels()
                messagebox.showinfo(f"{mode} Discovered", f"{mode} is active:\n\n{url}", parent=self)
            elif self.is_server_running:
                port = cfg.get("port", 8000)
                if mode == "Serveo (Public SSH Tunnel)":
                    self._start_serveo_tunnel(port)
                else:
                    self._start_ngrok_tunnel(port)
                messagebox.showinfo(f"{mode} Starting", f"Connecting {mode} in background. The Public URL will update shortly.", parent=self)
            else:
                messagebox.showinfo(f"{mode}", f"Click '▶ START SERVER' on the left to start the server and connect {mode}.", parent=self)
                
        else:
            self._refresh_all_endpoint_labels()
            messagebox.showinfo("URL Refreshed", f"Refreshed URL display for mode: {mode}", parent=self)

    def _copy_to_clipboard(self, text: str, label_name: str = "Item"):
        if text and text.startswith("dpapi:"):
            try:
                decrypted = _decrypt_dpapi(text)
                if decrypted and not decrypted.startswith("dpapi:"):
                    text = decrypted
            except Exception:
                pass
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log(f"[CLIPBOARD] Copied {label_name} to clipboard: {text}")
        messagebox.showinfo("Copied to Clipboard", f"Copied {label_name} to clipboard:\n\n{text}", parent=self)

    _LOG_MAX_LINES = 5000
    _LOG_FLUSH_MS = 150

    def _log(self, message: str):
        """Thread-safe console logging.

        Tk widgets must only be touched from the main thread, so every caller (tunnel threads,
        uvicorn, scheduler workers) just enqueues the line; the main thread flushes the queue in
        batches every 150 ms and caps the console at _LOG_MAX_LINES lines.
        """
        clean_msg = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(message))
        clean_msg = redact_secrets(clean_msg)
        timestamp = time.strftime("[%H:%M:%S]")
        queue_ = self.__dict__.get("_log_queue")
        if queue_ is None:
            import queue as _queue_mod
            queue_ = self.__dict__.setdefault("_log_queue", _queue_mod.SimpleQueue())
        queue_.put(f"{timestamp} {clean_msg}\n")
        if threading.current_thread() is threading.main_thread():
            self._flush_log_queue()

    def _flush_log_queue(self):
        queue_ = self.__dict__.get("_log_queue")
        if queue_ is None or not hasattr(self, "log_textbox"):
            self._schedule_log_flush()
            return
        lines = []
        try:
            while True:
                lines.append(queue_.get_nowait())
        except Exception:
            pass
        if lines:
            try:
                self.log_textbox.insert("end", "".join(lines))
                line_count = int(self.log_textbox.index("end-1c").split(".")[0])
                if line_count > self._LOG_MAX_LINES:
                    self.log_textbox.delete("1.0", f"{line_count - self._LOG_MAX_LINES}.0")
                self.log_textbox.see("end")
            except Exception:
                pass
        self._schedule_log_flush()

    def _schedule_log_flush(self):
        # Single recurring pump on the Tk thread that drains lines queued by background threads
        if not self.__dict__.get("_log_pump_active"):
            self.__dict__["_log_pump_active"] = True

            def _pump():
                self.__dict__["_log_pump_active"] = False
                self._flush_log_queue()

            self.after(self._LOG_FLUSH_MS, _pump)

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")
        self._log("Console cleared.")

    # ---------------------------------------------------------
    # TAB: MAMMOUTH CODE CLI AGENT
    # ---------------------------------------------------------
    def _setup_mammouth_code_tab(self):
        top_bar = ctk.CTkFrame(self.tab_mammouth_code, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(
            title_box,
            text="💻 Mammouth Code Terminal Agent",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=THEME_TEXT_PRIMARY
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Offizieller Terminal-basierter AI Coding-Agent von Mammouth AI (Fork von OpenCode)",
            font=ctk.CTkFont(size=12),
            text_color=THEME_TEXT_MUTED
        ).pack(anchor="w")

        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right")

        self.btn_mc_refresh = ctk.CTkButton(
            btn_box,
            text="🔄 Status prüfen",
            width=120,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._refresh_mammouth_code_status
        )
        self.btn_mc_refresh.pack(side="left", padx=(0, 8))

        self.btn_mc_sync = ctk.CTkButton(
            btn_box,
            text="🔗 Defroster MCP verknüpfen",
            width=190,
            height=32,
            fg_color=THEME_ACCENT,
            hover_color=THEME_ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._sync_mammouth_code_mcp
        )
        self.btn_mc_sync.pack(side="left")

        mc_scroll = ctk.CTkScrollableFrame(self.tab_mammouth_code, fg_color="transparent")
        mc_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # CARD 1: Status & Quick Installer
        card_status = ctk.CTkFrame(mc_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        card_status.pack(fill="x", pady=6)

        c1_inner = ctk.CTkFrame(card_status, fg_color="transparent")
        c1_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(c1_inner, text="STATUS & INSTALLATION", font=ctk.CTkFont(size=12, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 4))

        status_row = ctk.CTkFrame(c1_inner, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 6))

        self.lbl_mc_status = ctk.CTkLabel(
            status_row,
            text="Prüfe Installation...",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#475569", "#CBD5E1")
        )
        self.lbl_mc_status.pack(side="left")

        self.btn_mc_install = ctk.CTkButton(
            status_row,
            text="⚡ Installieren / Aktualisieren",
            width=200,
            height=30,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._install_mammouth_code_bg
        )
        self.btn_mc_install.pack(side="right")

        self.lbl_mc_path = ctk.CTkLabel(
            c1_inner,
            text="Pfad: -",
            font=ctk.CTkFont(size=11),
            text_color=THEME_TEXT_MUTED
        )
        self.lbl_mc_path.pack(anchor="w")

        self.lbl_mc_bridge = ctk.CTkLabel(
            c1_inner,
            text="MCP Bridge: -",
            font=ctk.CTkFont(size=11),
            text_color=THEME_TEXT_MUTED
        )
        self.lbl_mc_bridge.pack(anchor="w")

        # CARD 2: Interactive Terminal Launcher
        card_launch = ctk.CTkFrame(mc_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        card_launch.pack(fill="x", pady=6)

        c2_inner = ctk.CTkFrame(card_launch, fg_color="transparent")
        c2_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(c2_inner, text="INTERAKTIVES TERMINAL LAUNCHEN", font=ctk.CTkFont(size=12, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(c2_inner, text="Startet ein sichtbares Konsolenfenster direkt in deinem ausgewählten Projektordner mit gesetzten Umgebungsvariablen.", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 8))

        ws_row = ctk.CTkFrame(c2_inner, fg_color="transparent")
        ws_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(ws_row, text="Workspace Ordner:", width=130, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
        default_ws = self.config_data.get("server", {}).get("workspace_root", "./workspace")
        if not os.path.isabs(default_ws):
            default_ws = str((BASE_DIR / default_ws).resolve())

        self.ent_mc_ws = ctk.CTkEntry(ws_row, height=32)
        self.ent_mc_ws.insert(0, default_ws)
        self.ent_mc_ws.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse_ws = ctk.CTkButton(
            ws_row,
            text="📁 Durchsuchen",
            width=110,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            command=self._browse_mc_workspace
        )
        btn_browse_ws.pack(side="right")

        opts_row = ctk.CTkFrame(c2_inner, fg_color="transparent")
        opts_row.pack(fill="x", pady=(4, 8))

        self.chk_mc_continue = ctk.CTkCheckBox(
            opts_row,
            text="Letzte Session in diesem Projektordner fortsetzen (-c)",
            font=ctk.CTkFont(size=12)
        )
        self.chk_mc_continue.pack(side="left")

        ctk.CTkLabel(opts_row, text="Terminal:", font=ctk.CTkFont(size=12, weight="bold"), text_color=THEME_TEXT_MUTED).pack(side="left", padx=(20, 6))
        self.opt_mc_term = ctk.CTkOptionMenu(
            opts_row,
            values=["PowerShell Console", "Windows Terminal (wt)"],
            width=175,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_ACCENT,
            button_hover_color=THEME_ACCENT_HOVER,
            text_color=THEME_TEXT_PRIMARY,
        )
        self.opt_mc_term.set("PowerShell Console")
        self.opt_mc_term.pack(side="left")

        btn_term_launch = ctk.CTkButton(
            c2_inner,
            text="▶ Interaktives Terminal öffnen",
            height=36,
            fg_color=THEME_ACCENT,
            hover_color=THEME_ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._launch_mc_terminal_from_tab
        )
        btn_term_launch.pack(fill="x", pady=(4, 0))

        # CARD 3: Headless Task Execution (mammouth run)
        card_headless = ctk.CTkFrame(mc_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        card_headless.pack(fill="x", pady=6)

        c3_inner = ctk.CTkFrame(card_headless, fg_color="transparent")
        c3_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(c3_inner, text="HEADLESS TASK RUNNER (mammouth run)", font=ctk.CTkFont(size=12, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(c3_inner, text="Übergib Coding-Aufgaben direkt an Mammouth Code im Hintergrund. Ausgabe erscheint live im Fenster unten.", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 8))

        self.txt_mc_prompt = ctk.CTkTextbox(c3_inner, height=70, font=ctk.CTkFont(size=12))
        self.txt_mc_prompt.pack(fill="x", pady=(0, 6))

        h_controls = ctk.CTkFrame(c3_inner, fg_color="transparent")
        h_controls.pack(fill="x", pady=(0, 6))

        self.chk_mc_auto = ctk.CTkCheckBox(h_controls, text="Berechtigungen auto-bestätigen (--auto)", font=ctk.CTkFont(size=12))
        self.chk_mc_auto.select()
        self.chk_mc_auto.pack(side="left")

        self.btn_mc_run = ctk.CTkButton(
            h_controls,
            text="🚀 Headless Task ausführen",
            width=200,
            height=32,
            fg_color=THEME_ACCENT,
            hover_color=THEME_ACCENT_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._run_mc_headless_task_bg
        )
        self.btn_mc_run.pack(side="right")

        self.txt_mc_console = ctk.CTkTextbox(
            c3_inner,
            height=140,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("#0F172A", "#1E1E24"),
            text_color=("#F8FAFC", "#E2E8F0")
        )
        self.txt_mc_console.pack(fill="x", pady=(4, 0))

        # CARD 4: API Key & Configuration
        card_cfg = ctk.CTkFrame(mc_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        card_cfg.pack(fill="x", pady=6)

        c4_inner = ctk.CTkFrame(card_cfg, fg_color="transparent")
        c4_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(c4_inner, text="AUTHENTIFIZIERUNG & EINSTELLUNGEN", font=ctk.CTkFont(size=12, weight="bold"), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(c4_inner, text="Der Mammouth API-Key wird via Windows DPAPI hardware-verschlüsselt und automatisch an Mammouth Code übergeben.", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(anchor="w", pady=(0, 8))

        key_row = ctk.CTkFrame(c4_inner, fg_color="transparent")
        key_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(key_row, text="MAMMOUTH_API_KEY:", width=150, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")

        current_key = self.config_data.get("mammouth_code", {}).get("api_key", "")
        self.ent_mc_key = ctk.CTkEntry(key_row, show="*", height=32)
        if current_key:
            self.ent_mc_key.insert(0, current_key)
        self.ent_mc_key.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_mc_show_key = ctk.CTkButton(
            key_row,
            text="👁️",
            width=40,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            command=self._toggle_mc_key_visibility
        )
        self.btn_mc_show_key.pack(side="left", padx=(0, 8))

        btn_save_key = ctk.CTkButton(
            key_row,
            text="💾 Speichern (DPAPI)",
            width=160,
            height=32,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._save_mc_api_key
        )
        btn_save_key.pack(side="right")

        # Initial background status query
        self.after(500, self._refresh_mammouth_code_status)

    def _refresh_mammouth_code_status(self):
        try:
            from modules.mammouth_code import get_mammouth_code_status
            st = get_mammouth_code_status()
            if st.get("installed"):
                ver = st.get("version", "Installed")
                self.lbl_mc_status.configure(
                    text=f"🟢 Mammouth Code: Installiert ({ver})",
                    text_color=("#059669", "#10B981")
                )
                self.btn_mc_install.configure(text="⚡ Upgraden (mammouth upgrade)")
            else:
                self.lbl_mc_status.configure(
                    text="🔴 Mammouth Code: Nicht installiert",
                    text_color=("#DC2626", "#EF4444")
                )
                self.btn_mc_install.configure(text="⚡ Installieren (PowerShell)")

            p = st.get("executable_path", "-") or "-"
            self.lbl_mc_path.configure(text=f"Executable: {p}")

            if st.get("mcp_bridge_synced"):
                self.lbl_mc_bridge.configure(
                    text="MCP Bridge: 🟢 Verbunden (mammouth-defroster-9000 aktiv in opencode.json)",
                    text_color=("#059669", "#10B981")
                )
            else:
                self.lbl_mc_bridge.configure(
                    text="MCP Bridge: ⚪ Noch nicht synchronisiert (Klicke oben auf 'Defroster MCP verknüpfen')",
                    text_color=THEME_TEXT_MUTED
                )
        except Exception as ex:
            self._log(f"[MAMMOUTH CODE] Status refresh failed: {ex}")

    def _browse_mc_workspace(self):
        folder = filedialog.askdirectory(title="Projektordner für Mammouth Code auswählen", parent=self)
        if folder:
            self.ent_mc_ws.delete(0, "end")
            self.ent_mc_ws.insert(0, folder)

    def _launch_mc_terminal_from_tab(self):
        ws = self.ent_mc_ws.get().strip()
        cont = bool(self.chk_mc_continue.get())
        pref = self.opt_mc_term.get() if hasattr(self, "opt_mc_term") else "PowerShell"
        pref_term = "wt" if "Windows Terminal" in pref else "powershell"
        from modules.mammouth_code import launch_mammouth_terminal
        res = launch_mammouth_terminal(workspace_path=ws, continue_session=cont, preferred_terminal=pref_term)
        if res.get("success"):
            self._log(f"[MAMMOUTH CODE] 💻 Launched {res.get('terminal')} in '{res.get('workspace')}' (resumed={cont})")
        else:
            self._log(f"[MAMMOUTH CODE ERROR] {res.get('error')}")
            messagebox.showerror("Fehler beim Starten", f"Mammouth Code konnte nicht gestartet werden:\n\n{res.get('error')}", parent=self)

    def _install_mammouth_code_bg(self):
        self.btn_mc_install.configure(text="⏳ Wird ausgeführt...", state="disabled")
        self._log("[MAMMOUTH CODE] Installation / Upgrade gestartet...")

        def _worker():
            from modules.mammouth_code import install_or_update_mammouth_code
            res = install_or_update_mammouth_code()
            def _done():
                self.btn_mc_install.configure(state="normal")
                self._refresh_mammouth_code_status()
                if res.get("success"):
                    self._log(f"[MAMMOUTH CODE] ✓ {res.get('action').capitalize()} erfolgreich abgeschlossen ({res.get('duration_seconds')}s)!")
                    messagebox.showinfo("Mammouth Code", f"Mammouth Code wurde erfolgreich eingerichtet!\n\nPfad: {res.get('path')}", parent=self)
                else:
                    self._log(f"[MAMMOUTH CODE ERROR] Installation fehlgeschlagen: {res.get('stderr')}")
                    messagebox.showerror("Fehler", f"Installation fehlgeschlagen:\n\n{res.get('stderr')}", parent=self)
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_mc_headless_task_bg(self):
        prompt = self.txt_mc_prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Leerer Prompt", "Bitte gib eine Aufgabe für Mammouth Code ein.", parent=self)
            return

        ws = self.ent_mc_ws.get().strip()
        auto_appr = bool(self.chk_mc_auto.get())

        self.btn_mc_run.configure(text="⏳ Task läuft...", state="disabled")
        self.txt_mc_console.delete("1.0", "end")
        self.txt_mc_console.insert("end", f"🚀 Starte Task in {ws}...\nPrompt: {prompt}\n\n")
        self._log(f"[MAMMOUTH CODE] Headless task gestartet: '{prompt[:40]}...'")

        def _worker():
            from modules.mammouth_code import run_mammouth_task
            res = run_mammouth_task(prompt, workspace_path=ws, auto_approve=auto_appr)
            def _done():
                self.btn_mc_run.configure(text="🚀 Headless Task ausführen", state="normal")
                if res.get("success"):
                    self.txt_mc_console.insert("end", f"✓ Task erfolgreich abgeschlossen ({res.get('duration_seconds')}s):\n\n")
                    self.txt_mc_console.insert("end", res.get("output", "") + "\n")
                    self._log(f"[MAMMOUTH CODE] Task erfolgreich beendet ({res.get('duration_seconds')}s)")
                else:
                    self.txt_mc_console.insert("end", f"❌ Fehler (Returncode {res.get('returncode')}):\n\n")
                    self.txt_mc_console.insert("end", res.get("error", "") + "\n")
                    if res.get("output"):
                        self.txt_mc_console.insert("end", res.get("output") + "\n")
                    self._log(f"[MAMMOUTH CODE ERROR] Task fehlgeschlagen: {res.get('error')}")
                self.txt_mc_console.see("end")
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _sync_mammouth_code_mcp(self):
        url = self._calculate_active_endpoint_url()
        tok = self.config_data.get("server", {}).get("api_token", "")
        ws = self.ent_mc_ws.get().strip()
        from modules.mammouth_code import sync_opencode_mcp_config
        res = sync_opencode_mcp_config(workspace_path=ws, server_url=url, api_token=tok)
        if res.get("success"):
            cfgs = "\n".join(res.get("updated_configs", []))
            self._log(f"[MAMMOUTH CODE] MCP Bridge synchronisiert mit: {url}")
            messagebox.showinfo(
                "MCP Bridge Synchronisiert",
                f"Mammouth Defroster 9000 wurde erfolgreich als MCP Server für Mammouth Code registriert!\n\nAktualisierte Konfigurationen:\n{cfgs}\n\nMammouth Code verfügt jetzt über alle Defroster-Fähigkeiten (Vision, Systemdiagnose, Speicher, etc.)!",
                parent=self
            )
            self._refresh_mammouth_code_status()
        else:
            messagebox.showerror("Fehler", "MCP-Konfiguration konnte nicht aktualisiert werden.", parent=self)

    def _toggle_mc_key_visibility(self):
        cur = self.ent_mc_key.cget("show")
        if cur == "*":
            self.ent_mc_key.configure(show="")
            self.btn_mc_show_key.configure(text="🔒")
        else:
            self.ent_mc_key.configure(show="*")
            self.btn_mc_show_key.configure(text="👁️")

    def _save_mc_api_key(self):
        key = self.ent_mc_key.get().strip()
        if "mammouth_code" not in self.config_data:
            self.config_data["mammouth_code"] = {}
        self.config_data["mammouth_code"]["api_key"] = key
        saved = save_config(self.config_data)
        if saved:
            self._log("[SECURITY] Mammouth API-Key per Windows DPAPI hardware-verschlüsselt in config.json gesichert.")
            messagebox.showinfo("Gespeichert", "Mammouth API-Key wurde sicher per Windows DPAPI verschlüsselt gespeichert!", parent=self)
            self._refresh_mammouth_code_status()
        else:
            messagebox.showerror("Fehler", "Konfiguration konnte nicht gespeichert werden.", parent=self)

    # ---------------------------------------------------------
    # TAB 2: SKILLS & MODULES
    # ---------------------------------------------------------
    def _setup_skills_tab(self):
        top_bar = ctk.CTkFrame(self.tab_skills, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="⚡ Modular Defroster Capabilities", font=ctk.CTkFont(size=17, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Toggle individual tools dynamically exposed to Mammouth AI / connected models", font=ctk.CTkFont(size=12), text_color=("#475569", "#9CA3AF")).pack(anchor="w")

        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right")

        btn_enable_safe = ctk.CTkButton(
            btn_box,
            text="✅ Enable Safe Tools",
            width=140,
            height=32,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._enable_safe_skills
        )
        btn_enable_safe.pack(side="left", padx=5)

        btn_save_skills = ctk.CTkButton(
            btn_box,
            text="💾 Save Modules",
            width=130,
            height=32,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._save_skills
        )
        btn_save_skills.pack(side="left")

        scroll = ctk.CTkScrollableFrame(self.tab_skills, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self.module_switches = {}
        modules = self.config_data.get("modules", {})

        icons = {
            "memory": "🧠",
            "tasks_kanban": "📋",
            "task_scheduler": "⏱️",
            "file_ops": "📁",
            "shell_processes": "💻",
            "putty_ssh": "🔑",
            "system_monitor": "📊",
            "web_tools": "🌐",
            "screen_capture": "👁️",
            "mammouth_code": "💻",
            "desktop_input": "🖱️",
            "google_drive": "☁️",
            "browser_agent": "🌐"
        }

        tool_counts = {
            "memory": "5 Tools",
            "tasks_kanban": "4 Tools",
            "task_scheduler": "5 Tools (Automated Triggers)",
            "file_ops": "6 Tools",
            "shell_processes": "8 Tools (Privileged)",
            "putty_ssh": "6 Tools",
            "system_monitor": "4 Tools",
            "web_tools": "2 Tools (SSRF Shield)",
            "screen_capture": "4 Tools (Vision Gate)",
            "mammouth_code": "5 Tools (Agent Bridge)",
            "desktop_input": "9 Tools",
            "google_drive": "11 Tools (Cloud & Docs)",
            "browser_agent": "12 Tools (Edge / Playwright)"
        }

        for key, mod in modules.items():
            card = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=12, fill="x", expand=True)

            icon = icons.get(key, "⚙️")
            cnt = tool_counts.get(key, "Tools")
            
            title_row = ctk.CTkFrame(left, fg_color="transparent")
            title_row.pack(anchor="w")

            disp_name = f"{icon}  {mod.get('name', key)}"

            lbl_name = ctk.CTkLabel(title_row, text=disp_name, font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME_TEXT_PRIMARY)
            lbl_name.pack(side="left")

            badge_cnt = ctk.CTkFrame(title_row, fg_color=("#F1F5F9", "#1E2028"), border_width=1, border_color=THEME_CARD_BORDER, corner_radius=5)
            badge_cnt.pack(side="left", padx=6)
            ctk.CTkLabel(badge_cnt, text=f" {cnt} ", font=ctk.CTkFont(size=11), text_color=THEME_TEXT_MUTED).pack(padx=4, pady=1)

            lbl_desc = ctk.CTkLabel(left, text=mod.get("description", ""), font=ctk.CTkFont(size=12), text_color=THEME_TEXT_MUTED, anchor="w")
            lbl_desc.pack(anchor="w", pady=(4, 0))

            if key == "screen_capture":
                sub_opts = ctk.CTkFrame(left, fg_color=THEME_INPUT_BG, corner_radius=6)
                sub_opts.pack(fill="x", pady=(8, 0))

                self.var_screen_req_consent = ctk.BooleanVar(value=mod.get("require_consent", True))
                sw_consent = ctk.CTkSwitch(
                    sub_opts,
                    text="🔒 Require Consent",
                    variable=self.var_screen_req_consent,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=("#0F172A", "#E5E7EB"),
                    progress_color="#F59E0B",
                    command=self._on_screen_consent_toggled
                )
                sw_consent.pack(side="left", padx=10, pady=6)

                self.btn_ui_grant_consent = ctk.CTkButton(
                    sub_opts,
                    text="🔓 Grant Session Consent",
                    width=175,
                    height=26,
                    fg_color=("#059669", "#10B981"),
                    hover_color=("#047857", "#059669"),
                    text_color="#FFFFFF",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self._on_ui_grant_session_consent
                )
                self.btn_ui_grant_consent.pack(side="left", padx=10, pady=6)

                self.lbl_consent_badge = ctk.CTkLabel(
                    sub_opts,
                    text="● Status: Pending Consent" if self.var_screen_req_consent.get() else "● Status: Always Allowed",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#F59E0B" if self.var_screen_req_consent.get() else "#10B981"
                )
                self.lbl_consent_badge.pack(side="left", padx=10, pady=6)

            elif key == "shell_processes":
                sub_opts = ctk.CTkFrame(left, fg_color=THEME_INPUT_BG, corner_radius=6)
                sub_opts.pack(fill="x", pady=(8, 0))
                self.var_admin_shell = ctk.BooleanVar(value=self.config_data.get("server", {}).get("allow_admin_shell", False))
                sw_admin_shell = ctk.CTkSwitch(
                    sub_opts,
                    text="⚡ Admin / Modifizierend (Vollzugriff)" if self.var_admin_shell.get() else "🔒 Nur Diagnose & Read-Only",
                    variable=self.var_admin_shell,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=("#0F172A", "#E5E7EB"),
                    progress_color="#EF4444",
                    command=self._on_admin_shell_toggle
                )
                sw_admin_shell.pack(side="left", padx=10, pady=6)
                self.sw_admin_shell = sw_admin_shell
                self.lbl_admin_shell_hint = ctk.CTkLabel(
                    sub_opts,
                    text="Get-*/ipconfig only  vs  Set-*/Remove-*/sc/schtasks",
                    font=ctk.CTkFont(size=11),
                    text_color=THEME_TEXT_MUTED
                )
                self.lbl_admin_shell_hint.pack(side="left", padx=10, pady=6)

            elif key == "google_drive":
                sub_opts = ctk.CTkFrame(left, fg_color=THEME_INPUT_BG, corner_radius=6)
                sub_opts.pack(fill="x", pady=(8, 0))

                # The real status needs a network call; it is filled in from a worker thread.
                is_auth = False
                status_text = "● Checking..."
                status_color = "#94A3B8"

                self.lbl_gdrive_status = ctk.CTkLabel(
                    sub_opts,
                    text=status_text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=status_color
                )
                self.lbl_gdrive_status.pack(side="left", padx=10, pady=6)

                self.btn_gdrive_connect = ctk.CTkButton(
                    sub_opts,
                    text="🔑 Connect Google Drive" if not is_auth else "🔄 Re-authenticate",
                    width=170,
                    height=26,
                    fg_color=("#059669", "#10B981"),
                    hover_color=("#047857", "#059669"),
                    text_color="#FFFFFF",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self._on_gdrive_connect
                )
                self.btn_gdrive_connect.pack(side="left", padx=10, pady=6)
                self._refresh_gdrive_status_async()

                btn_gdrive_creds = ctk.CTkButton(
                    sub_opts,
                    text="📂 Select credentials.json",
                    width=165,
                    height=26,
                    fg_color=THEME_BTN_SEC_BG,
                    hover_color=THEME_BTN_SEC_HOVER,
                    text_color=THEME_TEXT_PRIMARY,
                    font=ctk.CTkFont(size=11),
                    border_width=1,
                    border_color=THEME_BTN_SEC_BORDER,
                    command=self._on_gdrive_browse_credentials
                )
                btn_gdrive_creds.pack(side="left", padx=5, pady=6)

                btn_gdrive_disconnect = ctk.CTkButton(
                    sub_opts,
                    text="🔌 Disconnect",
                    width=100,
                    height=26,
                    fg_color=("#EF4444", "#DC2626"),
                    hover_color=("#B91C1C", "#991B1B"),
                    text_color="#FFFFFF",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self._on_gdrive_disconnect
                )
                btn_gdrive_disconnect.pack(side="left", padx=5, pady=6)

            elif key == "browser_agent":
                sub_opts = ctk.CTkFrame(left, fg_color=THEME_INPUT_BG, corner_radius=6)
                sub_opts.pack(fill="x", pady=(8, 0))

                b_cfg = self.config_data.get("browser_agent", {})
                self.var_browser_agent_headless = ctk.BooleanVar(value=b_cfg.get("headless", False))

                sw_headless = ctk.CTkSwitch(
                    sub_opts,
                    text="🕶️ Headless (Hintergrund)" if self.var_browser_agent_headless.get() else "👁️ Sichtbares Fenster",
                    variable=self.var_browser_agent_headless,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=THEME_TEXT_PRIMARY,
                    progress_color=THEME_ACCENT,
                    command=self._on_browser_agent_headless_toggle
                )
                sw_headless.pack(side="left", padx=10, pady=6)
                self.sw_browser_agent_headless = sw_headless

                btn_start_browser = ctk.CTkButton(
                    sub_opts,
                    text="🚀 Browser starten",
                    width=130,
                    height=26,
                    fg_color=THEME_BTN_SEC_BG,
                    hover_color=THEME_BTN_SEC_HOVER,
                    border_width=1,
                    border_color=THEME_BTN_SEC_BORDER,
                    text_color=THEME_TEXT_PRIMARY,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self._on_browser_agent_launch
                )
                btn_start_browser.pack(side="left", padx=5, pady=6)

                btn_close_browser = ctk.CTkButton(
                    sub_opts,
                    text="⏹️ Schließen",
                    width=100,
                    height=26,
                    fg_color=("#EF4444", "#DC2626"),
                    hover_color=("#B91C1C", "#991B1B"),
                    text_color="#FFFFFF",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=self._on_browser_agent_close
                )
                btn_close_browser.pack(side="left", padx=5, pady=6)

            right_ctrl = ctk.CTkFrame(card, fg_color="transparent")
            right_ctrl.pack(side="right", padx=20, pady=12)

            switch_var = ctk.BooleanVar(value=mod.get("enabled", True))
            switch = ctk.CTkSwitch(
                right_ctrl,
                text="Active",
                variable=switch_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=("#0F172A", "#E5E7EB"),
                progress_color="#10B981"
            )
            switch.pack(side="right")

            self.module_switches[key] = switch_var

    def _on_screen_consent_toggled(self):
        val = self.var_screen_req_consent.get()
        self.config_data.setdefault("modules", {}).setdefault("screen_capture", {})["require_consent"] = val
        save_config(self.config_data)
        if hasattr(self, "var_settings_screen_consent"):
            self.var_settings_screen_consent.set(val)
        if hasattr(self, "lbl_consent_badge"):
            if val:
                self.lbl_consent_badge.configure(text="● Status: Pending Consent", text_color="#F59E0B")
            else:
                self.lbl_consent_badge.configure(text="● Status: Always Allowed", text_color="#10B981")
        self._log(f"[SECURITY] Screen capture 'require_consent' toggled to {val}.")

    def _on_browser_agent_headless_toggle(self):
        val = self.var_browser_agent_headless.get()
        if hasattr(self, "sw_browser_agent_headless"):
            self.sw_browser_agent_headless.configure(text="🕶️ Headless (Hintergrund)" if val else "👁️ Sichtbares Fenster")
        self.config_data.setdefault("browser_agent", {})["headless"] = val
        save_config(self.config_data)
        try:
            from modules.browser_agent import init_browser_agent
            init_browser_agent(self.config_data.get("browser_agent", {}))
        except Exception as e:
            self._log(f"[BROWSER AGENT] Config update: {e}")

    def _on_browser_agent_launch(self):
        try:
            from modules.browser_agent import init_browser_agent, browser_navigate
            init_browser_agent(self.config_data.get("browser_agent", {}))
            threading.Thread(target=lambda: browser_navigate("about:blank"), daemon=True).start()
            self._log("[BROWSER AGENT] Automated browser launched.")
            messagebox.showinfo("Browser Agent", "Automated browser started successfully!\n\nControlled by Mammouth Defroster MCP.", parent=self)
        except Exception as e:
            messagebox.showerror("Browser Error", f"Failed to launch browser: {e}", parent=self)

    def _on_browser_agent_close(self):
        try:
            from modules.browser_agent import browser_close
            threading.Thread(target=browser_close, daemon=True).start()
            self._log("[BROWSER AGENT] Automated browser closed.")
        except Exception as e:
            self._log(f"[BROWSER AGENT] Error closing browser: {e}")

    def _on_ui_grant_session_consent(self):
        from modules.screen_capture import screen_grant_consent
        screen_grant_consent("always")
        if hasattr(self, "lbl_consent_badge"):
            self.lbl_consent_badge.configure(text="● Status: Granted (Session)", text_color="#10B981")
        if hasattr(self, "btn_ui_grant_consent"):
            self.btn_ui_grant_consent.configure(text="✅ Consent Active", fg_color="#047857")
        self._log("[SECURITY] Explicit screen capture consent GRANTED for current session.")
        messagebox.showinfo("Consent Granted", "Screen capture permission has been granted for this session.\n\nConnected AI assistants and MCP clients can now capture screenshots.", parent=self)

    def _prompt_screen_capture_consent(self) -> str:
        """Thread-safe user prompt when incoming MCP screen capture requests consent."""
        import threading
        result = ["denied"]
        expired = [False]
        event = threading.Event()

        def ask():
            if expired[0]:
                # The MCP request already timed out before the dialog could be shown
                event.set()
                return
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
                ans = messagebox.askyesno(
                    "Desktop Screen Capture Request",
                    "A connected AI assistant / MCP client (e.g. Mammouth.ai) is requesting a screenshot of your desktop.\n\n"
                    "Do you want to grant screen capture permission for this session?",
                    parent=self
                )
                if expired[0]:
                    # Answer arrived after the request timed out: ignore it, consent was not granted
                    self._log("[VISION] Consent dialog answered after the request timed out — ignored.")
                elif ans:
                    result[0] = "always"
                    self._log("[VISION] Screen capture permission GRANTED by user via dialog.")
                    if hasattr(self, "lbl_consent_badge"):
                        self.lbl_consent_badge.configure(text="● Status: Granted (Session)", text_color="#10B981")
                    if hasattr(self, "btn_ui_grant_consent"):
                        self.btn_ui_grant_consent.configure(text="✅ Consent Active", fg_color="#047857")
                else:
                    result[0] = "denied"
                    self._log("[VISION] Screen capture permission DENIED by user.")
            except Exception as e:
                self._log(f"[VISION ERROR] Prompt dialog error: {e}")
            finally:
                event.set()

        if threading.current_thread() is threading.main_thread():
            # Called on the Tk thread: queuing via after() and waiting would deadlock the mainloop
            ask()
            return result[0]

        self.after(0, ask)
        if not event.wait(timeout=30):
            expired[0] = True
            return "denied"
        return result[0]

    def _enable_safe_skills(self):
        for k, v in self.module_switches.items():
            if k == "shell_processes":
                v.set(False)
            else:
                v.set(True)
        self._save_skills()

    def _save_skills(self):
        for key, var in self.module_switches.items():
            if key in self.config_data["modules"]:
                self.config_data["modules"][key]["enabled"] = var.get()

        if hasattr(self, "var_screen_req_consent"):
            self.config_data.setdefault("modules", {}).setdefault("screen_capture", {})["require_consent"] = self.var_screen_req_consent.get()

        if hasattr(self, "var_admin_shell"):
            self.config_data.setdefault("server", {})["allow_admin_shell"] = self.var_admin_shell.get()

        save_config(self.config_data)
        self._log("Updated module configuration in config.json.")
        if hasattr(self, "lbl_stat_tools"):
            self.lbl_stat_tools.configure(text=f"⚡ Active Tools: {self._count_active_tools()}")
        if self.is_server_running:
            messagebox.showinfo("Saved", "Skills configuration saved!\n\nNote: Please restart the server for active tool updates to take effect.", parent=self)
        else:
            messagebox.showinfo("Saved", "Skills configuration saved successfully!", parent=self)

    def _apply_gdrive_status(self, stat: dict):
        """Updates every Google Drive status widget from a gdrive_status() result (UI thread only)."""
        is_auth = bool(stat.get("authenticated", False))
        user_email = stat.get("user_email", "")
        updates = (
            ("lbl_gdrive_status", {"text": f"● Connected: {user_email}" if is_auth else "● Not Connected"}),
            ("lbl_settings_gdrive_status", {"text": f"● Status: Connected ({user_email})" if is_auth else "● Status: Not Connected"}),
        )
        color = "#10B981" if is_auth else "#94A3B8"
        for attr, kwargs in updates:
            widget = getattr(self, attr, None)
            try:
                if widget is not None and widget.winfo_exists():
                    widget.configure(text_color=color, **kwargs)
            except Exception:
                pass
        btn = getattr(self, "btn_gdrive_connect", None)
        try:
            if btn is not None and btn.winfo_exists():
                btn.configure(text="🔄 Re-authenticate" if is_auth else "🔑 Connect Google Drive")
        except Exception:
            pass

    def _refresh_gdrive_status_async(self, on_done=None):
        """Runs gdrive_status() (network I/O) off the UI thread, then applies the result."""
        def _worker():
            try:
                from modules.google_drive import gdrive_status
                stat = gdrive_status()
            except Exception as e:
                stat = {"authenticated": False, "error": str(e)}

            def _apply():
                self._apply_gdrive_status(stat)
                if on_done:
                    on_done(stat)
            try:
                self.after(0, _apply)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_gdrive_connect(self):
        self._refresh_gdrive_status_async(on_done=self._continue_gdrive_connect)

    def _continue_gdrive_connect(self, stat: dict):
        from modules.google_drive import start_oauth_flow
        if stat.get("authenticated", False):
            user_email = stat.get("user_email", "Connected")
            self._log(f"[GDRIVE] Google Drive is already authenticated as: {user_email}")
            messagebox.showinfo("Connected", f"Google Drive is already connected!\n\nAccount: {user_email}", parent=self)
            return

        res = start_oauth_flow()
        if not res.get("success"):
            messagebox.showerror("OAuth Error", res.get("error", "Unknown error"), parent=self)
            return
        auth_url = res.get("auth_url")
        self._log(f"[GDRIVE] Starting automated OAuth loopback login at {res.get('redirect_uri')}...")
        webbrowser.open(auth_url)
        messagebox.showinfo(
            "Browser Opened",
            "Opening your web browser for Google Drive authorization.\n\nPlease log in and grant permissions. The token exchange and setup will complete automatically.",
            parent=self
        )

        # Only the newest login attempt keeps polling, and it gives up after ~3 minutes.
        self._gdrive_poll_gen = getattr(self, "_gdrive_poll_gen", 0) + 1
        poll_gen = self._gdrive_poll_gen
        max_attempts = 90

        def poll_gdrive_auth(attempt=1):
            if poll_gen != self._gdrive_poll_gen:
                return

            def _on_result(stat):
                if poll_gen != self._gdrive_poll_gen:
                    return
                if stat.get("authenticated", False):
                    self._log(f"[GDRIVE] Successfully authenticated with Google Drive! Account: {stat.get('user_email', '')}")
                elif attempt < max_attempts:
                    self.after(2000, lambda: poll_gdrive_auth(attempt + 1))
                else:
                    self._log("[GDRIVE] Stopped waiting for Google Drive login (timeout).")

            self._refresh_gdrive_status_async(on_done=_on_result)

        self.after(2000, poll_gdrive_auth)

    def _on_gdrive_browse_credentials(self):
        from modules.google_drive import CREDENTIALS_FILE
        f = filedialog.askopenfilename(
            title="Select Google Cloud credentials.json",
            filetypes=[("JSON Files (*.json)", "*.json"), ("All Files (*.*)", "*.*")],
            parent=self
        )
        if f:
            try:
                shutil.copyfile(f, str(CREDENTIALS_FILE))
                self._log(f"[GDRIVE] Copied credentials.json to {CREDENTIALS_FILE}")
                messagebox.showinfo("Credentials Saved", "Successfully imported credentials.json!\n\nYou can now click 'Connect Google Drive'.", parent=self)
            except Exception as e:
                messagebox.showerror("Copy Error", f"Could not copy credentials file: {e}", parent=self)

    def _on_gdrive_disconnect(self):
        from modules.google_drive import disconnect_gdrive
        disconnect_gdrive()
        self._log("[GDRIVE] Google Drive disconnected and credentials removed.")
        if hasattr(self, "lbl_gdrive_status"):
            self.lbl_gdrive_status.configure(text="● Not Connected", text_color="#94A3B8")
        if hasattr(self, "lbl_settings_gdrive_status"):
            self.lbl_settings_gdrive_status.configure(text="● Status: Not Connected", text_color="#94A3B8")
        if hasattr(self, "btn_gdrive_connect"):
            self.btn_gdrive_connect.configure(text="🔑 Connect Google Drive")
        if hasattr(self, "entry_gdrive_client_id"):
            self.entry_gdrive_client_id.delete(0, "end")
        if hasattr(self, "entry_gdrive_client_secret"):
            self.entry_gdrive_client_secret.delete(0, "end")
        messagebox.showinfo("Disconnected", "Successfully disconnected Google Drive.", parent=self)

    # ---------------------------------------------------------
    # TAB 3: SSH HOST MANAGER
    # ---------------------------------------------------------
    def _setup_hosts_tab(self):
        top_bar = ctk.CTkFrame(self.tab_hosts, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Configured SSH Servers & PuTTY Aliases", font=ctk.CTkFont(size=17, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(title_box, text="🔒 Passwords stored with Windows DPAPI hardware encryption", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#059669", "#10B981")).pack(anchor="w")

        btn_add = ctk.CTkButton(
            top_bar,
            text="➕ Add Server",
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            width=130,
            height=32,
            command=self._add_host
        )
        btn_add.pack(side="right")

        self.hosts_scroll = ctk.CTkScrollableFrame(self.tab_hosts, fg_color="transparent")
        self.hosts_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._refresh_hosts_list()

    def _load_hosts_file(self) -> Dict[str, Any]:
        if HOSTS_FILE.exists():
            try:
                return json.loads(HOSTS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_hosts_file(self, data: Dict[str, Any]):
        HOSTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _refresh_hosts_list(self):
        for widget in self.hosts_scroll.winfo_children():
            widget.destroy()

        hosts = self._load_hosts_file()
        if not hosts:
            empty_card = ctk.CTkFrame(self.hosts_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
            empty_card.pack(fill="x", pady=20, padx=10)
            ctk.CTkLabel(
                empty_card,
                text="No remote SSH hosts configured yet.\nClick '➕ Add Server' above to configure server login profiles for plink / pscp.",
                font=ctk.CTkFont(size=13),
                text_color=THEME_TEXT_MUTED
            ).pack(padx=20, pady=25)
            return

        for alias, info in hosts.items():
            card = ctk.CTkFrame(self.hosts_scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=12, fill="x", expand=True)

            host_row = ctk.CTkFrame(left, fg_color="transparent")
            host_row.pack(anchor="w")

            host_str = f"🐧 {alias}  —  {info.get('username', 'root')}@{info.get('host', 'localhost')}:{info.get('port', 22)}"
            ctk.CTkLabel(host_row, text=host_str, font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")

            has_pw = str(info.get("password", "")).strip() != ""
            if has_pw:
                badge_sec = ctk.CTkFrame(host_row, fg_color=("#ECFDF5", "#1B2E24"), border_width=1, border_color=("#A7F3D0", "#244E38"), corner_radius=5)
                badge_sec.pack(side="left", padx=8)
                ctk.CTkLabel(badge_sec, text=" 🔒 DPAPI Protected ", font=ctk.CTkFont(size=10, weight="bold"), text_color=("#047857", "#10B981")).pack(padx=3, pady=1)

            desc = info.get("description") or "No description"
            has_key = f"Key: {Path(info.get('private_key_path', '')).name}" if info.get("private_key_path") else "No key file"
            subtext = f"{desc} | {has_key}"
            ctk.CTkLabel(left, text=subtext, font=ctk.CTkFont(size=12), text_color=THEME_TEXT_MUTED, anchor="w").pack(anchor="w", pady=(4, 0))

            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.pack(side="right", padx=15, pady=12)

            btn_putty = ctk.CTkButton(
                btn_box,
                text="🚀 PuTTY",
                width=80,
                height=28,
                fg_color=("#059669", "#10B981"),
                hover_color=("#047857", "#059669"),
                text_color="#FFFFFF",
                font=ctk.CTkFont(weight="bold"),
                command=lambda a=alias: self._launch_putty(a)
            )
            btn_putty.pack(side="left", padx=3)

            btn_edit = ctk.CTkButton(
                btn_box,
                text="Edit",
                width=65,
                height=28,
                fg_color=THEME_BTN_SEC_BG,
                hover_color=THEME_BTN_SEC_HOVER,
                text_color=THEME_TEXT_PRIMARY,
                font=ctk.CTkFont(weight="bold"),
                border_width=1,
                border_color=THEME_BTN_SEC_BORDER,
                command=lambda a=alias, d=info: self._edit_host(a, d)
            )
            btn_edit.pack(side="left", padx=3)

            btn_del = ctk.CTkButton(
                btn_box,
                text="Delete",
                width=65,
                height=28,
                fg_color=("#FEF2F2", "#3B1D22"),
                hover_color=("#FEE2E2", "#4C242B"),
                text_color=("#DC2626", "#F87171"),
                font=ctk.CTkFont(weight="bold"),
                border_width=1,
                border_color=("#FECACA", "#5C2B34"),
                command=lambda a=alias: self._delete_host(a)
            )
            btn_del.pack(side="left", padx=3)

    def _launch_putty(self, alias: str):
        try:
            res = ssh_open_putty_window(alias)
            if "error" in res:
                self._log(f"[PUTTY ERROR] {res['error']}")
                messagebox.showerror("PuTTY Error", res["error"], parent=self)
            else:
                self._log(f"[PUTTY] Launched interactive PuTTY session for '{alias}'")
        except Exception as e:
            self._log(f"[PUTTY ERROR] {e}")

    def _add_host(self):
        dlg = HostDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            alias = dlg.result["alias"]
            data = dlg.result["data"]
            ssh_save_host(
                alias=alias,
                host=data.get("host", ""),
                username=data.get("username", "root"),
                password=data.get("password", ""),
                private_key_path=data.get("private_key_path", ""),
                port=data.get("port", 22),
                description=data.get("description", "")
            )
            self._refresh_hosts_list()
            self._log(f"Added new SSH Host alias (DPAPI Encrypted): {alias}")

    def _edit_host(self, alias: str, info: Dict[str, Any]):
        dlg = HostDialog(self, host_data=info, alias=alias)
        self.wait_window(dlg)
        if dlg.result:
            new_alias = dlg.result["alias"]
            data = dlg.result["data"]
            if new_alias != alias:
                hosts = self._load_hosts_file()
                if alias in hosts:
                    del hosts[alias]
                    self._save_hosts_file(hosts)
            ssh_save_host(
                alias=new_alias,
                host=data.get("host", ""),
                username=data.get("username", "root"),
                password=data.get("password", ""),
                private_key_path=data.get("private_key_path", ""),
                port=data.get("port", 22),
                description=data.get("description", "")
            )
            self._refresh_hosts_list()
            self._log(f"Updated SSH Host alias (DPAPI Encrypted): {new_alias}")

    def _delete_host(self, alias: str):
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete host '{alias}'?", parent=self):
            hosts = self._load_hosts_file()
            if alias in hosts:
                del hosts[alias]
                self._save_hosts_file(hosts)
                self._refresh_hosts_list()
                self._log(f"Deleted SSH Host alias: {alias}")

    # ---------------------------------------------------------
    # TAB 4: SECURITY & SETTINGS
    # ---------------------------------------------------------
    def _setup_settings_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # 1. Network Settings Group
        net_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        net_group.pack(fill="x", pady=6)

        ctk.CTkLabel(net_group, text="🌐 Network & Server Binding", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f1 = ctk.CTkFrame(net_group, fg_color="transparent")
        f1.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f1, text="Server Port:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_port = ctk.CTkEntry(f1, width=120, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_port.insert(0, str(self.config_data.get("server", {}).get("port", 8000)))
        self.entry_port.pack(side="left")

        f2 = ctk.CTkFrame(net_group, fg_color="transparent")
        f2.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f2, text="Bind Address:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.opt_host = ctk.CTkOptionMenu(
            f2,
            values=["127.0.0.1", "0.0.0.0"],
            width=120,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=("#CBD5E1", "#42434B"),
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG
        )
        self.opt_host.set(self.config_data.get("server", {}).get("host", "127.0.0.1"))
        self.opt_host.pack(side="left")

        f3 = ctk.CTkFrame(net_group, fg_color="transparent")
        f3.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f3, text="Default Tunnel Mode:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.opt_tunnel_mode = ctk.CTkOptionMenu(
            f3,
            values=["Serveo (Public SSH Tunnel)", "Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"],
            width=200,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=("#CBD5E1", "#42434B"),
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG,
            command=self._on_settings_mode_changed
        )
        self.opt_tunnel_mode.set(self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel"))
        self.opt_tunnel_mode.pack(side="left")

        f4 = ctk.CTkFrame(net_group, fg_color="transparent")
        f4.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f4, text="Default Route Path:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.opt_endpoint_path = ctk.CTkOptionMenu(
            f4,
            values=["/sse", "/mcp", "/messages", "/"],
            width=120,
            fg_color=THEME_BTN_SEC_BG,
            button_color=THEME_BTN_SEC_HOVER,
            button_hover_color=("#CBD5E1", "#42434B"),
            text_color=THEME_TEXT_PRIMARY,
            dropdown_fg_color=THEME_CARD_BG,
            dropdown_text_color=THEME_TEXT_PRIMARY,
            dropdown_hover_color=THEME_BTN_SEC_BG
        )
        self.opt_endpoint_path.set(self.config_data.get("server", {}).get("endpoint_path", "/sse"))
        self.opt_endpoint_path.pack(side="left")

        # Cloudflare Binary Path
        f_cf = ctk.CTkFrame(net_group, fg_color="transparent")
        f_cf.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_cf, text="Cloudflare Path:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_cf_bin = ctk.CTkEntry(
            f_cf,
            width=280,
            placeholder_text="e.g. cloudflared.exe (auto-detected if blank)",
            fg_color=THEME_INPUT_BG,
            border_color=THEME_CARD_BORDER,
            text_color=THEME_TEXT_PRIMARY
        )
        saved_cf = self.config_data.get("server", {}).get("cloudflared_path", "")
        if saved_cf:
            self.entry_cf_bin.insert(0, saved_cf)
        else:
            detected_cf = find_cloudflared_binary()
            if detected_cf:
                self.entry_cf_bin.insert(0, detected_cf)
        self.entry_cf_bin.pack(side="left", padx=(0, 5))

        btn_browse_cf = ctk.CTkButton(
            f_cf,
            text="📁 Browse",
            width=85,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._browse_cloudflared
        )
        btn_browse_cf.pack(side="left", padx=(0, 5))

        btn_detect_cf = ctk.CTkButton(
            f_cf,
            text="🔄 Detect",
            width=80,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._detect_cloudflared_in_settings
        )
        btn_detect_cf.pack(side="left")

        # 2. Authentication & Tokens Group (Secure by Default)
        auth_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        auth_group.pack(fill="x", pady=6)

        ctk.CTkLabel(auth_group, text="🔒 Authentication & API Tokens (Secure by Default)", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f5 = ctk.CTkFrame(auth_group, fg_color="transparent")
        f5.pack(fill="x", padx=15, pady=5)
        self.var_enforce_auth = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enforce_auth", True))
        sw_auth = ctk.CTkSwitch(f5, text="Require Bearer Token Authentication (Authorization Header)", variable=self.var_enforce_auth, font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY, progress_color="#10B981")
        sw_auth.pack(side="left")

        f6 = ctk.CTkFrame(auth_group, fg_color="transparent")
        f6.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f6, text="Active Bearer Token:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_token = ctk.CTkEntry(f6, width=280, show="*", fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        tok_val = self.config_data.get("server", {}).get("api_token", "")

        self.entry_token.insert(0, tok_val)
        self.entry_token.pack(side="left", padx=(0, 5))

        self.btn_show_token = ctk.CTkButton(
            f6,
            text="👁️",
            width=36,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._toggle_token_visibility
        )
        self.btn_show_token.pack(side="left", padx=(0, 5))

        self.btn_copy_tok = ctk.CTkButton(
            f6,
            text="📋 Copy Key",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=lambda: self._copy_to_clipboard(self.entry_token.get(), "Bearer Key")
        )
        self.btn_copy_tok.pack(side="left", padx=(0, 5))

        btn_gen_tok = ctk.CTkButton(
            f6,
            text="🎲 Generate",
            width=95,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._generate_new_token
        )
        btn_gen_tok.pack(side="left")

        # 4. Workspace & Sandbox Security Group
        ws_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        ws_group.pack(fill="x", pady=6)

        ctk.CTkLabel(ws_group, text="📁 Workspace & Sandboxing Security", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f_ws1 = ctk.CTkFrame(ws_group, fg_color="transparent")
        f_ws1.pack(fill="x", padx=15, pady=5)
        self.var_sandbox = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enforce_workspace_sandbox", True))
        sw_sandbox = ctk.CTkSwitch(f_ws1, text="Enforce Workspace Sandbox (Restricts file access to ./workspace)", variable=self.var_sandbox, font=ctk.CTkFont(size=13, weight="bold"), text_color=THEME_TEXT_PRIMARY, progress_color="#10B981")
        sw_sandbox.pack(side="left")

        f_ws2 = ctk.CTkFrame(ws_group, fg_color="transparent")
        f_ws2.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_ws2, text="Workspace Path:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_workspace = ctk.CTkEntry(f_ws2, width=280, fg_color=THEME_INPUT_BG, border_color=THEME_CARD_BORDER, text_color=THEME_TEXT_PRIMARY)
        self.entry_workspace.insert(0, str(self.config_data.get("server", {}).get("workspace_root", "./workspace")))
        self.entry_workspace.pack(side="left", padx=(0, 5))

        btn_browse_ws = ctk.CTkButton(
            f_ws2,
            text="📂 Browse",
            width=85,
            height=28,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._browse_workspace
        )
        btn_browse_ws.pack(side="left")

        # 5. LAN TLS Encryption Group
        tls_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        tls_group.pack(fill="x", pady=6)

        ctk.CTkLabel(tls_group, text="🛡️ LAN HTTPS / TLS Encryption", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f_tls1 = ctk.CTkFrame(tls_group, fg_color="transparent")
        f_tls1.pack(fill="x", padx=15, pady=(5, 15))
        self.var_enable_tls = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enable_tls", False))
        sw_tls = ctk.CTkSwitch(
            f_tls1,
            text="Enable Local HTTPS TLS (Uses auto-generated cert.pem if missing)",
            variable=self.var_enable_tls,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#10B981"
        )
        sw_tls.pack(side="left")

        # 6. Screen Capture & Vision Privacy Gate
        vis_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        vis_group.pack(fill="x", pady=6)

        ctk.CTkLabel(vis_group, text="👁️ Vision & Desktop Screen Capture Privacy Gate", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f_vis1 = ctk.CTkFrame(vis_group, fg_color="transparent")
        f_vis1.pack(fill="x", padx=15, pady=5)
        self.var_settings_screen_consent = ctk.BooleanVar(value=self.config_data.get("modules", {}).get("screen_capture", {}).get("require_consent", True))
        sw_vis = ctk.CTkSwitch(
            f_vis1,
            text="Require User Consent before capturing screenshots (Privacy Shield)",
            variable=self.var_settings_screen_consent,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#F59E0B",
            command=self._on_settings_screen_consent_changed
        )
        sw_vis.pack(side="left")

        f_vis2 = ctk.CTkFrame(vis_group, fg_color="transparent")
        f_vis2.pack(fill="x", padx=15, pady=(5, 15))
        btn_grant_session = ctk.CTkButton(
            f_vis2,
            text="🔓 Grant Screen Capture Consent for this Session",
            width=320,
            height=30,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_ui_grant_session_consent
        )
        btn_grant_session.pack(side="left")

        # 7. Google Drive Cloud Integration & Browser Login
        gdrive_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        gdrive_group.pack(fill="x", pady=6)

        ctk.CTkLabel(gdrive_group, text="📁 Google Drive Cloud Integration & Browser Login", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        # Status row
        f_gd_stat = ctk.CTkFrame(gdrive_group, fg_color="transparent")
        f_gd_stat.pack(fill="x", padx=15, pady=5)

        self.lbl_settings_gdrive_status = ctk.CTkLabel(
            f_gd_stat,
            text="● Status: Checking...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94A3B8"
        )
        self.lbl_settings_gdrive_status.pack(side="left")
        self._refresh_gdrive_status_async()

        # Buttons row: Launch Browser Login, Import credentials.json, Disconnect
        f_gd_btns = ctk.CTkFrame(gdrive_group, fg_color="transparent")
        f_gd_btns.pack(fill="x", padx=15, pady=8)

        btn_launch_login = ctk.CTkButton(
            f_gd_btns,
            text="🌐 Launch Login Browser",
            width=180,
            height=30,
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_gdrive_connect
        )
        btn_launch_login.pack(side="left", padx=(0, 8))

        btn_import_creds = ctk.CTkButton(
            f_gd_btns,
            text="📂 Import credentials.json",
            width=180,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            command=self._on_gdrive_browse_credentials
        )
        btn_import_creds.pack(side="left", padx=(0, 8))

        btn_disc_gd = ctk.CTkButton(
            f_gd_btns,
            text="🔌 Disconnect",
            width=100,
            height=30,
            fg_color=("#FEF2F2", "#3B1D22"),
            hover_color=("#FEE2E2", "#4D242B"),
            text_color=("#DC2626", "#F87171"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#FECACA", "#5C2B34"),
            command=self._on_gdrive_disconnect
        )
        btn_disc_gd.pack(side="left")

        # Custom GCP OAuth Client Credentials (optional)
        f_gd_cid = ctk.CTkFrame(gdrive_group, fg_color="transparent")
        f_gd_cid.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f_gd_cid, text="OAuth Client ID:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_gdrive_client_id = ctk.CTkEntry(
            f_gd_cid,
            width=320,
            placeholder_text="Optional: Google Cloud OAuth Client ID",
            fg_color=THEME_INPUT_BG,
            border_color=THEME_CARD_BORDER,
            text_color=THEME_TEXT_PRIMARY
        )
        saved_cid = self.config_data.get("modules", {}).get("google_drive", {}).get("client_id", "")
        if saved_cid:
            self.entry_gdrive_client_id.insert(0, saved_cid)
        self.entry_gdrive_client_id.pack(side="left", padx=(0, 8))

        f_gd_csec = ctk.CTkFrame(gdrive_group, fg_color="transparent")
        f_gd_csec.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_gd_csec, text="OAuth Client Secret:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_gdrive_client_secret = ctk.CTkEntry(
            f_gd_csec,
            width=320,
            show="*",
            placeholder_text="Optional: Google Cloud Client Secret",
            fg_color=THEME_INPUT_BG,
            border_color=THEME_CARD_BORDER,
            text_color=THEME_TEXT_PRIMARY
        )
        saved_csec = self.config_data.get("modules", {}).get("google_drive", {}).get("client_secret", "")
        if saved_csec and saved_csec.startswith("dpapi:"):
            try:
                decrypted = _decrypt_dpapi(saved_csec)
                if decrypted and not decrypted.startswith("dpapi:"):
                    saved_csec = decrypted
            except Exception:
                pass
        if saved_csec:
            self.entry_gdrive_client_secret.insert(0, saved_csec)
        self.entry_gdrive_client_secret.pack(side="left", padx=(0, 8))

        # 8. In-App Browser & Mammouth.ai
        browser_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        browser_group.pack(fill="x", pady=6)

        ctk.CTkLabel(browser_group, text="💬 In-App Browser & Mammouth.ai", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f_br1 = ctk.CTkFrame(browser_group, fg_color="transparent")
        f_br1.pack(fill="x", padx=15, pady=5)
        self.var_browser_auto_open = ctk.BooleanVar(value=self.config_data.get("embedded_browser", {}).get("auto_open_on_server_start", True))
        sw_browser_auto = ctk.CTkSwitch(
            f_br1,
            text="Automatisch Mammouth AI Web-Tab öffnen wenn Server startet",
            variable=self.var_browser_auto_open,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#10B981"
        )
        sw_browser_auto.pack(side="left")

        f_br_zen = ctk.CTkFrame(browser_group, fg_color="transparent")
        f_br_zen.pack(fill="x", padx=15, pady=5)
        self.var_start_in_web_tab = ctk.BooleanVar(value=self.config_data.get("server", {}).get("start_in_web_tab", False))
        sw_start_in_web = ctk.CTkSwitch(
            f_br_zen,
            text="Beim Programmstart direkt im Chat-Tab starten (Chat-First / Zen Mode)",
            variable=self.var_start_in_web_tab,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#10B981"
        )
        sw_start_in_web.pack(side="left")

        f_br_hk = ctk.CTkFrame(browser_group, fg_color="transparent")
        f_br_hk.pack(fill="x", padx=15, pady=5)
        self.var_global_hotkey = ctk.BooleanVar(value=self.config_data.get("server", {}).get("global_hotkey_enabled", True))
        sw_global_hk = ctk.CTkSwitch(
            f_br_hk,
            text="Globaler Windows-Schnellzugriff (Ctrl+Shift+M toggelt Cockpit & fokussiert Chat)",
            variable=self.var_global_hotkey,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#10B981"
        )
        sw_global_hk.pack(side="left")

        f_br2 = ctk.CTkFrame(browser_group, fg_color="transparent")
        f_br2.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_br2, text="Start-URL:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(side="left")
        self.entry_browser_start_url = ctk.CTkEntry(
            f_br2,
            width=320,
            fg_color=THEME_INPUT_BG,
            border_color=THEME_CARD_BORDER,
            text_color=THEME_TEXT_PRIMARY
        )
        start_page_val = self.config_data.get("embedded_browser", {}).get("start_page", "https://mammouth.ai")
        self.entry_browser_start_url.insert(0, start_page_val)
        self.entry_browser_start_url.pack(side="left", padx=(0, 8))

        # 9. Software Updates
        upd_group = ctk.CTkFrame(scroll, fg_color=THEME_CARD_BG, border_width=1, border_color=THEME_CARD_BORDER, corner_radius=10)
        upd_group.pack(fill="x", pady=6)

        ctk.CTkLabel(upd_group, text="🔄 Software Updates & Version", font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_TEXT_PRIMARY).pack(anchor="w", padx=15, pady=(15, 10))

        f_upd1 = ctk.CTkFrame(upd_group, fg_color="transparent")
        f_upd1.pack(fill="x", padx=15, pady=5)
        self.var_auto_check_updates = ctk.BooleanVar(value=self.config_data.get("server", {}).get("auto_check_updates", True))
        sw_auto_upd = ctk.CTkSwitch(
            f_upd1,
            text="Automatisch beim Start nach Updates suchen (GitHub Releases)",
            variable=self.var_auto_check_updates,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME_TEXT_PRIMARY,
            progress_color="#10B981"
        )
        sw_auto_upd.pack(side="left")

        f_upd2 = ctk.CTkFrame(upd_group, fg_color="transparent")
        f_upd2.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_upd2, text=f"Installierte Version: {APP_VERSION}", width=220, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#64748B", "#94A3B8")).pack(side="left")
        btn_manual_upd = ctk.CTkButton(
            f_upd2,
            text="🔍 Jetzt nach Updates suchen",
            width=220,
            height=30,
            fg_color=THEME_BTN_SEC_BG,
            hover_color=THEME_BTN_SEC_HOVER,
            text_color=THEME_TEXT_PRIMARY,
            border_width=1,
            border_color=THEME_BTN_SEC_BORDER,
            font=ctk.CTkFont(weight="bold"),
            command=lambda: self._check_updates_async(manual=True)
        )
        btn_manual_upd.pack(side="left")

        # Save Settings Button
        btn_save_all = ctk.CTkButton(
            scroll,
            text="💾 Save All Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            height=40,
            command=self._save_settings
        )
        btn_save_all.pack(fill="x", pady=15)

    def _browse_workspace(self):
        folder = filedialog.askdirectory(title="Select Workspace Directory")
        if folder:
            self.entry_workspace.delete(0, "end")
            self.entry_workspace.insert(0, folder)

    def _browse_cloudflared(self):
        filename = filedialog.askopenfilename(
            title="Select cloudflared Executable",
            filetypes=[("Executable Files", "*.exe;cloudflared*"), ("All Files", "*.*")]
        )
        if filename:
            self.entry_cf_bin.delete(0, "end")
            self.entry_cf_bin.insert(0, filename)

    def _detect_cloudflared_in_settings(self):
        detected = find_cloudflared_binary()
        if detected:
            self.entry_cf_bin.delete(0, "end")
            self.entry_cf_bin.insert(0, detected)
            messagebox.showinfo("cloudflared Detected", f"Found cloudflared binary at:\n\n{detected}", parent=self)
        else:
            messagebox.showwarning("cloudflared Not Found", "Could not automatically locate cloudflared.\n\nPlease place cloudflared.exe in the app directory or use Browse to select it.", parent=self)

    def _toggle_token_visibility(self):
        if self.entry_token.cget("show") == "*":
            self.entry_token.configure(show="")
            self.btn_show_token.configure(text="🔒")
        else:
            self.entry_token.configure(show="*")
            self.btn_show_token.configure(text="👁️")

    def _generate_new_token(self):
        if messagebox.askyesno("Generate Token", "Generate a new 32-character authentication token?", parent=self):
            new_tok = generate_secure_token()
            self.entry_token.delete(0, "end")
            self.entry_token.insert(0, new_tok)
            self._log("Generated new secure API authentication token.")

    def _on_admin_shell_toggle(self):
        if self.var_admin_shell.get():
            confirm = messagebox.askyesno(
                "Enable Administrative Shell Execution?",
                "WARNING: Enabling administrative shell execution allows MCP tools to execute modifying PowerShell commands and system binaries.\n\nAre you sure you want to enable this?",
                parent=self
            )
            if not confirm:
                self.var_admin_shell.set(False)
        if hasattr(self, "sw_admin_shell"):
            self.sw_admin_shell.configure(
                text="⚡ Admin / Modifizierend (Vollzugriff)" if self.var_admin_shell.get() else "🔒 Nur Diagnose & Read-Only"
            )

    def _on_settings_mode_changed(self, choice: str):
        self.dash_mode_menu.set(choice)

    def _on_settings_screen_consent_changed(self):
        val = self.var_settings_screen_consent.get()
        self.config_data.setdefault("modules", {}).setdefault("screen_capture", {})["require_consent"] = val
        save_config(self.config_data)
        if hasattr(self, "var_screen_req_consent"):
            self.var_screen_req_consent.set(val)
        if hasattr(self, "lbl_consent_badge"):
            if val:
                self.lbl_consent_badge.configure(text="● Status: Pending Consent", text_color="#F59E0B")
            else:
                self.lbl_consent_badge.configure(text="● Status: Always Allowed", text_color="#10B981")
        self._log(f"[SECURITY] Screen capture 'require_consent' updated to {val} from Settings.")

    def _save_settings(self):
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            port = 8000

        self.config_data["server"]["port"] = port
        self.config_data["server"]["host"] = self.opt_host.get().strip() or "127.0.0.1"
        self.config_data["server"]["tunnel_mode"] = self.opt_tunnel_mode.get()
        self.config_data["server"]["endpoint_path"] = self.opt_endpoint_path.get()
        self.config_data["server"]["enforce_auth"] = self.var_enforce_auth.get()
        raw_tok = self.entry_token.get().strip()
        if raw_tok.startswith("dpapi:"):
            try:
                decrypted = _decrypt_dpapi(raw_tok)
                if decrypted and not decrypted.startswith("dpapi:"):
                    raw_tok = decrypted
            except Exception:
                pass
        self.config_data["server"]["api_token"] = raw_tok
        if hasattr(self, "var_admin_shell"):
            self.config_data["server"]["allow_admin_shell"] = self.var_admin_shell.get()
        self.config_data["server"]["enable_tls"] = self.var_enable_tls.get()
        self.config_data["server"]["enforce_workspace_sandbox"] = self.var_sandbox.get()
        self.config_data["server"]["workspace_root"] = self.entry_workspace.get().strip() or "./workspace"
        if hasattr(self, "entry_cf_bin"):
            self.config_data["server"]["cloudflared_path"] = self.entry_cf_bin.get().strip()

        if hasattr(self, "var_settings_screen_consent"):
            self.config_data.setdefault("modules", {}).setdefault("screen_capture", {})["require_consent"] = self.var_settings_screen_consent.get()
            if hasattr(self, "var_screen_req_consent"):
                self.var_screen_req_consent.set(self.var_settings_screen_consent.get())

        if hasattr(self, "entry_gdrive_client_id"):
            gd_cid = self.entry_gdrive_client_id.get().strip()
            self.config_data.setdefault("modules", {}).setdefault("google_drive", {})["client_id"] = gd_cid
        if hasattr(self, "entry_gdrive_client_secret"):
            gd_csec = self.entry_gdrive_client_secret.get().strip()
            if gd_csec and not gd_csec.startswith("dpapi:"):
                gd_csec = _encrypt_dpapi(gd_csec)
            self.config_data.setdefault("modules", {}).setdefault("google_drive", {})["client_secret"] = gd_csec

        if hasattr(self, "var_browser_auto_open"):
            self.config_data.setdefault("embedded_browser", {})["auto_open_on_server_start"] = self.var_browser_auto_open.get()
        if hasattr(self, "entry_browser_start_url"):
            new_url = self.entry_browser_start_url.get().strip() or "https://mammouth.ai"
            self.config_data.setdefault("embedded_browser", {})["start_page"] = new_url
            if hasattr(self, "mammouth_browser"):
                self.mammouth_browser.start_url = new_url

        if hasattr(self, "var_auto_check_updates"):
            self.config_data.setdefault("server", {})["auto_check_updates"] = self.var_auto_check_updates.get()

        if hasattr(self, "var_start_in_web_tab"):
            self.config_data.setdefault("server", {})["start_in_web_tab"] = self.var_start_in_web_tab.get()

        if hasattr(self, "var_global_hotkey"):
            self.config_data.setdefault("server", {})["global_hotkey_enabled"] = self.var_global_hotkey.get()

        if hasattr(self, "var_browser_agent_headless"):
            self.config_data.setdefault("browser_agent", {})["headless"] = self.var_browser_agent_headless.get()

        save_config(self.config_data)
        self.dash_mode_menu.set(self.opt_tunnel_mode.get())
        self.dash_path_menu.set(self.opt_endpoint_path.get())
        self._refresh_all_endpoint_labels()
        self._log("Updated settings in config.json.")
        messagebox.showinfo("Saved", "Settings saved successfully!", parent=self)

    # ---------------------------------------------------------
    # IN-PROCESS SERVER LIFECYCLE (THREAD-BASED)
    # ---------------------------------------------------------
    def toggle_server(self):
        if not self.is_server_running:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self):
        if self.is_server_running:
            return

        if self.config_data.get("server", {}).get("enforce_auth", True):
            token = self.config_data.get("server", {}).get("api_token", "").strip()
            if not token:
                token = generate_secure_token()
                self.config_data["server"]["api_token"] = token
                save_config(self.config_data)
                if hasattr(self, "entry_token"):
                    self.entry_token.delete(0, "end")
                    self.entry_token.insert(0, token)
                self._refresh_all_endpoint_labels()
                self._log("[SECURITY] Generated new secure Bearer token because auth is enabled.")
        else:
            token = ""

        host = str(self.config_data.get("server", {}).get("host", "127.0.0.1")).strip() or "127.0.0.1"
        try:
            port = int(self.config_data.get("server", {}).get("port", 8000))
        except (ValueError, TypeError):
            port = 8000

        # Check if port is already bound by an existing process
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        check_ip = host if host not in ("0.0.0.0", "") else "127.0.0.1"
        port_in_use = (sock.connect_ex((check_ip, port)) == 0)
        sock.close()

        if port_in_use:
            owner_info = ""
            blocking_pid = None
            try:
                import psutil
                for conn in psutil.net_connections(kind="inet"):
                    if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                        blocking_pid = conn.pid
                        if blocking_pid:
                            p = psutil.Process(blocking_pid)
                            owner_info = f" (PID {blocking_pid}: {p.name()})"
                        break
            except Exception:
                pass

            err_msg = f"Port {port} is already in use by another application{owner_info}!"
            self._log(f"[PORT CONFLICT] {err_msg}")
            
            if blocking_pid and "mammouth" in owner_info.lower() and blocking_pid != os.getpid():
                ask_kill = messagebox.askyesno(
                    "Port In Use",
                    f"Port {port} is currently occupied by a previous Defroster instance{owner_info}.\n\nWould you like to terminate the previous instance and free the port?",
                    parent=self
                )
                if ask_kill:
                    try:
                        import psutil
                        psutil.Process(blocking_pid).terminate()
                        time.sleep(0.5)
                        self._log(f"[PORT] Terminated previous instance PID {blocking_pid}. Port {port} is now free.")
                    except Exception as k_err:
                        self._log(f"[PORT WARNING] Could not terminate PID {blocking_pid}: {k_err}")
                else:
                    return
            else:
                messagebox.showerror(
                    "Port Conflict",
                    f"{err_msg}\n\nPlease close the blocking application or run 'stop_server.bat' before starting.",
                    parent=self
                )
                return

        self._log(f"Starting in-process FastMCP server on {host}:{port}...")

        # Activate public tunnel in background if selected
        server_cfg = self.config_data.get("server", {})
        tunnel_choice = server_cfg.get("tunnel_mode")

        self._start_tunnel_for_mode(tunnel_choice, port)

        try:
            import uvicorn

            enable_tls = bool(self.config_data.get("server", {}).get("enable_tls", False))
            cert_file = self.config_data.get("server", {}).get("ssl_certfile")
            key_file = self.config_data.get("server", {}).get("ssl_keyfile")

            if enable_tls and (not cert_file or not os.path.exists(str(cert_file))):
                default_cert = str(BASE_DIR / "cert.pem")
                default_key = str(BASE_DIR / "key.pem")
                if not os.path.exists(default_cert):
                    self._log("[TLS] Generating self-signed TLS certificate for local network security...")
                    generate_self_signed_cert(default_cert, default_key, host)
                cert_file = default_cert
                key_file = default_key

            if not enable_tls and host not in ("127.0.0.1", "localhost"):
                self._log("[SECURITY WARNING] Server is bound to external interface without TLS! LAN traffic is unencrypted.")

            server_app = build_app(token=token)
            uvicorn_kwargs = {
                "app": server_app,
                "host": host,
                "port": port,
                "log_level": "info",
                "use_colors": False,
                "log_config": None
            }
            if enable_tls and cert_file and os.path.exists(cert_file):
                uvicorn_kwargs["ssl_certfile"] = cert_file
                uvicorn_kwargs["ssl_keyfile"] = key_file

            uvicorn_cfg = uvicorn.Config(**uvicorn_kwargs)
            self.uvicorn_server = uvicorn.Server(uvicorn_cfg)

            def run_server():
                try:
                    self.uvicorn_server.run()
                except Exception as ex:
                    self.after(0, self._log, f"[SERVER CRASH] {ex}")
                finally:
                    self.after(0, self._handle_server_stopped)

            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()

            self.is_server_running = True
            self.server_start_time = time.time()
            self.status_badge.configure(text=f"● ONLINE (Port {port})", text_color="#10B981")
            self.btn_toggle_server.configure(text="⏹ STOP SERVER", fg_color="#EF4444", hover_color="#DC2626")
            self._refresh_all_endpoint_labels()
            self._log(f"Server is LIVE! Active Endpoint: {self._calculate_active_endpoint_url()}")
            if self.config_data.get("embedded_browser", {}).get("auto_open_on_server_start", True):
                self.after(500, self._switch_to_mammouth_tab)
        except Exception as e:

            self._log(f"[ERROR] Failed to start server: {e}")
            messagebox.showerror("Start Error", f"Failed to start server:\n\n{e}", parent=self)

    # ---------------------------------------------------------
    # TUNNEL LIFECYCLE
    # Every start captures the current generation; _stop_all_tunnels() bumps it, so a tunnel
    # thread that only reaches Popen after a stop kills its own process instead of leaving the
    # port publicly exposed.
    # ---------------------------------------------------------
    def _tunnel_state_lock(self) -> threading.Lock:
        lock = self.__dict__.get("_tunnel_lock")
        if lock is None:
            lock = self.__dict__.setdefault("_tunnel_lock", threading.Lock())
        return lock

    def _tunnel_generation(self) -> int:
        return self.__dict__.get("_tunnel_gen", 0)

    def _register_tunnel_proc(self, attr: str, proc: subprocess.Popen, gen: int) -> bool:
        """Store a freshly started tunnel process unless a stop happened meanwhile."""
        with self._tunnel_state_lock():
            if gen == self._tunnel_generation():
                setattr(self, attr, proc)
                return True
        try:
            proc.terminate()
        except Exception:
            pass
        return False

    def _start_tunnel_for_mode(self, mode: Optional[str], port: int):
        if mode == "Tailscale Funnel":
            self._start_tailscale_funnel(port)
        elif mode == "Cloudflare Tunnel":
            self._start_cloudflare_tunnel(port)
        elif mode == "Serveo (Public SSH Tunnel)":
            self._start_serveo_tunnel(port)
        elif mode == "ngrok":
            self._start_ngrok_tunnel(port)

    def _enqueue_funnel_op(self, op):
        """Run funnel on/off commands strictly in order on one worker, so an earlier
        "off" can never land after a later "on" (e.g. when switching TO Funnel)."""
        with self._tunnel_state_lock():
            q = self.__dict__.get("_funnel_queue")
            if q is None:
                q = self._funnel_queue = queue.Queue()

                def worker():
                    while True:
                        fn = q.get()
                        try:
                            fn()
                        except Exception as e:
                            self._log(f"[NETWORK WARNING] Tailscale funnel worker: {e}")

                threading.Thread(target=worker, daemon=True, name="TailscaleFunnelWorker").start()
        q.put(op)

    def _start_tailscale_funnel(self, port: int):
        gen = self._tunnel_generation()
        ts_path = self.config_data.get("server", {}).get("tailscale_path", r"C:\Program Files\Tailscale\tailscale.exe")

        def run_funnel():
            if gen != self._tunnel_generation():
                return  # superseded by a stop before this op got its turn
            ts_bin = find_tailscale_binary(ts_path)
            if not ts_bin:
                return
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                res = subprocess.run(
                    [ts_bin, "funnel", "--bg", "--yes", str(port)],
                    capture_output=True, text=True, timeout=10, creationflags=flags
                )
                if res.returncode == 0:
                    with self._tunnel_state_lock():
                        still_wanted = gen == self._tunnel_generation()
                        self._funnel_active = True
                    if not still_wanted:
                        self._disable_tailscale_funnel()
                        return
                    self._log("[NETWORK] Tailscale Funnel background proxy activated.")
                else:
                    err = res.stderr.strip() or res.stdout.strip()
                    self._log(f"[NETWORK WARNING] Tailscale funnel: {err}")
            except Exception as e:
                self._log(f"[NETWORK WARNING] Tailscale funnel trigger: {e}")

        # `tailscale funnel` can take up to 10s: keep it off the UI thread
        self._enqueue_funnel_op(run_funnel)

    def _disable_tailscale_funnel(self):
        ts_path = self.config_data.get("server", {}).get("tailscale_path", r"C:\Program Files\Tailscale\tailscale.exe")
        ts_bin = find_tailscale_binary(ts_path)
        if not ts_bin:
            return
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run([ts_bin, "funnel", "--https=443", "off"], capture_output=True, timeout=5, creationflags=flags)
            self._funnel_active = False
            self._log("[NETWORK] Tailscale Funnel proxy disabled.")
        except Exception:
            pass

    def _stop_all_tunnels(self):
        """Close every tunnel that may currently expose the port, regardless of the selected mode."""
        with self._tunnel_state_lock():
            self._tunnel_gen = self._tunnel_generation() + 1
            procs = [
                ("Serveo Tunnel", self.__dict__.get("serveo_proc")),
                ("Cloudflare Tunnel", self.__dict__.get("cf_proc")),
                ("ngrok Tunnel", self.__dict__.get("ngrok_proc")),
            ]
            self.serveo_proc = None
            self.cf_proc = None
            self.ngrok_proc = None
            funnel_was_active = bool(self.__dict__.get("_funnel_active", False))
        for label, proc in procs:
            if proc is not None:
                try:
                    proc.terminate()
                    self._log(f"[NETWORK] {label} closed.")
                except Exception:
                    pass
        # Reset stale public URLs so dashboard / "Copy MCP Config" never show a dead tunnel
        self.dynamic_tunnel_url = None
        self.serveo_url = None
        configured_funnel = self.config_data.get("server", {}).get("tunnel_mode") == "Tailscale Funnel"
        if funnel_was_active or configured_funnel:
            self._enqueue_funnel_op(self._disable_tailscale_funnel)

    def _start_cloudflare_tunnel(self, port: int):
        if self.__dict__.get("cf_proc", None) and self.cf_proc.poll() is None:
            return
        if self.__dict__.get("_cf_starting"):
            return  # a start is already in flight (binary lookup can be slow)
        self._cf_starting = True
        gen = self._tunnel_generation()

        self.dynamic_tunnel_url = None
        def run_cloudflare():
            try:
                cf_path_cfg = self.config_data.get("server", {}).get("cloudflared_path", "")
                cf_bin = find_cloudflared_binary(cf_path_cfg)
                if not cf_bin:
                    self._log("[NETWORK WARNING] cloudflared binary not found on system or app directory. Automatic tunnel aborted.")
                    return

                self._log(f"[NETWORK] Found cloudflared: {cf_bin}")
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.Popen(
                    [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, creationflags=flags
                )
                if not self._register_tunnel_proc("cf_proc", proc, gen):
                    self._log("[NETWORK] Cloudflare tunnel start cancelled (server stopped meanwhile).")
                    return
                self._cf_starting = False
                self._log("[NETWORK] Starting Cloudflare Quick Tunnel (trycloudflare.com)...")
                found = False
                while proc.poll() is None:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if "trycloudflare.com" in line:
                        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                        if match:
                            url = match.group(0)
                            if gen != self._tunnel_generation():
                                return
                            self.dynamic_tunnel_url = url
                            self._log(f"[NETWORK] Cloudflare Tunnel Active: {url}")
                            self.after(0, self._refresh_all_endpoint_labels)
                            found = True
                            break

                if not found and proc.poll() is not None:
                    self._log(f"[NETWORK WARNING] cloudflared process exited with code {proc.poll()}.")

                # Keep reading output so buffer does not block
                while proc.poll() is None:
                    line = proc.stdout.readline()
                    if not line:
                        break
            except Exception as e:
                self._log(f"[NETWORK WARNING] Cloudflare tunnel trigger: {e}")
            finally:
                self._cf_starting = False

        threading.Thread(target=run_cloudflare, daemon=True).start()

    def _start_serveo_tunnel(self, port: int):
        if self.__dict__.get("serveo_proc", None) and self.serveo_proc.poll() is None:
            return
        self.serveo_url = None
        gen = self._tunnel_generation()
        def run_serveo():
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                # accept-new pins serveo's host key on first use instead of accepting any key (MITM)
                proc = subprocess.Popen(
                    ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
                     "-R", f"80:127.0.0.1:{port}", "serveo.net"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, creationflags=flags
                )
                if not self._register_tunnel_proc("serveo_proc", proc, gen):
                    return
                self._log("[NETWORK] Starting Serveo SSH Tunnel...")
                for line in proc.stdout:
                    line = line.strip()
                    if "Forwarding HTTP traffic from" in line and gen == self._tunnel_generation():
                        url = line.split("from")[-1].strip()
                        self.serveo_url = url
                        self.dynamic_tunnel_url = url
                        self._log(f"[NETWORK] Serveo Tunnel Active: {url}")
                        self.after(0, self._refresh_all_endpoint_labels)
                        break
                # Keep draining stdout, otherwise ssh blocks once the pipe buffer is full
                for _ in proc.stdout:
                    pass
            except Exception as e:
                self._log(f"[NETWORK WARNING] Serveo tunnel trigger: {e}")
        threading.Thread(target=run_serveo, daemon=True).start()

    def _start_ngrok_tunnel(self, port: int):
        if self.__dict__.get("ngrok_proc", None) and self.ngrok_proc.poll() is None:
            return
        self.dynamic_tunnel_url = None
        gen = self._tunnel_generation()
        def run_ngrok():
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.Popen(
                    ["ngrok", "http", str(port)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags
                )
                if not self._register_tunnel_proc("ngrok_proc", proc, gen):
                    return
                self._log("[NETWORK] Starting ngrok Tunnel...")
                for _ in range(10):
                    time.sleep(1)
                    try:
                        resp = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
                        if resp.status_code == 200:
                            tunnels = resp.json().get("tunnels", [])
                            for t in tunnels:
                                if t.get("public_url", "").startswith("https://"):
                                    if gen != self._tunnel_generation():
                                        return
                                    url = t["public_url"]
                                    self.dynamic_tunnel_url = url
                                    self._log(f"[NETWORK] ngrok Tunnel Active: {url}")
                                    self.after(0, self._refresh_all_endpoint_labels)
                                    return
                    except Exception:
                        pass
                self._log("[NETWORK WARNING] Could not fetch ngrok URL from local API after 10s.")
            except Exception as e:
                self._log(f"[NETWORK WARNING] ngrok tunnel trigger: {e}")
        threading.Thread(target=run_ngrok, daemon=True).start()

    def _stop_server(self):
        if not self.is_server_running:
            return

        self._log("Stopping MCP server...")
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        else:
            self._handle_server_stopped()
            
        self._stop_all_tunnels()
        self.after(0, self._refresh_all_endpoint_labels)

    def _handle_server_stopped(self):
        if not self.is_server_running:
            return
        self.is_server_running = False
        self.server_start_time = None
        self.status_badge.configure(text="● Server Stopped", text_color="#EF4444")
        self.btn_toggle_server.configure(text="▶ START SERVER", fg_color=("#059669", "#10B981"), hover_color=("#047857", "#059669"))
        self._log("Server shutdown complete.")

    def _on_close(self, force: bool = False) -> bool:
        """Close the cockpit. Returns False if the user cancelled (app keeps running)."""
        if self.is_server_running:
            if not force and not messagebox.askyesno("Exit Cockpit", "The MCP server is currently running. Stop server and exit?", parent=self):
                return False  # keep running — hotkey stays registered
            self._stop_server()
            # os._exit below kills background threads, so turn the public funnel off synchronously
            if self.__dict__.get("_funnel_active", False):
                self._disable_tailscale_funnel()
        try:
            unregister_global_hotkey()
        except Exception:
            pass
        self.destroy()
        os._exit(0)

    def report_callback_exception(self, exc, val, tb):
        import traceback
        traceback.print_exception(exc, val, tb)
        if hasattr(self, "_log"):
            try:
                self._log(f"[ERROR] UI Callback Fehler: {val}")
            except Exception:
                pass


def main():
    try:
        app = MammouthControlCenter()
        app.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            from tkinter import messagebox
            messagebox.showerror("Mammouth Defroster Fehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}\n\nDetails im Konsolen-Log.")
        except Exception:
            pass
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
