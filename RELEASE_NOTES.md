# 🦣 Mammouth Defroster 9000 — Release Notes

> **Platform:** Dedicated Sovereign Windows Cockpit & DevOps Automation for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Current Version:** **v0.7.5**

---

## 🚀 What's New in v0.7.5 — `v0.7.5 - Mammouth Defroster 9000`

> **Note for Public Users:** `v0.7.5` is the first public release following `v0.7.2`. This release consolidates all security hardening, architectural enhancements, Anthropic Claude OAuth 2.1 integration, multilingual tool discovery advancements (from `v0.7.4`), autonomous web chat automation improvements (from `v0.7.3`), and system stability updates.

### 🌟 Cumulative Highlights (v0.7.2 → v0.7.5)
- **Security Hardening & Zero-Vulnerability Baseline (v0.7.5):** Zero-vulnerability dependency baseline with `opentelemetry-api>=1.45.2` (remediating CVE-2026-126360), `fastmcp>=4.1.4`, `starlette>=1.10.0`, and `pillow>=13.0.0`. Parameterized terminal command execution preventing PowerShell injection, strict profile authorization gating for `defroster_execute_tool`, strict CORS origin preflights, and URL query-string tokens disabled by default (opt-in via `server.allow_query_token`).
- **Architecture & Robustness Overhaul (v0.7.5):** Standardized execution contracts with structured status, structured error codes, integer exit codes, and `duration_ms` latency telemetry. Machine-readable on-demand tool schemas via `defroster_catalog(tool_schema=...)`, read-only `defroster_health_check` system health probe, task scheduler simulation / preview mode, and persistent execution run history tracking.
- **Anthropic Claude & OAuth 2.1 Compliance (v0.7.4 Milestone):** Full compliance with RFC 8414, RFC 9728, and RFC 7591 dynamic client registration. Standardized discovery endpoints (`/.well-known/oauth-authorization-server`, `/.well-known/openid-configuration`), subpath routing (`/mcp/.well-known/...`), exclusive S256 PKCE enforcement, CSP `frame-ancestors` clickjacking defense, Streamable HTTP `.mcp.json` sync, and Claude Code cloud session terminal launcher.
- **MCP Transport & Defroster Catalog Token Optimization (v0.7.4 Milestone):** Dual SSE transport mounted at `/sse` and root `/mcp`. Tiered defroster catalog discovery resolving platform chat token limits (reducing default overview from ~2,876 tokens to <1,080 tokens, >62% savings) with targeted category and search drilldowns.
- **Multilingual Tool Discovery & Quick Profiles (v0.7.4 Milestone):** Trilingual tool hint metadata (`_MULTILINGUAL_TOOL_HINTS` in German, French, English), persistent UI profile selectors on Dashboard and Navigation Sidebar, real-time `tools/list_changed` broadcast to active MCP sessions, and optimized schema budgets.
- **Autonomous Web Chat Prompt Automation (v0.7.3 Milestone):** Asynchronous DOM input polling (`pollAndInject`) eliminating prompt drops during scheduled background tasks, multilingual button resolver with React 18 pointer/mouse event sequencing, and Microsoft Robocopy updater engine.

---

### 🛡️ Security Hardening & Vulnerability Remediation (v0.7.5)
- **PowerShell Execution Sanitization (`launch_claude_terminal`):**
  - Completely eliminated dynamic string interpolation of user and MCP arguments (`prompt`, `workspace_path`, `exe`) into PowerShell execution scripts (`modules/claude_code.py`).
  - Parameterized process execution via child environment variables (`MD_CLAUDE_WS`, `MD_CLAUDE_EXE`, `MD_CLAUDE_PROMPT`, `MD_CLAUDE_TITLE`). The generated script contains solely fixed constants (`Set-Location -LiteralPath $env:MD_CLAUDE_WS; & $env:MD_CLAUDE_EXE ...`).
  - Hardened against Unicode quotation mark variations (`' ‘ ’ ‚ ‛`), command chaining (`;`), subexpressions (`$()`), and backticks.
  - Hardened Windows Terminal (`wt.exe`) launch path to invoke directly without `cmd.exe /c start`, preventing command-line metacharacter interpretation (`&`, `|`, `^`, `%`).
  - Added strict control character and path validation for `workspace_path`. Regression tested in `tests/test_v075_terminal_security.py`.
- **MCP Tool Profile Authorization Enforcement (`defroster_execute_tool`):**
  - Hardened on-demand universal tool execution against the active tool profile allowlist (e.g. `mammouth_safe`). Execution requests for tools outside the active profile fail with `"tool not in active profile"`.
  - Enforced `require_module(...)` active module checks and `allow_admin_shell` privilege boundaries across the on-demand execution pathway. Regression tested in `tests/test_v075_server_security.py`.
- **CORS Preflight & Origin Reflection Guard:**
  - Hardened `SecurityAndAuthMiddleware` to reject reflecting arbitrary `Origin` headers on `OPTIONS` preflight requests.
  - `Access-Control-Allow-Origin` and credentials headers are now strictly emitted only for origins matching configured `allowed_origins` or `allow_origin_regex` (e.g. `mammouth.ai`, `claude.ai`, `localhost`), preventing cross-origin credential harvesting.
- **URL Query Token Authentication Disabled by Default (`allow_query_token`) - BREAKING:**
  - Tokens passed as URL query parameters (`?token=...`, `?api_key=...`, `?access_token=...`) are now rejected with 401 Unauthorized unless `"server": {"allow_query_token": true}` is set explicitly in configuration. This prevents token leakage via tunnel/proxy access logs, browser history, and referrer headers.
  - Clients should send `Authorization: Bearer <token>` or use OAuth 2.1. Web clients that require URL query tokens can explicitly opt in.
  - Removed duplicate `allow_query_token` entry from `config.example.json`.
- **Credential Storage Hardening (`sync_claude_code_mcp`):**
  - `sync_claude_code_mcp()` now defaults to environment variable reference mode (`Bearer ${MAMMOUTH_DEFROSTER_TOKEN}`) instead of writing plaintext tokens to `.mcp.json` and user global `~/.claude.json`.
