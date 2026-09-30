# 🦣 Mammouth Defroster 9000 — Release Notes

> **Platform:** Dedicated Sovereign Windows Cockpit & DevOps Automation for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Current Version:** **v0.4.3**

---

## 🚀 What's New in v0.4.3

### 🐛 Bug Fixes & Stability Enhancements
* **Download Crash Elimination (`modules/embedded_browser.py`):** Resolved the `0xc0000409` (`FAST_FAIL_FATAL_APP_EXIT` in `ucrtbase.dll`) crash that terminated the application upon selecting a destination in the save dialog.
* **Thread-Safe UI Queue Marshalling:** Replaced re-entrant synchronous Tkinter widget calls during WebView2 COM message dispatch with a thread-safe message queue (`_safe_ui_call` and `_schedule_ui_queue_poll`), completely preventing Tcl re-entrancy panics.
* **Protected Download State Tracking:** Replaced unmanaged COM event subscriptions on `CoreWebView2DownloadOperation.StateChanged` with a non-blocking background filesystem watcher (`_watch_download_completion`) that safely signals completion without native delegate thunk crashes.
* **Dedicated STA File Dialog Thread:** Run WinForms `SaveFileDialog` inside an isolated STA thread (`SetApartmentState(ApartmentState.STA)`), eliminating apartment state conflicts and removing legacy buffer-vulnerable struct calls.
* **Resilient Workspace Initialization (`server.py`):** Added automatic creation of the workspace root in `local_exec_command` if not yet present on disk.
* **OAuth Reconnection & Multi-Session Persistence (`server.py`):** Fixed an issue where restarting Defroster 9000 prevented Mammouth.ai from reconnecting without deleting and re-adding the MCP server. Added standard OAuth root route aliases (`/authorize`, `/token`, `/register`) and RFC 9728 discovery subpaths (`/.well-known/oauth-protected-resource/{subpath:path}`) alongside case-insensitive Bearer header parsing, allowing refresh tokens and reconnect handshakes to persist seamlessly across restarts.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.4.3-windows-x64.zip`
* **SHA-256 Checksum:**
  ```text
  1e1fd3b41282655878442bed7a1fde7215ec7639ac895cccae311ed88128e12b
  ```

---

## 🚀 What's New in v0.4.2

### 🐛 Bug Fixes & Security Enhancements
* **Download Dialog Freeze Fix:** Fixed a critical cross-thread deadlock where native download file dialogs and WebView2 COM events attempted to synchronously update the Tkinter UI from a background thread. File downloads in the Mammouth browser will no longer cause the application to hang.
* **DPAPI Authentication Security:** Restored strict DPAPI (`CryptProtectData`) encryption for the `api_token` in `config.json`. Removed insecure plaintext fallbacks that caused silent token regeneration, breaking client configuration on every restart.
* **Cryptographically Secure Tokens:** Enforced strict `mc_<32-hex-chars>` token generation format as per fail-closed security guidelines.
* **Robust Exception Handling:** DPAPI encryption and decryption now raise explicit errors on failure, preventing invalid state loops or silent plaintext exposure.

## 🚀 What's New in v0.4.1

### 🛡️ Security Audit Remediations & OAuth Hardening
* **OAuth Consent CSRF Protection (F-01):** Bound ephemeral cryptographic anti-CSRF tokens to authorization consent requests (`/oauth/authorize`). Consent form submissions must validate against server-side session state, eliminating cross-site request forgery risks.
* **RFC 7591 Dynamic Client Registration with Allowlisting (F-02):** Dynamic client registration (`/oauth/register`) allows trusted endpoints (`mammouth.ai` and `localhost`) with strict IP rate limiting, while strictly rejecting untrusted origins unless authenticated via `registration_token` or `api_token`.
* **Shell Statement Separator Bypass Defense (F-03):** Expanded statement splitting in `_validate_shell_command` and `_check_readonly_path_guard` to include newlines (`\n`, `\r\n`), and boolean chaining operators (`&&`, `||`). `Out-File` is explicitly blocked in read-only shell mode.
* **Automatic Tailscale Funnel & Safe Tunnel Modes:** Streamlined Tailscale Funnel background proxy activation on port 8000 when selected, providing seamless public HTTPS SSE connectivity for Mammouth.ai without manual CLI steps.
* **Query-String Token Deprecation (F-05):** Removed query-string `?token=` credential acceptance in `SecurityAndAuthMiddleware`. Credentials must be supplied via `Authorization: Bearer` headers, preventing token leakage in browser histories, referer headers, and proxy access logs.
* **OAuth PKCE & Client Secret Verification (F-09):** The token endpoint (`/oauth/token`) verifies `client_secret` against registered confidential client records using timing-safe comparisons, while supporting standard public PKCE S256 clients.

### 📝 Parameter Parsing & File Write Hardening
* **Elimination of Quote Truncation & Phantom Files:** Introduced path input sanitation (`_clean_path_input`) in `file_ops.py` to strip accidental wrapping and internal double quotes (`"`). Solves the issue where paths with quotes or spaces were split or truncated, creating corrupted files (such as phantom `2.0` files).
* **Strict Workspace Root Anchoring:** Relative paths and paths with leading slashes (`/` or `\`) are strictly anchored to the workspace root (`ws_root / rel_clean`) instead of jumping to the drive root (`D:\`).
* **1:1 Byte-for-Byte File Writes:** Switched `file_write` and `file_replace_chunk` to `open(..., newline="")` ensuring scripts, headers, and code content are preserved byte-for-byte without CRLF translation mangling.
* **1:1 Shell Command Execution:** Upgraded `local_exec_command` to execute via PowerShell (`shell=False`) instead of `cmd.exe /c` (`shell=True`). Arguments, quotes, backslashes, multiline scripts, and exit codes are passed through 1:1 without `cmd.exe` quote stripping. Added workspace anchoring for relative `cwd` parameters.

### 🐛 Browser Stability & Navigation Crash Fixes
* **Cloudflare Turnstile & SPA Navigation Fix:** Eliminated frame script injection (`AddScriptToExecuteOnDocumentCreatedAsync`) that interfered with Cloudflare Turnstile verification iframes on mammouth.ai, resolving renderer crashes when clicking "Start / Loslegen".
* **Download Dialog Crash Fix:** Neutralized unhandled delegate events (`on_download_starting`, `on_navigation_completed`, `on_script_notify`) at the class level on `EdgeChrome` to prevent Python.NET COM interop crashes during file downloads.
* **Screenshot & Paste Freeze Fix:** Ensured WebView2 script execution runs exclusively on the main UI thread, added guaranteed `finally` key-up releases for modifier keys, and added retry loops with safe clipboard closing.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.4.1-windows-x64.zip`
* **SHA-256 Checksum:**
  ```text
  ba13dadea17ae7230fe4cd2a629b37fe163022d2ccee6dcf7e1c1d8d889f0642
  ```

---

## 🚀 What's New in v0.4.0

### 💬 Native In-App Mammouth.ai WebView2 Cockpit
* **Integrated Mammouth.ai WebApp Tab:** Embedded Microsoft Edge WebView2 control directly inside the Cockpit. No need for a separate browser window.
* **Persistent Sessions & Profiles:** Cookies, sessions, local storage, and Google/GitHub OAuth logins persist across restarts in `data/browser_profile/`.
* **Full Keyboard Shortcuts & Context Menus:** Full support for `Ctrl+C`, `Ctrl+V`, `Ctrl+A`, `Ctrl+X`, and right-click context menus.
* **Native File Downloads & SaveFileDialog:** Automatic download interception with native Windows save dialog, live status bar feedback, and auto-fallback to `~/Downloads`.
* **OAuth Popup Windows:** Modal popups for Google, GitHub, and Apple login flows sharing the same session environment.

### 🛡️ Security Hardening & Fail-Closed Authentication
* **Fail-Closed Token Gate (H-1):** Enforced fail-closed token policy; auto-generates high-entropy cryptographic keys (`mc_...`) if unconfigured.
* **Verified Auto-Updater (H-2):** Mandatory SHA256 checksum verification against release assets before code execution.
* **Unreal Engine Remote Execution HMAC (H-3):** All discovery pong messages require valid HMAC authentication with session keys.
* **1-Click Sovereign Web-Installer (H-4):** Complete `install.ps1` installer with SHA256 checksum integrity verification and SmartScreen MotW removal.
* **Hardware-Backed DPAPI Fail-Closed (M-1):** Eliminated identity fallback in `google_drive.py`; enforces strict `RuntimeError` fail-closed policy (zero plaintext token fallback).
* **Live Windows Runtime Blackbox Pentest:** Verified compiled `MammouthDefroster9000-server.exe` against 4 live security gates (401 unauth, 429 backoff lockout after 5 failures, empty-token auto-gen, constant-time `compare_digest` tamper rejection).
* **Sensitive Token Redaction:** Comprehensive regex redaction masking all Bearer tokens, OAuth secrets, and authorization codes in logs.

### 🎨 Visual Redesign & Unified Shell Permissions
* **SaaS Charcoal Aesthetic:** Theme aligned with Mammouth.ai Charcoal (`#202124`) and emerald accents (`#10B981`).
* **Consolidated Shell Permissions:** Unified diagnostics and admin shell toggles into Tab 2.
* **1-Click Screenshot Vision Injector:** Captures screen via Windows Snipping Tool and automatically injects image into Mammouth AI chat.

---

## 🚀 What's New in v0.3.2

### ⚡ Native OAuth 2.0 & RFC 7591 Authorization Server
* **Native 1-Click Login for Mammouth AI:** Full support for RFC 8414 / RFC 9728 Discovery, RFC 7591 Dynamic Client Registration, PKCE (`S256`), and Token Exchange.
* **No More Manual API Key Pasting:** Mammouth AI connects directly via native OAuth consent screen and maintains access via refresh tokens.
* **Security & Auth Hardening:**
  * **Refresh Token Rotation:** Refresh tokens are rotated on each exchange, invalidating the previous token.
  * **Registration Rate-Limiting & Gate:** Limits registration to 5/hour per IP, with an optional `registration_token` secret gate in `config.json`.
  * **Strict `redirect_uri` Validation:** Prevents authorization code theft and open redirects.

### 🛡️ Comprehensive Security Audit Fixes
* **Shell Command Defense (`local_exec_command`):** Integrated full 60+ pattern shell blocklist with de-obfuscation, blocking destructive cmdlets and scripts.
* **Unreal Engine Bridge Hardening (`unreal_engine.py`):** Eliminated all f-string script injections across all 12 actor/asset/light/material tools using safe `json.dumps()` serialization.
* **API Key Protection:** Dashboard now masks the API key by default (`••••••••`) with an eye toggle.

### 🎨 Dashboard UI Overhaul
* **Mammouth AI Aesthetic:** Restyled with dark and light mode palettes matching Mammouth AI.
* **OAuth Status Badge:** Real-time `⚡ OAuth 2.0 Ready` indicator in the dashboard header.

---

## 🚀 What's New in v0.3.0

### ☁️ Google Drive Cloud Storage & Document Automation (`modules/google_drive.py`)
* **Seamless Google Drive Integration:** Full cloud drive connectivity for connected AI assistants (Mammouth.ai, Claude Desktop, Cursor), bringing the total platform capabilities to **11 modules and 77 active tools**.
* **Interactive Desktop OAuth 2.0 Loopback:** Built-in HTTP loopback flow (`http://127.0.0.1:8085`) that allows instantaneous 1-click browser login without manual token pasting.
* **Hardware-Backed DPAPI Encryption:** Stores Google OAuth refresh and access tokens encrypted at rest via Windows Data Protection API (`CryptProtectData`).
* **Service Account & Headless Support:** Seamless fallback to Google Cloud Service Account credentials (`service_account.json`).
* **Complete Read & Write Toolset:**
  * `gdrive_status`: Diagnostics, account email, display name, and storage usage/quota.
  * `gdrive_list_files`: Browse folders or search by MIME type and custom Drive query filters.
  * `gdrive_search_files`: Full-text document and filename search across the entire Drive.
  * `gdrive_get_metadata`: Inspect detailed file attributes, owners, and web links.
  * `gdrive_read_file`: Read content with automatic conversion (Google Docs -> markdown/text, Google Sheets -> CSV).
  * `gdrive_write_file`: Create and write new files directly in Google Drive with text/markdown/code content.
  * `gdrive_update_file`: Overwrite and update existing file contents directly in Google Drive.
  * `gdrive_download_to_workspace`: Download files directly into the sandboxed local workspace.
  * `gdrive_upload_from_workspace`: Upload local workspace files to Google Drive.
  * `gdrive_create_folder`: Create directory structures in Google Drive.
  * `gdrive_delete_file`: Safely move files to trash or permanently remove them.
* **Cockpit GUI Integration (`gui.py`):** Added a dedicated Google Drive card in Tab 2 (Modular Capabilities) with live connection badge, "🔑 Connect Google Drive" browser launcher, "📂 Select credentials.json" file picker, and "🔌 Disconnect" control.

---

## 🚀 What's New in v0.2.3

### 🪶 Binary Footprint Optimization (~80% Size Reduction)
* **Eliminated Transitive ML/Data-Science Bloat:** Excluded heavy, unneeded libraries (`torch`, `torchvision`, `torchaudio`, `transformers`, `accelerate`, `optimum`, `onnxruntime`, `faiss`, `sklearn`, `scipy`, `cv2`, `pandas`, `pyarrow`, `av`, `botocore`, `boto3`, `google`, `anthropic`, `matplotlib`, `nltk`) inadvertently collected from system Python development environments by PyInstaller.
* **Massive Bandwidth & Storage Reduction:**
  * **Compressed ZIP:** Reduced from **~540 MB** down to **~109 MB** (~80% reduction).
  * **Unpacked Footprint:** Reduced from **~1.5 GB** down to **~280 MB**.
* **Fixed Server Startup Crash in Windowed GUI:** Resolved an issue where starting the server from the windowed executable failed with an uncaught `AttributeError: 'NoneType' object has no attribute 'isatty'` / `DefaultFormatter` crash due to `sys.stdout` being `None` in windowed mode. Integrated a `SafeStream` stream shim and explicitly bypassed Uvicorn's tty formatter.
* **Faster Startup:** Drastically reduced DLL loading overhead, memory consumption, and cold-start latency.
* **Single Release Documentation:** Unified all versioned release notes into this canonical `RELEASE_NOTES.md`.

---

## 🛠️ Core Capabilities (v0.2.2 & v0.2.3)

### 👁️ Desktop Vision & Privacy Consent Gate (`modules/screen_capture.py`)
* **Interactive Desktop Prompt:** When an MCP client requests a screenshot while consent is active, a native confirmation modal appears directly in the GUI asking for approval.
* **Session Consent & Granular Controls:** Added toggle switch (`Require Consent`) and `🔓 Grant Session Consent` button to both Tab 2 (Skills) and Tab 4 (Settings).
* **New MCP Tools:** Registered `screen_grant_consent(duration="once"|"always")` and `screen_revoke_consent()` as MCP tools for autonomous or programmatic approval.

### 🖱️ Desktop Mouse & Keyboard Automation (`modules/desktop_input.py`)
* **Native Windows User32 Subsystem:** Direct `user32.mouse_event`, `user32.SetCursorPos`, and `user32.keybd_event` (with `KEYEVENTF_UNICODE`) for 100% reliable execution in interactive desktop sessions without PyAutoGUI failsafe crashes.
* **Full Toolset:**
  * `desktop_get_screen_info`: Returns screen resolution (width x height) and current mouse cursor coordinates.
  * `mouse_move`: Coordinates-based cursor positioning with optional smooth interpolation (`smooth=True`, `duration`).
  * `mouse_click`: Left, right, and middle clicks with multiple click count (`clicks=1..5`) and configurable interval.
  * `mouse_drag`: Robust drag-and-drop between points with smooth movement interpolation.
  * `mouse_scroll`: Precise vertical mouse wheel scrolling up or down.
  * `mouse_get_position`: Immediate cursor coordinates `(x, y)`.
  * `keyboard_type`: Types arbitrary strings and Unicode symbols reliably into the focused window.
  * `keyboard_press`: Single-key strokes (`enter`, `esc`, `tab`, `space`, arrows, etc.) with repeated press support.
  * `keyboard_hotkey`: Multi-key combination sequences (`ctrl+t`, `ctrl+w`, `alt+f4`, `ctrl+c`, etc.).

### 🖥️ Dual-Executable Architecture & Packaging
* **`MammouthDefroster9000.exe`:** Sovereign windowed desktop cockpit GUI. Supports `--autostart` flag and `auto_start_server` config setting.
* **`MammouthDefroster9000-server.exe`:** Dedicated CLI console server with live Uvicorn log streaming and graceful Ctrl+C shutdown.
* **`start_server.bat` & `start_gui.bat`:** Clean, reliable batch launchers included in the release distribution.

### 🔑 Original Plaintext Bearer API Key Display & Hygiene
* **Interactive Dashboard Card (`gui.py`):** The main endpoint card displays the clean alphanumeric Bearer key.
* **Privacy Toggle:** Quickly switch between `🔒 Hide Key` and `👁️ Show Key`.
* **One-Click Copy:** `📋 Copy Key` copies the plaintext token straight to your clipboard for instant setup in Mammouth.ai.
* **Transparent Migration (`config.py`):** Automatically upgrades legacy `dpapi:` tokens to clean plaintext tokens.

### 🛡️ FastMCP & MCP Client Compatibility Fixes
* **Empty List IndexError Fix:** Prevented MCP clients from crashing on empty lists (`memory_list`, `task_list`) by guaranteeing valid `[TextContent(text="[]")]` payloads.
* **Flexible Parameter Aliases:** Added `path` alias for `directory_path` / `file_path` across file operations and `id` alias for `task_id`.

---

## 📦 Downloads & Artifacts

| File | Platform | Size | Description |
| :--- | :---: | :---: | :--- |
| **`MammouthDefroster9000-v0.4.0-windows-x64.zip`** | **Windows x64** | **~86.4 MB** | Official optimized standalone release package with executables, modules, and documentation. |

---

## 📜 Full Version History
For detailed commit history and changes across earlier releases, see [CHANGELOG.md](CHANGELOG.md).
