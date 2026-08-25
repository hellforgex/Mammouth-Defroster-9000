# 🦣 Mammouth Control Center & MCP Server for Windows 11

> **Enterprise-Grade Desktop Control Center and FastMCP Server with Hardened Security, Modular DevOps & System Automation Toolsets for [Mammouth.ai](https://mammouth.ai).**

![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-blue)
![Vibecoded](https://img.shields.io/badge/Vibecoded%20By-noskillz%20⚡-purple)
![Security](https://img.shields.io/badge/Security-Bearer%20Token%20%2B%20DPAPI%20%2B%20Sandbox-green)
![License](https://img.shields.io/badge/License-MIT%20%2B%20%C2%A7%20521%20BGB-orange)
![FastMCP](https://img.shields.io/badge/MCP-FastMCP%203.4%2B-purple)
![Interface](https://img.shields.io/badge/UI-CustomTkinter%20Dark%20Theme-blueviolet)

---

> [!CAUTION]
> ### ⚠️ ⚡ NOSKILLZ VIBECODED DISCLAIMER & HARDCORE WARNING ⚡ ⚠️
>
> **WELCOME TO THE RAW AGENTIC POWERHOUSE.**
>
> This software is **100% pure vibe-coded** by **noskillz** for maximum speed, sovereign Windows 11 DevOps supremacy, and zero-compromise automation.
>
> 🦣 **With great agentic power comes absolute responsibility:**
> - You are handing an autonomous AI assistant real keys to your operating system: PowerShell execution, sandboxed file modifications, hardware diagnostics, and remote SSH servers.
> - **NEVER** expose this server publicly to the open internet without **Tailscale**, a private VPN, or Token Authentication enabled, unless you enjoy chaotic uninvited guests playing Doom in your PowerShell console.
> - By running this tool, you acknowledge that you are a sovereign captain of your machine. If you instruct an AI to *"clean up everything"* and it happily deletes your favorite meme stash, that is between you, the AI, and the cosmos.
> - Test your prompts, sandbox your workspaces, and embrace the agentic vibe responsibly. 🚀

---

## ⚖️ Rechtlicher Haftungsausschluss (Disclaimer nach deutschem Recht)

> [!IMPORTANT]
> **Bitte vor der Nutzung aufmerksam lesen:**
>
> 1. **Unentgeltliche Bereitstellung (§ 521 BGB)**:  
>    Diese Software wird als Open-Source-Projekt vollkommen unentgeltlich und im aktuellen Entwicklungsstadium (*„as is“*) zur Verfügung gestellt. Gemäß **§ 521 BGB** ist die gesetzliche Haftung des Entwicklers / Urhebers (**noskillz / hellforgex**) auf **Vorsatz und grobe Fahrlässigkeit** beschränkt. Eine Haftung für einfache/leichte Fahrlässigkeit ist im gesetzlich zulässigen Rahmen ausgeschlossen.
>
> 2. **Nutzung auf eigene Gefahr & Eigenverantwortung**:  
>    Die Nutzung sämtlicher Funktionen dieser Software – insbesondere der Module zur Ausführung lokaler **PowerShell-Befehle**, zur **Dateimanipulation (Schreiben, Ersetzen, Löschen)**, zur **Systemdiagnose** sowie zur Steuerung von **Remote-SSH-Servern (PuTTY/Plink)** – erfolgt auf **ausschließliches, eigenes Risiko** des Anwenders. Der Anwender trägt die alleinige Verantwortung für alle Aktionen und Befehle, die er oder angebundene KI-Modelle / Agenten ausführen lassen.
>
> 3. **Ausschluss von Folgeschäden und Datenverlust**:  
>    Der Urheber haftet ausdrücklich **nicht** für Schäden an Soft- oder Hardware, Datenverlust, Betriebsunterbrechungen, Serverausfälle, Sicherheitsvorfälle oder wirtschaftliche Folgeschäden, die durch die Installation, Konfiguration, Ausführung oder Netzwerk-Freigabe dieser Software entstehen.
>
> 4. **Netzwerk- und Tunnelsicherheit**:  
>    Der Anwender ist eigenverantwortlich dafür zuständig, den Server über sichere Netzwerke (wie Tailscale VPN, geschützte Tunnels oder aktive Token-Authentifizierung) abzusichern. Der Betrieb des Servers auf öffentlich erreichbaren IP-Adressen oder Tunnels ohne Authentifizierung geschieht auf alleinige Gefahr des Betreibers.

---

## 🌟 Highlights & Features

Mammouth Control Center gibt deinen Mammouth AI-Assistenten sicheren, modularen Zugriff auf deine lokale Windows-Umgebung, Remote-Server und Hintergrund-Dienste.

- 🔒 **Gehärtete Sicherheits-Architektur**:
  - **API-Token Authentifizierung**: Optionaler Bearer-Token / Query-Token Schutz (`Authorization: Bearer <token>` oder `?token=...`).
  - **Striktes CORS-Hardening**: Beschränkt auf `mammouth.ai`-Domains und lokale Entwicklung (keine Wildcard `*`).
  - **Workspace Path-Sandboxing**: Dateizugriffe sind auf das autorisierte Verzeichnis (`./workspace`) eingesperrt; Systempfade (`C:\Windows`, `Startup` etc.) sind blockiert.
  - **Windows DPAPI Passwort-Verschlüsselung**: SSH-Passwörter in `hosts.json` werden über die native Windows Data Protection API verschlüsselt.
  - **SSRF-Schutzfilter**: Verhindert das Abrufen interner IP-Bereiche, Loopbacks und Cloud-Metadata-Services im Web-Scraper.
  - **PowerShell-Sanitization**: Whitelist-Validierung bei Windows-Event-Log Diagnosen.
- 🖥️ **Moderne Windows 11 Desktop GUI**: Dark-Mode Dashboard mit Live-Status, 1-Klick Start/Stop, Log-Stream und kopierbaren Endpoints.
- ⚡ **Modulare Skill-Toggles**: 7 Werkzeug-Sets einzeln per Schalter aktivierbar (Memory, Kanban, File Ops, PowerShell, SSH, Hardware-Monitor, Web).
- 🌐 **Flexible Tunnel- & Endpoint-Wahl**:
  - **Tailscale Funnel**: Zero-Config Auto-Discovery & öffentliche HTTPS-Domain (`https://<node>.ts.net/sse`).
  - **Cloudflare Tunnel**: Kostenlose Quick-Tunnels via `trycloudflare.com` oder Custom Domains.
  - **ngrok Tunnel**: Instant HTTP-Tunnel mit lokaler API-Erkennung (`127.0.0.1:4040`).
  - **Direct IP / LAN**: Direkte Verbindung via `127.0.0.1` oder lokaler Netzwerk-IP (`192.168.x.x`).
  - **Custom Domain**: Eigene Reverse-Proxies (Nginx, Caddy, Traefik).
- 🔀 **Wählbare Routen-Pfade**: Umschalten zwischen `/sse`, `/mcp`, `/messages` oder `/`.
- 🔑 **Integrierter SSH-Host-Manager**: Schnelles Verwalten von Linux-VPS & Servern für PuTTY, Plink und SCP ohne JSON-Bearbeitung.
- 📦 **1-Klick EXE-Builder**: `build_exe.bat` erstellt eine eigenständige Windows-Anwendung.

---

## 🛠️ Enthaltene MCP Toolsets (Skills)

| Skill / Modul | Sicherheitsstufe | Hauptfunktionen | Beispiel-Tools |
| :--- | :---: | :--- | :--- |
| 🧠 **Persistent Memory** | 🟢 Sicher | SQLite Cross-Session Wissensspeicher mit Suchfunktion & Kategorien | `memory_save`, `memory_recall`, `memory_list`, `memory_get` |
| 📋 **Task & Kanban Board** | 🟢 Sicher | SQLite Task- & Projektverwaltung (`todo`, `in_progress`, `done`, `blocked`) | `task_create`, `task_update`, `task_list`, `task_delete` |
| 📁 **File & Code Operations** | 🔒 Sandboxed | Zeilenweises Lesen, Ripgrep-Suche, Chunk-Ersetzung innerhalb des Workspaces | `file_read`, `file_write`, `file_replace_chunk`, `file_search_text`, `directory_tree` |
| 💻 **PowerShell Execution** | ⚠️ Hohe Rechte | Synchrone Befehle & Hintergrund-Prozesse mit Echtzeit-Logs | `command_run`, `process_start_background`, `process_get_output`, `process_kill_background` |
| 🔑 **PuTTY & SSH Management** | 🔒 DPAPI-Verschlüsselt | Remote-Befehle via Plink, SCP Dateitransfer, interaktives PuTTY-Fenster | `ssh_exec_command`, `ssh_open_putty_window`, `ssh_transfer_file`, `ssh_list_saved_hosts` |
| 📊 **System & Diagnostics** | 🟢 Sicher | CPU, RAM, Datenträger, GPU-Details, Top-Prozesse, Windows Event Logs | `system_get_specs`, `system_get_processes`, `system_get_gpu_info`, `system_get_event_logs` |
| 🌐 **Web Scraper & Tools** | 🛡️ SSRF-Geschützt | Webseiten-Text-/Markdown-Extraktor mit privater IP-Sperre & Status-Check | `web_fetch_url`, `web_check_status` |

---

## 🚀 Schnellstart

### Voraussetzungen
- Windows 10 oder 11
- Python 3.10+ (oder [uv Package Manager](https://docs.astral.sh/uv/) — empfohlen)
- Optional: [Tailscale](https://tailscale.com/), [cloudflared](https://github.com/cloudflare/cloudflared) oder [ngrok](https://ngrok.com/).

---

### Option A: Starten via Python / `uv` (Empfohlen)

1. Repository klonen:
   ```bash
   git clone https://github.com/hellforgex/Mammouth-MCP-Control-Center.git
   cd Mammouth-MCP-Control-Center
   ```

2. Doppelklick auf **`start_gui.bat`**  
   *(oder `uv run gui.py` / `python gui.py` in der Konsole ausführen)*

---

### Option B: Standalone Windows EXE erstellen

1. Doppelklick auf **`build_exe.bat`**
2. Die fertige Datei liegt in `dist\MammouthControlCenter\MammouthControlCenter.exe`.

---

## 🔗 Verbindung mit Mammouth.ai

1. Öffne das **Mammouth Control Center**, wähle deinen gewünschten **Exposure Mode** (z. B. Tailscale Funnel) und klicke auf **`▶ Start Server`**.
2. Klicke auf **`📋 Copy`** neben der berechneten **Endpoint URL** (z. B. `https://<node>.ts.net/sse`).
3. In **[Mammouth.ai](https://mammouth.ai)**:
   - Gehe auf **Settings** → **Custom MCP Servers** (oder Tools).
   - Klicke auf **Add MCP Server**:
     - **Name**: `Mammouth Powerhouse`
     - **Type**: `SSE` (Server-Sent Events)
     - **URL**: Füge deine kopierte URL ein (`https://.../sse`).
   - Klicke auf **Save / Connect**.
4. Starte einen neuen Chat mit Mammouth!

---

## 📂 Projektstruktur

```
mammouth-control-center/
├── modules/
│   ├── __init__.py
│   ├── memory.py            # SQLite Long-term memory
│   ├── tasks_kanban.py      # SQLite Kanban & tasks
│   ├── file_ops.py          # Sandboxed file editing & search
│   ├── shell_processes.py   # PowerShell execution & background daemons
│   ├── putty_ssh.py         # DPAPI-encrypted PuTTY / Plink / PSCP remote tools
│   ├── system_monitor.py    # Hardware & Windows diagnostics
│   └── web_tools.py         # SSRF-protected web scraping & status checks
├── config.py                # Security & Configuration manager
├── config.example.json      # Hardened template configuration
├── hosts.example.json       # Template SSH hosts configuration
├── server.py                # FastMCP server with Auth & CORS middleware
├── gui.py                   # CustomTkinter Windows 11 Desktop GUI
├── start_gui.bat            # Quick launcher script
├── build_exe.bat            # PyInstaller one-click builder
├── requirements.txt         # Pip dependency manifest
├── pyproject.toml           # Project metadata
├── LICENSE                  # MIT License & § 521 BGB Haftungsausschluss
├── .gitignore               # Git security & cache filter
└── README.md                # Dokumentation, Haftungsausschluss & noskillz Manifesto
```

---

## 📄 Lizenz & Rechtliches
MIT License. Copyright (c) 2026 **noskillz** ([hellforgex](https://github.com/hellforgex)).  
Gilt in Verbindung mit dem obenstehenden **Rechtlichen Haftungsausschluss nach § 521 BGB**.