- **Dependency Upgrades & Vulnerability Remediation (CVE-2026-126360):**
  - Patched `opentelemetry-api` to `>=1.45.2` (CVE-2026-126360 remediation) across `pyproject.toml`, `requirements.txt`, and `uv.lock`.
  - Upgraded core dependencies to eliminate known CVEs: `fastmcp>=4.1.4`, `starlette>=1.10.0`, `pillow>=13.0.0`.
  - Harmonized Python requirement to `>=3.11`.
  - Verified zero known vulnerabilities across `pip-audit`.

### 🏗️ Architecture & Robustness Overhaul (v0.7.5)
- **Standardized Execution Contracts & Telemetry:**
  - Standardized execution tool output contracts across `powershell_exec`, `cmd_exec`, and related execution tools to return structured responses with `status` (`"success"`, `"permission_denied"`, `"error"`), structured error codes (e.g. `ERR_SECURITY_SHIELD`, `ERR_TIMEOUT`), integer `exit_code`, and execution latency telemetry `duration_ms`.
- **Unified Tool Catalog & On-Demand Machine-Readable Schemas:**
  - Added distinct 3-tier inventory metrics in `defroster_catalog` (`loaded_in_profile`, `activated_in_config`, `total_catalog_suite`).
  - Introduced on-demand machine-readable tool schema retrieval via `defroster_catalog(tool_schema="<tool_name>")`, returning complete parameter schemas without requiring token-heavy schema dumps.
- **Read-Only System Health Probe (`defroster_health_check`):**
  - Added `defroster_health_check` diagnostic endpoint and tool providing read-only system telemetry across runtime, security (workspace containment, DPAPI availability), storage, and dependencies, with execution latency metrics (`duration_ms`).
- **Hardened Task Automation & Scheduling:**
  - Added simulation / dry run (`preview`) mode in task scheduler (`scheduler_test_run(dry_run=True)`, `task_schedule_control(action="preview")`) to preview actions safely before execution.
  - Added isolated single `test_run` execution mode.
  - Implemented persistent execution history tracking (`scheduler_get_history`, `task_schedule_control(action="history")`) recording execution run status, start/finish timestamps, and duration.
- **Browser Automation Resilience:**
  - Enhanced Playwright browser automation in `modules/browser_agent.py` with selector priority engines and verified page state checks.

### 🤖 Anthropic Claude & OAuth 2.1 Compliance (from v0.7.4 Milestone)
- **Standardized OAuth 2.1 Discovery & Endpoints:**
  - Added standard discovery metadata endpoints: `/.well-known/oauth-authorization-server` (RFC 8414), `/.well-known/oauth-protected-resource` (RFC 9728), and `/.well-known/openid-configuration`.
  - Canonical subpath and alias routing (`/mcp/.well-known/...`, `/sse/.well-known/...`, `/mcp/oauth/...`).
  - RFC 7591 dynamic client registration endpoint (`/oauth/register`, `/mcp/register`).
  - Enforced `S256` PKCE exclusively; rejected plaintext challenges.
  - Clickjacking defense: CSP `frame-ancestors 'self' https://mammouth.ai https://*.mammouth.ai https://claude.ai https://*.claude.ai https://anthropic.com https://*.anthropic.com` on OAuth consent pages.
  - Standard `WWW-Authenticate: Bearer` response headers on 401 challenges.
- **Claude Code & Cloud Sessions (.mcp.json) Integration:**
  - Support for Anthropic Claude Code Cloud Sessions (`claude --cloud`).
  - Generates and merges repository-root `.mcp.json` using standard Streamable HTTP transport (`"type": "http"`), pointing to public tunnel HTTPS endpoints (`/mcp`).
  - Added "📋 Copy Claude.ai URL" quick-action button in Cockpit GUI (Settings and Dashboard).

### ⚡ MCP Transport & Token Budget Optimization (from v0.7.4 Milestone)
- **Dual SSE Transport Mounting:**
  - Mounted FastMCP SSE transport at both `/sse` and root `/mcp` endpoints to accommodate diverse MCP client implementations.
  - Sanitized tool schemas aligning with MCP 2024-11-05 specification.
- **Defroster Catalog Token Optimization for Mammouth AI Limits:**
  - Resolved platform token exhaustion in Mammouth AI chat by replacing massive monolithic catalog dumps with tiered discovery:
    - Compact Overview (Default): lightweight category overview with tool names and hint breadcrumbs (<1,080 tokens, >62% reduction).
    - Targeted Drilldown: `category="<name>"` (~399 tokens).
    - Keyword Search: `search="<term>"` (~320 tokens).
    - Explicit detailed mode: `detailed=True`.
  - Streamlined FastMCP server instructions to save prompt tokens on session handshakes.

### 🌍 Multilingual Tool Search & Quick Profiles (from v0.7.4 Milestone)
- **Multilingual Tool Search Keyword Hints:**
  - Added `_MULTILINGUAL_TOOL_HINTS` across all Defroster tools in German, French, and English (e.g. *"Browser-Automatisierung"*, *"Verzeichnis auflisten"*, *"Datei lesen"*, *"lister répertoire"*, *"lire fichier"*).
- **Persistent Tool Profile Quick Selectors:**
  - Dedicated Tool Profile selector row on Dashboard Hero Card and permanent profile card in Left Navigation Sidebar.
  - Bidirectional UI synchronization and immediate MCP `tools/list_changed` broadcast to connected clients upon profile change.

### 🐛 Autonomous Web Chat & Desktop Automation (from v0.7.3 Milestone)
- **Automated Task Prompt Submission Engine Overhaul:**
  - Asynchronous input polling (`pollAndInject`, up to 25 attempts / 3.0s) eliminating prompt drops while chat textarea is rendering.
  - Multilingual button resolver (German: `senden`, `absenden`, `abschicken`; English/French: `send`, `envoyer`, `submit`, `prompt`, `valider`, `transmettre`).
  - Full pointer and mouse event sequence (`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`) compatible with React 18 synthetic event dispatchers and Tailwind UI.
  - Recursive ancestor walk for SVG/icon-only submit buttons.
  - React disabled-state synchronization retry loop.
  - Dual redundancy prompt submission (button pointer events + synthetic Enter KeyboardEvents + `form.requestSubmit()`).
