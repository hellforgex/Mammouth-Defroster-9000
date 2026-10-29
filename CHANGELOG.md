# Changelog

## [0.7.2] - 2026-10-29

### ⚡ Features & MCP Tool Promotion Architecture
- **Tool Profiles & Schema Budget Management:** Resolved tool promotion failures in Mammouth AI chat ("No matching tools were promoted") caused by schema token overload (86 tools totaling ~16,461 tokens vs ~7,719 token session budget):
  - **Dynamic Tool Profiles:** Introduced configurable tool exposure profiles:
    - `🛡️ Mammouth Chat Safe` (Default): 12 core tools (`defroster_catalog`, `directory_list`, `file_read`, `file_write`, `command_run`, `screen_capture`, `browser_navigate`, `browser_snapshot`, `memory_save`, `memory_recall`, `system_get_specs`, `clipboard_get_text`) consuming only **~2,700 tokens** (< 35% of platform budget), giving models immediate directory listing capability on session start.
    - `💻 Developer & Scripting`: 14 tools (~3,800 tokens) for workspace file editing, search, local PowerShell execution, and diagnostics.
  - **Automated Tool Promotion Refresh (`tools/list_changed`):** When switching tool profiles via `defroster_catalog(switch_profile=...)` or the GUI combobox, the server broadcasts an MCP `notifications/tools/list_changed` notification to active sessions, allowing connected AI models to automatically re-discover tools without requiring manual intervention.
  - **Path Aliases (`workspace:/<path>` & `@workspace/<path>`):** Both file tools (`file_read`, `file_write`, `file_replace_chunk`, `file_search_text`, `directory_list`, `directory_tree`) and shell path guard now recognize `workspace:/` and `@workspace/` aliases, eliminating path guessing and drive letter hallucinations.
  - **Actionable Sandbox Violation Feedback:** Enhanced path violation messages to provide actionable guidance, directing models to use `directory_list` and `workspace:/` relative syntax.
  - **Crystal-Clear Schema Budget Status:** Eliminated contradictory limit messages; token budgets are evaluated and displayed consistently against the platform limit (~7,719 tokens).
    - `👁️ Web & Vision`: 12 tools (~3,300 tokens) for Playwright browser automation and multi-monitor screen capture.
    - `⏱️ Tasks & Automation`: 11 tools (~2,900 tokens) for scheduled background triggers and Kanban boards.
    - `⚡ Full Defroster`: 86 tools (~16,461 tokens) for uncapped clients (Claude Desktop, Cursor).
    - `⚙️ Custom Module Selection`: Dynamically exposes only tools belonging to modules toggled Active in the GUI.
  - **Dynamic Server-Side Tool Filtering:** FastMCP `_list_tools_mcp` dynamically reads the active profile from `config.json` on every request. Switching profiles in the GUI takes effect **immediately** on the very next chat session without requiring a server restart.
  - **OpenAPI Schema Sanitization & Type Bug Fixes:**
    - Repaired `screen_set_tracked_window` in `screen_capture.py` (`target: Union[str, int] = "auto"`), eliminating untyped `{}` parameter schemas.
    - Repaired `memory_get` in `memory.py` (`id: Optional[Union[str, int]] = None`), eliminating empty dict `{}` inside `anyOf` arrays.
    - Added automated `_sanitize_mcp_tool_schema` in `server.py` that inspects every tool's `inputSchema` before serialization, ensuring 100% valid OpenAPI types.
  - **Enhanced `defroster_catalog` Router:** Now reports the active tool profile, promoted tools count, schema budget status, and supports on-the-fly profile switching via `switch_profile` parameter.
  - **GUI Modular Capabilities Overhaul:** Added an Active Tool Exposure Profile dropdown, live Schema Token Budget meter (`Estimated Schema Budget: ~2,485 tokens / 7,719 limit (Safe ✅)`), and 1-click `🛡️ Mammouth Chat Safe` preset button. Dashboard KPI tile displays `⚡ 10 Promoted (86 Total)`.

