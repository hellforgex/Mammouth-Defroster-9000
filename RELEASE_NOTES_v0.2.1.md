# 🦣 Mammouth Defroster 9000 — Release Notes (v0.2.1)

> **Platform:** Dedicated Sovereign Windows Cockpit for **Mammouth.ai**  
> **Target OS:** Windows 11 / Windows 10 (x64)  
> **Type:** Hotfix & Stability Release

---

## 🛠️ Key Fixes & Stability Improvements in v0.2.1

* **Fixed Server Launch Exception:** Inlined self-signed TLS certificate generation directly into `gui.py`, eliminating `ImportError: cannot import name 'generate_self_signed_cert'` on server start.
* **Fixed Standalone Binary Crash on Startup:** Upgraded PyInstaller build scripts with complete `--collect-all` bundling for CustomTkinter themes, fonts, FastMCP, and Uvicorn dependencies.
* **Fixed Release Packager Paths:** Corrected distribution directory resolution in `package_clean_release.py` to bundle the latest hardened binary.
* **Verified Server Lifecycle:** Guaranteed reliable server startup and shutdown with verified `/sse` and `/mcp` endpoints.

---

## 📦 Downloads

| File | Platform | Description |
| :--- | :---: | :--- |
| **`MammouthDefroster9000-v0.2.1-windows-x64.zip`** | **Windows x64** | Official standalone release package with executable, modules, and documentation. |
