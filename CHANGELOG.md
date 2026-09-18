# Changelog

All notable changes to **Mammouth Defroster 9000** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] - 2026-09-18

### 🪶 Packaging & Binary Footprint Optimization
- **Eliminated Transitive ML/Data-Science Bloat:** Explicitly configured PyInstaller `excludes` in `MammouthDefroster9000.spec` to omit non-essential libraries (`torch`, `torchvision`, `torchaudio`, `transformers`, `accelerate`, `optimum`, `onnxruntime`, `faiss`, `sklearn`, `scipy`, `cv2`, `pandas`, `pyarrow`, `av`, `botocore`, `boto3`, `google`, `anthropic`, `matplotlib`, `nltk`) inadvertently collected from system Python environments.
- **Drastic Size Reduction:** Release ZIP package compressed size slashed from **540 MB** to **~80 MB** (~85% reduction), and uncompressed footprint reduced from **1.5 GB** to **~280 MB**.
- **Improved Cold-Start Performance:** Significantly reduced DLL scanning and assembly overhead on startup.
- **Full Compatibility & Feature Parity:** Maintained 100% functionality across desktop vision, input automation, and FastMCP server endpoints.

## [0.2.2] - 2026-09-18

### 🖱️ Desktop Mouse & Keyboard Automation (`modules/desktop_input.py`)
- **Native Win32 Subsystem & Fallback (`modules/desktop_input.py`):** Fully implemented native Windows User32 API input events (`user32.mouse_event`, `user32.SetCursorPos`, `user32.keybd_event` with `KEYEVENTF_UNICODE`). Bypasses PyAutoGUI failsafe crashes and works robustly on interactive desktop sessions.
- **Mouse Tools:** `mouse_move`, `mouse_click`, `mouse_drag`, `mouse_scroll`, `mouse_get_position` with smooth interpolation, boundary clamping, and left/right/middle button support.
- **Keyboard Tools:** `keyboard_type` with full international Unicode character support, `keyboard_press` with key aliases, and `keyboard_hotkey` with multi-key combination sequences.
- **Screen Bounds Detection:** `desktop_get_screen_info` reporting primary monitor width, height, and real-time cursor coordinates.

### 🔑 Authentication Key Display & Plaintext Token Hygiene
- **Dashboard Bearer API Key Display (`gui.py`):** Added a dedicated `🔑 Bearer API Key` row directly to the primary Dashboard endpoint card with an interactive show/hide toggle (`🔒 Hide Key` / `👁️ Show Key`) and a direct `📋 Copy Key` button.
- **Removed DPAPI Key Storage (`config.py`):** Eliminated Windows DPAPI ciphertext encryption (`dpapi:<base64>`) for `api_token` in `config.json`. The original alphanumeric authentication key is now preserved, stored, and displayed cleanly without cryptographic hashing.
- **Transparent Migration on Load (`config.py`, `gui.py`):** Automatically migrates any legacy `dpapi:` tokens on disk back to original keys upon startup. If a foreign/corrupted DPAPI blob is detected, a fresh 32-character token is seamlessly generated so the app never displays broken ciphertext.
- **MCP JSON Configuration Client (`gui.py`):** Verified client configuration snippets and clipboard export always bundle the original Bearer key.

### 👁️ Desktop Vision & Interactive Consent Gate (`modules/screen_capture.py`, `gui.py`)
- **Interactive UI Modal:** When a connected AI or MCP client calls `screen_capture`, a native modal prompt appears on screen asking for explicit confirmation, preventing silent screen scraping.
- **Session & Setting Controls:** Added `🔒 Require Consent` toggle and `🔓 Grant Session Consent` buttons across both the Modular Capabilities and Settings tabs.
- **Exposed MCP Tools:** Registered `screen_grant_consent` and `screen_revoke_consent` in `server.py` allowing autonomous AI workflows to negotiate permissions.

### 🖥️ Dual Executable Packaging & CLI Server Mode (`MammouthDefroster9000.spec`, `build.bat`)
- **Dedicated Console Server (`MammouthDefroster9000-server.exe`):** Built alongside the windowed GUI (`MammouthDefroster9000.exe`), providing real-time streaming Uvicorn logs, batch file compatibility, and graceful Ctrl+C shutdown.
- **Headless Mode Fix:** Fixed `ImportError` in `--server-only` / `--cli` mode and attached to Windows console when launched from a terminal.
- **Autostart Support:** Added `--autostart` flag and `"auto_start_server"` configuration option for headless/instant boot.

### 🛡️ FastMCP & MCP Client Compatibility
- **Empty List Protection (`server.py`):** Intercepted empty list results (`memory_list`, `task_list`) to return valid `[TextContent(text="[]")]`, eliminating client-side `IndexError: list index out of range` crashes.
- **Flexible Schema Aliases (`modules/file_ops.py`, `modules/tasks_kanban.py`):** Supported `path` as alias for `directory_path` and `file_path`, and `id` for `task_id`.

### 🌐 Network & Tunnel Integrations (`gui.py`, `config.py`)
- **Direct Tunnel Management:** Support for Tailscale Funnel, Cloudflare Tunnel (`cloudflared`), and ngrok with auto-detection of local binary paths and automatic process lifecycle management.

