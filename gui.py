import os
import sys
import json
import time
import shutil
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

from config import load_config, save_config, CONFIG_FILE

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
        self.geometry("980x720")
        self.minsize(880, 640)

        self.config_data = load_config()
        self.server_process: Optional[subprocess.Popen] = None
        self.server_thread: Optional[threading.Thread] = None
        self.log_stream_active = False

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

        # Public Endpoint Row
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(10, 5))
        ctk.CTkLabel(row1, text="🌐 Public SSE Endpoint:", font=ctk.CTkFont(size=13, weight="bold"), width=160, anchor="w").pack(side="left")
        self.lbl_public_url = ctk.CTkLabel(row1, text=self._get_current_public_url(), font=ctk.CTkFont(size=13, weight="bold"), text_color="#38BDF8")
        self.lbl_public_url.pack(side="left", padx=10)
        btn_copy_pub = ctk.CTkButton(row1, text="📋 Copy", width=70, height=26, command=lambda: self._copy_to_clipboard(self.lbl_public_url.cget("text")))
        btn_copy_pub.pack(side="right")

        # Local Endpoint Row
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(5, 10))
        ctk.CTkLabel(row2, text="💻 Local SSE Endpoint:", font=ctk.CTkFont(size=13, weight="bold"), width=160, anchor="w").pack(side="left")
        port = self.config_data.get("server", {}).get("port", 8000)
        self.lbl_local_url = ctk.CTkLabel(row2, text=f"http://127.0.0.1:{port}/sse", font=ctk.CTkFont(size=13), text_color="#94A3B8")
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
        self._log("System initialized. Click '▶ Start Server' to launch the FastMCP service.")

    def _get_current_public_url(self) -> str:
        custom = self.config_data.get("server", {}).get("custom_public_url", "").strip()
        if custom:
            return f"{custom.rstrip('/')}/sse"
        ts_domain = get_tailscale_public_domain(self.config_data.get("server", {}).get("tailscale_path", ""))
        if ts_domain:
            return f"{ts_domain}/sse"
        port = self.config_data.get("server", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}/sse (Tailscale Funnel not detected)"

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

        ctk.CTkLabel(group_net, text="⚙️ Network & Tunnel Settings", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        form = ctk.CTkFrame(group_net, fg_color="transparent")
        form.pack(fill="x", padx=15, pady=(0, 15))

        # Port
        ctk.CTkLabel(form, text="Server Port:").grid(row=0, column=0, sticky="w", pady=6)
        self.entry_port = ctk.CTkEntry(form, width=200)
        self.entry_port.grid(row=0, column=1, sticky="w", padx=15, pady=6)
        self.entry_port.insert(0, str(self.config_data.get("server", {}).get("port", 8000)))

        # Host
        ctk.CTkLabel(form, text="Bind Host:").grid(row=1, column=0, sticky="w", pady=6)
        self.entry_host = ctk.CTkEntry(form, width=200)
        self.entry_host.grid(row=1, column=1, sticky="w", padx=15, pady=6)
        self.entry_host.insert(0, str(self.config_data.get("server", {}).get("host", "127.0.0.1")))

        # Tailscale Auto Funnel
        self.var_tailscale = ctk.BooleanVar(value=self.config_data.get("server", {}).get("auto_tailscale", True))
        self.switch_tailscale = ctk.CTkSwitch(form, text="Auto-start Tailscale Funnel on launch", variable=self.var_tailscale)
        self.switch_tailscale.grid(row=2, column=0, columnspan=2, sticky="w", pady=8)

        # Custom Public URL
        ctk.CTkLabel(form, text="Custom Tunnel URL:").grid(row=3, column=0, sticky="w", pady=6)
        self.entry_custom_url = ctk.CTkEntry(form, width=320, placeholder_text="e.g. https://my-tunnel.trycloudflare.com")
        self.entry_custom_url.grid(row=3, column=1, sticky="w", padx=15, pady=6)
        self.entry_custom_url.insert(0, self.config_data.get("server", {}).get("custom_public_url", ""))

        btn_save_settings = ctk.CTkButton(group_net, text="💾 Save Network Settings", fg_color="#10B981", hover_color="#059669", command=self._save_settings)
        btn_save_settings.pack(anchor="e", padx=15, pady=(0, 15))

        # Mammouth Integration Guide Group
        guide_group = ctk.CTkFrame(scroll, fg_color="#1E293B", corner_radius=8)
        guide_group.pack(fill="x", pady=(0, 10), padx=5)

        ctk.CTkLabel(guide_group, text="📖 How to connect with Mammouth.ai", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=15, pady=(12, 8))

        guide_text = (
            "1. Start the server using the '▶ Start Server' button in the header.\n"
            "2. Click the '📋 Copy' button next to the Public SSE Endpoint URL.\n"
            "3. Open your browser and go to Mammouth.ai (Settings -> Custom Tools / MCP Servers).\n"
            "4. Add a new MCP Server:\n"
            "     • Name: Mammouth Powerhouse\n"
            "     • Server Type: SSE (or HTTP Streaming)\n"
            "     • Endpoint URL: Paste the copied URL (e.g. https://your-node.ts.net/sse)\n"
            "5. Save and start chatting! Mammouth AI can now execute tools, edit code, and query systems."
        )
        ctk.CTkLabel(guide_group, text=guide_text, font=ctk.CTkFont(size=13), text_color="#CBD5E1", justify="left").pack(anchor="w", padx=15, pady=(0, 15))

    def _save_settings(self):
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            port = 8000

        self.config_data["server"]["port"] = port
        self.config_data["server"]["host"] = self.entry_host.get().strip() or "127.0.0.1"
        self.config_data["server"]["auto_tailscale"] = self.var_tailscale.get()
        self.config_data["server"]["custom_public_url"] = self.entry_custom_url.get().strip()

        save_config(self.config_data)
        self.lbl_public_url.configure(text=self._get_current_public_url())
        self.lbl_local_url.configure(text=f"http://127.0.0.1:{port}/sse")
        self._log("Updated network settings in config.json.")
        messagebox.showinfo("Saved", "Network settings saved successfully!")

    # ---------------------------------------------------------
    # SERVER RUNNER & LIFECYCLE
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
        auto_ts = cfg.get("server", {}).get("auto_tailscale", True)
        ts_path = cfg.get("server", {}).get("tailscale_path", r"C:\Program Files\Tailscale\tailscale.exe")

        # Auto-activate Tailscale Funnel if enabled
        if auto_ts:
            ts_bin = shutil.which("tailscale") or ts_path
            if os.path.exists(ts_bin) or shutil.which("tailscale"):
                self._log(f"Activating Tailscale Funnel on port {port}...")
                try:
                    subprocess.Popen([ts_bin, "funnel", "--bg", str(port)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                except Exception as e:
                    self._log(f"Tailscale Funnel warning: {e}")

        self._log(f"Launching FastMCP Server on http://{host}:{port}...")
        
        # Build command: use current python executable
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

            self.lbl_public_url.configure(text=self._get_current_public_url())
            self.lbl_local_url.configure(text=f"http://127.0.0.1:{port}/sse")
            self._log("FastMCP Server started successfully.")

        except Exception as e:
            self._log(f"Failed to start server: {e}")
            messagebox.showerror("Server Launch Error", str(e))

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
            self.server_process.stdout.close()

    def _stop_server(self):
        self._log("Stopping FastMCP Server...")
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