- **Browser Agent Multi-Engine Launch Resilience:**
  - Installed Playwright Chromium binaries and added multi-channel fallback chain (`channel` -> system channels -> bundled Chromium -> temp profile fallback) in `modules/browser_agent.py`.
- **Microsoft Robocopy Updater Engine:**
  - Microsoft Robocopy (`/R:5 /W:1`), explicit process termination wait (`WaitForExit(15000)`), SmartScreen `Unblock-File` unblocking, and verified working directory preservation.

### 🧹 Code Quality, Linting & Test Infrastructure
- **Modern Python Linter & Formatter (`Ruff`):**
  - Integrated `[tool.ruff]` configuration in `pyproject.toml` (line-length 120; rule sets `E`, `F`, `B`, `SIM`, `UP`, `BLE`).
  - Remediated unused imports, dead variables, and legacy syntax constructs across the codebase.
- **Structured Exception Logging:**
  - Silent `except: pass` handlers in the OAuth, token and CORS code paths now log with `exc_info=True`.
- **Tkinter GUI Test Teardown & Event Cleanup:**
  - Implemented automatic tracking and teardown of scheduled Tkinter `after()` callbacks in `gui.py` (`destroy()` / `on_close()`).
  - Added test fixture lifecycle cleanup (`tests/conftest.py`), eliminating stale Tcl callback leaks during headless test suite runs.
- **Comprehensive Regression Test Suite:**
  - Added dedicated regression suites: `tests/test_v075_terminal_security.py`, `tests/test_v075_server_security.py`, `tests/test_v075_gui_cleanup.py`, `tests/test_claude_oauth.py`, `tests/test_v074_features.py`, and `tests/test_v080_architecture_improvements.py`.
  - Test suite expanded to 381 tests, with all tests passing cleanly.
- **Version Alignment:**
  - Synchronized project version to `v0.7.5` across `pyproject.toml`, `server.py`, `gui.py`, `config.py`, and test suites.

---

## 🚀 What's New in v0.7.4 — `v0.7.4 - Mammouth Defroster 9000`

### 🤖 Anthropic Claude & OAuth 2.1 Compliance
- **Standardized OAuth 2.1 Discovery & Endpoints:**
  - Added standard discovery metadata endpoints: `/.well-known/oauth-authorization-server` (RFC 8414), `/.well-known/oauth-protected-resource` (RFC 9728), and `/.well-known/openid-configuration`.
  - Canonical subpath and alias routing (`/mcp/.well-known/...`, `/sse/.well-known/...`, `/mcp/oauth/...`).
  - RFC 7591 dynamic client registration endpoint (`/oauth/register`, `/mcp/register`).
  - Enforced `S256` PKCE exclusively; rejected plaintext challenges.
  - Clickjacking defense: CSP `frame-ancestors 'self' https://mammouth.ai https://*.mammouth.ai https://claude.ai https://*.claude.ai https://anthropic.com https://*.anthropic.com` on OAuth consent pages.
  - Standard `WWW-Authenticate: Bearer` response headers on 401 challenges.
- **Claude Code & Cloud Sessions (.mcp.json) Integration:**
  - Support for Anthropic Claude Code Cloud Sessions (`claude --cloud`).
  - Generates and merges repository-root `.mcp.json` using standard Streamable HTTP transport (`"type": "http"`), pointing to public tunnel HTTPS endpoints (`/mcp`).
  - Added "📋 Copy Claude.ai URL" quick-action button in Cockpit GUI (Settings and Dashboard).

### ⚡ MCP Transport & Token Budget Optimization
- **Dual SSE Transport Mounting:**
  - Mounted FastMCP SSE transport at both `/sse` and root `/mcp` endpoints to accommodate diverse MCP client implementations.
  - Sanitized tool schemas aligning with MCP 2024-11-05 specification.
- **Defroster Catalog Token Optimization for Mammouth AI Limits:**
  - Resolved platform token exhaustion in Mammouth AI chat by replacing massive monolithic catalog dumps with tiered discovery:
    - Compact Overview (Default): lightweight category overview with tool names and hint breadcrumbs (<1,080 tokens, >62% reduction).
    - Targeted Drilldown: `category="<name>"` (~399 tokens).
    - Keyword Search: `search="<term>"` (~320 tokens).
    - Explicit detailed mode: `detailed=True`.
  - Streamlined FastMCP server instructions to save prompt tokens on session handshakes.

### 🌍 Multilingual MCP Tool Search & Rapid Profile Switching
- **Multilingual Tool Search Keyword Enrichment:**
  - Added comprehensive `_MULTILINGUAL_TOOL_HINTS` across all Defroster tools (German, French, English).
  - Search terms such as *"Browser-Automatisierung"*, *"Verzeichnis auflisten"*, *"Datei lesen"*, *"lister répertoire"*, *"lire fichier"* match tools directly with 100% precision.
  - Idempotent schema sanitization ensures keywords are never duplicated across repeated requests.
- **Persistent Tool Profile Quick Selectors in Cockpit GUI:**
  - Added dedicated Tool Profile row on Dashboard Hero Card with full-width menu, token badge, and live description subtext.
  - Added permanent Tool Profile card in Left Navigation Sidebar, making profile switching instantly accessible across all application tabs.
  - Live bidirectional synchronization across Dashboard, Sidebar, and Skills tab, triggering immediate MCP `tools/list_changed` broadcast to connected clients upon profile change.
  - Automatic background synchronization in GUI telemetry loop when profile is changed externally via MCP `defroster_catalog(switch_profile=...)`.