### 🐛 UI & Desktop Automation Fixes
- **Embedded Mammouth AI Browser Initialization & Anti-Shrink Guards:**
  - Resolved an issue where the embedded Mammouth AI WebView2 control would not appear or shrank to 1x1 pixels upon tab switching:
    - Added `update_idletasks()` and enforced minimum bounds (`max(self.viewport.winfo_width(), 400x300)`) in `set_tab_visible`.
    - Added dual deferred layout synchronizations (at 50ms and 150ms) to recalculate and expand the Win32 window to the fully rendered viewport dimensions.
    - Added deferred layout synchronizations in `ensure_initialized` (at 60ms and 200ms).
  - Packed the `"💬 Mammouth AI"` shortcut button in the top header bar (`right_box`) next to the Screenshot button for instant 1-click tab switching from any screen.
  - Added a primary accent `"💬 Mammouth AI"` button to the Dashboard quick actions bar for rapid navigation.
  - Updated startup lifecycle so that `auto_open_on_server_start: true` reliably brings the Mammouth AI tab into view.
  - Hardened `send_chat_prompt` with automatic `ensure_initialized()` and asynchronous polling for `CoreWebView2` initialization (up to 20 retries), preventing lost prompts during background tasks.
  - Added foreground window activation (`deiconify`, `lift`, `focus_force`) when automated tasks trigger.
- **Tasks & Automation Header Anti-Clipping:** Reordered Tkinter pack geometry across `tab_tasks`, `tab_memory`, `tab_mammouth_code`, `tab_skills`, and individual task cards so action buttons (`➕ New Task`, `🔄 Refresh`) are packed right-first (`side="right"`), preventing clipping against the window edge at all display resolutions. Subtitle labels now wrap gracefully via `wraplength=480`.
- **Web Chat Prompt Submission Engine:** Overhauled `send_chat_prompt` in `embedded_browser.py`:
  - Reset React synthetic value tracker (`el._valueTracker.setValue('')`), prompting React to recognize injected text and enable the Send button.
  - Implemented an intelligent multilingual send button resolver (`send`, `envoyer`, `submit`, `prompt`, `valider`) that strictly filters out file attachment, mic, and tool buttons, selecting the true action submit button.
  - Added an asynchronous polling retry loop (every 100ms up to 800ms) for React state synchronization.
  - Added native Win32 hardware keystroke fallback (`user32.keybd_event(VK_RETURN)`) with `isTrusted: true` on the UI thread for 100% reliable prompt dispatch.
- **In-App Updater & Auto-Update Overhaul:**
  - **Immediate Manual Feedback:** Clicking "Check for Updates Now" in Settings now opens the update dialog immediately upon finding an update, displaying release notes and download progress.
  - **Robocopy Engine (`apply_update.bat`):** Replaced fragile PowerShell file copying with Microsoft Robocopy (`/E /R:5 /W:1 /XF config.json oauth.db tasks.db memory.db hosts.json credentials.json /XD data workspace`), guaranteeing automatic retries on locked files and zero directory nesting bugs while fully preserving user configurations and databases.
  - **Process Lifecycle & Lock Management:** Added exact PID wait via PowerShell `$p.WaitForExit(15000)` and terminated lingering background server processes before file copying.
  - **SmartScreen Mark-of-the-Web Unblocking:** Automatically unblocks all extracted binaries via `Unblock-File`.
  - **Execution Working Directory:** Relaunches `MammouthDefroster9000.exe` with explicit working directory (`/D "%~2"`), preventing crashes caused by temporary directory cleanup.
  - **Dev-Mode Protection:** Gracefully informs users running from Python source to use `git pull` rather than attempting self-replacement of the git workspace.

