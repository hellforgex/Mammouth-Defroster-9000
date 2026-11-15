# v0.7.5 - Mammouth Defroster 9000

> **Platform:** Dedicated Sovereign Windows Cockpit & DevOps Automation for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Release:** `v0.7.5 - Mammouth Defroster 9000`

---

## 🚀 Public Release Overview

`v0.7.5` is the first public release following `v0.7.2`. This release consolidates all security hardening, architectural enhancements, Anthropic Claude OAuth 2.1 integration, multilingual tool discovery advancements (from `v0.7.4`), autonomous web chat automation improvements (from `v0.7.3`), and system stability updates.

---

## 🌟 Cumulative Highlights (v0.7.2 → v0.7.5)

- **Security Hardening & Zero-Vulnerability Baseline (v0.7.5):** Zero-vulnerability dependency baseline with `opentelemetry-api>=1.45.2` (remediating CVE-2026-126360), `fastmcp>=4.1.4`, `starlette>=1.10.0`, and `pillow>=13.0.0`. Parameterized terminal command execution preventing PowerShell injection, strict profile authorization gating for `defroster_execute_tool`, strict CORS origin preflights, and URL query-string tokens disabled by default (opt-in via `server.allow_query_token`).
- **Architecture & Robustness Overhaul (v0.7.5):** Standardized execution contracts with structured status, structured error codes, integer exit codes, and `duration_ms` latency telemetry. Machine-readable on-demand tool schemas via `defroster_catalog(tool_schema=...)`, read-only `defroster_health_check` system health probe, task scheduler simulation / preview mode, and persistent execution run history tracking.
- **Anthropic Claude & OAuth 2.1 Compliance (v0.7.4 Milestone):** Full compliance with RFC 8414, RFC 9728, and RFC 7591 dynamic client registration. Standardized discovery endpoints (`/.well-known/oauth-authorization-server`, `/.well-known/openid-configuration`), subpath routing (`/mcp/.well-known/...`), exclusive S256 PKCE enforcement, CSP `frame-ancestors` clickjacking defense, Streamable HTTP `.mcp.json` sync, and Claude Code cloud session terminal launcher.
- **MCP Transport & Defroster Catalog Token Optimization (v0.7.4 Milestone):** Dual SSE transport mounted at `/sse` and root `/mcp`. Tiered defroster catalog discovery resolving platform chat token limits (reducing default overview from ~2,876 tokens to <1,080 tokens, >62% savings) with targeted category and search drilldowns.
- **Multilingual Tool Discovery & Quick Profiles (v0.7.4 Milestone):** Trilingual tool hint metadata (`_MULTILINGUAL_TOOL_HINTS` in German, French, English), persistent UI profile selectors on Dashboard and Navigation Sidebar, real-time `tools/list_changed` broadcast to active MCP sessions, and optimized schema budgets.
- **Autonomous Web Chat Prompt Automation (v0.7.3 Milestone):** Asynchronous DOM input polling (`pollAndInject`) eliminating prompt drops during scheduled background tasks, multilingual button resolver with React 18 pointer/mouse event sequencing, and Microsoft Robocopy updater engine.

---

## 🛡️ Security Hardening & Vulnerability Remediation (v0.7.5)

- **PowerShell Execution Sanitization (`launch_claude_terminal`):**
  - Completely eliminated dynamic string interpolation of user and MCP arguments (`prompt`, `workspace_path`, `exe`) into PowerShell execution scripts (`modules/claude_code.py`).
  - Parameterized process execution via child environment variables (`MD_CLAUDE_WS`, `MD_CLAUDE_EXE`, `MD_CLAUDE_PROMPT`, `MD_CLAUDE_TITLE`). The generated script contains solely constant statements (`Set-Location -LiteralPath $env:MD_CLAUDE_WS; & $env:MD_CLAUDE_EXE ...`).
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
- **Credential Storage Hardening (`sync_claude_code_mcp`):**
  - `sync_claude_code_mcp()` now defaults to environment variable reference mode (`Bearer ${MAMMOUTH_DEFROSTER_TOKEN}`) instead of writing plaintext tokens to `.mcp.json` and user global `~/.claude.json`.
- **Dependency Upgrades & Vulnerability Remediation (CVE-2026-126360):**
  - Patched `opentelemetry-api` to `>=1.45.2` (CVE-2026-126360 remediation) across `pyproject.toml`, `requirements.txt`, and `uv.lock`.
  - Upgraded core dependencies to eliminate known CVEs: `fastmcp>=4.1.4`, `starlette>=1.10.0`, `pillow>=13.0.0`.
  - Harmonized Python requirement to `>=3.11`.
  - Verified zero known vulnerabilities across `pip-audit`.

---

## 🏗️ Architecture & Robustness Overhaul (v0.7.5)

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

---

## 🤖 Anthropic Claude & OAuth 2.1 Compliance (Consolidated from v0.7.4)

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

---

## ⚡ MCP Transport & Token Budget Optimization (Consolidated from v0.7.4)

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

---

## 🌍 Multilingual Tool Search & Quick Profiles (Consolidated from v0.7.4)

- **Multilingual Tool Search Keyword Hints:**
  - Added `_MULTILINGUAL_TOOL_HINTS` across all Defroster tools in German, French, and English (e.g. *"Browser-Automatisierung"*, *"Verzeichnis auflisten"*, *"Datei lesen"*, *"lister répertoire"*, *"lire fichier"*).
- **Persistent Tool Profile Quick Selectors:**
  - Dedicated Tool Profile selector row on Dashboard Hero Card and permanent profile card in Left Navigation Sidebar.
  - Bidirectional UI synchronization and immediate MCP `tools/list_changed` broadcast to connected clients upon profile change.

---

## 🐛 Autonomous Web Chat & Desktop Automation (Consolidated from v0.7.3)

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

---

## 🧹 Code Quality, Linting & Test Infrastructure

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