- **Schema Token Optimization:**
  - Streamlined `file_read` docstring and redundant schema overhead, reducing total advertised schema size to ~2,264 tokens (strictly within client 2,500 token search budgets) with concise entry point breadcrumbs.

### 🐛 Critical Bugfixes & Stability
- **Resolved Dashboard Hero Card Security Badge Clipping:** Re-architected Hero Card packing geometry so `pills_box` (`⚡ OAuth 2.0 Ready`, `🔐 Bearer Token Active`, `🔒 Sandbox ON`) is packed right-first and Tool Profile is housed in a dedicated row, resolving complete clipping of security status badges on standard and minimum window widths.
- **Resolved Cross-Loop MCP Broadcast Exceptions:** Implemented `broadcast_tool_list_changed()` and server event loop tracking (`_SERVER_EVENT_LOOP`), ensuring `tools/list_changed` notifications are dispatched safely across threads without loop mismatch runtime errors.
- **Resolved `_enable_safe_skills` Desynchronization:** Bound "Mammouth Chat Safe" preset button directly to `_on_tool_profile_change`, correctly updating instance tracking, all 3 UI menus, and broadcasting to clients without intrusive modal restart alerts.
- **Resolved OptionMenu Profile ID vs. Label Resolution:** Added defensive resolution in `_on_tool_profile_change` to accept both human labels and raw profile IDs interchangeably.
- **Corrected Web & Vision Tool Count:** Aligned `TOOL_PROFILES["web_vision"]` label to 13 tools matching the tools array.
- **Resolved GUI Startup Crash (`NameError: curr_prof_id`):** Fixed critical variable scoping defect in `_setup_skills_tab` where `curr_prof_id` was unreferenced, preventing the GUI from crashing on launch.
- **Resolved Server Logger NameError:** Added proper `logging.getLogger` definition in `server.py`, ensuring MCP session notification error handlers do not raise unhandled `NameError: name 'logger' is not defined`.
- **Version Alignment:** Synchronized project version to `v0.7.4` across `pyproject.toml`, `server.py`, `gui.py`, build scripts, and test suites.

---

## 🚀 What's New in v0.7.3 — `v0.7.3 - Mammouth Defroster 9000`

### 🐛 Web Chat Automation & In-App Browser Fixes
- **Autonomous Task Prompt Submission Engine Overhaul:**
  - **Asynchronous Input Polling (`pollAndInject`):** Resolved intermittent task execution drops where prompt injection failed if the web chat textarea was still rendering upon tab activation. The engine now retries asynchronously for up to 3.0 seconds (25 attempts @ 120ms intervals) until the input container is mounted.
  - **Multilingual Button Detection:** Extended dictionary matching to include German verbs (`senden`, `absenden`, `abschicken`) alongside English and French (`send`, `envoyer`, `submit`, `prompt`, `valider`, `transmettre`), with comprehensive exclusion of auxiliary buttons (`attach`, `file`, `upload`, `mic`, `audio`, `voice`, `camera`, `settings`).
  - **Full Pointer & Mouse Event Chain:** Upgraded button activation from simple DOM `.click()` to a complete event chain (`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`), guaranteeing execution in React 18 and Tailwind UI event systems.
  - **DOM Tree Ancestor Traversal:** Added upward tree traversal from the input field to accurately detect icon-only and SVG action buttons within nested layout wrappers.
  - **React Disabled-State Synchronization:** Implemented a polling retry loop (up to 12 attempts / 1.2s) to smoothly wait for React state updates to clear the button disabled state.
  - **Dual Redundancy Submission:** Triggers both button pointer events and synthetic `Enter` KeyboardEvents (`keydown`, `keypress`, `keyup` with keyCode 13) plus `form.requestSubmit()`, guaranteeing prompt dispatch even when running in the background without stealing OS focus.

### ⚡ Updater & Automation Hardening
- **In-App Updater Robocopy Engine:** Refactored `apply_update_and_restart` to use Microsoft Robocopy with retry parameters (`/R:5 /W:1`), explicit process termination wait (`WaitForExit(15000)`), SmartScreen `Unblock-File` unblocking, and verified working directory preservation.
- **Version Alignment:** Synchronized project version to `v0.7.3` across `pyproject.toml`, `server.py`, `gui.py`, `build.bat`, and test suites.

---

## 🚀 What's New in v0.7.2 — `v0.7.2 - Mammouth Defroster 9000`

### ⚡ Features & MCP Tool Promotion Architecture
- **Tool Profiles & Schema Budget Management:** Resolved tool promotion failures in Mammouth AI chat ("No matching tools were promoted") caused by schema token overload (86 tools totaling ~16,461 tokens vs ~7,719 token session budget):
  - **Dynamic Tool Profiles:** Introduced configurable tool exposure profiles:
    - `🛡️ Mammouth Chat Safe` (Default): 12 core tools (`defroster_catalog`, `directory_list`, `file_read`, `file_write`, `command_run`, `screen_capture`, `browser_navigate`, `browser_snapshot`, `memory_save`, `memory_recall`, `system_get_specs`, `clipboard_get_text`) consuming only **~2,700 tokens** (< 35% of platform budget), giving models immediate directory listing capability on session start.
    - `💻 Developer & Scripting`: 14 tools (~3,800 tokens) for workspace file editing, search, local PowerShell execution, and diagnostics.
  - **Automated Tool Promotion Refresh (`tools/list_changed`):** When switching tool profiles via `defroster_catalog(switch_profile=...)` or the GUI combobox, the server broadcasts an MCP 2024-11-05 `notifications/tools/list_changed` notification to active sessions, allowing connected AI models to automatically re-discover tools without requiring manual intervention.
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

