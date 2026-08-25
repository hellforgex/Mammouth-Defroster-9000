# 🦣 Mammouth Control Center & MCP Server for Windows 11

> **Enterprise-Grade Desktop Control Center and FastMCP Server with Hardened Security, Modular DevOps & System Automation Toolsets for [Mammouth.ai](https://mammouth.ai).**

![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-blue)
![Security](https://img.shields.io/badge/Security-Bearer%20Token%20%2B%20DPAPI%20%2B%20Sandbox-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen)
![FastMCP](https://img.shields.io/badge/MCP-FastMCP%203.4%2B-purple)
![Interface](https://img.shields.io/badge/UI-CustomTkinter%20Dark%20Theme-orange)

---

## 🌟 Highlights & Features

Mammouth Control Center gives your Mammouth AI assistants secure, controlled access to your local Windows environment, remote servers, and background automation daemons.

- 🔒 **Hardened Security Architecture**:
  - **API Token Authentication**: Every request requires a 32-character Bearer token (`Authorization: Bearer <token>` or `?token=...`).
  - **CORS Protection**: Restricted specifically to `mammouth.ai` domains and local development origins (no open wildcard `*`).
  - **Workspace Path Sandboxing**: File operations are jailed to an authorized workspace directory to prevent system file tampering or traversal attacks.
  - **Windows DPAPI Password Encryption**: SSH passwords stored in `hosts.json` are encrypted using the native Windows Data Protection API bound to your Windows user account.
  - **Safe Defaults**: High-privilege tools (PowerShell execution) are disabled by default and require deliberate activation in the GUI.
- 🖥️ **Modern Windows 11 Desktop UI**: Beautiful dark-mode dashboard with real-time status indicators, 1-click token-ready endpoint copy, and live console logs.
- ⚡ **Modular Skill Toggles**: Granularly enable or disable individual toolsets directly from the GUI (Memory, Kanban, File Ops, PowerShell, SSH, System Monitor, Web).
- 🌐 **Flexible Network & Tunnel Providers**:
  - **Tailscale Funnel**: Zero-config auto-detection and public HTTPS domain (`https://<node>.ts.net/sse`).
  - **Cloudflare Tunnel**: Quick free tunnels via `trycloudflare.com` or custom Cloudflare domains.
  - **ngrok Tunnel**: Instant public HTTP tunnel support with local API auto-discovery.
  - **Direct IP / LAN**: Connect directly via Localhost (`127.0.0.1`) or local network LAN IP (`192.168.x.x`).
  - **Custom Domain**: Use your own reverse proxy (Nginx, Caddy, Traefik).
- 🔀 **Custom Route Endpoints**: Select between `/sse`, `/mcp`, `/messages`, or `/` root paths.
- 🔑 **Integrated SSH Host Manager**: Add, edit, and test remote Linux VPS/servers for PuTTY, Plink commands, and SCP file synchronization without touching JSON files.
- 📦 **Standalone EXE Packaging**: 1-click build script (`build_exe.bat`) to package the entire Control Center into an `.exe` for any Windows machine.

---

## 🛠️ Included MCP Toolsets (Skills)

| Skill / Module | Security Level | Key Capabilities | Example Tools |
| :--- | :---: | :--- | :--- |
| 🧠 **Persistent Memory** | 🟢 Safe | SQLite cross-session knowledge storage with keyword search & categories | `memory_save`, `memory_recall`, `memory_list`, `memory_get` |
| 📋 **Task & Kanban Board** | 🟢 Safe | SQLite-backed task & project tracker (`todo`, `in_progress`, `done`) | `task_create`, `task_update`, `task_list`, `task_delete` |
| 📁 **File & Code Operations** | 🔒 Sandboxed | Line slicing, ripgrep search, chunk replacement within authorized workspace | `file_read`, `file_write`, `file_replace_chunk`, `file_search_text`, `directory_tree` |
| 💻 **PowerShell Execution** | ⚠️ High Privilege | Sync command execution & background daemon process manager with live logs | `command_run`, `process_start_background`, `process_get_output`, `process_kill_background` |
| 🔑 **PuTTY & SSH Management** | 🔒 DPAPI Encrypted | Remote execution via Plink, SCP file transfers, PuTTY GUI launch, registry sessions | `ssh_exec_command`, `ssh_open_putty_window`, `ssh_transfer_file`, `ssh_list_saved_hosts` |
| 📊 **System & Diagnostics** | 🟢 Safe | CPU, RAM, Disk usage, GPU details, top process listing, Windows Event Logs | `system_get_specs`, `system_get_processes`, `system_get_gpu_info`, `system_get_event_logs` |
| 🌐 **Web Scraper & Tools** | 🟢 Safe | URL fetcher with automatic HTML-to-markdown text cleaning & endpoint ping | `web_fetch_url`, `web_check_status` |

---

## 🚀 Quickstart

### Prerequisites
- Windows 10 or 11
- Python 3.10+ (or [uv package manager](https://docs.astral.sh/uv/) — recommended)
- Optional tunnel CLI tools: [Tailscale](https://tailscale.com/), [cloudflared](https://github.com/cloudflare/cloudflared), or [ngrok](https://ngrok.com/).

---

### Option A: Launching via Python / `uv` (Recommended)

1. Clone or extract the repository:
   ```bash
   git clone https://github.com/hellforgex/Mammouth-MCP-Control-Center.git
   cd Mammouth-MCP-Control-Center
   ```

2. Double-click **`start_gui.bat`**  
   *(or run `uv run gui.py` / `python gui.py` in your terminal)*

---

### Option B: Building a Standalone Windows EXE

1. Double-click **`build_exe.bat`**
2. The compiled application will be generated in `dist\MammouthControlCenter\MammouthControlCenter.exe`.
3. You can now distribute the folder or create a shortcut on your Desktop!

---

## 🔗 Connecting to Mammouth.ai

1. Open **Mammouth Control Center**, choose your preferred **Exposure Mode** (e.g. Tailscale, Cloudflare, Direct IP, etc.) and click **`▶ Start Server`**.
2. Click the **`📋 Copy`** button next to the calculated **Endpoint URL** (the URL already includes your secure authentication token e.g. `?token=...`).
3. In **[Mammouth.ai](https://mammouth.ai)**:
   - Navigate to **Settings** → **Custom MCP Servers** (or Tools).
   - Click **Add MCP Server**:
     - **Name**: `Mammouth Powerhouse`
     - **Type**: `SSE` (Server-Sent Events)
     - **URL**: Paste your copied URL (`https://.../sse?token=...`).
   - Click **Save / Connect**.
4. Start a new chat with Mammouth! The AI can now run diagnostics, edit files, manage remote servers, and retain long-term memory across sessions.

---

## 🔒 Security Best Practices

> [!IMPORTANT]
> **Token Authentication**: Always keep **Enforce Token Authentication** enabled in the Settings tab. This prevents unauthorized internet users or crawlers from calling your tools.
> 
> **Workspace Sandboxing**: By default, file read/write operations are confined to `./workspace`. You can change this directory in the **Security & Settings** tab to target specific project folders.
> 
> **PowerShell Module**: If you do not require arbitrary PowerShell execution, keep the `PowerShell & Background Daemons` module disabled in the **Skills & Modules** tab.

---

## 📂 Project Structure

```
mammouth-control-center/
├── modules/
│   ├── __init__.py
│   ├── memory.py            # SQLite Long-term memory
│   ├── tasks_kanban.py      # SQLite Kanban & tasks
│   ├── file_ops.py          # Sandboxed file editing & search
│   ├── shell_processes.py   # PowerShell execution & background daemons
│   ├── putty_ssh.py         # DPAPI-encrypted PuTTY / Plink / PSCP remote tools
│   ├── system_monitor.py    # Hardware & Windows diagnostics
│   └── web_tools.py         # Web scraping & status checks
├── config.py                # Security & Configuration manager
├── config.example.json      # Hardened template configuration
├── hosts.example.json       # Template SSH hosts configuration
├── server.py                # FastMCP server with Auth & CORS middleware
├── gui.py                   # CustomTkinter Windows 11 Desktop GUI
├── start_gui.bat            # Quick launcher script
├── build_exe.bat            # PyInstaller one-click builder
├── requirements.txt         # Pip dependency manifest
├── pyproject.toml           # Project metadata
├── .gitignore               # Git security & cache filter
└── README.md                # Documentation
```

---

## 📄 License
MIT License. Free to use, modify, and distribute for personal and commercial projects.
