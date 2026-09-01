# 🦣 Mammouth Defroster 9000 — Release Notes (v0.2.1)

> **Platform:** Dedicated Sovereign Windows Cockpit for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Status:** Production Ready

---

## 🌟 Key Highlights in v0.2.1

### 🚀 1. Robust Standalone Binary & GUI Server Launch
* **Zero-Dependency Startup:** Fixed server launch exception by making local TLS certificate generation self-contained inside `gui.py`.
* **Full Theme & Asset Packaging:** Standalone PyInstaller binary bundles all CustomTkinter themes, fonts, FastMCP, and Uvicorn runtime assets.
* **Verified Server Lifecycle:** Guaranteed instant server startup on click with verified live `/sse` and `/mcp` endpoints.

### 🔑 2. Native Mammouth.ai Bearer Token Authentication
Mammouth.ai now officially supports **Bearer Token authentication** directly in their web app. Connect your local MCP server with full token security (`Authorization: Bearer <token>`). Token enforcement is active by default with Windows DPAPI hardware encryption.

### 👁️ 3. Desktop Vision Support
Multimodal AI models connected through Mammouth.ai can inspect your desktop across all monitors with intelligent token downscaling and user consent gate privacy protection.

### 🎮 4. Live Unreal Engine 5 Automation
A direct bi-directional remote execution bridge for Unreal Engine 4 and 5 with real-time Python execution, actor spawning, viewport captures, and a strict 19-module AST Allowlist.

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
| **`MammouthDefroster9000-v0.2.1-windows-x64.zip`** | **Windows x64** | Official standalone release package with executable, modules, and documentation. |