### 🔒 Security Hardening & Remediation
- **Autonomous CLI Agent Sandboxing (A-01):** Disabled `mammouth_code` by default in configuration. Enforced strict admin shell permission check on `mammouth_code_run_task`, `launch_mammouth_terminal`, and installer tools, preventing arbitrary command and code execution when `allow_admin_shell=false`. Defaulted `auto_approve` to `False`.
- **Public Exposure Tunnel Gating (A-03):** Gated Tailscale Funnel in `start_server.bat`, `start_server.ps1`, and GUI server startup behind `server.auto_tunnel: true` and the configured port, preventing unwanted external port exposure.
- **Universal Path Guard Hardening (B-01, B-02, B-03):** 
  - Normalized parameter colon syntax (e.g. `-Path:C:\...`, `-LiteralPath:C:\...`) so parameters are properly inspected against the workspace boundary.
  - Expanded read-only inspection to all file-reading cmdlets (`Select-String`, `Get-FileHash`, `Get-ItemProperty`, `Get-WinEvent`, `Get-AuthenticodeSignature`, etc.).
  - Hardened root recursion detection against drive root traversal variants.
  - Blocked access to PowerShell PSDrives (`env:`, `HKLM:`, `HKCU:`, `cert:`, `variable:`, `wsman:`), `$env:` expansion, tilde (`~`) home directory expansion, and `Get-Clipboard`.
  - Prohibited UNC network paths (`//` and `\`) in Read-Only mode.
  - Expanded sensitive credentials denylist to include `credentials.json`, `oauth.db`, `gdrive_token.json`, `tasks.db`, `memory.db`, `.env`, and wildcard variants.
- **Security Shield Blacklist Expansion (B-07):** Added `curl.exe`, `wget.exe`, `Start-Process`/`saps`, `pwsh.exe -c`, `python.exe -c`/`-m`, and `Invoke-Command -ScriptBlock` to `BLOCKED_COMMAND_PATTERNS` across all modes.
- **Desktop Open Execution Gate (B-08):** Restricted `desktop_open` when `allow_admin_shell=false`: prohibited command-line arguments and execution of desktop binaries/scripts (`.exe`, `.bat`, `.cmd`, `.ps1`, etc.), permitting only safe web URLs (`http://`, `https://`, `mailto:`) and workspace documents.
- **PuTTY & SSH Management Hardening (B-09):** Disabled `putty_ssh` by default in configuration. Gated remote command execution and SCP file transfers behind admin shell permissions. Prohibited leading `-` in all parameter values and validated `remote_path`.
- **Package Supply Chain & Dependency Upgrades (C-05):** Fully upgraded all locked dependencies in `uv.lock` via `uv lock --upgrade` (`fastmcp` 4.1.4, `mcp` 2.3.0, `authlib` 1.9.1, `pillow` 13.0.0, `pyjwt` 2.15.1, `certifi`, etc.).
- **Update Verification & Zip-Slip Defense (C-01):** Added archive traversal checks (`_verify_zip_slip_safe`) to updater and `install.ps1` to prevent Zip-Slip vulnerabilities. Added support for release signature verification.

### ⚡ Features
- **Daily Startup Auto-Update Check:** Added 1x daily rate-limiting to automatic startup update checks (throttled to 24-hour intervals) while preserving immediate checks on manual button clicks.

## [0.7.1] - 2026-10-28

### 🐛 Fixes & Stability
- **Startup Crash Resolution (`gui.py`):** Fixed `NameError: name 'datetime' is not defined` when scheduled tasks exist in `tasks.db` by promoting `datetime`, `timezone`, `timedelta`, and `_encrypt_dpapi` to module level.
- **Splash Screen Masking:** Added `SplashScreen.close()` with full window unmapping, unmasking dialogs on unhandled startup errors.
- **Task Scheduler Hardening:** Added timezone normalization for ISO 8601 UTC stamps (`Z`) and error isolation across task card widgets.

## [0.7.0] - 2026-10-27

### ⚡ Feature 1: The Crown Jewel — Autonomous Self-Tooling & Infinite Skills
- **On-the-Fly Skill Creation:** AI assistants can autonomously author tailored Python and PowerShell scripts (`skills/*.py`, `skills/*.ps1`) using `file_write` when built-in tools do not cover a specific objective.
- **Zero-Cost Local Win32 Execution ($0.00 API Cost):** Direct execution of workspace scripts via `powershell_exec` or `command_run` inside the secured Win32 workspace sandbox, bypassing expensive external agent loops and API budget caps (`Budget has been exceeded`).
- **Infinite Capabilities:** Dynamically extends Defroster 9000 beyond its 85 built-in MCP tools without restarting the server or adding code to the binary.

### 🦣 Feature 2: Token-Budget-Safe Tool Discovery & Capability Router
- **Initial Discovery Anchor (`file_read`):** Enhanced `file_read` docstring with an embedded Module Compass describing the 10 capability domains. Resolves Mammouth.ai client schema budget exhaustion (where 85 tools exceed the 7,719-token limit in "On-Demand" mode).
- **Skill Directory & Capability Router (`defroster_catalog`):** Added a new FastMCP tool enabling AI assistants to explore tools by category (`files`, `shell`, `browser`, `screen`, `desktop`, `system`, `scheduler`, `gdrive`, `clipboard`, `memory`) or search terms without consuming large schema token budgets upfront.
- **Budget Interceptor:** Automated guidance and error interception instructing assistants to avoid external CLI calls when scripts can be executed locally.

### 🔒 Feature 3: Security Hardening — Read-Only Path Containment Fix
- **Command Suffix Stripping Fix (`modules/shell_processes.py`):** Replaced `.rstrip(".exe")` with `.removesuffix(".exe")` to prevent character set truncation that previously bypassed path containment checks for commands like `type`.
- **Read-Only File Command Coverage:** Added `findstr` and `type` to `READONLY_FILE_COMMANDS` with mandatory workspace boundary enforcement.

### 🌐 Feature 4: Multi-Browser Support & Model-Controlled Browser Mode

#### Browser Engine Selection (GUI + MCP)
- **Browser Dropdown in Cockpit UI:** The Browser Agent settings card now shows a live-detected dropdown of all installed browsers alongside the existing Headless toggle. Switching triggers an automatic browser restart.
- **Auto-Detection (`list_available_browsers`):** Scans known installation paths for Microsoft Edge (stable/beta/dev/canary), Google Chrome (stable/beta/dev/canary), Brave, and Chromium. Firefox and WebKit/Safari are always listed as Playwright built-ins. Returns `channel`, `label`, `path`, and optional `note` per entry.
- **New MCP Tool `browser_list_browsers`:** The AI model can enumerate available browsers on the host system before deciding which to launch.
- **New MCP Tool `browser_restart(headless, channel)`:** The AI model can switch browser engine or toggle headless mode at runtime without user intervention. Closes the current session and relaunches with the new settings.

#### Firefox & WebKit Support (Full DOM Access)
- **Firefox engine via Playwright:** Supports all existing MCP tools (`browser_snapshot`, `browser_click`, `browser_fill`, etc.) with full DOM access. Resolves the limitation where `desktop_input` coordinate-based clicking was unreliable on dynamic/responsive pages (e.g. at 2560×1392 resolution).
- **Persistent Login Sessions for Firefox/WebKit:** Playwright's `storage_state` API (cookies + localStorage) is saved to `data/browser_states/storage_state_<channel>.json` automatically on every page load. Login sessions survive browser restarts — no re-authentication needed after closing and reopening Firefox.
- **Per-channel state isolation:** Each browser channel (firefox, webkit, msedge, chrome, …) maintains its own independent session file.

#### Technical Details
- `_resolve_channel()`: Maps user-supplied channel names (including aliases like "edge", "google-chrome") to Playwright-compatible values; unknown channels fall back to "chromium".
- `_BrowserWorker._ensure_browser()`: Dispatches to Firefox/WebKit `launch()` + `new_context()` or Chromium `launch_persistent_context()` based on channel.
- `_BrowserWorker._cmd_restart()`: Closes existing context, updates config, calls `_ensure_browser()` — fully synchronous on the worker thread.
- `_BrowserWorker._cmd_status()`: Now includes `available_browsers` list in every status response.
- `_do_close()`: Handles both Chromium (context-only) and Firefox/WebKit (browser handle + context) teardown paths.

## [0.6.0] - 2026-10-12

### 📸 Feature 1: Multimodal Screen & Window Copilot
- **Active Window Capture (`modules/screen_capture.py`):** Added `screen_capture_active_window` FastMCP tool (consent-gated) and `screen_capture_active_window_local` with active foreground window inspection (title, process, bounds via `DwmGetWindowAttribute`).
- **Global Hotkey Bridge (`modules/global_hotkey.py`):** Added multi-hotkey manager supporting composite shortcuts (`Ctrl+Shift+Space`) on dedicated STA message pump threads.
- **In-App Toast Banner & Chat Focus:** Added `show_toast` non-blocking visual feedback and automated clipboard paste bridge to Mammouth AI Web tab.

### 🧠 Feature 2: Sovereign Workspace Memory & Semantic Code Search (Local RAG)
- **Local SQLite FTS5 Search Engine (`modules/workspace_indexer.py`):** Zero-external-dependency local code search engine with bm25 ranking, snippet generation, and exact prefix matching.
- **AST & Regex Symbol Indexer:** Extracted functions, async functions, classes with inheritance bases, and methods from Python via AST, and multi-language declarations via regex.
- **Incremental mtime Tracking & Safety Filtering:** Incremental indexing with mtime cache, automatic deletion pruning, 0-byte file cleanup, and safety caps.
- **FastMCP Tools:** Added `workspace_index_directory`, `workspace_search`, `workspace_find_symbols`, and `workspace_get_stats`.

### 📋 Feature 3: Smart Clipboard AI & Quick-Actions
- **Native Win32 64-bit Unicode Clipboard (`modules/smart_clipboard.py`):** Direct Win32 clipboard API access for UTF-16 Unicode reading and writing.
- **Quick-Actions & Deterministic Transformers:** FastMCP tool `clipboard_transform` supporting `explain`, `fix_bug`, `translate`, `format_data` (deterministic JSON and Markdown table formatter with escaped pipe syntax), `git_commit`, `summarize`, and `custom`.
- **Global Quick-Action Shortcut (`Ctrl+Shift+K`):** Summon Cockpit and focus chat with clipboard content.
- **FastMCP Tools:** Added `clipboard_get_text`, `clipboard_set_text`, and `clipboard_transform`.

### ⚙️ Configurable Keyboard Shortcuts & Settings UI
- Added dedicated Settings UI card with customizable keybind entry fields and toggles for all global shortcuts with live re-binding.

### 🎯 Screen Capture Target Selector & Self-Capture Prevention
- **Target Tracking & Selection (`modules/screen_capture.py` & `gui.py`):** Added interactive application target selector (`Auto`, `Snipping Tool`, `Full Desktop`, or specific running application window).
- **Self-Capture Prevention:** Intelligently ignores Defroster and WebView2 windows in `auto` mode, resolving the user's active external target application via Z-order hierarchy.
- **Direct Background Capture:** Added `PrintWindow` with `PW_RENDERFULLCONTENT` fallback for non-intrusive capture.

### 🔍 Feature 4: Advanced Windows Event Log Diagnostics (Get-WinEvent)
- **Deep Event Log Channel Support (`modules/system_monitor.py`):** Upgraded `system_get_event_logs` from legacy `Get-EventLog` to modern `Get-WinEvent`, unlocking all Applications and Services channels (e.g. `Microsoft-Windows-Kernel-PnP/Device Management`, `Kernel-Power`, `USB-USBXHCI`).
- **Targeted Event ID & Level Filtering:** Direct filtering by `event_id` (e.g. Event ID 1010 for USB/device surprise removal diagnostics) and flexible level resolution (`Critical`, `Error`, `Warning`, `Information`, `Verbose`, or `All`/None).
- **Channel Discovery Tool (`system_list_event_channels`):** Added FastMCP tool to discover, search, and inspect available event log channels on the system with record counts and enabled status.
- **Strict Parameter Sanitization & Aliases:** Parameter aliases (`channel`, `level`, `id`, `limit`) and regex-based input validation preventing command injection.

### 🛠️ Feature 5: Mammouth Code CLI Bridge Hardening & Resilient Streams
- **Safe Stream Handling (`modules/mammouth_code.py`):** Guarded `proc.stdout` and `proc.stderr` against `NoneType` values in `run_mammouth_task`, `install_or_update_mammouth_code`, and `get_mammouth_code_status`, eliminating crashes on headless tasks.
- **Subprocess Security Guard:** Reinforced stream handling in `modules/putty_ssh.py`.

### 🧠 Feature 6: Persistent Memory & Knowledge Vault Tab + Seamless Upgrade Migration
- **Interactive Knowledge Cockpit UI (`gui.py`):** Added dedicated "🧠 Memory Vault" navigation rail tab with live search, category filtering dropdown, and telemetry summary banner.
- **Full CRUD Management:** Interactive cards displaying keys, category pill badges, timestamps, multi-line content views, modal `MemoryDialog`, 1-click clipboard copy, and delete confirmation dialogs.
- **Seamless Upgrade Migration (`modules/memory.py`):** Automatic discovery and migration of `memory.db` from previous releases (`MammouthDefroster9000-v*`), ensuring no user knowledge is lost across upgrades.
- **LLM Immunity & Parameter Aliases:** Flexible parameter aliases for `memory_save`, `memory_recall`, `memory_get`, and `memory_delete`.

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
