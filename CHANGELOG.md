# Changelog

All notable changes to **Mammouth Defroster 9000** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-08-25

### 🚀 Initial Public Release — Mammouth Defroster 9000 🦣❄️🔥

The sovereign Windows 11 FastMCP desktop cockpit and DevOps powerhouse engineered by **noskillz** for [Mammouth.ai](https://mammouth.ai).

### Added
- **Modern Desktop Cockpit GUI**:
  - Dark-mode dashboard built with CustomTkinter.
  - 1-click server lifecycle management with live process status badge and console log stream.
  - Windows Taskbar and Titlebar integration with cybernetic fire & ice Mammoth icons.
  - Integrated visual SSH Host Manager with PuTTY, Plink, and PSCP support.
- **32 Defrosted MCP Tools across 7 Modules**:
  - 🧠 **Persistent Long-Term Memory**: SQLite cross-session knowledge store with keyword search and category tags.
  - 📋 **Task & Kanban Board**: SQLite project management and task tracker (`todo`, `in_progress`, `done`, `blocked`).
  - 📁 **Sandboxed File Operations**: Line slicing, ripgrep text search, and exact code chunk replacement.
  - 💻 **PowerShell & Background Tasks**: Synchronous command execution and background daemon task manager.
  - 🔑 **PuTTY / SSH Remote Shell**: Remote execution via Plink, SCP file transfers, and desktop PuTTY window launcher.
  - 📊 **Hardware & Windows Diagnostics**: CPU, RAM, Disk partitions, GPU specs, top processes, and Windows Event Logs.
  - 🌐 **Web Scraper & Tools**: Webpage text/markdown extractor and URL latency/status checker.
- **Multi-Tunnel Network Hub**:
  - Auto-detected **Tailscale Funnel** (`https://<node>.ts.net/mcp`).
  - **Cloudflare Quick Tunnels** with dynamic URL discovery (`trycloudflare.com`).
  - **ngrok HTTP Tunnels** with local API polling (`127.0.0.1:4040`).
  - Direct LAN IP (`192.168.x.x`) and Localhost (`127.0.0.1`) connections.
  - Configurable route endpoints (`/mcp`, `/sse`, `/messages`, `/`).

### Security Hardening (100% Audit Cleared)
- **Token Authentication**: Bearer token and URL query parameter validation (`Authorization: Bearer <token>` and `?token=...`).
- **Strict CORS Protection**: Restricted specifically to `mammouth.ai` domains and local origins.
- **Workspace Sandboxing**: Path traversal defense preventing writes outside `./workspace` and blocking access to system-protected locations (`C:\Windows`, `Startup`).
- **Windows DPAPI Password Encryption**: SSH passwords stored in `hosts.json` are encrypted using the native Windows Data Protection API bound to the user profile.
- **SSRF Defense Filter**: Web scraper blocks private IP networks, loopbacks, and cloud metadata services.
- **ReDoS Protection**: Regex patterns are checked against catastrophic backtracking quantifiers and capped at 150 characters.
- **Destructive Command Filter**: Blocks dangerous system commands (`Format-Volume`, `Diskpart`, `Bcdedit`, `Remove-Item C:\Windows`).
- **Response Security Headers**: Injected `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy: no-referrer`.
- **Log Rotation & Retention**: Automatic cleanup of background task logs capped at 50 files.
- **Legal Protection**: Comprehensive legal disclaimer under statutory gratuitous software provision (*Section 521 German Civil Code / BGB*) and MIT License.
