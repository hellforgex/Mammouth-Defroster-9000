# 🦣 Mammouth Defroster 9000 — Release Notes

> **Platform:** Dedicated Sovereign Windows Cockpit & DevOps Automation for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Current Version:** **v0.3.2**

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
* **Seamless Google Drive Integration:** Full cloud drive connectivity for connected AI assistants (Mammouth.ai, Agent Zero, Claude Desktop, Cursor), bringing the total platform capabilities to **11 modules and 77 active tools**.
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
* **Empty List IndexError Fix:** Prevented MCP clients (including Agent Zero) from crashing on empty lists (`memory_list`, `task_list`) by guaranteeing valid `[TextContent(text="[]")]` payloads.
* **Flexible Parameter Aliases:** Added `path` alias for `directory_path` / `file_path` across file operations and `id` alias for `task_id`.

---

## 📦 Downloads & Artifacts

| File | Platform | Size | Description |
| :--- | :---: | :---: | :--- |
| **`MammouthDefroster9000-v0.2.3-windows-x64.zip`** | **Windows x64** | **~109 MB** | Official optimized standalone release package with executables, modules, and documentation. |

---

## 📜 Full Version History
For detailed commit history and changes across earlier releases, see [CHANGELOG.md](CHANGELOG.md).
