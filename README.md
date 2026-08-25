# 🦣 Mammouth Defroster 9000 ❄️🔥

> **Thawing 10,000 years of frozen Windows automation power for [Mammouth.ai](https://mammouth.ai). An enterprise-grade, vibecoded FastMCP control center by noskillz.**

![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-blue)
![Vibecoded](https://img.shields.io/badge/Vibecoded%20By-noskillz%20⚡-purple)
![Security](https://img.shields.io/badge/Security-Bearer%20Token%20%2B%20DPAPI%20%2B%20Sandbox-green)
![Status](https://img.shields.io/badge/Defroster%20State-100%25%20THAWED%20%F0%9F%94%A5-orange)
![License](https://img.shields.io/badge/License-MIT%20%2B%20Legal%20Disclaimer-orange)
![FastMCP](https://img.shields.io/badge/MCP-FastMCP%203.4%2B-purple)
![Interface](https://img.shields.io/badge/UI-CustomTkinter%20Dark%20Theme-blueviolet)

---

> [!CAUTION]
> ### ⚠️ ⚡ NOSKILLZ VIBECODED DISCLAIMER & HARDCORE WARNING ⚡ ⚠️
>
> **WELCOME TO THE RAW AGENTIC POWERHOUSE.**
>
> This software is **100% pure vibe-coded** by **noskillz** for maximum execution speed, sovereign Windows 11 DevOps supremacy, and zero-compromise automation.
>
> 🦣 **With great agentic power comes absolute responsibility:**
> - You are handing an autonomous AI assistant real keys to your operating system: PowerShell execution, sandboxed file modifications, hardware diagnostics, and remote SSH servers.
> - **NEVER** expose this server publicly to the open internet without **Tailscale**, a private VPN, or Token Authentication enabled, unless you enjoy chaotic uninvited guests playing Doom in your PowerShell console.
> - By running this tool, you acknowledge that you are a sovereign captain of your machine. If you instruct an AI to *"clean up everything"* and it happily deletes your favorite meme stash, that is between you, the AI, and the cosmos.
> - Test your prompts, sandbox your workspaces, and embrace the agentic vibe responsibly. 🚀

---

## ⚖️ Legal Disclaimer & Limitation of Liability

> [!IMPORTANT]
> **Please read carefully before deploying or operating this software:**
>
> 1. **Gratuitous Provision ("As-Is" / Statutory Basis)**:  
>    This software is provided as an open-source project entirely free of charge on an **"as-is"** and **"as-available"** basis without warranties of any kind, either express or implied. Under governing statutory law for gratuitous software provision (including Section 521 of the German Civil Code / BGB), the legal liability of the author and developer (**noskillz / hellforgex**) is strictly limited to **intentional misconduct** (*Vorsatz*) and **gross negligence** (*grobe Fahrlässigkeit*). Any liability for ordinary, slight, or simple negligence is expressly excluded to the fullest extent permitted by applicable law.
>
> 2. **Sole Risk and Operator Responsibility**:  
>    The execution and utilization of all functions within this software—specifically modules executing local **PowerShell commands**, **file system modifications (writing, modifying, deleting)**, **system diagnostics**, and **remote SSH/VPS server operations (PuTTY / Plink / PSCP)**—is undertaken strictly at the user's sole risk. The operator assumes full and exclusive liability for all actions, scripts, and operations initiated by themselves or triggered by connected AI models and autonomous agents.
>
> 3. **Exclusion of Consequential Damages & Data Loss**:  
>    The author/developer shall not be held liable for any direct, indirect, incidental, special, consequential, or punitive damages, including but not limited to loss of data, corrupted databases, hardware damage, operating system crashes, downtime, security breaches, unauthorized third-party access, or financial losses resulting from the installation, execution, or network exposure of this software.
>
> 4. **Network and Tunnel Security**:  
>    The operator is solely responsible for properly configuring and securing all network interfaces, reverse proxies, and tunnel endpoints (e.g. via Tailscale VPN, private network isolation, firewalls, or token authentication). Exposing this server to the public internet without adequate authentication is performed entirely at the user's own peril.

---

## 🌟 Highlights & Features

**Mammouth Defroster 9000** gives your Mammouth AI assistants secure, controlled access to your local Windows environment, remote servers, and background automation daemons.

- 🔒 **Hardened Security Architecture**:
  - **API Token Authentication**: Optional Bearer token / query auth (`Authorization: Bearer <token>` or `?token=...`).
  - **CORS Protection**: Restricted specifically to `mammouth.ai` domains and local development origins (no open wildcard `*`).
  - **Workspace Path Sandboxing**: File operations are jailed to an authorized workspace directory (`./workspace`) to prevent system file tampering or traversal attacks.
  - **Windows DPAPI Password Encryption**: SSH passwords stored in `hosts.json` are encrypted using the native Windows Data Protection API bound to your Windows user profile.
  - **SSRF Filter**: Web scraper blocks private IP networks, loopbacks, and cloud metadata services.
  - **Safe Defaults**: High-privilege tools (PowerShell execution) are disabled by default in template configurations.
- 🖥️ **Modern Windows 11 Desktop Cockpit**: Beautiful dark-mode dashboard with real-time status indicators, 1-click token-ready endpoint copy, and live console logs.
- ⚡ **Modular Skill Toggles**: Granularly enable or disable individual toolsets directly from the GUI (Memory, Kanban, File Ops, PowerShell, SSH, System Monitor, Web).
- 🌐 **Flexible Network & Tunnel Providers**:
  - **Tailscale Funnel**: Zero-config auto-detection and public HTTPS domain (`https://<node>.ts.net/sse`).
  - **Cloudflare Tunnel**: Quick free tunnels via `trycloudflare.com` or custom Cloudflare domains.
  - **ngrok Tunnel**: Instant public HTTP tunnel support with local API auto-discovery (`127.0.0.1:4040`).
  - **Direct IP / LAN**: Connect directly via Localhost (`127.0.0.1`) or local network LAN IP (`192.168.x.x`).
  - **Custom Domain**: Use your own reverse proxy (Nginx, Caddy, Traefik).
- 🔀 **Custom Route Endpoints**: Select between `/sse`, `/mcp`, `/messages`, or `/` root paths.
- 🔑 **Integrated SSH Host Manager**: Add, edit, and test remote Linux VPS/servers for PuTTY, Plink commands, and SCP file synchronization without touching JSON files.
- 📦 **Standalone EXE Packaging**: 1-click build script (`build_exe.bat`) to package the entire Defroster into an `.exe` for any Windows machine.

---

## 🛠️ Included MCP Toolsets (32 Defrosted Tools)

| Skill / Module | Security Level | Key Capabilities | Example Tools |
| :--- | :---: | :--- | :--- |
| 🧠 **Persistent Memory** | 🟢 Safe | SQLite cross-session knowledge storage with keyword search & categories | `memory_save`, `memory_recall`, `memory_list`, `memory_get` |
| 📋 **Task & Kanban Board** | 🟢 Safe | SQLite-backed task & project tracker (`todo`, `in_progress`, `done`, `blocked`) | `task_create`, `task_update`, `task_list`, `task_delete` |
| 📁 **File & Code Operations** | 🔒 Sandboxed | Line slicing, ripgrep search, chunk replacement within authorized workspace | `file_read`, `file_write`, `file_replace_chunk`, `file_search_text`, `directory_tree` |
| 💻 **PowerShell Execution** | ⚠️ High Privilege | Sync command execution & background daemon process manager with live logs | `command_run`, `process_start_background`, `process_get_output`, `process_kill_background` |
| 🔑 **PuTTY & SSH Management** | 🔒 DPAPI Encrypted | Remote execution via Plink, SCP file transfers, PuTTY GUI launch, registry sessions | `ssh_exec_command`, `ssh_open_putty_window`, `ssh_transfer_file`, `ssh_list_saved_hosts` |
| 📊 **System & Diagnostics** | 🟢 Safe | CPU, RAM, Disk usage, GPU details, top process listing, Windows Event Logs | `system_get_specs`, `system_get_processes`, `system_get_gpu_info`, `system_get_event_logs` |
| 🌐 **Web Scraper & Tools** | 🛡️ SSRF Protected | URL fetcher with HTML-to-markdown text cleaning, private IP blocking & endpoint ping | `web_fetch_url`, `web_check_status` |

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
2. The compiled application will be generated in `dist\MammouthDefroster9000\MammouthDefroster9000.exe`.
3. You can now distribute the folder or create a shortcut on your Desktop!

---

## 🔗 Connecting to Mammouth.ai

1. Open **Mammouth Defroster 9000**, choose your preferred **Exposure Mode** (e.g. Tailscale Funnel) and click **`▶ Start Server`**.
2. Click the **`📋 Copy`** button next to the calculated **Endpoint URL** (e.g. `https://<node>.ts.net/sse`).
3. In **[Mammouth.ai](https://mammouth.ai)**:
   - Navigate to **Settings** → **Custom MCP Servers** (or Tools).
   - Click **Add MCP Server**:
     - **Name**: `Mammouth Defroster 9000`
     - **Type**: `SSE` (Server-Sent Events)
     - **URL**: Paste your copied URL (`https://.../sse`).
   - Click **Save / Connect**.
4. Start a new chat with Mammouth! The AI can now run diagnostics, edit files, manage remote servers, and retain long-term memory across sessions.

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
│   └── web_tools.py         # SSRF-protected web scraping & status checks
├── config.py                # Security & Configuration manager
├── config.example.json      # Hardened template configuration
├── hosts.example.json       # Template SSH hosts configuration
├── server.py                # FastMCP server with Auth & CORS middleware
├── gui.py                   # CustomTkinter Windows 11 Desktop Cockpit
├── start_gui.bat            # Quick launcher script
├── build_exe.bat            # PyInstaller one-click builder
├── requirements.txt         # Pip dependency manifest
├── pyproject.toml           # Project metadata
├── LICENSE                  # MIT License & Legal Disclaimer
├── .gitignore               # Git security & cache filter
└── README.md                # Documentation, Legal Disclaimer & noskillz Manifesto
```

---

## 📄 License
MIT License. Copyright (c) 2026 **noskillz** ([hellforgex](https://github.com/hellforgex)).  
Governed by the **Legal Disclaimer & Limitation of Liability** above.
