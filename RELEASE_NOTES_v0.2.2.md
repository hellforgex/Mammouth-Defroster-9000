# 🦣 Mammouth Defroster 9000 — Release Notes (v0.2.2)

> **Platform:** Dedicated Sovereign Windows Cockpit for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Type:** Major Feature & Usability Release

---

## 🛠️ Key Highlights & New Features in v0.2.2

### 🖱️ Desktop Mouse & Keyboard Automation (`modules/desktop_input.py`)
* **Native Windows User32 Subsystem:** Uses direct `user32.mouse_event`, `user32.SetCursorPos`, and `user32.keybd_event` (with `KEYEVENTF_UNICODE`) for 100% reliable execution in interactive desktop sessions without PyAutoGUI failsafe crashes.
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

### 🔑 Original Plaintext Bearer API Key Display & Hygiene
* **Interactive Dashboard Card (`gui.py`):** The main endpoint card now displays the clean alphanumeric Bearer key.
* **Privacy Toggle:** Quickly switch between `🔒 Hide Key` and `👁️ Show Key`.
* **One-Click Copy:** `📋 Copy Key` copies the plaintext token straight to your clipboard for instant setup in Mammouth.ai.
* **Transparent Migration (`config.py`):** Automatically upgrades legacy `dpapi:` tokens to clean plaintext tokens.

### 👁️ Desktop Vision & Interactive Consent Gate (`modules/screen_capture.py`)
* **Interactive Desktop Prompt:** When an MCP client requests a screenshot while consent is active, a native confirmation modal appears directly in the GUI asking for approval.
* **Session Consent & Granular Controls:** Added toggle switch (`Require Consent`) and `🔓 Grant Session Consent` button to both Tab 2 (Skills) and Tab 4 (Settings).
* **New MCP Tools:** Registered `screen_grant_consent(duration="once"|"always")` and `screen_revoke_consent()` as MCP tools for autonomous or programmatic approval.

### 🖥️ Dual-Executable Architecture & Packaging
* **`MammouthDefroster9000.exe`:** Sovereign windowed desktop cockpit GUI. Supports `--autostart` flag and `auto_start_server` config setting.
* **`MammouthDefroster9000-server.exe`:** Dedicated CLI console server with live Uvicorn log streaming and graceful Ctrl+C shutdown.
* **`start_server.bat` & `start_gui.bat`:** Clean, reliable batch launchers included in the release distribution.

### 🛡️ FastMCP & MCP Client Compatibility Fixes
* **Empty List IndexError Fix:** Prevented MCP clients (including Agent Zero) from crashing on empty lists (`memory_list`, `task_list`) by guaranteeing valid `[TextContent(text="[]")]` payloads.
* **Flexible Parameter Aliases:** Added `path` alias for `directory_path` / `file_path` across file operations and `id` alias for `task_id`.

### 🌐 Dynamic Network & Multi-Tunnel Support
* **Tailscale, Cloudflare & ngrok:** Full GUI support for automatic tunnel configuration, path detection, and health monitoring.

---

## 📦 Downloads

| File | Platform | Description |
| :--- | :---: | :--- |
| **`MammouthDefroster9000-v0.2.2-windows-x64.zip`** | **Windows x64** | Official standalone release package with executable, modules, and documentation. |
