# Changelog

## [0.5.2] - 2026-10-10

### 🌐 Complete English Localization
- **Cockpit UI & Navigation:** Fully translated all GUI elements, sidebar navigation, metric tiles, scheduler modals, settings, tray menu, console, Mammouth Code CLI tab, and global exception handlers to English.
- **Embedded Browser & Download Dialogs:** Converted native Windows save file picker, download notifications, toolbar actions, and WebView2 fallback messages to English.
- **Task Scheduler Presets:** Converted all bundled preset task templates (`football_live`, `crypto_ticker`, `system_health`, `mammouth_code_scan`, `news_flash`) to English names, descriptions, and prompt payloads while retaining exact internal trigger keys.
- **OAuth Consent Flow & Docstrings:** Updated the browser-based OAuth authorization interface and all FastMCP server tool docstrings to English.

## [0.5.1] - 2026-10-08

### 🔒 Security Fixes
- **OAuth consent requires owner proof:** Approving a client now requires the Defroster API token from the Cockpit; failed attempts count toward the IP lockout. The CSRF fallback was removed. Client IPs behind tunnels are taken from `CF-Connecting-IP` / the last `X-Forwarded-For` entry.
- **Shell gating:** `local_exec_command` is only available when the `shell_processes` module is enabled and runs exactly the validated command. Read-only mode rejects script blocks, subexpressions, redirection, `&`, backticks, `%` and `Out-File`/`Tee-Object`.
- **Screen capture consent:** `screen_grant_consent` / `screen_revoke_consent` are no longer exposed as MCP tools.
- **Browser agent:** Navigation is limited to http(s); link-local, reserved and metadata addresses are blocked.
- **Web tools:** DNS pinning on every redirect hop and a response size cap.
- **Mammouth Code:** The API key is passed via environment instead of the command line; the workspace `opencode.json` references `{env:MAMMOUTH_DEFROSTER_TOKEN}` instead of the token.
- **Google Drive:** OAuth `state` validation, escaped error pages, tools no longer open a login browser on their own.
- **Embedded browser:** Web messages are only accepted from mammouth.ai or the configured start page.
- **SSH:** `ssh_transfer_file` respects the file sandbox; editing a host no longer wipes the stored password.

### 🐛 Bug Fixes & Stability
- Atomic `save_config` with an mtime-based read cache; the `browser_agent` config section is loaded again.
- OAuth tokens are looked up by SHA-256 hash with an index instead of decrypting every row per request.
- Scheduler tasks are claimed atomically (no double runs); handlers no longer block the GUI thread.
- Timeouts kill the whole process tree; shell output is UTF-8.
- Tunnel lifecycle no longer leaves orphaned cloudflared/ngrok/Funnel processes; thread-safe GUI logging; global hotkey deadlock fixed.
- Google Drive status and login polling run in the background; snipping watcher uses the clipboard sequence number.
- Unicode typing via `SendInput`; updater passes paths via environment; tray restart waits for the old server.
- **OAuth database is now central:** Release builds store `oauth.db` in `%APPDATA%\MammouthDefroster9000`, so registered MCP connections survive updates; the install's existing `oauth.db` is taken over once.
- Tailscale Funnel on/off commands run in order on one worker, so switching to Funnel no longer turns it off right away.
- A valid token always passes authentication; the IP lockout only applies to missing or invalid tokens (one stale client no longer locks out all tunnelled connections).
- Refresh tokens get their own 90-day lifetime instead of expiring with the 30-day access token.
- The browser agent launches Edge/Chromium with its sandbox enabled (no `--no-sandbox` warning).

## [0.5.0] - 2026-10-06

### 🌐 Playwright Browser Automation Agent
- **Full Agentic Browser Control (`modules/browser_agent.py`):** Integrated Microsoft Playwright running directly against native Microsoft Edge (`channel="msedge"`), offering Claude Desktop-equivalent browser navigation, click, form fill, and JavaScript evaluation tools with zero external browser downloads.
- **Numbered Interactive Element Indexing:** Automatically extracts and numbers visible interactive elements (`[1]`, `[2]`), providing deterministic click and fill targets for LLM decision making.
- **Multimodal Visual Inspection:** Dedicated `browser_screenshot` tool returning high-resolution captures via `FastMCPImage` for vision-capable models.
- **Rendered Markdown Extraction:** Extracts structured Markdown from modern client-rendered single-page applications.
- **Persistent Profile & Session Storage:** Isolated profile directory (`data/agent_browser_profile/`) preserving logins, cookies, and local storage.
- **SSRF Shield:** Blocks private cloud metadata endpoint navigation (`169.254.169.254`).