---

## [0.2.1] - 2026-09-01

### 🚀 Packaging, GUI Stability & Standalone Binary Fixes
- **Inlined Self-Signed TLS Generation (`gui.py`):** Inlined TLS certificate generation directly into GUI startup to guarantee zero-dependency server launches across all execution environments.
- **PyInstaller Asset Collection (`build.bat`):** Upgraded build scripts with full `--collect-all` for `customtkinter`, `fastmcp`, `uvicorn`, and `PIL` ensuring all UI themes, fonts, and runtime dependencies are fully bundled in standalone `.exe` packages.
- **Synchronized Workspaces:** Unified multi-directory builds and eliminated legacy script paths.

---

## [0.2.0] - 2026-08-31

### 🛡️ Security Hardening & Audit Remediation (Rounds 5–7 Verification)

### Fixed & Verified
- **Shell Path Resolution & Root-Recurse Sandbox Guard (R7-N1 & R7-N2 in `modules/shell_processes.py`):**
  - Path arguments in read-only commands (`Get-Content`, `gc`, `cat`, `type`, `Get-Item`, `gi`, `Get-ChildItem`, `gci`, `dir`, `ls`, `Get-Acl`) are fully extracted and resolved against the workspace root before evaluating containment and denylists.
  - Non-workspace paths (`..\..\Windows\win.ini`, `..\config.json`, `C:\Windows\win.ini`) unconditionally fail closed with `PermissionError`.
  - Upgraded root-recurse detection regex with boundary lookahead (`(?=[\s"'\\]|$)`) blocking drive roots (`Get-ChildItem C:\ -Recurse`, `Get-ChildItem D:\data -Recurse`), while permitting legitimate workspace traversal (`Get-ChildItem .\workspace -Recurse`).
- **Unreal Engine Strict Import Allowlist & HMAC Handshake (`modules/unreal_engine.py`, `modules/remote_execution.py`):**
  - Enforced AST `ALLOWED_MODULES = {'unreal', 'math', 'string', 'enum', 'dataclasses', 'typing', 'collections', 'functools', 'itertools', 'json', 're', 'datetime', 'hashlib', 'random', 'uuid', 'decimal', 'copy', 'statistics', 'time'}`.
  - Blocked dunder reflection (`__mro__`, `__members__`, `__class__`, `__subclasses__`, `__globals__`).
  - Instantiated `RemoteExecution` with server `api_token` for cryptographic HMAC-SHA256 challenge-response verification with separated broadcast nonces and authenticated connection responses.
- **PowerShell Execution & Read-Only Default (`modules/shell_processes.py`):**
  - Default shell execution mode converted to **Read-Only Allowlist** (permitting only diagnostic verbs `Get-*`, `Test-*`, `Measure-*`, `Select-*`, `whoami`, `ipconfig`, `tasklist`, `netstat`, `hostname`, `reg query`).
  - Modifying commands require explicit `allow_admin_shell: true` with GUI confirmation dialog.
- **M-07 Desktop Vision User Consent Gate (`modules/screen_capture.py`):**
  - Added explicit user consent requirement (`require_consent: true`).
  - Unapproved screen capture calls return `{"status": "consent_required", ...}`.
  - Purged test bypass parameters from public tool signatures.
  - Added GUI interactive prompt and helper functions `screen_grant_consent("once"|"always")` and `screen_revoke_consent()`.
- **M-05 / R4-N3 DPAPI Token Storage & Proactive Migration (`config.py`):**
  - `api_token` in `config.json` is encrypted using Windows DPAPI (`dpapi:<base64>`).
  - Proactive encryption on load ensures plaintext tokens on disk are immediately converted to DPAPI format.
  - Removed unconditional token regeneration on load.
- **M-01 Transport-Level SSRF IP Pinning (`modules/web_tools.py`):**
  - Outbound HTTP requests resolve DNS upfront, validate IP against private/loopback/metadata subnets, and pin connection.
  - Redirects validated against the same rule.
  - `web_tools` disabled by default in configuration.
- **M-09 Local LAN TLS Support (`server.py`, `gui.py`):**
  - Added support for `ssl_certfile` / `ssl_keyfile` with automated self-signed certificate generation (`generate_self_signed_cert`).
  - Added security warning banners for unencrypted LAN exposure.
- **PuTTY `-pwfile` Temporary File Security (`modules/putty_ssh.py`):**
  - Replaced CLI `-pw` arguments with temporary `-pwfile` protected by Owner ACLs (`icacls`) via `getpass.getuser()` and deleted in `finally:` blocks.
- **Progressive Exponential Backoff per IP (`server.py`):**
  - 1–4 failures return 401; 5+ failures enforce progressive delay of $2^{(failures - 5)}$ seconds (capped at 60s).
  - Valid token immediately resets failure count.
  - Injected response security headers (`Cache-Control: no-store`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, etc.).

---

## [0.1.0] - 2026-08-25

### 🚀 Initial Public Release — Mammouth Defroster 9000 🦣❄️🔥

The sovereign Windows 11 FastMCP desktop cockpit and DevOps powerhouse engineered for Mammouth.ai.
