# 🦣❄️ Mammouth Defroster 9000

> **Sovereign Windows 11 FastMCP Desktop Cockpit & DevOps Powerhouse**  
> Custom-Engineered for **Mammouth.ai** with Live Unreal Engine 5 Automation, Multi-Monitor Vision, and Hardware-Secured Bearer Authentication.

---

## 🌟 Flagship Highlights

### 1. 🦣 Seamless Mammouth.ai Integration & Bearer Token Security
- **Instant Cloud & Desktop Pairing:** Connects effortlessly to [Mammouth.ai](https://mammouth.ai) and [app.mammouth.ai](https://app.mammouth.ai) via high-throughput SSE / MCP endpoints.
- **Hardware DPAPI Token Security:** API tokens and host credentials are encrypted directly via Windows DPAPI (`win32crypt.CryptProtectData`), ensuring zero plaintext leaks on disk or in git.
- **Zero-Config Public Tunneling:** One-click integration with **Tailscale Funnel**, **Cloudflare Tunnels**, **ngrok**, or custom domains with progressive IP backoff anti-bruteforce defense ($2^n$s delay).

### 2. 🎮 Live Unreal Engine 5 & 4 Automation Engine
- **Direct Viewport & Scene Control:** Execute Python commands directly inside running Unreal Engine 5.x / 4.x Editor sessions in real time.
- **Actor Spawning & Scene Inspection:** Inspect World Outliners, spawn static meshes, adjust materials, align viewport cameras, and trigger editor transactions.
- **Hardened AST Sandbox & Cryptographic Handshake:** Protected by an AST Import Allowlist (`ALLOWED_MODULES = 19 standard modules`) and HMAC-SHA256 challenge-response verification on loopback sockets.

### 3. 👁️ Multi-Monitor Desktop Vision for Multimodal LLMs
- **High-Performance Multi-Screen Capture:** Instant screenshot captures across primary, secondary, or unified multi-monitor desktop spaces using hardware-accelerated MSS.
- **LLM Token Optimization:** Intelligent downscaling and JPEG/PNG quality clamping to maximize vision accuracy while conserving AI context tokens.
- **Interactive Consent Gate:** User-controlled privacy shield requiring interactive approval before screenshots are taken, coupled with 24-hour automated file pruning.

---

## 🛠️ Complete Tool Ecosystem

| Module | Description | MCP Capabilities |
|---|---|---|
| 🦣 **Auth & Server** | Bearer token verification, DPAPI encryption, progressive IP lockout | Fail-closed protection, OPTIONS preflight, Security headers |
| 🎮 **Unreal Engine** | Live UE5/UE4 Editor Python remote execution & viewport bridge | `unreal_execute_python`, `unreal_get_actors`, `unreal_spawn_actor` |
| 👁️ **Desktop Vision** | Multi-monitor screen capture & downscaling for multimodal LLMs | `screen_capture`, `screen_list_monitors`, `screen_grant_consent` |
| 💻 **PowerShell Shell** | Read-Only default shell with R7-N1 Path Guard & admin opt-in | `command_run`, `process_start_background`, `process_list` |
| 📁 **File Operations** | Fail-closed workspace sandboxing, text search, code replacement | `file_read`, `file_write`, `file_search_text`, `file_replace_chunk` |
| 🔑 **PuTTY & SSH** | Remote Linux terminal execution, SCP file transfers, PuTTY GUI launch | `ssh_exec_command`, `ssh_transfer_file`, `ssh_open_putty_window` |
| 🧠 **Memory & Kanban** | SQLite persistent cross-session memory & Kanban task management | `memory_save`, `memory_recall`, `task_create`, `task_list` |
| 📊 **System Monitor** | Real-time CPU, RAM, GPU, process listing, and Windows Event Logs | `system_get_specs`, `system_get_gpu_info`, `system_list_processes` |

---

## 🚀 Getting Started

### Prerequisites
- Windows 10/11 (64-bit)
- Python 3.10+ (for source installation) or standalone binary from `dist/MammouthDefroster9000`

### Quick Start (Source)
```cmd
git clone https://github.com/mammouth-ai/mcpserv.git
cd mcpserv
pip install -r requirements.txt
python gui.py
```

### Quick Start (Standalone Release)
Run `MammouthDefroster9000.exe` from the release package.

---

## 🧪 Testing & Verification

Run the full automated security regression test suite:
```cmd
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📄 License & Security

Refer to [`SECURITY.md`](SECURITY.md) for the complete security specification and [`CHANGELOG.md`](CHANGELOG.md) for version history.
