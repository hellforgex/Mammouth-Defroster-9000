# 🦣❄️ Mammouth Defroster 9000

> **Sovereign Windows 11 FastMCP Desktop Cockpit & DevOps Powerhouse**  
> Tailored for Mammouth.ai with Live Unreal Engine 5 Automation, DPAPI Credential Security, Sandboxed File Operations, and Multi-Monitor Vision.

---

## 🌟 Overview

**Mammouth Defroster 9000** is a production-grade, sovereign Model Context Protocol (MCP) server and desktop control cockpit. It provides local and remote AI models with powerful, sandboxed tools to automate development workflows, perform system diagnostics, manage SSH/PuTTY hosts, capture desktop screens, and interact directly with Unreal Engine 5.

### 🛡️ Security Architecture Highlights (v0.2.0)
- **Fail-Closed Bearer Token Authentication:** Progressive exponential backoff per IP after failed attempts.
- **DPAPI Hardware Token & Host Encryption:** API tokens and SSH passwords encrypted using Windows DPAPI (`win32crypt`).
- **Strict Unreal Engine AST Allowlist:** Only 19 pre-approved standard modules permitted (`ALLOWED_MODULES`); all unauthorized imports, reflection, and dynamic code execution are unconditionally blocked.
- **HMAC-SHA256 Challenge-Response Protocol:** Cryptographically authenticated remote execution on loopback sockets.
- **Read-Only Shell Default with R7-N1 Path Guard:** PowerShell execution runs in Read-Only mode by default; path traversal outside workspace is strictly blocked. Admin mode requires explicit user confirmation.
- **Desktop Vision Consent Gate:** Screen capture requires explicit interactive user consent (`require_consent: true`).
- **Transport-Level SSRF Shield:** DNS pre-resolution and IP validation preventing access to internal/cloud metadata networks.
- **Local LAN HTTPS / TLS Support:** Automated self-signed certificate generation (`generate_self_signed_cert`).

---

## 🚀 Getting Started

### Prerequisites
- Windows 10/11 (64-bit)
- Python 3.10+ (for source installation) or standalone binary from `dist/MammouthDefroster9000`

### Quick Start (Source)
1. Clone the repository and install dependencies:
   ```cmd
   git clone https://github.com/mammouth-ai/mcpserv.git
   cd mcpserv
   pip install -r requirements.txt
   ```
2. Start the graphical cockpit:
   ```cmd
   python gui.py
   ```
3. Or start the headless server:
   ```cmd
   python server.py
   ```

### Quick Start (Standalone Release)
Run `MammouthDefroster9000.exe` from the release package.

---

## ⚙️ Configuration (`config.json`)

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8000,
    "enforce_auth": true,
    "api_token": "dpapi:...",
    "allow_admin_shell": false,
    "enable_tls": false,
    "enforce_workspace_sandbox": true,
    "workspace_root": "./workspace"
  }
}
```

---

## 🧪 Testing

Run the full automated security regression test suite:
```cmd
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📄 License & Security

Refer to [`SECURITY.md`](SECURITY.md) for the complete security specification and [`CHANGELOG.md`](CHANGELOG.md) for version history.
