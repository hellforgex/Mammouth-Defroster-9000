# Changelog

All notable changes to **Mammouth Defroster 9000** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.1] - 2026-09-01

### 🚀 Packaging, GUI Stability & Standalone Binary Fixes
- **Inlined Self-Signed TLS Generation (`gui.py`):** Inlined TLS certificate generation directly into GUI startup to guarantee zero-dependency server launches across all execution environments.
- **PyInstaller Asset Collection (`build.bat`):** Upgraded build scripts with full `--collect-all` for `customtkinter`, `fastmcp`, `uvicorn`, and `PIL` ensuring all UI themes, fonts, and runtime dependencies are fully bundled in standalone `.exe` packages.
- **Synchronized Workspaces:** Unified multi-directory builds and eliminated legacy script paths.

---

## [0.2.0] - 2026-08-31

### 🛡️ Security Hardening & Audit Remediation (Rounds 5–7 Verification)

### Fixed & Verified
- **Shell Path Resolution & Root-Recurse Sandbox Guard (R7-N1 & R7-N2 in `modules/shell_processes.py`):**
  - Path arguments in read-only commands (`Get-Content`, `gc`, `cat`, `type`, `Get-Item`, `gi`, `Get-ChildItem`, `gci`, `dir`, `ls`, `Get-Acl`) are fully extracted and resolved against the workspace root before evaluating containment and denylists.
  - Non-workspace paths (`..\..\Windows\win.ini`, `..\config.json`, `C:\Windows\win.ini`) unconditionally fail closed with `PermissionError`.
  - Upgraded root-recurse detection regex with boundary lookahead (`(?=[\s"'\\]|$)`) blocking drive roots (`Get-ChildItem C:\ -Recurse`, `Get-ChildItem D:\data -Recurse`), while permitting legitimate workspace traversal (`Get-ChildItem .\workspace -Recurse`).
- **Unreal Engine Strict Import Allowlist & HMAC Handshake (`modules/unreal_engine.py`, `modules/remote_execution.py`):**
  - Enforced AST `ALLOWED_MODULES = {'unreal', 'math', 'string', 'enum', 'dataclasses', 'typing', 'collections', 'functools', 'itertools', 'json', 're', 'datetime', 'hashlib', 'random', 'uuid', 'decimal', 'copy', 'statistics', 'time'}`.
  - Blocked dunder reflection (`__mro__`, `__members__`, `__class__`, `__subclasses__`, `__globals__`).
  - Instantiated `RemoteExecution` with server `api_token` for cryptographic HMAC-SHA256 challenge-response verification with separated broadcast nonces and authenticated connection responses.
- **PowerShell Execution & Read-Only Default (`modules/shell_processes.py`):**
  - Default shell execution mode converted to **Read-Only Allowlist** (permitting only diagnostic verbs `Get-*`, `Test-*`, `Measure-*`, `Select-*`, `whoami`, `ipconfig`, `tasklist`, `netstat`, `hostname`, `reg query`).
  - Modifying commands require explicit `allow_admin_shell: true` with GUI confirmation dialog.
- **M-07 Desktop Vision User Consent Gate (`modules/screen_capture.py`):**
  - Added explicit user consent requirement (`require_consent: true`).
  - Unapproved screen capture calls return `{"status": "consent_required", ...}`.
  - Purged test bypass parameters from public tool signatures.
  - Added GUI interactive prompt and helper functions `screen_grant_consent("once"|"always")` and `screen_revoke_consent()`.
- **M-05 / R4-N3 DPAPI Token Storage & Proactive Migration (`config.py`):**
  - `api_token` in `config.json` is encrypted using Windows DPAPI (`dpapi:<base64>`).
  - Proactive encryption on load ensures plaintext tokens on disk are immediately converted to DPAPI format.
  - Removed unconditional token regeneration on load.
- **M-01 Transport-Level SSRF IP Pinning (`modules/web_tools.py`):**
  - Outbound HTTP requests resolve DNS upfront, validate IP against private/loopback/metadata subnets, and pin connection.
  - Redirects validated against the same rule.
  - `web_tools` disabled by default in configuration.
- **M-09 Local LAN TLS Support (`server.py`, `gui.py`):**
  - Added support for `ssl_certfile` / `ssl_keyfile` with automated self-signed certificate generation (`generate_self_signed_cert`).
  - Added security warning banners for unencrypted LAN exposure.
- **PuTTY `-pwfile` Temporary File Security (`modules/putty_ssh.py`):**
  - Replaced CLI `-pw` arguments with temporary `-pwfile` protected by Owner ACLs (`icacls`) via `getpass.getuser()` and deleted in `finally:` blocks.
- **Progressive Exponential Backoff per IP (`server.py`):**
  - 1–4 failures return 401; 5+ failures enforce progressive delay of $2^{(failures - 5)}$ seconds (capped at 60s).
  - Valid token immediately resets failure count.
  - Injected response security headers (`Cache-Control: no-store`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, etc.).

---

## [0.1.0] - 2026-08-25

### 🚀 Initial Public Release — Mammouth Defroster 9000 🦣❄️🔥

The sovereign Windows 11 FastMCP desktop cockpit and DevOps powerhouse engineered for Mammouth.ai.
