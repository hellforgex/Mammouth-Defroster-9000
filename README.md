# 🦣 Mammouth Control Center & MCP Server for Windows 11

> **High-Performance Desktop Control Center and FastMCP Server with Modular DevOps & System Automation Toolsets for [Mammouth.ai](https://mammouth.ai).**

![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen)
![FastMCP](https://img.shields.io/badge/MCP-FastMCP%203.4%2B-purple)
![Interface](https://img.shields.io/badge/UI-CustomTkinter%20Dark%20Theme-orange)

---

## 🌟 Highlights & Features

Mammouth Control Center gives your Mammouth AI assistants direct, secure access to your local Windows environment, remote servers, and background automation daemons.

- 🖥️ **Modern Windows 11 Desktop UI**: Beautiful dark-mode dashboard with real-time status indicators, 1-click endpoint copy, and live console logs.
- ⚡ **Modular Skill Toggles**: Granularly enable or disable individual toolsets directly from the GUI (Memory, Kanban, File Ops, PowerShell, SSH, System Monitor, Web).
- 🔑 **Integrated SSH Host Manager**: Add, edit, and test remote Linux VPS/servers for PuTTY, Plink commands, and SCP file synchronization without touching JSON files.
- 🌐 **Automated Tailscale Funnel & Remote SSE**: Instant 1-click tunneling that securely exposes your MCP SSE endpoint (`https://<node>.ts.net/sse`) directly to Mammouth.ai in the cloud.
- 📦 **Standalone EXE Packaging**: 1-click build script (`build_exe.bat`) to package the entire Control Center into an `.exe` for any Windows machine.

---

## 🛠️ Included MCP Toolsets (Skills)

| Skill / Module | Key Capabilities | Example Tools |
| :--- | :--- | :--- |
| 🧠 **Persistent Memory** | SQLite cross-session knowledge storage with keyword search & categories | `memory_save`, `memory_recall`, `memory_list`, `memory_get` |
| 📋 **Task & Kanban Board** | SQLite-backed task & project tracker (`todo`, `in_progress`, `done`) | `task_create`, `task_update`, `task_list`, `task_delete` |
| 📁 **File & Code Operations** | Line slicing, ripgrep-style recursive search, chunk replacement, tree view | `file_read`, `file_write`, `file_replace_chunk`, `file_search_text`, `directory_tree` |
| 💻 **PowerShell Execution** | Sync command execution & background daemon process manager with live logs | `command_run`, `process_start_background`, `process_get_output`, `process_kill_background` |
| 🔑 **PuTTY & SSH Management** | Remote execution via Plink, SCP file transfers, PuTTY GUI launch, registry sessions | `ssh_exec_command`, `ssh_open_putty_window`, `ssh_transfer_file`, `ssh_list_saved_hosts` |
| 📊 **System & Diagnostics** | CPU, RAM, Disk usage, GPU details, top process listing, Windows Event Logs | `system_get_specs`, `system_get_processes`, `system_get_gpu_info`, `system_get_event_logs` |
| 🌐 **Web Scraper & Tools** | URL fetcher with automatic HTML-to-markdown text cleaning & endpoint ping | `web_fetch_url`, `web_check_status` |

---

## 🚀 Quickstart

### Prerequisites
- Windows 10 or 11
- Python 3.10+ (or [uv package manager](https://docs.astral.sh/uv/) — recommended)
- [Tailscale](https://tailscale.com/) (optional, for cloud access via Tailscale Funnel)

---

### Option A: Launching via Python / `uv` (Recommended)

1. Clone or extract the repository:
   ```bash
   git clone https://github.com/your-username/mammouth-control-center.git
   cd mammouth-control-center
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

1. Open **Mammouth Control Center** and click **`▶ Start Server`**.
2. Click the **`📋 Copy`** button next to the **Public SSE Endpoint** (e.g. `https://your-machine.tailnet.ts.net/sse`).
3. In **[Mammouth.ai](https://mammouth.ai)**:
   - Navigate to **Settings** → **Custom MCP Servers** (or Tools).
   - Click **Add MCP Server**:
     - **Name**: `Mammouth Powerhouse`
     - **Type**: `SSE` (Server-Sent Events)
     - **URL**: Paste your copied URL (`https://.../sse`).
   - Click **Save / Connect**.
4. Start a new chat with Mammouth! The AI can now run diagnostics, edit files, manage remote servers, and retain long-term memory across sessions.

---

## 🔒 Security Best Practices

> [!WARNING]
> This MCP server provides tools for executing local PowerShell commands, modifying files, and connecting to SSH servers.
> 
> - **Do not share your Public Funnel URL publicly.**
> - Use **Tailscale** for end-to-end encrypted personal access.
> - In the **Skills & Modules** tab, you can disable powerful modules (such as PowerShell or SSH) if they are not needed for a specific workflow.

---

## 📂 Project Structure

```
mammouth-control-center/
├── modules/
│   ├── __init__.py
│   ├── memory.py            # SQLite Long-term memory
│   ├── tasks_kanban.py      # SQLite Kanban & tasks
│   ├── file_ops.py          # File editing & search
│   ├── shell_processes.py   # PowerShell execution & background daemons
│   ├── putty_ssh.py         # PuTTY / Plink / PSCP remote tools
│   ├── system_monitor.py    # Hardware & Windows diagnostics
│   └── web_tools.py         # Web scraping & status checks
├── config.py                # Configuration manager
├── config.example.json      # Template configuration
├── hosts.example.json       # Template SSH hosts configuration
├── server.py                # FastMCP server with dynamic tool loader
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