### 💻 Mammouth Code CLI Agent Bridge
- **Official CLI Agent Integration (`modules/mammouth_code.py`):** 1-click PowerShell installer, interactive console launcher, headless runner, and dual-bridge MCP auto-synchronization for `mammouth.exe`.

### ⏱️ Automated Task Scheduler & Triggers
- **Automated Task Scheduler (`modules/task_scheduler.py`):** Recurring background prompt executions targeting Mammouth Web chat, Mammouth Code CLI, or PowerShell scripts with bundled presets and live countdown UI timers.

### 🎨 Brand Theme & Cockpit Enhancements
- **Authentic Brand Theme:** Aligned Cockpit UI with official Mammouth AI palette (Warm Charcoal, Pure Ivory, Tusk Bronze).
- **Zen Mode:** One-click distraction-free full-viewport toggle for the embedded web app.
- **Global Win32 Hotkey (`modules/global_hotkey.py`):** System-wide shortcut (`Ctrl+Shift+M`) to instantly summon or minimize the Cockpit.

### 🔒 Security Hardening
- **SQLite OAuth DPAPI Encryption:** Hardware-backed DPAPI encryption for tokens stored in `oauth.db` with fail-closed security and `compare_digest` validation.

## [0.4.3] - 2026-09-28

### 🐛 Bug Fixes & Stability Enhancements
- **Crash Elimination on Download (`modules/embedded_browser.py`):** Resolved the `0xc0000409` (`FAST_FAIL_FATAL_APP_EXIT` in `ucrtbase.dll`) crash that terminated the application when selecting a save destination.
- **Thread-Safe UI Queue Marshalling:** Replaced re-entrant synchronous Tkinter calls (`configure`, `after`) during WebView2 COM message dispatch with a thread-safe message queue (`_safe_ui_call` and `_schedule_ui_queue_poll`), preventing Tcl re-entrancy panics.
- **Protected Download State Tracking:** Replaced unmanaged COM event subscriptions on `CoreWebView2DownloadOperation.StateChanged` with a non-blocking background filesystem watcher (`_watch_download_completion`) that safely signals completion without native delegate thunk crashes.
- **Dedicated STA File Dialog Thread:** Run WinForms `SaveFileDialog` inside an isolated STA thread (`SetApartmentState(ApartmentState.STA)`), eliminating apartment state conflicts and removing legacy buffer-vulnerable struct calls.
- **Resilient Workspace Initialization (`server.py`):** Added automatic creation of the workspace root in `local_exec_command` if not yet present on disk.
- **OAuth Reconnection & Multi-Session Persistence (`server.py`):** Added root route aliases (`/authorize`, `/token`, `/register`) and RFC 9728 subpath support (`/.well-known/oauth-protected-resource/{subpath:path}`, `/.well-known/oauth-authorization-server/{subpath:path}`) in `server.py` and `SecurityAndAuthMiddleware`. Resolves connection drops where restarting Defroster 9000 blocked Mammouth AI from refreshing tokens or re-authenticating across sessions.

## [0.4.2] - 2026-09-28

### 🐛 Bug Fixes & Security Enhancements
- **Download Dialog Freeze Fix (`modules/embedded_browser.py`):** Fixed a cross-thread deadlock where native download file dialogs and WebView2 COM events attempted to update the Tkinter UI from a background thread, causing the application to hang when saving files.
- **DPAPI Authentication Security (`config.py`, `gui.py`, `server.py`):** Restored strict DPAPI (`CryptProtectData`) encryption for the `api_token` in `config.json`. Removed plaintext fallbacks that caused silent token regeneration and broken client configurations. Enforced cryptographically secure 32-hex character tokens (`mc_<32-hex-chars>`) as per strict fail-closed security guidelines.
- **Robust Exception Handling:** DPAPI encryption and decryption now raise explicit errors on failure, preventing invalid state loops or silent plaintext exposure.


All notable changes to **Mammouth Defroster 9000** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-09-25

