import os
import sys
import re
import json
import time
import shutil
import socket
import logging
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Any, Optional, List

# If spawned in CLI / server-only mode, run headless server without GUI
if "--server-only" in sys.argv or "--cli" in sys.argv or "--headless" in sys.argv:
    import uvicorn
    # Add mcpserv to sys.path
    base_p = Path(__file__).parent
    if (base_p / "mcpserv").exists():
        sys.path.insert(0, str(base_p / "mcpserv"))
    elif (base_p / "modules").exists():
        sys.path.insert(0, str(base_p))
    from server import app, MCP_API_TOKEN
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info", use_colors=False)
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
import mss
from PIL import Image as PILImage

try:
    import win32crypt
except ImportError:
    pass

# Add project directories to sys.path
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if (BASE_DIR / "mcpserv").exists() and str(BASE_DIR / "mcpserv") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "mcpserv"))
if (BASE_DIR / "modules").exists() and str(BASE_DIR / "modules") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "modules"))

from config import load_config, save_config, get_lan_ip, generate_secure_token, CONFIG_FILE
from modules.putty_ssh import ssh_save_host, ssh_list_saved_hosts, ssh_open_putty_window, ssh_exec_command
from server import build_app, app

# Appearance setup
INITIAL_CONFIG = load_config()
INITIAL_MODE = INITIAL_CONFIG.get("server", {}).get("appearance_mode", "Dark")
ctk.set_appearance_mode(INITIAL_MODE)
ctk.set_default_color_theme("dark-blue")

HOSTS_FILE = BASE_DIR / "hosts.json"
APP_VERSION = "v0.2.0 Hardened"


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


