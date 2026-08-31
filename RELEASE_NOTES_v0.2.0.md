# 🦣 Mammouth Defroster 9000 — Release Notes (v0.2.0)

> **Platform:** Dedicated Sovereign Windows Cockpit for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Status:** Production Ready

---

## 🌟 Key Highlights in v0.2.0

### 🔑 1. Native Mammouth.ai Bearer Token Authentication
Mammouth.ai now officially supports **Bearer Token authentication** directly in their web app. You can now connect your local MCP server with full token security (`Authorization: Bearer <token>`). Token enforcement is active by default in Mammouth Defroster to protect your endpoint from unauthorized access.

### 👁️ 2. Desktop Vision Support
Multimodal AI models connected through Mammouth.ai can now see and inspect your desktop:
* Capture full displays or specific monitor indices in multi-screen setups.
* Automatically downscale captures to conserve vision LLM tokens while maintaining high clarity.
* Test screen captures instantly using the new `📸 Capture Desktop` quick-action button in the toolbar.

### 🎨 3. Complete Cockpit UI Overhaul
The desktop interface has been completely redesigned for daily workflow efficiency:
* **Cyber-Obsidian Dark Mode:** Deep charcoal & obsidian background with subtle neon-green accents.
* **High-Contrast Light Mode:** Crisp daylight theme with dark slate typography and clear borders.
* **Live System Telemetry:** Real-time visual progress gauges for CPU % and RAM % utilization, active tool tracking (52 tools across 9 modules), and a session uptime clock.
* **1-Click MCP Exporters:** Instant clipboard buttons to copy your public Tailscale URL, Bearer Key, or complete MCP JSON configurations.
* **Web Launcher:** Top-bar shortcut button to open Mammouth.ai directly in your default browser.
* **Log Stream Exporter:** Save and export diagnostic session logs directly via `💾 Save Log`.

### 🎮 4. Unreal Engine 5 Integration (ALPHA)
A direct bi-directional remote execution bridge for Unreal Engine 4 and 5:
* **23 Dedicated MCP Tools:** Spawn actors, transform geometry, create materials, load levels, and capture viewport screenshots directly from Mammouth.ai prompts.
* **Safety Filters:** Built-in validation blocks destructive console commands and script escapes.

### 🛡️ 5. Under-the-Hood Security Hardening
* **Sandboxed Workspace:** File operations are strictly isolated to `./workspace` by default with path traversal protection.
* **Hardware DPAPI Encryption:** SSH credentials in the host manager are encrypted at rest via Windows DPAPI (TPM-backed).
* **SSRF Shield:** Web fetching tools resolve and validate destination IP addresses prior to connecting, blocking private network probing.
* **Resource Safeguards:** Background tasks and PowerShell executions are subject to strict limits and command sanitization.

---

## 🚀 Quick Setup with Mammouth.ai

1. Open **Mammouth Defroster 9000** and click **`▶ START SERVER`**.
2. Click **`📋 Copy URL`** to copy your public Tailscale Funnel endpoint.
3. Click **`📋 Copy Key`** to copy your Bearer API token.
4. In **Mammouth.ai**, add your MCP Server and paste your URL and Bearer Key!

```json
{
  "mcpServers": {
    "MammouthDefroster9000": {
      "url": "https://[your-tailscale-node].ts.net/sse",
      "headers": {
        "Authorization": "Bearer YOUR_MAMMOUTH_BEARER_TOKEN"
      }
    }
  }
}
```

---

## 📦 Downloads

| File | Platform | Description |
| :--- | :---: | :--- |
| **`MammouthDefroster9000-v0.2.0-windows-x64.zip`** | **Windows x64** | Official standalone release package with executable, modules, and documentation. |
