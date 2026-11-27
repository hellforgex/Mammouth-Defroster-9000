# v0.8.2 - Mammouth Defroster 9000

> **Platform:** FastMCP Desktop Cockpit & Windows 10/11 Automation for **ChatGPT**, **Claude**, and **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Release:** `v0.8.2 - Mammouth Defroster 9000`

---

## 🚀 Public Release Overview

`v0.8.2` is the cumulative public release following `v0.7.5`, expanding Mammouth Defroster 9000 into a multi-assistant desktop cockpit with full **ChatGPT** and **Anthropic Claude** integration (parallel embedded WebApp tabs, OAuth 2.1 DCR/PKCE connectors, and Claude Code `.mcp.json` cloud sessions), a **streamlined 42-tool MCP architecture**, **secret-file read protection**, **Windows `known_folders` discovery**, **bounded directory listings**, **optional MCP tool annotations**, a collision-free **default port `8742`**, and an **opt-in shell HTTP/download gate**.

---

## 🛡️ Claude Connector Ergonomics & Secret Hygiene (`v0.8.2`)

- **Secret-File Read Protection (`protect_secret_files: true`):**
  - `file_read` refuses credential and token files (`.env`, `.env.*`, `credentials.json`, `gdrive_token.json`, `service_account.json`, `storage_state.json`, `*.token.json`, `oauth.db`, SSH private keys, `*.pfx`/`*.p12`/`*.ppk`, and Defroster's own `config.json` / `hosts.json`), and `file_search_text` skips them.
  - Template files (`*.example`, `*.sample`, `*.template`) remain readable, and protection fails closed if config cannot be read.
- **Optional MCP Tool Annotations (`expose_tool_annotations`):**
  - Tools include MCP `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` metadata when `server.expose_tool_annotations` is `true` (defaults to `false` for strict MCP 2024-11-05 compatibility).
- **Windows `known_folders` in `system_get_specs`:**
  - Resolves `home`, `desktop`, `documents`, `downloads`, `pictures`, `music`, and `videos` via `SHGetKnownFolderPath` so OneDrive-redirected user folders are reported accurately.
- **Bounded Directory Listings:**
  - `directory_list` accepts `max_entries` (default `500`) and appends a truncation marker instead of returning unbounded payloads.
- **New Default Port `8742`:**
  - Fresh installs default to `8742` instead of `8000` to avoid collisions with local dev servers or prior instances (existing `config.json` files and `PORT` env overrides take precedence).
- **Opt-In Shell HTTP & Download Control (`allow_shell_downloads`):**
  - Added `server.allow_shell_downloads` (default `false`, fail-closed) and a dedicated Cockpit confirmation toggle under **Skills → PowerShell** allowing `Invoke-RestMethod` (`irm`), `Invoke-WebRequest` (`iwr`), `curl`, `wget`, `Start-BitsTransfer`, and `.NET WebClient` downloads only when both `allow_admin_shell` and `allow_shell_downloads` are enabled.
  - Download-and-execute stagers and LOLBins (`iex`, `Invoke-Expression`, `certutil`, `bitsadmin`, `Start-Process`, `powershell -Command/-File`, `python -c`) remain permanently blocked.

---

## 🟠 Embedded Claude WebApp & Streamlined 42-Tool Architecture (`v0.8.1`)

- **Parallel Claude Web Tab:** Dedicated **🟠 Claude Web** tab (`https://claude.ai`) alongside **🤖 ChatGPT Web** and **💬 Mammouth AI Web** with isolated WebView2 profiles, OAuth 2.1 DCR onboarding (`🟠 Claude URL`), Zen Mode, global hotkeys, and `claude_web` scheduled task triggers.
- **Streamlined 42-Tool Consolidation:** Consolidated 106 MCP tools down to **42 canonical action-dispatched tools** across 16 modules (-60% tools, -47% wire tokens), preserving transparent legacy aliases inside `defroster_execute_tool` and all workspace/shell/SSRF/consent security gates.

---

## 🤖 ChatGPT Integration & Task Scheduler Reliability (`v0.8.0`)

- **Embedded ChatGPT Web Tab & OAuth 2.1:** Parallel **🤖 ChatGPT Web** tab (`https://chatgpt.com`), trusted OpenAI OAuth 2.1 redirect/DCR/PKCE `S256` endpoints, and `chatgpt_web` scheduled task triggers.
- **Background Scheduler Loop & Web Chat Injection:** Started `TaskSchedulerEngine.start_background_loop()` in both GUI and headless server lifespans, added thread-safe Tk `after()` queue marshalling, and hardened WebView2 prompt injection for ProseMirror/TipTap editors.

---

## 📦 Packaging & Verification

- Self-contained Windows x64 package (`MammouthDefroster9000-v0.8.2-windows-x64.zip` + `.sha256` checksum), scrubbed of personal configs, tokens, and local databases.
- Verified with full automated unit/integration test suite and compiled binary runtime security gate tests (`verify_compiled_runtime.py`).
