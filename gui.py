import os
import sys
import re
import json
import time
import shutil
import socket
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog

# Add project directory to sys.path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from config import load_config, save_config, get_lan_ip, CONFIG_FILE

# Appearance setup
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

HOSTS_FILE = BASE_DIR / "hosts.json"


def get_tailscale_public_domain(tailscale_path: str = r"C:\Program Files\Tailscale\tailscale.exe") -> Optional[str]:
    """Attempt to detect the machine's Tailscale domain name."""
    ts_bin = shutil.which("tailscale") or tailscale_path
    if not os.path.exists(ts_bin) and not shutil.which("tailscale"):
        return None
    try:
        proc = subprocess.run([ts_bin, "status", "--json"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            self_node = data.get("Self", {})
            dns_name = self_node.get("DNSName", "").rstrip(".")
            if dns_name:
                return f"https://{dns_name}"
    except Exception:
        pass
    return None


class HostDialog(ctk.CTkToplevel):
    """Modal dialog for adding or editing an SSH host."""
    def __init__(self, parent, host_data: Optional[Dict[str, Any]] = None, alias: str = ""):
        super().__init__(parent)
        self.title("Edit SSH Host" if alias else "Add New SSH Host")
        self.geometry("520x560")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None
        self.original_alias = alias

        # Header
        title_label = ctk.CTkLabel(self, text="Configure SSH Host Alias", font=ctk.CTkFont(size=18, weight="bold"))
        title_label.pack(padx=20, pady=(15, 10))

        form_frame = ctk.CTkFrame(self)
        form_frame.pack(padx=20, pady=10, fill="both", expand=True)

        # Alias
        ctk.CTkLabel(form_frame, text="Alias Name:").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.entry_alias = ctk.CTkEntry(form_frame, placeholder_text="e.g. prod-server, vps-backup", width=280)
        self.entry_alias.grid(row=0, column=1, padx=10, pady=6, sticky="ew")
        if alias:
            self.entry_alias.insert(0, alias)
            if alias:
                self.entry_alias.configure(state="disabled")

        # Host / IP
        ctk.CTkLabel(form_frame, text="Host / IP:").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.entry_host = ctk.CTkEntry(form_frame, placeholder_text="e.g. 192.168.1.100 or node.domain.com", width=280)
        self.entry_host.grid(row=1, column=1, padx=10, pady=6, sticky="ew")

        # Port
        ctk.CTkLabel(form_frame, text="Port:").grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.entry_port = ctk.CTkEntry(form_frame, placeholder_text="22", width=280)
        self.entry_port.grid(row=2, column=1, padx=10, pady=6, sticky="ew")
        self.entry_port.insert(0, "22")

        # Username
        ctk.CTkLabel(form_frame, text="Username:").grid(row=3, column=0, padx=10, pady=6, sticky="w")
        self.entry_user = ctk.CTkEntry(form_frame, placeholder_text="e.g. root, ubuntu", width=280)
        self.entry_user.grid(row=3, column=1, padx=10, pady=6, sticky="ew")
        self.entry_user.insert(0, "root")

        # Password
        ctk.CTkLabel(form_frame, text="Password:").grid(row=4, column=0, padx=10, pady=6, sticky="w")
        self.entry_pw = ctk.CTkEntry(form_frame, placeholder_text="(Optional password)", show="*", width=280)
        self.entry_pw.grid(row=4, column=1, padx=10, pady=6, sticky="ew")

        # Key Path
        ctk.CTkLabel(form_frame, text="Private Key:").grid(row=5, column=0, padx=10, pady=6, sticky="w")
        key_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        key_box.grid(row=5, column=1, padx=10, pady=6, sticky="ew")
        self.entry_key = ctk.CTkEntry(key_box, placeholder_text="(Path to .ppk or id_rsa)", width=210)
        self.entry_key.pack(side="left", fill="x", expand=True, padx=(0, 5))
        btn_browse = ctk.CTkButton(key_box, text="Browse", width=65, command=self._browse_key)
        btn_browse.pack(side="right")

        # Description
        ctk.CTkLabel(form_frame, text="Description:").grid(row=6, column=0, padx=10, pady=6, sticky="w")
        self.entry_desc = ctk.CTkEntry(form_frame, placeholder_text="Short description of this server", width=280)
        self.entry_desc.grid(row=6, column=1, padx=10, pady=6, sticky="ew")

        if host_data:
            self.entry_host.delete(0, "end")
            self.entry_host.insert(0, host_data.get("host", ""))
            self.entry_port.delete(0, "end")
            self.entry_port.insert(0, str(host_data.get("port", 22)))
            self.entry_user.delete(0, "end")
            self.entry_user.insert(0, host_data.get("username", "root"))
            self.entry_pw.delete(0, "end")
            self.entry_pw.insert(0, host_data.get("password", ""))
            self.entry_key.delete(0, "end")
            self.entry_key.insert(0, host_data.get("private_key_path", ""))
            self.entry_desc.delete(0, "end")
            self.entry_desc.insert(0, host_data.get("description", ""))

        # Button row
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=(10, 15), fill="x")

        btn_cancel = ctk.CTkButton(btn_frame, text="Cancel", fg_color="#4B5563", hover_color="#374151", command=self.destroy)
        btn_cancel.pack(side="right", padx=(10, 0))

        btn_save = ctk.CTkButton(btn_frame, text="Save Host", fg_color="#10B981", hover_color="#059669", command=self._on_save)
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
        self.title("Mammouth AI — MCP Control Center")
        self.geometry("1000x740")
        self.minsize(900, 660)

        self.config_data = load_config()
        self.server_process: Optional[subprocess.Popen] = None
        self.tunnel_process: Optional[subprocess.Popen] = None
        self.server_thread: Optional[threading.Thread] = None
        self.tunnel_thread: Optional[threading.Thread] = None
        self.log_stream_active = False
        self.dynamic_tunnel_url: Optional[str] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 1. Top Header Banner
        header = ctk.CTkFrame(self, height=75, corner_radius=0, fg_color="#1E293B")
        header.pack(fill="x", side="top")

        # App Logo & Title
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=10)
        
        lbl_icon = ctk.CTkLabel(title_box, text="🦣", font=ctk.CTkFont(size=30))
        lbl_icon.pack(side="left", padx=(0, 10))

        title_text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        title_text_box.pack(side="left")
        lbl_title = ctk.CTkLabel(title_text_box, text="Mammouth Control Center", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_title.pack(anchor="w")
        lbl_subtitle = ctk.CTkLabel(title_text_box, text="FastMCP Server & DevOps Toolset for Windows 11", font=ctk.CTkFont(size=12), text_color="#94A3B8")
        lbl_subtitle.pack(anchor="w")

        # Top Right Controls: Status badge & Toggle Server Button
        right_box = ctk.CTkFrame(header, fg_color="transparent")
        right_box.pack(side="right", padx=20, pady=10)

        self.status_badge = ctk.CTkLabel(
            right_box,
            text="● Server Stopped",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#EF4444"
        )
        self.status_badge.pack(side="left", padx=(0, 15))

        self.btn_toggle_server = ctk.CTkButton(
            right_box,
            text="▶ Start Server",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            width=140,
            height=36,
            command=self.toggle_server
        )
        self.btn_toggle_server.pack(side="left")

        # 2. Main Tabview
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=15)

        self.tab_dashboard = self.tabview.add("📊 Dashboard & Logs")
        self.tab_skills = self.tabview.add("⚡ Skills & Modules")
        self.tab_hosts = self.tabview.add("🔑 SSH Host Manager")
        self.tab_settings = self.tabview.add("⚙️ Settings & Guide")

        self._setup_dashboard_tab()
        self._setup_skills_tab()
        self._setup_hosts_tab()
        self._setup_settings_tab()

    # ---------------------------------------------------------
    # TAB 1: DASHBOARD & LIVE LOGS
    # ---------------------------------------------------------
    def _setup_dashboard_tab(self):
        # Endpoints Info Card
        card = ctk.CTkFrame(self.tab_dashboard, fg_color="#1E293B", corner_radius=8)
        card.pack(fill="x", padx=10, pady=(10, 10))

        # Mode Selection Bar inside Dashboard
        mode_bar = ctk.CTkFrame(card, fg_color="transparent")
        mode_bar.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(mode_bar, text="Exposure Mode:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        
        tunnel_modes = ["Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"]
        current_mode = self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel")
        self.dash_mode_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=tunnel_modes,
            width=180,
            command=self._on_dash_mode_changed
        )
        self.dash_mode_menu.set(current_mode)
        self.dash_mode_menu.pack(side="left", padx=10)

        # Endpoint Path Selector
        ctk.CTkLabel(mode_bar, text="Path:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(10, 5))
        paths = ["/sse", "/mcp", "/messages", "/"]
        current_path = self.config_data.get("server", {}).get("endpoint_path", "/sse")
        self.dash_path_menu = ctk.CTkOptionMenu(
            mode_bar,
            values=paths,
            width=110,
            command=self._on_dash_path_changed
        )
        self.dash_path_menu.set(current_path)
        self.dash_path_menu.pack(side="left")

        # Primary Endpoint Row
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(5, 5))
        self.lbl_primary_title = ctk.CTkLabel(row1, text="🌐 Public SSE Endpoint:", font=ctk.CTkFont(size=13, weight="bold"), width=170, anchor="w")
        self.lbl_primary_title.pack(side="left")
        self.lbl_public_url = ctk.CTkLabel(row1, text=self._calculate_active_endpoint_url(), font=ctk.CTkFont(size=13, weight="bold"), text_color="#38BDF8")
        self.lbl_public_url.pack(side="left", padx=10)
        btn_copy_pub = ctk.CTkButton(row1, text="📋 Copy", width=70, height=26, command=lambda: self._copy_to_clipboard(self.lbl_public_url.cget("text")))
        btn_copy_pub.pack(side="right")

        # Localhost Endpoint Row
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(5, 10))
        ctk.CTkLabel(row2, text="💻 Localhost Endpoint:", font=ctk.CTkFont(size=13, weight="bold"), width=170, anchor="w").pack(side="left")
        port = self.config_data.get("server", {}).get("port", 8000)
        path = self.config_data.get("server", {}).get("endpoint_path", "/sse")
        self.lbl_local_url = ctk.CTkLabel(row2, text=f"http://127.0.0.1:{port}{path}", font=ctk.CTkFont(size=13), text_color="#94A3B8")
        self.lbl_local_url.pack(side="left", padx=10)
        btn_copy_loc = ctk.CTkButton(row2, text="📋 Copy", width=70, height=26, command=lambda: self._copy_to_clipboard(self.lbl_local_url.cget("text")))
        btn_copy_loc.pack(side="right")

        # Console Header
        console_bar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        console_bar.pack(fill="x", padx=10, pady=(5, 2))
        ctk.CTkLabel(console_bar, text="Live Server Logs & MCP Activity", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        
        btn_clear = ctk.CTkButton(console_bar, text="Clear Logs", width=90, height=26, fg_color="#4B5563", hover_color="#374151", command=self._clear_logs)
        btn_clear.pack(side="right")

        # Text Console
        self.log_textbox = ctk.CTkTextbox(
            self.tab_dashboard,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
            fg_color="#0F172A"
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._log("System initialized. Select your tunnel mode and click '▶ Start Server'.")

    def _on_dash_mode_changed(self, choice: str):
        self.config_data["server"]["tunnel_mode"] = choice
        save_config(self.config_data)
        self._refresh_all_endpoint_labels()
        self._log(f"Switched exposure mode to: {choice}")

    def _on_dash_path_changed(self, choice: str):
        self.config_data["server"]["endpoint_path"] = choice
        save_config(self.config_data)
        self._refresh_all_endpoint_labels()
        self._log(f"Switched endpoint route path to: {choice}")

    def _calculate_active_endpoint_url(self) -> str:
        cfg = self.config_data.get("server", {})
        mode = cfg.get("tunnel_mode", "Tailscale Funnel")
        path = cfg.get("endpoint_path", "/sse")
        port = cfg.get("port", 8000)

        if mode == "Tailscale Funnel":
            ts_domain = get_tailscale_public_domain(cfg.get("tailscale_path", ""))
            if ts_domain:
                return f"{ts_domain}{path}"
            return f"http://127.0.0.1:{port}{path} (Tailscale not connected)"

        elif mode == "Cloudflare Tunnel":
            if self.dynamic_tunnel_url:
                return f"{self.dynamic_tunnel_url.rstrip('/')}{path}"
            custom_cf = cfg.get("cloudflare_custom_url", "").strip()
            if custom_cf:
                return f"{custom_cf.rstrip('/')}{path}"
            return f"https://[your-tunnel].trycloudflare.com{path} (Start server to activate)"

        elif mode == "ngrok":
            custom_ng = cfg.get("ngrok_custom_url", "").strip()
            if custom_ng:
                return f"{custom_ng.rstrip('/')}{path}"
            return f"https://[your-domain].ngrok-free.app{path} (Start server to activate)"

        elif mode == "Direct / LAN IP":
            bind_host = cfg.get("host", "127.0.0.1")
            lan_ip = get_lan_ip()
            target_ip = lan_ip if bind_host in ["0.0.0.0", lan_ip] else "127.0.0.1"
            return f"http://{target_ip}:{port}{path}"

        elif mode == "Custom Domain":
            custom = cfg.get("custom_public_url", "").strip()
            if custom:
                return f"{custom.rstrip('/')}{path}"
            return f"http://127.0.0.1:{port}{path} (Enter custom URL in Settings)"

        return f"http://127.0.0.1:{port}{path}"

    def _refresh_all_endpoint_labels(self):
        url = self._calculate_active_endpoint_url()
        self.lbl_public_url.configure(text=url)
        port = self.config_data.get("server", {}).get("port", 8000)
        path = self.config_data.get("server", {}).get("endpoint_path", "/sse")
        self.lbl_local_url.configure(text=f"http://127.0.0.1:{port}{path}")
        mode = self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel")
        self.lbl_primary_title.configure(text=f"🌐 {mode}:")

    def _log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_textbox.insert("end", f"[{timestamp}] {text}\n")
        self.log_textbox.see("end")

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"Copied endpoint URL to clipboard:\n\n{text}")

    # ---------------------------------------------------------
    # TAB 2: SKILLS & MODULES
    # ---------------------------------------------------------
    def _setup_skills_tab(self):
        top_bar = ctk.CTkFrame(self.tab_skills, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        ctk.CTkLabel(top_bar, text="Modular MCP Toolsets (Enable / Disable)", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        
        btn_save_skills = ctk.CTkButton(top_bar, text="💾 Save Active Skills", fg_color="#10B981", hover_color="#059669", command=self._save_skills)
        btn_save_skills.pack(side="right")

        # Scrollable container for modules
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
            "web_tools": "🌐"
        }

        for key, mod in modules.items():
            card = ctk.CTkFrame(scroll, fg_color="#1E293B", corner_radius=8)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=10, fill="x", expand=True)

            icon = icons.get(key, "⚙️")
            lbl_name = ctk.CTkLabel(left, text=f"{icon}  {mod.get('name', key)}", font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
            lbl_name.pack(anchor="w")

            lbl_desc = ctk.CTkLabel(left, text=mod.get("description", ""), font=ctk.CTkFont(size=12), text_color="#94A3B8", anchor="w")
            lbl_desc.pack(anchor="w", pady=(3, 0))

            switch_var = ctk.BooleanVar(value=mod.get("enabled", True))
            switch = ctk.CTkSwitch(card, text="Active", variable=switch_var, font=ctk.CTkFont(size=13, weight="bold"))
            switch.pack(side="right", padx=20, pady=10)

            self.module_switches[key] = switch_var

    def _save_skills(self):
        for key, var in self.module_switches.items():
            if key in self.config_data["modules"]:
                self.config_data["modules"][key]["enabled"] = var.get()

        save_config(self.config_data)
        self._log("Updated module configuration in config.json.")
        if self.server_process:
            messagebox.showinfo("Saved", "Skills configuration saved!\n\nNote: Please restart the server for module changes to take effect.")
        else:
            messagebox.showinfo("Saved", "Skills configuration saved successfully!")

    # ---------------------------------------------------------
    # TAB 3: SSH HOST MANAGER
    # ---------------------------------------------------------
    def _setup_hosts_tab(self):
        top_bar = ctk.CTkFrame(self.tab_hosts, fg_color="transparent")
        top_bar.pack(fill="x", padx=15, pady=(10, 10))

        ctk.CTkLabel(top_bar, text="Configured SSH Servers & PuTTY Aliases", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        btn_add = ctk.CTkButton(top_bar, text="➕ Add Server", fg_color="#10B981", hover_color="#059669", width=120, command=self._add_host)
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
            empty_lbl = ctk.CTkLabel(
                self.hosts_scroll,
                text="No SSH hosts configured yet.\nClick '➕ Add Server' above to configure remote servers for plink / pscp.",
                font=ctk.CTkFont(size=13),
                text_color="#94A3B8"
            )
            empty_lbl.pack(pady=40)
            return

        for alias, info in hosts.items():
            card = ctk.CTkFrame(self.hosts_scroll, fg_color="#1E293B", corner_radius=8)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=15, pady=10, fill="x", expand=True)

            host_str = f"🔑 {alias}  —  {info.get('username', 'root')}@{info.get('host', 'localhost')}:{info.get('port', 22)}"
            ctk.CTkLabel(left, text=host_str, font=ctk.CTkFont(size=14, weight="bold"), anchor="w").pack(anchor="w")

            desc = info.get("description") or "No description"
            has_pw = "Password set" if info.get("password") else "No password"
            has_key = f"Key: {Path(info.get('private_key_path', '')).name}" if info.get("private_key_path") else "No key file"
            subtext = f"{desc} | {has_pw} | {has_key}"
            ctk.CTkLabel(left, text=subtext, font=ctk.CTkFont(size=12), text_color="#94A3B8", anchor="w").pack(anchor="w", pady=(3, 0))

            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.pack(side="right", padx=15, pady=10)

            btn_edit = ctk.CTkButton(btn_box, text="✏️ Edit", width=70, height=28, command=lambda a=alias, d=info: self._edit_host(a, d))
            btn_edit.pack(side="left", padx=(0, 8))

            btn_del = ctk.CTkButton(btn_box, text="🗑️", width=36, height=28, fg_color="#EF4444", hover_color="#DC2626", command=lambda a=alias: self._delete_host(a))
            btn_del.pack(side="left")

    def _add_host(self):
        dialog = HostDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            hosts = self._load_hosts_file()
            hosts[dialog.result["alias"]] = dialog.result["data"]
            self._save_hosts_file(hosts)
            self._refresh_hosts_list()
            self._log(f"Added SSH host '{dialog.result['alias']}' to hosts.json.")

    def _edit_host(self, alias: str, data: Dict[str, Any]):
        dialog = HostDialog(self, host_data=data, alias=alias)
        self.wait_window(dialog)
        if dialog.result:
            hosts = self._load_hosts_file()
            hosts[alias] = dialog.result["data"]
            self._save_hosts_file(hosts)
            self._refresh_hosts_list()
            self._log(f"Updated SSH host '{alias}' in hosts.json.")

    def _delete_host(self, alias: str):
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete host alias '{alias}'?", parent=self):
            hosts = self._load_hosts_file()
            if alias in hosts:
                del hosts[alias]
                self._save_hosts_file(hosts)
                self._refresh_hosts_list()
                self._log(f"Deleted SSH host '{alias}' from hosts.json.")

    # ---------------------------------------------------------
    # TAB 4: SETTINGS & SETUP GUIDE
    # ---------------------------------------------------------
    def _setup_settings_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # Network Settings Group
        group_net = ctk.CTkFrame(scroll, fg_color="#1E293B", corner_radius=8)
        group_net.pack(fill="x", pady=(0, 15), padx=5)

        ctk.CTkLabel(group_net, text="⚙️ Tunnel Provider & Exposure Settings", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        form = ctk.CTkFrame(group_net, fg_color="transparent")
        form.pack(fill="x", padx=15, pady=(0, 15))

        # Tunnel Mode
        ctk.CTkLabel(form, text="Tunnel Provider:").grid(row=0, column=0, sticky="w", pady=6)
        tunnel_modes = ["Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"]
        self.opt_tunnel_mode = ctk.CTkOptionMenu(form, values=tunnel_modes, width=240, command=self._on_settings_mode_changed)
        self.opt_tunnel_mode.grid(row=0, column=1, sticky="w", padx=15, pady=6)
        self.opt_tunnel_mode.set(self.config_data.get("server", {}).get("tunnel_mode", "Tailscale Funnel"))

        # Endpoint Path
        ctk.CTkLabel(form, text="Route Endpoint Path:").grid(row=1, column=0, sticky="w", pady=6)
        paths = ["/sse", "/mcp", "/messages", "/"]
        self.opt_endpoint_path = ctk.CTkOptionMenu(form, values=paths, width=240)
        self.opt_endpoint_path.grid(row=1, column=1, sticky="w", padx=15, pady=6)
        self.opt_endpoint_path.set(self.config_data.get("server", {}).get("endpoint_path", "/sse"))

        # Port
        ctk.CTkLabel(form, text="Server Port:").grid(row=2, column=0, sticky="w", pady=6)
        self.entry_port = ctk.CTkEntry(form, width=240)
        self.entry_port.grid(row=2, column=1, sticky="w", padx=15, pady=6)
        self.entry_port.insert(0, str(self.config_data.get("server", {}).get("port", 8000)))

        # Bind Host
        ctk.CTkLabel(form, text="Bind Host Address:").grid(row=3, column=0, sticky="w", pady=6)
        lan_ip = get_lan_ip()
        hosts_list = ["127.0.0.1", "0.0.0.0", lan_ip]
        self.opt_host = ctk.CTkComboBox(form, values=hosts_list, width=240)
        self.opt_host.grid(row=3, column=1, sticky="w", padx=15, pady=6)
        self.opt_host.set(str(self.config_data.get("server", {}).get("host", "127.0.0.1")))

        # Auto Tunnel Toggle
        self.var_auto_tunnel = ctk.BooleanVar(value=self.config_data.get("server", {}).get("auto_tunnel", True))
        self.switch_auto_tunnel = ctk.CTkSwitch(form, text="Auto-start selected Tunnel provider on Server launch", variable=self.var_auto_tunnel)
        self.switch_auto_tunnel.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)

        # Custom / Provider Domain Overrides
        ctk.CTkLabel(form, text="Cloudflare Custom URL:").grid(row=5, column=0, sticky="w", pady=6)
        self.entry_cf_url = ctk.CTkEntry(form, width=320, placeholder_text="e.g. https://mcp.mydomain.com")
        self.entry_cf_url.grid(row=5, column=1, sticky="w", padx=15, pady=6)
        self.entry_cf_url.insert(0, self.config_data.get("server", {}).get("cloudflare_custom_url", ""))

        ctk.CTkLabel(form, text="ngrok Custom Domain:").grid(row=6, column=0, sticky="w", pady=6)
        self.entry_ngrok_url = ctk.CTkEntry(form, width=320, placeholder_text="e.g. https://my-node.ngrok-free.app")
        self.entry_ngrok_url.grid(row=6, column=1, sticky="w", padx=15, pady=6)
        self.entry_ngrok_url.insert(0, self.config_data.get("server", {}).get("ngrok_custom_url", ""))

        ctk.CTkLabel(form, text="Custom / Proxy Domain:").grid(row=7, column=0, sticky="w", pady=6)
        self.entry_custom_url = ctk.CTkEntry(form, width=320, placeholder_text="e.g. https://my-reverse-proxy.com")
        self.entry_custom_url.grid(row=7, column=1, sticky="w", padx=15, pady=6)
        self.entry_custom_url.insert(0, self.config_data.get("server", {}).get("custom_public_url", ""))

        btn_save_settings = ctk.CTkButton(group_net, text="💾 Save Network & Endpoint Settings", fg_color="#10B981", hover_color="#059669", command=self._save_settings)
        btn_save_settings.pack(anchor="e", padx=15, pady=(0, 15))

        # Mammouth Integration Guide Group
        guide_group = ctk.CTkFrame(scroll, fg_color="#1E293B", corner_radius=8)
        guide_group.pack(fill="x", pady=(0, 10), padx=5)

        ctk.CTkLabel(guide_group, text="📖 How to connect with Mammouth.ai", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        guide_text = (
            "1. Choose your exposure mode (Tailscale, Cloudflare, ngrok, Direct IP, or Custom Domain).\n"
            "2. Start the server using the '▶ Start Server' button in the header.\n"
            "3. Click the '📋 Copy' button next to the calculated Endpoint URL.\n"
            "4. Open Mammouth.ai -> Settings -> Custom MCP Servers / Tools.\n"
            "5. Add a new MCP Server:\n"
            "     • Name: Mammouth Powerhouse\n"
            "     • Server Type: SSE (or HTTP Streaming)\n"
            "     • Endpoint URL: Paste your copied URL\n"
            "6. Save and start chatting! Mammouth AI will now use all active tools on your system."
        )
        ctk.CTkLabel(guide_group, text=guide_text, font=ctk.CTkFont(size=13), text_color="#CBD5E1", justify="left").pack(anchor="w", padx=15, pady=(0, 15))

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
        self.config_data["server"]["auto_tunnel"] = self.var_auto_tunnel.get()
        self.config_data["server"]["cloudflare_custom_url"] = self.entry_cf_url.get().strip()
        self.config_data["server"]["ngrok_custom_url"] = self.entry_ngrok_url.get().strip()
        self.config_data["server"]["custom_public_url"] = self.entry_custom_url.get().strip()

        save_config(self.config_data)
        self.dash_mode_menu.set(self.opt_tunnel_mode.get())
        self.dash_path_menu.set(self.opt_endpoint_path.get())
        self._refresh_all_endpoint_labels()
        self._log("Updated network & endpoint settings in config.json.")
        messagebox.showinfo("Saved", "Network and endpoint settings saved successfully!")

    # ---------------------------------------------------------
    # SERVER & TUNNEL RUNNER LIFECYCLE
    # ---------------------------------------------------------
    def toggle_server(self):
        if self.server_process is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self):
        cfg = load_config()
        port = cfg.get("server", {}).get("port", 8000)
        host = cfg.get("server", {}).get("host", "127.0.0.1")
        mode = cfg.get("server", {}).get("tunnel_mode", "Tailscale Funnel")
        auto_tunnel = cfg.get("server", {}).get("auto_tunnel", True)

        # 1. Start Tunnel if required
        if auto_tunnel:
            if mode == "Tailscale Funnel":
                ts_bin = shutil.which("tailscale") or cfg.get("server", {}).get("tailscale_path", r"C:\Program Files\Tailscale\tailscale.exe")
                if os.path.exists(ts_bin) or shutil.which("tailscale"):
                    self._log(f"Activating Tailscale Funnel on port {port}...")
                    try:
                        subprocess.Popen([ts_bin, "funnel", "--bg", str(port)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    except Exception as e:
                        self._log(f"Tailscale Funnel warning: {e}")

            elif mode == "Cloudflare Tunnel":
                cf_bin = shutil.which("cloudflared") or cfg.get("server", {}).get("cloudflared_path", "cloudflared")
                if shutil.which(cf_bin) or os.path.exists(cf_bin):
                    self._log(f"Launching Cloudflare Quick Tunnel on port {port}...")
                    try:
                        self.tunnel_process = subprocess.Popen(
                            [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        self.tunnel_thread = threading.Thread(target=self._stream_tunnel_logs, daemon=True)
                        self.tunnel_thread.start()
                    except Exception as e:
                        self._log(f"Cloudflare Tunnel start warning: {e}")
                else:
                    self._log("Notice: 'cloudflared' not found in PATH. Install cloudflared to use quick tunnels.")

            elif mode == "ngrok":
                ng_bin = shutil.which("ngrok") or cfg.get("server", {}).get("ngrok_path", "ngrok")
                if shutil.which(ng_bin) or os.path.exists(ng_bin):
                    self._log(f"Launching ngrok HTTP tunnel on port {port}...")
                    try:
                        self.tunnel_process = subprocess.Popen(
                            [ng_bin, "http", str(port)],
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        threading.Thread(target=self._poll_ngrok_api, daemon=True).start()
                    except Exception as e:
                        self._log(f"ngrok start warning: {e}")
                else:
                    self._log("Notice: 'ngrok' not found in PATH.")

        # 2. Launch FastMCP server
        self._log(f"Launching FastMCP Server on http://{host}:{port} (Exposure: {mode})...")
        cmd = [sys.executable, str(BASE_DIR / "server.py"), "--host", host, "--port", str(port)]
        
        try:
            self.server_process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )

            self.status_badge.configure(text="● Server Running", text_color="#10B981")
            self.btn_toggle_server.configure(text="⏹ Stop Server", fg_color="#EF4444", hover_color="#DC2626")

            # Start background reader thread
            self.log_stream_active = True
            self.server_thread = threading.Thread(target=self._stream_server_logs, daemon=True)
            self.server_thread.start()

            self._refresh_all_endpoint_labels()
            self._log("FastMCP Server process started.")

        except Exception as e:
            self._log(f"Failed to start server: {e}")
            messagebox.showerror("Server Launch Error", str(e))

    def _poll_ngrok_api(self):
        """Poll ngrok local inspection API on 127.0.0.1:4040 to discover dynamic public URL."""
        import httpx
        for _ in range(12):
            if not self.server_process:
                break
            time.sleep(1)
            try:
                with httpx.Client(timeout=1.5) as client:
                    resp = client.get("http://127.0.0.1:4040/api/tunnels")
                    if resp.status_code == 200:
                        data = resp.json()
                        for t in data.get("tunnels", []):
                            pub = t.get("public_url", "")
                            if pub:
                                self.dynamic_tunnel_url = pub
                                self.after(0, self._on_dynamic_tunnel_discovered)
                                return
            except Exception:
                pass

    def _stream_tunnel_logs(self):
        """Read tunnel stdout to detect quick tunnel URLs (e.g. trycloudflare.com)."""
        if not self.tunnel_process or not self.tunnel_process.stdout:
            return
        cf_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        for line in iter(self.tunnel_process.stdout.readline, ""):
            if line:
                match = cf_pattern.search(line)
                if match:
                    self.dynamic_tunnel_url = match.group(0)
                    self.after(0, self._on_dynamic_tunnel_discovered)
        if self.tunnel_process:
            try:
                self.tunnel_process.stdout.close()
            except Exception:
                pass

    def _on_dynamic_tunnel_discovered(self):
        self._log(f"Tunnel online & URL discovered: {self.dynamic_tunnel_url}")
        self._refresh_all_endpoint_labels()

    def _stream_server_logs(self):
        if not self.server_process or not self.server_process.stdout:
            return
        for line in iter(self.server_process.stdout.readline, ""):
            if not self.log_stream_active:
                break
            if line:
                cleaned = line.rstrip()
                self.after(0, lambda msg=cleaned: self._log(msg))
        if self.server_process:
            try:
                self.server_process.stdout.close()
            except Exception:
                pass
        self.after(0, self._on_server_exited)

    def _on_server_exited(self):
        if self.server_process is not None and self.server_process.poll() is not None:
            self.server_process = None
            self.status_badge.configure(text="● Server Stopped", text_color="#EF4444")
            self.btn_toggle_server.configure(text="▶ Start Server", fg_color="#10B981", hover_color="#059669")
            self._log("Server process terminated.")

    def _stop_server(self):
        self._log("Stopping FastMCP Server & Tunnels...")
        self.log_stream_active = False

        if self.server_process:
            try:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)], capture_output=True)
                else:
                    self.server_process.terminate()
            except Exception as e:
                self._log(f"Error terminating server: {e}")
            self.server_process = None

        if self.tunnel_process:
            try:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.tunnel_process.pid)], capture_output=True)
                else:
                    self.tunnel_process.terminate()
            except Exception:
                pass
            self.tunnel_process = None

        self.status_badge.configure(text="● Server Stopped", text_color="#EF4444")
        self.btn_toggle_server.configure(text="▶ Start Server", fg_color="#10B981", hover_color="#059669")
        self._log("FastMCP Server stopped.")

    def _on_close(self):
        if self.server_process:
            self._stop_server()
        self.destroy()


def main():
    app = MammouthControlCenter()
    app.mainloop()


if __name__ == "__main__":
    main()