### 🔒 Security Audit Remediation & Hardening
- **Autonomous CLI Agent Sandboxing (A-01):** Disabled `mammouth_code` by default. Enforced strict admin shell gate on `mammouth_code_run_task`, blocking autonomous file modifications and command execution in Read-Only mode. Defaulted `auto_approve` to `False`.
- **Public Tunnel Safe Defaults (A-03):** Gated Tailscale Funnel in `start_server.bat`, `start_server.ps1`, and GUI server startup behind `server.auto_tunnel: true` and the configured server port.
- **Universal Path Guard & PSDrive Isolation (B-01, B-02, B-03):**
  - Normalized parameter colon syntax (`-Path:C:\...`) to ensure containment within the workspace.
  - Expanded path inspection across all read cmdlets (`Select-String`, `Get-FileHash`, `Get-ItemProperty`, etc.).
  - Blocked access to PowerShell PSDrives (`env:`, `HKCU:`, `HKLM:`, `cert:`), `$env:` expansion, tilde (`~`), and `Get-Clipboard`.
  - Blocked UNC network paths (`//` and `\`) in Read-Only mode.
  - Added credentials and database files (`credentials.json`, `oauth.db`, `gdrive_token.json`, `tasks.db`, `memory.db`, `.env`) to sensitive denylist.
- **Security Shield Blacklist Expansion (B-07):** Added `curl.exe`, `wget.exe`, `Start-Process`, `pwsh.exe -c`, `python.exe -c`, and `Invoke-Command -ScriptBlock` to `BLOCKED_COMMAND_PATTERNS`.
- **Desktop Open Execution Gate (B-08):** Prohibited launching executable files and passing command-line arguments via `desktop_open` in Read-Only mode.
- **PuTTY & SSH Management Hardening (B-09):** Disabled `putty_ssh` by default in configuration. Gated remote command execution on admin permissions, and rejected leading `-` option switches on all parameters.
- **Dependency Upgrades (C-05):** Fully upgraded dependencies in `uv.lock` (`fastmcp` 4.1.4, `mcp` 2.3.0, `authlib` 1.9.1, `pillow` 13.0.0, `pyjwt` 2.15.1, `certifi`, etc.).
- **Zip-Slip & Integrity Verification (C-01):** Hardened package extraction against directory traversal in updater and installer.

### ⚡ Features
- **Daily Startup Auto-Update Check:** Rate-limited background startup update checks to once per 24 hours while allowing instant manual checks from Settings.

---

## 🚀 What's New in v0.7.1 — `v0.7.1 - Mammouth Defroster 9000`

### 🐛 Bug Fix 1: Startup Resolution for Scheduled Tasks (`datetime` Scope)
* **Resolved Startup Crash:** Fixed an issue where the Cockpit failed to initialize when pre-existing scheduled tasks were present in `tasks.db`. The task countdown and card rendering logic previously threw `NameError: name 'datetime' is not defined` because datetime symbols were only imported locally in helper functions.
* **Module-Level Datetime & DPAPI Scope:** Promoted `datetime`, `timezone`, `timedelta`, and `_encrypt_dpapi` to the top-level module scope in `gui.py`, harmonizing datetime arithmetic and cryptographic credential handling across all UI components.

### 🛡️ Bug Fix 2: Splash Screen Unmasking & Fail-Safe Crash Reporting
* **Unmasked Error Reporting:** Enhanced `SplashScreen.close()` with explicit `withdraw()`, `update_idletasks()`, and topmost-state clearing.
* **Isolated Startup Error Dialogs:** Wrapped root window initialization and UI callbacks to ensure that any startup exception immediately unmaps and destroys the splash window, rendering a topmost modal error dialog and appending full stack traces to `gui_crash.log`. Error dialogs are never hidden behind an always-on-top splash screen.

### ⏱️ Feature Hardening: Task Scheduler & Countdown Robustness
* **Timezone-Aware Countdown Arithmetic:** Added automatic timezone normalization (`.astimezone().replace(tzinfo=None)`) for ISO 8601 timestamps containing UTC `Z` indicators or explicit UTC offsets, preventing `TypeError: can't subtract offset-naive and offset-aware datetimes`.
* **Dynamic KPI Stat Cleanup:** Ensured the "Next Trigger" KPI label properly resets to `"No active task"` when tasks are deleted, completed, or when the task database is empty.
* **Per-Card Error Isolation:** Wrapped individual task card countdown updates in isolated exception blocks so corrupted or destroyed widget handles never halt updates for remaining tasks.

---

## 🚀 What's New in v0.7.0 — `v0.7.0 - Mammouth Defroster 9000`

### ⚡ Feature 1: The Crown Jewel — Autonomous Self-Tooling & Infinite Skills
* **Autonomous Skill Authoring:** AI assistants are no longer constrained by static toolsets. When encountering an unserved requirement, the model autonomously writes custom Python or PowerShell scripts into `skills/` using `file_write`.
* **Zero-Cost Local Win32 Sandbox Execution:** Scripts are executed locally via `powershell_exec` or `command_run` inside the secured Win32 workspace sandbox at **$0.00 API cost**, bypassing external agent CLI budget limits and preventing runaway token expenditure.
* **Infinite Extensibility:** The assistant can write, test, debug, and chain its own tools in real time, granting Mammouth Defroster 9000 limitless task-solving capabilities.

### 🦣 Feature 2: Token-Budget-Safe Tool Discovery & Catalog Meta-Tool
* **Dynamic Tool Discovery Bootstrap (`file_read` Anchor):** Resolved Mammouth.ai client schema budget exhaustion (where 85 tools exceed the 7,719-token budget in "On-Demand" mode) by equipping the core `file_read` tool with a compact module compass so models immediately recognize available capability domains.
* **Skill Directory & Router (`defroster_catalog`):** New FastMCP tool allowing models to query tool listings by category (`files`, `browser`, `shell`, `screen`, `desktop`, `system`, `scheduler`, `gdrive`, `clipboard`, `memory`) or search keywords without loading all 85 tool schemas into the system prompt simultaneously.
* **Budget Limit Interceptor:** Built-in guidance and error interception instructing assistants to avoid expensive external CLI loops (`mammouth run`) when scripts are already present locally.

### 🌐 Feature 3: Multi-Browser Support & Model-Controlled Browser Automation
* **Model-Controlled Headless & Browser Switching:** Added FastMCP tool `browser_restart(headless, channel)` allowing AI assistants to autonomously switch between headless background execution and visible window mode, or switch browser engines on the fly without user intervention.
* **Host Browser Discovery (`browser_list_browsers`):** FastMCP tool scanning and listing all installed browsers (Microsoft Edge, Google Chrome, Brave, Chromium) as well as Playwright built-in engines (Firefox, WebKit/Safari) with channel IDs, labels, and installation paths.
* **Firefox & WebKit Engines with Full DOM Tree Inspection:** Full integration with Playwright's Firefox and WebKit runtimes. Resolves the limitations of desktop coordinate-based clicks on responsive/dynamic interfaces at high display resolutions (e.g. 2560×1392), unlocking reliable DOM-level selectors (`browser_snapshot`, `browser_click`, `browser_fill`).
* **Session & Login State Persistence (`storage_state`):** Automated per-channel cookie and LocalStorage extraction saved to `data/browser_states/storage_state_<channel>.json` on page loads. Firefox and WebKit login sessions survive browser restarts without requiring re-authentication.
* **Cockpit GUI Browser Selection:** Interactive dropdown selector embedded in the Browser Agent card in the Cockpit GUI alongside the Headless switch, allowing 1-click browser selection and real-time auto-restart.

### 🔒 Feature 4: Security Hardening — Read-Only Path Containment Fix
* **Command Suffix Stripping Fix:** Replaced `.rstrip(".exe")` with `.removesuffix(".exe")` in `modules/shell_processes.py` preventing character set truncation that previously bypassed path guards for commands such as `type`.
* **Complete Read-Only File Command Coverage:** Added `findstr` and `type` to `READONLY_FILE_COMMANDS` with strict workspace sandbox containment checks.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.7.0-windows-x64.zip`
* **Size:** `133,476,967 bytes` (~127.29 MB)
* **SHA-256 Checksum:**
  ```text
  057d5cc80d1de30fccf27a943f37c57c77b1a5a3fe73a44d1ca901c951c130b3
  ```
* **Test Suite:** 242 tests passing (100% clean, 0 failures, 0 errors).

---

## 🚀 What's New in v0.6.0 — `v0.6.0 - Mammouth Defroster 9000`

### 📸 Feature 1: Multimodal Screen & Window Copilot
* **Targeted Foreground Window Vision:** Captures the active application window using Win32 API (`GetForegroundWindow`, `DwmGetWindowAttribute`), extracting window title, process ID, executable name, and borderless frame bounds.
* **Target Application Selector:** Interactive dropdown in the Cockpit header (`Auto`, `Snipping Tool`, `Full Desktop`, or any open desktop window) allowing precise window selection for multimodal tasks.
* **Self-Capture Prevention:** Intelligently identifies Defroster and WebView2 processes; in `Auto` mode, walks top-level windows in Z-order hierarchy (`get_topmost_external_window`) to reliably capture the user's active application rather than Defroster itself.
* **Direct Background Capture:** Implemented `PrintWindow` with `PW_RENDERFULLCONTENT` to capture obscured background windows directly from the compositor without focus stealing.
* **Consent-Gated MCP Tool:** Added `screen_capture_active_window`, `screen_capture_window`, `screen_list_windows`, `screen_set_tracked_window`, and `screen_get_tracked_window` tools protected by user consent and token authentication.
* **Global Win32 Copilot Shortcut (`Ctrl+Shift+Space`):** Dedicated background STA message pump thread instantly captures the selected target window, copies the image to clipboard, displays non-blocking in-app toast feedback, switches to Mammouth AI chat, and focuses the input prompt.

### 🧠 Feature 2: Sovereign Workspace Memory & Semantic Code Search (Local RAG)
* **High-Performance Offline SQLite FTS5 Indexer (`modules/workspace_indexer.py`):** Lightning-fast full-text search across codebase files with snippet generation and bm25 ranking.
* **AST & Multi-Language Symbol Extraction:** Automatically extracts function definitions, async functions, classes with inheritance bases, and methods from Python via AST, plus regex extraction for TypeScript/JavaScript/Go/Rust.
* **Incremental mtime Tracking & Safety Filtering:** Avoids re-indexing unchanged files; automatically skips ignored folders (`.git`, `node_modules`, `.venv`, `dist`, `build`, etc.), binary files, and files > 2 MB. Emptied or deleted files are immediately pruned.
* **FastMCP Tools:** Added `workspace_index_directory`, `workspace_search`, `workspace_find_symbols`, and `workspace_get_stats` tools, gated by the `workspace_memory` module switch.

### 📋 Feature 3: Smart Clipboard AI & Quick-Actions
* **Native 64-bit Win32 Unicode Clipboard (`modules/smart_clipboard.py`):** Low-level Win32 clipboard API access supporting international characters, emojis, and multiline text.
* **Deterministic Transformers & AI Quick-Actions:**
  - `format_data`: Deterministically parses and pretty-prints JSON or converts CSV/TSV into clean Markdown tables with escaped pipe syntax.
  - `git_commit`: Conventional commit message proposals (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`) from diffs or descriptions.
  - `explain`, `fix_bug`, `translate`, `summarize`, and `custom` prompt generation.