class GuiLogHandler(logging.Handler):
    """Custom logging handler to route python/uvicorn logs directly to the GUI console."""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
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
        header_card = ctk.CTkFrame(self, fg_color=("#F8FAFC", "#111217"), border_width=1, border_color=("#CBD5E1", "#1E2029"), corner_radius=8)
        header_card.pack(fill="x", padx=20, pady=(15, 10))

        title_label = ctk.CTkLabel(header_card, text="🔑 Configure SSH Host Alias", font=ctk.CTkFont(size=18, weight="bold"), text_color=("#0F172A", "#F3F4F6"))
        title_label.pack(anchor="w", padx=15, pady=(10, 2))

        lbl_sec = ctk.CTkLabel(
            header_card,
            text="🔒 Passwords are encrypted at rest via Windows DPAPI before saving",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#059669", "#10B981")
        )
        lbl_sec.pack(anchor="w", padx=15, pady=(0, 10))

        form_frame = ctk.CTkFrame(self, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=8)
        form_frame.pack(padx=20, pady=5, fill="both", expand=True)

        # Alias
        ctk.CTkLabel(form_frame, text="Alias Name:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=0, column=0, padx=15, pady=8, sticky="w")
        self.entry_alias = ctk.CTkEntry(form_frame, placeholder_text="e.g. prod-server, vps-backup", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_alias.grid(row=0, column=1, padx=15, pady=8, sticky="ew")
        if alias:
            self.entry_alias.insert(0, alias)
            self.entry_alias.configure(state="disabled")

        # Host / IP
        ctk.CTkLabel(form_frame, text="Host / IP:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=1, column=0, padx=15, pady=8, sticky="w")
        self.entry_host = ctk.CTkEntry(form_frame, placeholder_text="e.g. 192.168.1.100 or node.example.com", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_host.grid(row=1, column=1, padx=15, pady=8, sticky="ew")

        # Port
        ctk.CTkLabel(form_frame, text="SSH Port:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=2, column=0, padx=15, pady=8, sticky="w")
        self.entry_port = ctk.CTkEntry(form_frame, placeholder_text="22", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_port.grid(row=2, column=1, padx=15, pady=8, sticky="ew")
        self.entry_port.insert(0, "22")

        # User
        ctk.CTkLabel(form_frame, text="Username:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=3, column=0, padx=15, pady=8, sticky="w")
        self.entry_user = ctk.CTkEntry(form_frame, placeholder_text="e.g. root, ubuntu, admin", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_user.grid(row=3, column=1, padx=15, pady=8, sticky="ew")
        self.entry_user.insert(0, "root")

        # Password
        ctk.CTkLabel(form_frame, text="Password:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=4, column=0, padx=15, pady=8, sticky="w")
        self.entry_pw = ctk.CTkEntry(form_frame, placeholder_text="(Optional - DPAPI Encrypted)", show="*", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_pw.grid(row=4, column=1, padx=15, pady=8, sticky="ew")

        # Key Path
        ctk.CTkLabel(form_frame, text="Private Key:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=5, column=0, padx=15, pady=8, sticky="w")
        key_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        key_box.grid(row=5, column=1, padx=15, pady=8, sticky="ew")
        self.entry_key = ctk.CTkEntry(key_box, placeholder_text="(Recommended: .ppk or id_rsa)", width=230, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_key.pack(side="left", fill="x", expand=True, padx=(0, 5))
        btn_browse = ctk.CTkButton(
            key_box,
            text="Browse",
            width=70,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._browse_key
        )
        btn_browse.pack(side="right")

        # Description
        ctk.CTkLabel(form_frame, text="Description:", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).grid(row=6, column=0, padx=15, pady=8, sticky="w")
        self.entry_desc = ctk.CTkEntry(form_frame, placeholder_text="Short description of this server", width=310, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
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
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
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


class MammouthControlCenter(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Mammouth Defroster 9000 🦣❄️🔥 ({APP_VERSION})")
        self.geometry("1140x840")
        self.minsize(1050, 740)
        self.configure(fg_color=("#F8FAFC", "#0A0A0C"))

        # Set window icon if present
        for icon_p in [BASE_DIR / "assets" / "icon.ico", BASE_DIR.parent / "assets" / "icon.ico"]:
            if icon_p.exists():
                try:
                    self.iconbitmap(str(icon_p))
                    break
                except Exception:
                    pass

        self.config_data = load_config()
        self.appearance_mode = self.config_data.get("server", {}).get("appearance_mode", "Dark")
        ctk.set_appearance_mode(self.appearance_mode)

        self.uvicorn_server = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_server_running = False
        self.dynamic_tunnel_url: Optional[str] = None
        self.server_start_time = None
        self.log_filter_mode = "ALL"

        self._setup_logging()
        self._build_ui()
        self._start_stats_timer()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_logging(self):
        handler = GuiLogHandler(lambda msg: self.after(0, self._log, msg))
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logging.getLogger("uvicorn").addHandler(handler)
        logging.getLogger("uvicorn.access").addHandler(handler)
        logging.getLogger("uvicorn.error").addHandler(handler)
        logging.getLogger("fastmcp").addHandler(handler)

    def _build_ui(self):
        # 1. Top Hero Header Banner
        header = ctk.CTkFrame(self, height=86, corner_radius=0, fg_color=("#F8FAFC", "#0F1014"), border_width=1, border_color=("#CBD5E1", "#1C1D24"))
        header.pack(fill="x", side="top")

        # App Logo & Title
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=(15, 5), pady=10)
        
        lbl_icon = ctk.CTkLabel(title_box, text="🦣🔥", font=ctk.CTkFont(size=34))
        lbl_icon.pack(side="left", padx=(0, 10))

        title_text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        title_text_box.pack(side="left")
        
        title_top_row = ctk.CTkFrame(title_text_box, fg_color="transparent")
        title_top_row.pack(anchor="w")
        
        lbl_title = ctk.CTkLabel(title_top_row, text="Mammouth Defroster 9000", font=ctk.CTkFont(size=19, weight="bold"), text_color=("#0F172A", "#F3F4F6"))
        lbl_title.pack(side="left", padx=(0, 8))

        # Version Pill Badge
        badge_ver = ctk.CTkFrame(title_top_row, fg_color=("#ECFDF5", "#12261C"), border_width=1, border_color=("#A7F3D0", "#1B4332"), corner_radius=6)
        badge_ver.pack(side="left")
        ctk.CTkLabel(badge_ver, text=f" {APP_VERSION} ", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#059669", "#10B981")).pack(padx=4, pady=1)

        lbl_subtitle = ctk.CTkLabel(
            title_text_box,
            text="❄️ Defrost Your Machine • Sovereign Neural Vision, Automation & UE5 Matrix",
            font=ctk.CTkFont(size=11),
            text_color=("#475569", "#9CA3AF")
        )
        lbl_subtitle.pack(anchor="w")

        # Top Right Controls: Theme Selector, Quick Web Launcher, Status badge & Big Start Button
        right_box = ctk.CTkFrame(header, fg_color="transparent")
        right_box.pack(side="right", padx=15, pady=10)

        # Quick Mammouth.ai Connect Button
        btn_open_mammouth = ctk.CTkButton(
            right_box,
            text="🌐 Mammouth",
            width=100,
            height=32,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=lambda: webbrowser.open("https://mammouth.ai")
        )
        btn_open_mammouth.pack(side="left", padx=(0, 8))

        # Theme Switcher
        theme_box = ctk.CTkFrame(right_box, fg_color="transparent")
        theme_box.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(theme_box, text="🎨 Theme:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#9CA3AF")).pack(anchor="w")
        self.theme_menu = ctk.CTkOptionMenu(
            theme_box,
            values=["Dark", "System", "Light"],
            width=85,
            height=28,
            fg_color=("#F1F5F9", "#1B1C24"),
            button_color=("#E2E8F0", "#262732"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E"),
            command=self._on_theme_changed
        )
        self.theme_menu.set(self.appearance_mode)
        self.theme_menu.pack(anchor="w")

        # Status badge frame
        status_box = ctk.CTkFrame(right_box, fg_color="transparent")
        status_box.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(status_box, text="Status:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("#475569", "#9CA3AF")).pack(anchor="w")
        self.status_badge = ctk.CTkLabel(
            status_box,
            text="● Server Stopped",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#EF4444"
        )
        self.status_badge.pack(anchor="w")

        # Main Power Toggle Button
        self.btn_toggle_server = ctk.CTkButton(
            right_box,
            text="▶ START SERVER",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#059669", "#10B981"),
            hover_color=("#047857", "#059669"),
            text_color="#FFFFFF",
            width=135,
            height=36,
            corner_radius=8,
            command=self.toggle_server
        )
        self.btn_toggle_server.pack(side="left")

        # 2. Main Tabview (With High Contrast Tabs in Light & Dark Mode)
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=10,
            fg_color=("#FFFFFF", "#0D0E12"),
            segmented_button_selected_color=("#059669", "#10B981"),
            segmented_button_selected_hover_color=("#047857", "#059669"),
            segmented_button_unselected_color=("#E2E8F0", "#1C1D24"),
            segmented_button_unselected_hover_color=("#CBD5E1", "#282A36"),
            segmented_button_fg_color=("#E2E8F0", "#14151B"),
            text_color=("#0F172A", "#F3F4F6")
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=10)

        # Explicitly configure segmented button for high contrast text on unselected tabs
        if hasattr(self.tabview, "_segmented_button"):
            self.tabview._segmented_button.configure(
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#0F172A", "#F3F4F6")
            )

        self.tab_dashboard = self.tabview.add("📊 Dashboard & Live Console")
        self.tab_skills = self.tabview.add("⚡ Modular Capabilities (9 Modules)")
        self.tab_hosts = self.tabview.add("🔑 SSH Fleet & PuTTY Manager")
        self.tab_settings = self.tabview.add("⚙️ Security & Settings")

        self._setup_dashboard_tab()
        self._setup_skills_tab()
        self._setup_hosts_tab()
        self._setup_settings_tab()

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
        # 1. Endpoint Card
        card = ctk.CTkFrame(self.tab_dashboard, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        card.pack(fill="x", padx=10, pady=(10, 8))

        # Mode Selection Bar inside Dashboard
        mode_bar = ctk.CTkFrame(card, fg_color="transparent")
        mode_bar.pack(fill="x", padx=15, pady=(12, 6))

        ctk.CTkLabel(mode_bar, text="Exposure Mode:", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        
        tunnel_modes = ["Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"]
        current_mode = self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel")
        self.dash_mode_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=tunnel_modes,
            width=170,
            fg_color=("#F1F5F9", "#1F2029"),
            button_color=("#E2E8F0", "#2A2B37"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E"),
            command=self._on_dash_mode_changed
        )
        self.dash_mode_menu.set(current_mode)
        self.dash_mode_menu.pack(side="left", padx=10)

        ctk.CTkLabel(mode_bar, text="Route Path:", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left", padx=(10, 5))
        paths = ["/sse", "/mcp", "/messages", "/"]
        current_path = self.config_data.get("server", {}).get("endpoint_path", "/sse")
        self.dash_path_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=paths,
            width=100,
            fg_color=("#F1F5F9", "#1F2029"),
            button_color=("#E2E8F0", "#2A2B37"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E"),
            command=self._on_dash_path_changed
        )
        self.dash_path_menu.set(current_path)
        self.dash_path_menu.pack(side="left")

        # Security Status Badges
        pills_box = ctk.CTkFrame(mode_bar, fg_color="transparent")
        pills_box.pack(side="right")

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
        
        self.lbl_primary_title = ctk.CTkLabel(row1, text="🌐 Public SSE URL:", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB"), width=160, anchor="w")
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
            fg_color=("#ECFDF5", "#14281E"),
            hover_color=("#D1FAE5", "#1C3D2D"),
            text_color=("#047857", "#10B981"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#A7F3D0", "#1E4B35"),
            command=self._manual_detect_tailscale
        )
        btn_detect_ts.pack(side="left", padx=3)

        btn_copy_pub = ctk.CTkButton(
            btn_box1,
            text="📋 Copy URL",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=lambda: self._copy_to_clipboard(self.lbl_public_url.cget("text"), "Public URL")
        )
        btn_copy_pub.pack(side="left", padx=3)

        btn_copy_key1 = ctk.CTkButton(
            btn_box1,
            text="📋 Copy Key",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=lambda: self._copy_to_clipboard(self.config_data.get("server", {}).get("api_token", ""), "Bearer Key")
        )
        btn_copy_key1.pack(side="left", padx=3)

        btn_copy_json = ctk.CTkButton(
            btn_box1,
            text="⚙️ MCP JSON",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._copy_mcp_client_config
        )
        btn_copy_json.pack(side="left", padx=3)

        # Localhost Endpoint Row
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(4, 12))
        
        ctk.CTkLabel(row2, text="💻 Localhost URL:", font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB"), width=160, anchor="w").pack(side="left")
        self.lbl_local_url = ctk.CTkLabel(row2, text=self._calculate_local_endpoint_url(), font=ctk.CTkFont(size=12), text_color=("#475569", "#9CA3AF"))
        self.lbl_local_url.pack(side="left", padx=10)
        
        btn_box2 = ctk.CTkFrame(row2, fg_color="transparent")
        btn_box2.pack(side="right")
        
        btn_copy_loc = ctk.CTkButton(
            btn_box2,
            text="📋 Copy URL",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=lambda: self._copy_to_clipboard(self.lbl_local_url.cget("text"), "Localhost URL")
        )
        btn_copy_loc.pack(side="left", padx=3)

        # 2. Fancy Live Telemetry & Progress Strip
        stats_strip = ctk.CTkFrame(self.tab_dashboard, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=8)
        stats_strip.pack(fill="x", padx=10, pady=(0, 6))

        stats_inner = ctk.CTkFrame(stats_strip, fg_color="transparent")
        stats_inner.pack(fill="x", padx=15, pady=8)

        # CPU Meter
        cpu_box = ctk.CTkFrame(stats_inner, fg_color="transparent")
        cpu_box.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self.lbl_stat_cpu = ctk.CTkLabel(cpu_box, text="💻 CPU: 0.0%", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#0F172A", "#E5E7EB"))
        self.lbl_stat_cpu.pack(anchor="w")
        self.bar_cpu = ctk.CTkProgressBar(cpu_box, height=8, progress_color="#10B981")
        self.bar_cpu.set(0.0)
        self.bar_cpu.pack(fill="x", pady=(2, 0))

        # RAM Meter
        ram_box = ctk.CTkFrame(stats_inner, fg_color="transparent")
        ram_box.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self.lbl_stat_ram = ctk.CTkLabel(ram_box, text="🧠 RAM: 0.0%", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#0F172A", "#E5E7EB"))
        self.lbl_stat_ram.pack(anchor="w")
        self.bar_ram = ctk.CTkProgressBar(ram_box, height=8, progress_color="#3B82F6")
        self.bar_ram.set(0.0)
        self.bar_ram.pack(fill="x", pady=(2, 0))

        # Active Tools
        tools_box = ctk.CTkFrame(stats_inner, fg_color="transparent")
        tools_box.pack(side="left", padx=(0, 15))
        self.lbl_stat_tools = ctk.CTkLabel(tools_box, text=f"⚡ Active Tools: {self._count_active_tools()}", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#059669", "#10B981"))
        self.lbl_stat_tools.pack(anchor="w", pady=(4, 0))

        # Uptime Clock
        uptime_box = ctk.CTkFrame(stats_inner, fg_color="transparent")
        uptime_box.pack(side="left")
        self.lbl_stat_uptime = ctk.CTkLabel(uptime_box, text="⏱️ Uptime: 00:00:00", font=ctk.CTkFont(size=12, weight="bold"), text_color=("#475569", "#9CA3AF"))
        self.lbl_stat_uptime.pack(anchor="w", pady=(4, 0))

        # 3. Quick Action Buttons Bar
        actions_bar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        actions_bar.pack(fill="x", padx=10, pady=(2, 6))

        btn_screen = ctk.CTkButton(
            actions_bar,
            text="📸 Capture Desktop",
            width=150,
            height=30,
            fg_color=("#EFF6FF", "#1C2130"),
            hover_color=("#DBEAFE", "#283046"),
            text_color=("#1D4ED8", "#E5E7EB"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#BFDBFE", "#2A324B"),
            command=self._test_screenshot
        )
        btn_screen.pack(side="left", padx=(0, 8))

        btn_ue = ctk.CTkButton(
            actions_bar,
            text="🎮 Ping UE5 [ALPHA]",
            width=170,
            height=30,
            fg_color=("#FAF5FF", "#251F33"),
            hover_color=("#F3E8FF", "#362C4A"),
            text_color=("#7E22CE", "#E5E7EB"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#E9D5FF", "#3C2F52"),
            command=self._test_unreal
        )
        btn_ue.pack(side="left", padx=(0, 8))

        btn_ws = ctk.CTkButton(
            actions_bar,
            text="📂 Open Workspace",
            width=150,
            height=30,
            fg_color=("#F0FDFA", "#1A2526"),
            hover_color=("#CCFBF1", "#253738"),
            text_color=("#0F766E", "#E5E7EB"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#99F6E4", "#294142"),
            command=self._open_workspace_folder
        )
        btn_ws.pack(side="left", padx=(0, 8))

        btn_export = ctk.CTkButton(
            actions_bar,
            text="💾 Save Log",
            width=100,
            height=30,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._export_logs
        )
        btn_export.pack(side="right", padx=(8, 0))

        btn_clear = ctk.CTkButton(
            actions_bar,
            text="🧹 Clear Logs",
            width=100,
            height=30,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._clear_logs
        )
        btn_clear.pack(side="right")

        # 4. Text Console with Cyber Monospace Styling
        self.log_textbox = ctk.CTkTextbox(
            self.tab_dashboard,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
            fg_color=("#FFFFFF", "#08090C"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#1C1D24"),
            corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._log(f"Mammouth Defroster 9000 {APP_VERSION} initialized. Sovereign Cockpit Ready.")

    def _count_active_tools(self) -> int:
        mods = self.config_data.get("modules", {})
        counts = {
            "memory": 5,
            "tasks_kanban": 4,
            "file_ops": 6,
            "shell_processes": 5,
            "putty_ssh": 6,
            "system_monitor": 4,
            "web_tools": 2,
            "screen_capture": 2,
            "unreal_engine": 23
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
                self.lbl_stat_cpu.configure(text=f"💻 CPU: {cpu:.1f}%")
                self.lbl_stat_ram.configure(text=f"🧠 RAM: {ram:.1f}%")
                self.bar_cpu.set(cpu / 100.0)
                self.bar_ram.set(ram / 100.0)
                
                if hasattr(self, "lbl_stat_tools"):
                    self.lbl_stat_tools.configure(text=f"⚡ Active Tools: {self._count_active_tools()}")

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
            from modules.screen_capture import screen_capture, screen_grant_consent
            res = screen_capture(monitor=1, save_to_workspace=True)
            if isinstance(res, dict) and res.get("status") == "consent_required":
                ask = messagebox.askyesno(
                    "Screen Capture Consent",
                    "Screen capture requires explicit user consent.\n\nGrant permission for screen capture?",
                    parent=self
                )
                if ask:
                    screen_grant_consent("always")
                    res = screen_capture(monitor=1, save_to_workspace=True)
                else:
                    self._log("[VISION] Screen capture cancelled by user.")
                    return

            saved_p = res.get("saved_path") if isinstance(res, dict) else None
            if saved_p and os.path.exists(saved_p):
                self._log(f"[VISION] Screenshot captured successfully: {saved_p}")
                os.startfile(saved_p)
            else:
                self._log(f"[VISION] Screenshot result: {res}")
        except Exception as e:
            self._log(f"[VISION ERROR] {e}")

    def _test_unreal(self):
        try:
            from modules.unreal_engine import unreal_ping
            res = unreal_ping()
            if res.get("connected"):
                node = res.get("node_id", "UE Editor")
                proj = res.get("project_root", "")
                self._log(f"[UNREAL ENGINE] 🎮 Connected! Node: {node} | Project: {proj}")
                messagebox.showinfo("Unreal Engine 5 Connected", f"Successfully connected to active Unreal Engine editor!\n\nNode ID: {node}\nProject: {proj}", parent=self)
            else:
                self._log(f"[UNREAL ENGINE] ⚠️ Ping result: {res.get('error', 'No active editor found')}")
                messagebox.showwarning("Unreal Engine Offline", "Could not reach Unreal Engine Editor.\n\nMake sure Unreal Engine is running and 'Python Remote Execution' is enabled in Project Settings.", parent=self)
        except Exception as e:
            self._log(f"[UNREAL ENGINE ERROR] {e}")

    def _on_dash_mode_changed(self, choice: str):
        self.config_data["server"]["tunnel_mode"] = choice
        self.opt_tunnel_mode.set(choice)
        save_config(self.config_data)
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
            ts_domain = get_tailscale_public_domain(cfg.get("tailscale_path", ""))
            if ts_domain:
                return f"{ts_domain}{path}"
            return f"https://[your-tailscale-node].ts.net{path}"

        elif mode == "Cloudflare Tunnel":
            if self.dynamic_tunnel_url:
                return f"{self.dynamic_tunnel_url.rstrip('/')}{path}"
            custom_cf = cfg.get("cloudflare_custom_url", "").strip()
            if custom_cf:
                return f"{custom_cf.rstrip('/')}{path}"
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

    def _manual_detect_tailscale(self):
        self._log("[DISCOVERY] Querying local Tailscale daemon for domain name...")
        cfg = self.config_data.get("server", {})
        domain = get_tailscale_public_domain(cfg.get("tailscale_path", ""))
        if domain:
            self._log(f"[DISCOVERY] Successfully detected Tailscale domain: {domain}")
            self._refresh_all_endpoint_labels()
            messagebox.showinfo("Tailscale Discovered", f"Successfully detected your Tailscale domain:\n\n{domain}", parent=self)
        else:
            self._log("[DISCOVERY WARNING] Could not detect active Tailscale domain. Ensure Tailscale is running and connected.")
            messagebox.showwarning("Tailscale Not Found", "Could not detect active Tailscale node.\n\nMake sure Tailscale is running and connected on this machine.", parent=self)

    def _copy_to_clipboard(self, text: str, label_name: str = "Item"):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log(f"[CLIPBOARD] Copied {label_name} to clipboard: {text}")
        messagebox.showinfo("Copied to Clipboard", f"Copied {label_name} to clipboard:\n\n{text}", parent=self)

    def _log(self, message: str):
        clean_msg = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(message))
        timestamp = time.strftime("[%H:%M:%S]")
        self.log_textbox.insert("end", f"{timestamp} {clean_msg}\n")
        self.log_textbox.see("end")

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")
        self._log("Console cleared.")

    # ---------------------------------------------------------
    # TAB 2: SKILLS & MODULES
    # ---------------------------------------------------------
    def _setup_skills_tab(self):
        top_bar = ctk.CTkFrame(self.tab_skills, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="⚡ Modular Defroster Capabilities", font=ctk.CTkFont(size=17, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Toggle individual tools dynamically exposed to Mammouth AI / connected models", font=ctk.CTkFont(size=12), text_color=("#475569", "#9CA3AF")).pack(anchor="w")

        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right")

        btn_enable_safe = ctk.CTkButton(
            btn_box,
            text="✅ Enable Safe Tools",
            width=140,
            height=32,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            font=ctk.CTkFont(weight="bold"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
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
            "file_ops": "📁",
            "shell_processes": "💻",
            "putty_ssh": "🔑",
            "system_monitor": "📊",
            "web_tools": "🌐",
            "screen_capture": "👁️",
            "unreal_engine": "🎮"
        }

        tool_counts = {
            "memory": "5 Tools",
            "tasks_kanban": "4 Tools",
            "file_ops": "6 Tools",
            "shell_processes": "5 Tools (Privileged)",
            "putty_ssh": "6 Tools",
            "system_monitor": "4 Tools",
            "web_tools": "2 Tools (SSRF Shield)",
            "screen_capture": "2 Tools",
            "unreal_engine": "23 Tools (ALPHA)"
        }

        for key, mod in modules.items():
            card = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=12, fill="x", expand=True)

            icon = icons.get(key, "⚙️")
            cnt = tool_counts.get(key, "Tools")
            
            title_row = ctk.CTkFrame(left, fg_color="transparent")
            title_row.pack(anchor="w")

            disp_name = f"{icon}  {mod.get('name', key)}"
            if key == "unreal_engine" and "ALPHA" not in disp_name:
                disp_name += "  [ALPHA]"

            lbl_name = ctk.CTkLabel(title_row, text=disp_name, font=ctk.CTkFont(size=14, weight="bold"), text_color=("#0F172A", "#F3F4F6"))
            lbl_name.pack(side="left")

            if key == "unreal_engine":
                badge_alpha = ctk.CTkFrame(title_row, fg_color=("#FEF3C7", "#2D2214"), border_width=1, border_color=("#FDE68A", "#4E371C"), corner_radius=5)
                badge_alpha.pack(side="left", padx=6)
                ctk.CTkLabel(badge_alpha, text=" EXPERIMENTAL ", font=ctk.CTkFont(size=10, weight="bold"), text_color=("#B45309", "#F59E0B")).pack(padx=4, pady=1)

            badge_cnt = ctk.CTkFrame(title_row, fg_color=("#F1F5F9", "#1C1D24"), border_width=1, border_color=("#E2E8F0", "#2A2B37"), corner_radius=5)
            badge_cnt.pack(side="left", padx=6)
            ctk.CTkLabel(badge_cnt, text=f" {cnt} ", font=ctk.CTkFont(size=11), text_color=("#475569", "#9CA3AF")).pack(padx=4, pady=1)

            lbl_desc = ctk.CTkLabel(left, text=mod.get("description", ""), font=ctk.CTkFont(size=12), text_color=("#475569", "#9CA3AF"), anchor="w")
            lbl_desc.pack(anchor="w", pady=(4, 0))

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

        save_config(self.config_data)
        self._log("Updated module configuration in config.json.")
        if hasattr(self, "lbl_stat_tools"):
            self.lbl_stat_tools.configure(text=f"⚡ Active Tools: {self._count_active_tools()}")
        if self.is_server_running:
            messagebox.showinfo("Saved", "Skills configuration saved!\n\nNote: Please restart the server for active tool updates to take effect.", parent=self)
        else:
            messagebox.showinfo("Saved", "Skills configuration saved successfully!", parent=self)

    # ---------------------------------------------------------
    # TAB 3: SSH HOST MANAGER
    # ---------------------------------------------------------
    def _setup_hosts_tab(self):
        top_bar = ctk.CTkFrame(self.tab_hosts, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Configured SSH Servers & PuTTY Aliases", font=ctk.CTkFont(size=17, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w")
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
            empty_card = ctk.CTkFrame(self.hosts_scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
            empty_card.pack(fill="x", pady=20, padx=10)
            ctk.CTkLabel(
                empty_card,
                text="No remote SSH hosts configured yet.\nClick '➕ Add Server' above to configure server login profiles for plink / pscp.",
                font=ctk.CTkFont(size=13),
                text_color=("#475569", "#9CA3AF")
            ).pack(padx=20, pady=25)
            return

        for alias, info in hosts.items():
            card = ctk.CTkFrame(self.hosts_scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=12, fill="x", expand=True)

            host_row = ctk.CTkFrame(left, fg_color="transparent")
            host_row.pack(anchor="w")

            host_str = f"🐧 {alias}  —  {info.get('username', 'root')}@{info.get('host', 'localhost')}:{info.get('port', 22)}"
            ctk.CTkLabel(host_row, text=host_str, font=ctk.CTkFont(size=14, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(side="left")

            has_pw = str(info.get("password", "")).strip() != ""
            if has_pw:
                badge_sec = ctk.CTkFrame(host_row, fg_color=("#ECFDF5", "#13281E"), border_width=1, border_color=("#A7F3D0", "#1B4332"), corner_radius=5)
                badge_sec.pack(side="left", padx=8)
                ctk.CTkLabel(badge_sec, text=" 🔒 DPAPI Protected ", font=ctk.CTkFont(size=10, weight="bold"), text_color=("#047857", "#10B981")).pack(padx=3, pady=1)

            desc = info.get("description") or "No description"
            has_key = f"Key: {Path(info.get('private_key_path', '')).name}" if info.get("private_key_path") else "No key file"
            subtext = f"{desc} | {has_key}"
            ctk.CTkLabel(left, text=subtext, font=ctk.CTkFont(size=12), text_color=("#475569", "#9CA3AF"), anchor="w").pack(anchor="w", pady=(4, 0))

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
                fg_color=("#EFF6FF", "#1C2130"),
                hover_color=("#DBEAFE", "#283046"),
                text_color=("#1D4ED8", "#E5E7EB"),
                font=ctk.CTkFont(weight="bold"),
                border_width=1,
                border_color=("#BFDBFE", "#2A324B"),
                command=lambda a=alias, d=info: self._edit_host(a, d)
            )
            btn_edit.pack(side="left", padx=3)

            btn_del = ctk.CTkButton(
                btn_box,
                text="Delete",
                width=65,
                height=28,
                fg_color=("#FEF2F2", "#2B191B"),
                hover_color=("#FEE2E2", "#3D2024"),
                text_color=("#DC2626", "#F87171"),
                font=ctk.CTkFont(weight="bold"),
                border_width=1,
                border_color=("#FECACA", "#48262C"),
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
        net_group = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        net_group.pack(fill="x", pady=6)

        ctk.CTkLabel(net_group, text="🌐 Network & Server Binding", font=ctk.CTkFont(size=15, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w", padx=15, pady=(15, 10))

        f1 = ctk.CTkFrame(net_group, fg_color="transparent")
        f1.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f1, text="Server Port:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.entry_port = ctk.CTkEntry(f1, width=120, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_port.insert(0, str(self.config_data.get("server", {}).get("port", 8000)))
        self.entry_port.pack(side="left")

        f2 = ctk.CTkFrame(net_group, fg_color="transparent")
        f2.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f2, text="Bind Address:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.opt_host = ctk.CTkOptionMenu(
            f2,
            values=["127.0.0.1", "0.0.0.0"],
            width=120,
            fg_color=("#F1F5F9", "#1F2029"),
            button_color=("#E2E8F0", "#2A2B37"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E")
        )
        self.opt_host.set(self.config_data.get("server", {}).get("host", "127.0.0.1"))
        self.opt_host.pack(side="left")

        f3 = ctk.CTkFrame(net_group, fg_color="transparent")
        f3.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(f3, text="Default Tunnel Mode:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.opt_tunnel_mode = ctk.CTkOptionMenu(
            f3,
            values=["Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"],
            width=180,
            fg_color=("#F1F5F9", "#1F2029"),
            button_color=("#E2E8F0", "#2A2B37"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E"),
            command=self._on_settings_mode_changed
        )
        self.opt_tunnel_mode.set(self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel"))
        self.opt_tunnel_mode.pack(side="left")

        f4 = ctk.CTkFrame(net_group, fg_color="transparent")
        f4.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f4, text="Default Route Path:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.opt_endpoint_path = ctk.CTkOptionMenu(
            f4,
            values=["/sse", "/mcp", "/messages", "/"],
            width=120,
            fg_color=("#F1F5F9", "#1F2029"),
            button_color=("#E2E8F0", "#2A2B37"),
            button_hover_color=("#CBD5E1", "#333544"),
            text_color=("#0F172A", "#F3F4F6"),
            dropdown_fg_color=("#FFFFFF", "#14151B"),
            dropdown_text_color=("#0F172A", "#F3F4F6"),
            dropdown_hover_color=("#F1F5F9", "#22242E")
        )
        self.opt_endpoint_path.set(self.config_data.get("server", {}).get("endpoint_path", "/sse"))
        self.opt_endpoint_path.pack(side="left")

        # 2. Authentication & Tokens Group (Secure by Default)
        auth_group = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        auth_group.pack(fill="x", pady=6)

        ctk.CTkLabel(auth_group, text="🔒 Authentication & API Tokens (Secure by Default)", font=ctk.CTkFont(size=15, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w", padx=15, pady=(15, 10))

        f5 = ctk.CTkFrame(auth_group, fg_color="transparent")
        f5.pack(fill="x", padx=15, pady=5)
        self.var_enforce_auth = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enforce_auth", True))
        sw_auth = ctk.CTkSwitch(f5, text="Require Bearer Token Authentication (Authorization Header)", variable=self.var_enforce_auth, font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB"), progress_color="#10B981")
        sw_auth.pack(side="left")

        f6 = ctk.CTkFrame(auth_group, fg_color="transparent")
        f6.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f6, text="Active Bearer Token:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.entry_token = ctk.CTkEntry(f6, width=280, show="*", fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_token.insert(0, self.config_data.get("server", {}).get("api_token", ""))
        self.entry_token.pack(side="left", padx=(0, 5))

        self.btn_show_token = ctk.CTkButton(
            f6,
            text="👁️",
            width=36,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._toggle_token_visibility
        )
        self.btn_show_token.pack(side="left", padx=(0, 5))

        self.btn_copy_tok = ctk.CTkButton(
            f6,
            text="📋 Copy Key",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=lambda: self._copy_to_clipboard(self.entry_token.get(), "Bearer Key")
        )
        self.btn_copy_tok.pack(side="left", padx=(0, 5))

        btn_gen_tok = ctk.CTkButton(
            f6,
            text="🎲 Generate",
            width=95,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._generate_new_token
        )
        btn_gen_tok.pack(side="left")

        # 3. Shell Execution & Administrative Permissions (Defense-in-Depth)
        shell_group = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        shell_group.pack(fill="x", pady=6)

        ctk.CTkLabel(shell_group, text="💻 Shell & Execution Permissions", font=ctk.CTkFont(size=15, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w", padx=15, pady=(15, 10))

        f_sh1 = ctk.CTkFrame(shell_group, fg_color="transparent")
        f_sh1.pack(fill="x", padx=15, pady=(5, 15))
        self.var_admin_shell = ctk.BooleanVar(value=self.config_data.get("server", {}).get("allow_admin_shell", False))
        sw_admin_shell = ctk.CTkSwitch(
            f_sh1,
            text="Allow Administrative Shell Execution (Set-*, New-*, Remove-*, sc, schtasks)",
            variable=self.var_admin_shell,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0F172A", "#E5E7EB"),
            progress_color="#EF4444",
            command=self._on_admin_shell_toggle
        )
        sw_admin_shell.pack(side="left")

        # 4. Workspace & Sandbox Security Group
        ws_group = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        ws_group.pack(fill="x", pady=6)

        ctk.CTkLabel(ws_group, text="📁 Workspace & Sandboxing Security", font=ctk.CTkFont(size=15, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w", padx=15, pady=(15, 10))

        f_ws1 = ctk.CTkFrame(ws_group, fg_color="transparent")
        f_ws1.pack(fill="x", padx=15, pady=5)
        self.var_sandbox = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enforce_workspace_sandbox", True))
        sw_sandbox = ctk.CTkSwitch(f_ws1, text="Enforce Workspace Sandbox (Restricts file access to ./workspace)", variable=self.var_sandbox, font=ctk.CTkFont(size=13, weight="bold"), text_color=("#0F172A", "#E5E7EB"), progress_color="#10B981")
        sw_sandbox.pack(side="left")

        f_ws2 = ctk.CTkFrame(ws_group, fg_color="transparent")
        f_ws2.pack(fill="x", padx=15, pady=(5, 15))
        ctk.CTkLabel(f_ws2, text="Workspace Path:", width=160, anchor="w", font=ctk.CTkFont(weight="bold"), text_color=("#0F172A", "#E5E7EB")).pack(side="left")
        self.entry_workspace = ctk.CTkEntry(f_ws2, width=280, fg_color=("#F8FAFC", "#0D0E12"), border_color=("#CBD5E1", "#22242E"), text_color=("#0F172A", "#F3F4F6"))
        self.entry_workspace.insert(0, str(self.config_data.get("server", {}).get("workspace_root", "./workspace")))
        self.entry_workspace.pack(side="left", padx=(0, 5))

        btn_browse_ws = ctk.CTkButton(
            f_ws2,
            text="📂 Browse",
            width=85,
            height=28,
            fg_color=("#F1F5F9", "#1E2028"),
            hover_color=("#E2E8F0", "#282A36"),
            text_color=("#0F172A", "#F3F4F6"),
            border_width=1,
            border_color=("#CBD5E1", "#2A2C38"),
            command=self._browse_workspace
        )
        btn_browse_ws.pack(side="left")

        # 5. LAN TLS Encryption Group
        tls_group = ctk.CTkFrame(scroll, fg_color=("#FFFFFF", "#14151B"), border_width=1, border_color=("#CBD5E1", "#22242E"), corner_radius=10)
        tls_group.pack(fill="x", pady=6)

        ctk.CTkLabel(tls_group, text="🛡️ LAN HTTPS / TLS Encryption", font=ctk.CTkFont(size=15, weight="bold"), text_color=("#0F172A", "#F3F4F6")).pack(anchor="w", padx=15, pady=(15, 10))

        f_tls1 = ctk.CTkFrame(tls_group, fg_color="transparent")
        f_tls1.pack(fill="x", padx=15, pady=(5, 15))
        self.var_enable_tls = ctk.BooleanVar(value=self.config_data.get("server", {}).get("enable_tls", False))
        sw_tls = ctk.CTkSwitch(
            f_tls1,
            text="Enable Local HTTPS TLS (Uses auto-generated cert.pem if missing)",
            variable=self.var_enable_tls,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0F172A", "#E5E7EB"),
            progress_color="#10B981"
        )
        sw_tls.pack(side="left")

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

    def _on_settings_mode_changed(self, choice: str):
        self.dash_mode_menu.set(choice)

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
        self.config_data["server"]["api_token"] = self.entry_token.get().strip()
        self.config_data["server"]["allow_admin_shell"] = self.var_admin_shell.get()
        self.config_data["server"]["enable_tls"] = self.var_enable_tls.get()
        self.config_data["server"]["enforce_workspace_sandbox"] = self.var_sandbox.get()
        self.config_data["server"]["workspace_root"] = self.entry_workspace.get().strip() or "./workspace"

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

        self._log(f"Starting in-process FastMCP server on {host}:{port}...")

        # Activate Tailscale Funnel in background if configured
        if self.config_data.get("server", {}).get("tunnel_mode") == "Tailscale Funnel" and self.config_data.get("server", {}).get("auto_tunnel", False):
            ts_path = self.config_data.get("server", {}).get("tailscale_path", r"C:\Program Files\Tailscale\tailscale.exe")
            ts_bin = find_tailscale_binary(ts_path)
            if ts_bin:
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.Popen([ts_bin, "funnel", "--bg", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                    self._log("[NETWORK] Tailscale Funnel background trigger executed.")
                except Exception as e:
                    self._log(f"[NETWORK WARNING] Tailscale funnel trigger: {e}")

        try:
            import uvicorn
            from server import generate_self_signed_cert

            enable_tls = bool(self.config_data.get("server", {}).get("enable_tls", False))
            cert_file = self.config_data.get("server", {}).get("ssl_certfile")
            key_file = self.config_data.get("server", {}).get("ssl_keyfile")

            if enable_tls and (not cert_file or not os.path.exists(str(cert_file))):
                default_cert = str(Path(__file__).parent / "cert.pem")
                default_key = str(Path(__file__).parent / "key.pem")
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
                "use_colors": False
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
        except Exception as e:
            self._log(f"[ERROR] Failed to start server: {e}")
            messagebox.showerror("Start Error", f"Failed to start server:\n\n{e}", parent=self)

    def _stop_server(self):
        if not self.is_server_running:
            return

        self._log("Stopping MCP server...")
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        self._handle_server_stopped()

    def _handle_server_stopped(self):
        self.is_server_running = False
        self.server_start_time = None
        self.status_badge.configure(text="● Server Stopped", text_color="#EF4444")
        self.btn_toggle_server.configure(text="▶ START SERVER", fg_color=("#059669", "#10B981"), hover_color=("#047857", "#059669"))
        self._log("Server shutdown complete.")

    def _on_close(self):
        if self.is_server_running:
            if messagebox.askyesno("Exit Cockpit", "The MCP server is currently running. Stop server and exit?", parent=self):
                self._stop_server()
                self.destroy()
        else:
            self.destroy()


def main():
    app = MammouthControlCenter()
    app.mainloop()


if __name__ == "__main__":
    main()