### 🐛 Critical Bugfixes: Downloads & Screenshot Paste
- **Download Dialog Crash Fix:** Fixed an immediate application crash when clicking "OK" on the native Save File dialog. Resolved premature closing and disposing of the popup WebView2 instance while downloads are starting or active. Added resilient `tkinter.filedialog` fallback and safe deferral completion.
- **Screenshot & Paste Freeze Fix:** Fixed an issue where the application could hang when capturing a screenshot and inserting it into chat. Moved WebView2 script execution to the main UI thread to eliminate COM cross-thread deadlocks. Added a guaranteed `finally` key-up release for `VK_CONTROL` and `VK_V` preventing stuck modifier keys. Added an exponential retry loop with safe `finally` clipboard closing in `copy_image_to_clipboard`.

### 🦣 Mammouth AI Quota & Usage Monitor in Sidebar
- **Native Sidebar Quota Widget (`CTkMammouthQuotaCard`):** Integrates real-time quota telemetry directly into the Cockpit sidebar above the telemetry card.
- **Reverse-Engineered Mammouth Telemetry Bridge:** Leverages the embedded WebView2 session via `ExecuteScriptAsync` to query `/api/user/currentUsage` and `/api/user/recentUsage` with zero credential or Cloudflare issues.
- **Model Family Breakdown:** Displays proportional stacked progress bar and legend dots for active AI model families (Claude, GPT, GLM, Gemini, Perplexity).
- **Plan Multipliers & Limits:** Accurately computes limits based on 150-cent ($1.50) rolling 3-hour window with plan multipliers (Starter x1, Standard x3, Expert x10).
- **5-Minute Background Auto-Refresh:** Automatically refreshes quota status in the background every 300 seconds (configurable) and upon navigating to the Mammouth WebApp tab.
- **Manual 🔄 Refresh Button:** One-click instant refresh with feedback animations and debouncing.
- **Interactive 1-Click Jump:** Clicking the quota card seamlessly focuses the in-app Mammouth AI Web tab.
- **Settings Tab Controls:** Toggle sidebar quota display and configure refresh interval (1, 2, 5, 10, or 15 minutes) under ⚙️ Settings.

---

## [0.4.0] - 2026-09-24

### 💬 In-App Mammouth.ai WebView2 Cockpit
- **Native Embedded WebView2:** Microsoft Edge WebView2 control embedded directly into the CustomTkinter Cockpit.
- **Session & Login Persistence:** Persistent cookies, credentials, and localStorage saved to `data/browser_profile/`.
- **Keyboard Shortcuts & Context Menus:** Enabled browser accelerator keys (`Ctrl+C`, `Ctrl+V`, `Ctrl+A`) and native right-click context menus.
- **Native Downloads:** Intercepts file downloads with native `SaveFileDialog`, live toolbar status updates, and auto-fallback to `~/Downloads`.
- **OAuth Popup Windows:** Modal popups for Google, GitHub, and Apple login flows sharing the parent session environment.

### 🛡️ Security Hardening & Fail-Closed Gates
- **H-1 Fail-Closed Token Gate:** Automatically generates high-entropy cryptographic keys (`mc_...`) if `enforce_auth: true` has an empty token, guaranteeing authentication never fails open.
- **H-2 Mandatory Updater Checksums:** Hard-fails update downloads if SHA256 assets are missing or checksums mismatch.
- **H-3 Unreal Engine HMAC Gate:** Rejects unauthenticated discovery pong messages and enforces session keys for remote execution.
- **H-4 Synchronized Documentation & Installer:** Added SHA256 integrity verification to `install.ps1` and aligned all version references across `README.md`, `CHANGELOG.md`, and `RELEASE_NOTES.md`.
- **M-1 Hardware-Backed DPAPI Fail-Closed:** Eliminated identity fallback in `google_drive.py`; enforces strict `RuntimeError` fail-closed policy with zero plaintext token storage.
- **Live Windows Blackbox Pentest Verification:** Verified compiled `MammouthDefroster9000-server.exe` against 4 live security gates (401 unauth, 429 backoff lockout after 5 failures, empty-token auto-gen, constant-time `compare_digest` tamper rejection).
- **Secret Redaction:** Comprehensive regex redaction masking all Bearer tokens, OAuth secrets, and authorization codes in logs.

### 🎨 Visual Redesign & DevOps Enhancements
- **Mammouth.ai SaaS Charcoal Theme:** Complete visual redesign aligning with Mammouth.ai identity (`#202124`, `#2F2F33`, `#10B981`).
- **Consolidated Shell Permissions:** Unified diagnostics and admin shell toggles into Tab 2.
- **1-Click Screenshot Vision Injector:** Captures screen via Windows Snipping Tool and automatically injects image into Mammouth AI chat.