* **Global Quick-Action Shortcut (`Ctrl+Shift+K`):** Summon Cockpit and focus chat with current clipboard content.
* **FastMCP Tools:** Added `clipboard_get_text`, `clipboard_set_text`, and `clipboard_transform` tools, gated by the `smart_clipboard` module switch.

### 🔍 Feature 4: Advanced Windows Event Log Diagnostics (Get-WinEvent)
* **Deep Event Log Channel Support (`modules/system_monitor.py`):** Migrated `system_get_event_logs` from legacy `Get-EventLog` to modern `Get-WinEvent` with clean UTF-8 pipeline output. Unlocks full access to Applications and Services ETW logs (e.g. `Microsoft-Windows-Kernel-PnP/Device Management`, `Microsoft-Windows-Kernel-Power`, `Microsoft-Windows-USB-USBXHCI/Operational`).
* **Targeted Event ID & Level Filtering:** Direct filtering by `event_id` (e.g. Event ID 1010 for USB/hardware surprise removal and freeze diagnostics) and flexible level resolution (`Critical`, `Error`, `Warning`, `Information`, `Verbose`, or `All`/None).
* **Channel Discovery Tool (`system_list_event_channels`):** New FastMCP tool to discover, search, and inspect available event channels on the system via wildcard patterns (e.g. `Kernel-PnP`, `USB`), reporting record count, enabled status, mode, and file size.
* **Strict Parameter Sanitization & Aliases:** Added convenient aliases (`channel`, `level`, `id`, `limit`) and regex-based validation blocking command injection, shell operators, and control characters.

