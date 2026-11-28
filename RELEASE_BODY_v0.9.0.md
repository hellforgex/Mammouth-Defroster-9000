# ❄️ Defrostr (Mammouth Defroster 9000) — v0.9.0

> **Every AI. One Local Bridge. Zero Lock-In.**  
> **Target OS:** Windows 10 / Windows 11 (x64) · **Release:** `v0.9.0 - Mammouth Defroster 9000`

---

## ✨ Highlights

| Feature | What's new for you |
| :--- | :--- |
| ❄️ **Rebranded to Defrostr** | Unified **Defrostr** branding across the Desktop Cockpit, Splash Screen, System Tray, FastMCP metadata, and OAuth consent pages — with full backward compatibility for existing tokens, configs, and updates. |
| ✨ **Google Gemini Web & Developer Mode** | Built-in **✨ Gemini Web** tab (`./data/gemini_browser_profile`, `en-US` WebView2 locale) with sticky `?hl=en` routing, one-shot post-login redirect to `/devmode?hl=en`, toolbar **`🧪 DevMode`** shortcut, and **`✨ Gemini URL`** onboarding dialog. |
| 🔐 **Gemini OAuth 2.1 DCR (PKCE `S256`)** | Exact-host callback & CORS/CSP validation for `oauth-redirect*.googleusercontent.com`, `vertexaisearch.cloud.google.com`, and `gemini.google.com` (strictly rejecting arbitrary `*.googleusercontent.com` hosts). |
| 🛡️ **Dedicated Security Tab** | Consolidated authentication, Bearer/query token policies, Workspace & Secret-File Shield, elevated shell/download gates, Vision consent, TLS, and MCP tool annotations into **`🛡️ Security`**, while renaming settings to **`⚙️ Settings`**. |
| 🎛️ **Selectable Provider Web Tabs** | Toggle visibility of **`🤖 ChatGPT`**, **`🟠 Claude`**, **`✨ Gemini`**, and **`💬 Mammouth AI`** tabs in Settings across Sidebar, Header, Dashboard Quick Launch, Hero URL buttons, and Default Chat Tab selection. |
| ⏱️ **Gemini Scheduler & DOM Automation** | Added `gemini_web` scheduled task target, `default_chat_tab="gemini"` resolution, and Quill (`rich-textarea div.ql-editor`) / `button.send-button` prompt submission. |

---

## 📝 Upgrade Notes
- **Existing configs & data:** Your existing `config.json`, DPAPI-encrypted `api_token`, `oauth.db`, `tasks.db`, `memory.db`, and browser profiles remain untouched and compatible on upgrade.
- **EU / German Google accounts:** Google hides custom MCP connectors on German/localized Gemini pages. Defrostr's **✨ Gemini Web** tab locks UI navigation to `?hl=en` automatically and supports both in-app **`🧪 DevMode`** and external **`🌐 Open in Browser`** setup workflows.

---

## 📦 Release Assets & Verification

- Self-contained Windows x64 package scrubbed of personal configs, tokens, and local databases (`config.json` matches `config.example.json`).
- Verified with **447 passing unit/integration tests (+ 82 subtests)** and all **4 compiled runtime security gates** (`verify_compiled_runtime.py`).

| File | Platform | Size | SHA-256 Checksum |
| :--- | :--- | :--- | :--- |
| **`MammouthDefroster9000-v0.9.0-windows-x64.zip`** | Windows 10/11 x64 | 133,745,521 bytes | `aaa3ad091043d01a74b662b26d27d1d1e3eb99de4e0243e08f2c74ce289b99d1` |
