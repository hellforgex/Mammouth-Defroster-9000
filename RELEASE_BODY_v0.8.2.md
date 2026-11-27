# 🦣 Mammouth Defroster 9000 — v0.8.2

> **One Windows Cockpit for ChatGPT, Anthropic Claude & Mammouth.ai.**  
> **Target OS:** Windows 10 / Windows 11 (x64) · **Release:** `v0.8.2 - Mammouth Defroster 9000`

---

## ✨ Highlights Since v0.7.5

| Feature | What's new for you |
| :--- | :--- |
| 🤖 **ChatGPT Web & Connector** | Built-in **🤖 ChatGPT Web** tab (`chatgpt.com`), OAuth 2.1 Developer Mode connector, **`🤖 ChatGPT URL`** 1-click copy, and scheduled `chatgpt_web` prompts. |
| 🟠 **Anthropic Claude Web & Connector** | Built-in **🟠 Claude Web** tab (`claude.ai`), OAuth 2.1 DCR setup (**`🟠 Claude URL`**), Claude Code `.mcp.json` cloud sync, and scheduled `claude_web` prompts. |
| ⚡ **Streamlined 42-Tool Architecture** | Reduced 106 MCP tools down to **42 clean action-dispatched tools** across 16 modules (**-47% wire tokens**), keeping full legacy alias compatibility. |
| 🛡️ **Secret-File Shield** | Blocks `file_read` and skips `file_search_text` on `.env`, tokens, SSH keys, `oauth.db`, and Defroster's own configs by default (`protect_secret_files: true`). |
| 🔌 **New Default Port `8742`** | Fresh installs avoid `8000` port collisions automatically (existing `config.json` files keep their configured port). |

---

## 🚀 What's New

### 🤖 Feature 1: Parallel ChatGPT & Anthropic Claude Cockpit
- **Three Built-In AI Web Tabs:** Use **🤖 ChatGPT Web**, **🟠 Claude Web**, and **💬 Mammouth AI Web** side by side with isolated browser login profiles and a configurable startup tab under **Settings → In-App Browsers**.
- **Full Cockpit Feature Parity:** **Zen Mode**, **Global Summon (`Ctrl+Shift+M`)**, **Screen Copilot (`Ctrl+Shift+Space`)**, **Smart Clipboard (`Ctrl+Shift+K`)**, **Snipping (`Ctrl+V`)**, and the **Prompt Catalog** all send straight to your active chat tab.
- **1-Click OAuth 2.1 Connector Setup:** Click **`🤖 ChatGPT URL`** or **`🟠 Claude URL`** on the Dashboard to copy your live `/mcp` tunnel URL — Dynamic Client Registration and PKCE `S256` work automatically.

### ⚡ Feature 2: Streamlined 42-Tool MCP Surface
- **Nearly Half the Schema Tokens:** Consolidated 106 tools into **42 canonical tools** across 16 modules (`browser_*`, `file_*`, `desktop_*`, `gdrive_*`, `memory_*`, `task_*`, `claude_code`, `mammouth_code`, etc.), making tool discovery faster and safer inside tight LLM context limits.
- **Optional MCP Tool Annotations:** Set `server.expose_tool_annotations: true` in `config.json` if your client uses `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` hints (`false` by default for strict MCP 2024-11-05 clients).

### 🛡️ Feature 3: Secret Hygiene & Opt-In Shell Downloads
- **Automatic Credential Shield (`protect_secret_files: true`):** Refuses reads on `.env`, `credentials.json`, `gdrive_token.json`, `service_account.json`, `oauth.db`, SSH private keys, certificates, and Defroster's `config.json` / `hosts.json`, while keeping `*.example` / `*.sample` templates readable.
- **Opt-In HTTP Downloads (`allow_shell_downloads`):** Elevated shell users get a dedicated confirmation toggle under **Skills → PowerShell** to allow `irm`, `iwr`, `curl`, `wget`, `Start-BitsTransfer`, and `.NET WebClient` downloads — while download-and-execute stagers (`iex`, `Invoke-Expression`, `certutil`, `bitsadmin`, `Start-Process`) remain permanently blocked.

### 🖥️ Feature 4: Windows Ergonomics, Scheduler & Port 8742
- **OneDrive-Aware `known_folders`:** `system_get_specs` resolves your real Windows shell paths (`desktop`, `documents`, `downloads`, etc.) via the Windows Shell API so OneDrive-redirected folders are always reported accurately.
- **Bounded Directory Listings:** `directory_list` caps flat folder listings at `max_entries=500` by default with a truncation marker, preventing massive folders from overflowing chat context.
- **Always-On Task Scheduler:** Runs recurring prompts reliably in both Cockpit and headless server modes, with hardened WebView2 prompt injection for ProseMirror/TipTap editors.

---

## 📝 Upgrade Notes
- **Existing configs:** Your existing `config.json`, `oauth.db`, `tasks.db`, `memory.db`, and browser login profiles are preserved on upgrade, including your existing server port.
- **Fresh installs:** Default port is now **`8742`** (override anytime in Settings or via the `PORT` environment variable).
- **Opt-in toggles:** `allow_shell_downloads` and `expose_tool_annotations` default to `false` (fail-closed / backward-compatible).

---

## 📦 Release Assets & Verification

- Self-contained Windows x64 package scrubbed of personal configs, tokens, and local databases (`config.json` matches `config.example.json`).
- Verified with **438 passing unit/integration tests (+ 72 subtests)** and all **4 compiled runtime security gates** (`verify_compiled_runtime.py`).

| File | Platform | Size | SHA-256 Checksum |
| :--- | :--- | :--- | :--- |
| **`MammouthDefroster9000-v0.8.2-windows-x64.zip`** | Windows 10/11 x64 | 133,713,574 bytes | `e150cb522ae7e061513b301d451e6bfdf422ee143feb138c09665f3282449438` |