### 🛠️ Feature 5: Mammouth Code CLI Bridge Hardening & Resilient Streams
* **Safe Stream Handling (`modules/mammouth_code.py`):** Guarded `proc.stdout` and `proc.stderr` against `NoneType` values in `run_mammouth_task`, `install_or_update_mammouth_code`, and `get_mammouth_code_status`. Headless tasks and detached process streams now complete smoothly without `AttributeError: 'NoneType' object has no attribute 'strip'`.
* **Subprocess Security Guard:** Reinforced stream handling in `modules/putty_ssh.py`.

### 🧠 Feature 6: Persistent Memory & Knowledge Vault Tab + Seamless Upgrade Migration
* **Interactive Knowledge Cockpit UI (`gui.py`):** Added a dedicated "🧠 Memory Vault" page in the Defroster Cockpit with real-time search, category filtering dropdown, and live statistics banner (memories count, categories count, total storage size).
* **Full CRUD Management:** Interactive cards displaying keys, category pill badges, formatted ISO timestamps, and full multi-line text views. Modal `MemoryDialog` for adding and editing memories; 1-click clipboard copy with visual feedback; delete with confirmation dialog.
* **Seamless Upgrade Migration (`modules/memory.py`):** Automatic discovery and migration of `memory.db` from previous releases (`MammouthDefroster9000-v*`), ensuring no knowledge is lost when upgrading or unpacking new releases.
* **LLM Immunity & Parameter Aliases:** Added flexible parameter aliases to `memory_save` (`value`, `text`, `note`, `data`, `name`), `memory_recall` (`query`, `search_query`, `q`, `search`, `keyword`), `memory_get` (`name`, `id`), and `memory_delete` (`name`), ensuring reliable tool execution even when LLMs vary their parameter naming.

### ⌨️ Fully Configurable Global Hotkeys & Cockpit Settings
* Dedicated Settings UI card with customizable keybind entry fields and toggles for Cockpit Summon (`Ctrl+Shift+M`), Screen Copilot (`Ctrl+Shift+Space`), and Smart Clipboard (`Ctrl+Shift+K`) with live re-binding.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.6.0-windows-x64.zip`
* **Size:** `131,053,668 bytes` (~124.98 MB)
* **SHA-256 Checksum:**
  ```text
  dfd8c911d2518c1c516bf7858d0c1fd18dbc574810a58f5aa3cb40d2776162c4
  ```
* **Test Suite:** 230 tests passing (100% clean, 0 failures, 0 errors).



---

## 🚀 What's New in v0.5.2

### 🌐 Complete English Localization
* **Pure English Cockpit UI:** Converted all interface texts, sidebar menu titles, status badges, metric counters, settings tabs, console outputs, and dialog alerts into clean, professional English.
* **Refined Task Scheduler Presets:** All default automated task triggers (Live Sports Tickers, Crypto & Market Watch, System & Hardware Diagnostics, Mammouth Code Security Scan, News Flash) now feature English titles, descriptions, and prompt instructions.
* **Unified Native Dialogs:** Native Windows save dialogs, download notifications, and browser fallback notices in the embedded WebView2 browser have been updated to English.
* **FastMCP Server & OAuth Authorization:** All server-side tool docstrings and the browser-based OAuth 2.0 authorization template now render in pure English.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.5.2-windows-x64.zip`
* **SHA-256 Checksum:**
  ```text
  ed006576c16194e41394c7ccdd5e83b8e27df667ef70dcd264d02fa224e191e8
  ```

---

## 🚀 What's New in v0.5.1

### 🔒 Centralized OAuth & Persistent MCP Authentication
* **Zero-Loss Connection Persistence:** The SQLite OAuth database (`oauth.db`) is now stored centrally in `%APPDATA%\MammouthDefroster9000\oauth.db`. Upgrading versions or moving application directories will never break registered MCP connections or require deleting and re-registering clients in Mammouth.ai.
* **Automatic One-Time Migration:** Seamlessly detects and imports existing clients, tokens, and scopes from local directory databases on first launch without modifying or corrupting legacy data.
* **Fast Indexed Token Lookup:** Migrated token verification to indexed SHA-256 hash queries (`access_hash`, `refresh_hash`), eliminating high-latency DPAPI decryption of all database records per request.
* **Extended 90-Day Refresh Lifetimes:** Dedicated 90-day renewal cycle (`refresh_expires_at`), preventing expired 30-day access tokens from prematurely invalidating client reconnect capabilities.

### 🛡️ Security Hardening & Owner Verification
* **Owner-Proof OAuth Authorization:** Client approval in the OAuth consent flow strictly mandates verification with the Defroster API token (`secrets.compare_digest`). Insecure CSRF fallbacks have been eliminated.
* **Smart Lockout & Remote Proxy Header Resolution:** Progressive backoff and IP lockouts only apply to invalid or unauthenticated requests. Valid authorized tokens immediately bypass rate counters, ensuring shared proxy/tunnel clients are not blocked by a single misconfigured peer. Client IP resolution parses `CF-Connecting-IP` and `X-Forwarded-For`.
* **PowerShell & Shell Command Gating:** `local_exec_command` is strictly disabled unless the `shell_processes` module is explicitly enabled in the Cockpit. Read-only mode enforces deep token verification to block script blocks, subexpressions, redirection operators, piping chains, and file overwrites.
* **SSRF & Browser Automation Shields:** Playwright automation context enforces `chromium_sandbox=True` for native Microsoft Edge. Web scraping and browser agent tools actively reject private IP spaces, link-local addresses, and cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
* **Web Tools DNS Pinning:** Added DNS pinning per redirect hop and hard response payload limits to prevent SSRF and memory exhaustion attacks.
* **Screen Consent Safety:** Deregistered `screen_grant_consent` and `screen_revoke_consent` MCP tools from public AI model exposure; GUI screenshots now operate strictly through localized captures.