---

## [0.3.2] - 2026-09-20

### ⚡ Native OAuth 2.0 & RFC 7591 Authorization Server
- **RFC 8414 & RFC 9728 Discovery:** Endpoint auto-discovery for Mammouth.ai and enterprise MCP clients.
- **PKCE Verification:** Support for both `S256` and `plain` code challenge methods.
- **Refresh Token Rotation:** Automatically rotates refresh tokens on every exchange.

---

## [0.3.1] - 2026-09-19

### 🛡️ Security Auditing & Defense-in-Depth
- **Shell Blocklist:** Integrated 60+ pattern shell security filter for `local_exec_command`.
- **Unreal Engine Injection Protection:** Converted all Unreal script string interpolations to `json.dumps()`.

---

## [0.3.0] - 2026-09-19

### ☁️ Google Drive Cloud Storage & Document Automation (`modules/google_drive.py`)
- **Native Google Drive Integration:** Added comprehensive Google Drive cloud connectivity to Mammouth Defroster 9000, bringing total modular capabilities to 11 modules and 77 active tools.
- **Desktop OAuth 2.0 Loopback Flow:** Built-in HTTP loopback authentication server on `http://127.0.0.1:8085` enabling seamless one-click browser authorization without manual copy-pasting of authorization codes.
- **Token Security with Windows DPAPI:** OAuth refresh and access tokens are encrypted at rest using hardware-backed Windows Data Protection API (`CryptProtectData`).
- **Service Account Support:** Seamless fallback to Google Cloud Service Account JSON (`service_account.json`) for headless and automated daemon environments.
- **Read & Write Cloud Tools:**
  - `gdrive_status`: Real-time connectivity diagnostics, authenticated account info, and cloud storage quota (used/total/trash).
  - `gdrive_list_files`: Browse folders and query files by name, MIME type, or metadata.
  - `gdrive_search_files`: Full-text content and filename search across Google Drive.
  - `gdrive_get_metadata`: Inspect detailed file attributes, owners, web links, and permissions.
  - `gdrive_read_file`: Read file contents with automatic export for Google Docs (to plain text/markdown) and Google Sheets (to CSV).
  - `gdrive_write_file`: Create and write new files directly in Google Drive with text/markdown/code content.
  - `gdrive_update_file`: Overwrite and update existing file contents directly in Google Drive.
  - `gdrive_download_to_workspace`: Download files directly into the sandboxed local workspace.
  - `gdrive_upload_from_workspace`: Upload workspace files directly to Google Drive.
  - `gdrive_create_folder`: Create directory structures in Google Drive.
  - `gdrive_delete_file`: Safely move files to trash or permanently remove them.
- **Cockpit GUI Integration (`gui.py`):** Added a dedicated Google Drive card in the Modular Capabilities tab with real-time status badge, "🔑 Connect Google Drive" browser launcher, "📂 Select credentials.json" file importer, and "🔌 Disconnect" button.

---

## [0.2.3] - 2026-09-18

### 🪶 Packaging & Binary Footprint Optimization
- **Eliminated Transitive ML/Data-Science Bloat:** Explicitly configured PyInstaller `excludes` in `MammouthDefroster9000.spec` to omit non-essential libraries (`torch`, `torchvision`, `torchaudio`, `transformers`, `accelerate`, `optimum`, `onnxruntime`, `faiss`, `sklearn`, `scipy`, `cv2`, `pandas`, `pyarrow`, `av`, `botocore`, `boto3`, `google`, `anthropic`, `matplotlib`, `nltk`) inadvertently collected from system Python environments.
- **Drastic Size Reduction:** Release ZIP package compressed size slashed from **540 MB** to **~109 MB** (~80% reduction), and uncompressed footprint reduced from **1.5 GB** to **~280 MB**.
- **Fixed Windowed Server Startup:** Added `SafeStream` wrapper and `log_config=None` to prevent Uvicorn `DefaultFormatter` crashes (`AttributeError: 'NoneType' object has no attribute 'isatty'`) when starting the server from the windowed GUI binary.
- **Improved Cold-Start Performance:** Significantly reduced DLL scanning and assembly overhead on startup.
- **Clean Distribution Mirroring:** Added `/PURGE` to `build.bat` robocopy synchronization to ensure no stale development scripts pollute distribution folders.
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