### ⚙️ Concurrency, Tunnels & UI Stability
* **Thread-Safe Tailscale Funnel Worker:** Serialized FIFO execution queue (`queue.Queue`) for Funnel background commands, preventing race conditions where shutdown commands executed out-of-order after startup.
* **Tkinter CTk Attribute Safety:** Replaced internal process attribute lookups with dictionary-backed access, preventing recursive delegation loops in mock and headless environments.
* **Atomic Configuration Persistence:** Implemented atomic file writes (temporary file + `fsync` + atomic `os.replace`) paired with mtime cache tracking, preventing configuration corruption.
* **Unicode Input Fidelity:** Replaced legacy typing calls with native Win32 `SendInput` handling for flawless international character typing.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.5.1-windows-x64.zip`
* **SHA-256 Checksum:**
  ```text
  92b0a8d95b7e555590a05b54f9f61d8012dd35b72a1de06dbbda2f7b2c02aa3e
  ```

---

## 🚀 What's New in v0.5.0

### 🌐 Playwright Browser Automation Agent (12 MCP Tools)
* **Claude Desktop-Equivalent Browser Control:** Mammouth AI can now programmatically navigate websites, interact with SPAs (React/Vue/Nuxt), click buttons, fill forms, extract rendered DOM content, and manage tabs.
* **Zero-Download Footprint:** Uses Microsoft Playwright running directly against the system-installed **Microsoft Edge** (`channel="msedge"`), eliminating any need for extra 150 MB Chromium downloads.
* **Live Visual Feedback & Headless Mode:** Opens a visible Edge window by default so the user can watch the AI browse in real-time (and intervene if a CAPTCHA or MFA challenge appears). Toggleable to silent Headless mode in the Cockpit GUI or `config.json`.
* **Numbered Interactive Element Indexing:** Automatically inspects the active page and indexes buttons, inputs, links, and textareas with compact numeric IDs (`[1]`, `[2]`), enabling accurate, deterministic clicks and form filling without relying on error-prone pixel coordinates.
* **Multimodal Vision Screenshots:** Dedicated `browser_screenshot` tool returning high-resolution images via `FastMCPImage` for visual reasoning by multimodal models (Claude 3.5 Sonnet, GPT-4o, Gemini 2.0).
* **Rendered Markdown Extraction:** `browser_get_content` executes client-side scripts before stripping clutter and extracting clean, structured Markdown (headings, tables, links).
* **Persistent Sessions & Storage:** Dedicated isolated profile directory (`data/agent_browser_profile/`) preserving cookies, logins, and sessions across server restarts.
* **SSRF Shield:** Blocks navigation to cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).

### 💻 Mammouth Code CLI Agent Bridge (`modules/mammouth_code.py`)
* **1-Click Official Installer & Upgrader:** Direct PowerShell installer (`irm https://code.mammouth.ai/install.ps1 | iex`) with automatic version checks and upgrade commands.
* **Top-Level Interactive Terminal Launcher:** Reliable console launcher opening PowerShell or Windows Terminal with `$env:MAMMOUTH_API_KEY` pre-configured.
* **Headless Background Task Runner:** Runs autonomous tasks via `mammouth run` and streams execution logs directly to the Defroster Cockpit.
* **Dual-Bridge MCP Auto-Sync:** Automatically registers Mammouth Defroster 9000 tools into `opencode.json` so CLI agents have full local tool access.

### ⏱️ Automated Task Scheduler & Triggers (`modules/task_scheduler.py`)
* **Recurring Background Prompts:** Schedules repeating prompts dispatched to Mammouth Web chat, Mammouth Code CLI, or local scripts.
* **Pre-Built Presets:** Bundled templates including Live Sports Tickers (5 min), Crypto & Market Watch (15 min), and System & Hardware Diagnostics (10 min).
* **Cockpit GUI Dashboard:** Live countdown timers, execution counters, and one-click pause, resume, and trigger controls.

### 🧘 Zen Mode & Authentic Mammouth AI Brand Theme
* **Brand Theme Alignment:** Complete overhaul utilizing the authentic Mammouth AI palette: Warm Charcoal (`#242428`), Pure Ivory (`#FCFAF7`), and Tusk Bronze (`#B88557`).
* **Zen Workspace:** One-click toggle collapsing the sidebar and maximizing the viewport for focused chat sessions.
* **Global Win32 Summon Hotkey:** System-wide shortcut (`Ctrl+Shift+M`) to instantly summon or minimize the Cockpit from any application.

### 🔒 Security Hardening & Zero Plaintext Fallback
* **SQLite OAuth DPAPI Encryption:** Windows DPAPI hardware-backed encryption (`_encrypt_dpapi()`) for access and refresh tokens in `oauth.db`.
* **Timing-Attack Resistance:** Constant-time comparisons using `secrets.compare_digest()`.

### 📦 Release Verification & Checksums
* **Archive:** `MammouthDefroster9000-v0.5.0-windows-x64.zip`
* **SHA-256 Checksum:**
  ```text
  0d1c96565c1877e9277fe23991b77b4e17229de7656534d8bf3331d360808f2b
  ```

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
  fb57a269b09938a6a50032c6630e73bfd85b88783658b028544951c7f3cccfa0
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
| **`MammouthDefroster9000-v0.4.3-windows-x64.zip`** | **Windows x64** | **~86.7 MB** | Official optimized standalone release package with executables, modules, and documentation. |

---

## 📜 Full Version History
For detailed commit history and changes across earlier releases, see [CHANGELOG.md](CHANGELOG.md).
