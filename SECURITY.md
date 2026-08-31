# 🛡️ Security Architecture & Vulnerability Prevention Standards

> **Mammouth Defroster 9000** — Sovereign FastMCP Desktop Cockpit  
> Security Architecture Specification, Hardening Standards & Threat Model (Round 6 Verified)

---

## 🔒 1. Authentication & API Protection (Fail-Closed)
* **Fail-Closed Auth Middleware:** When `enforce_auth: true`, any request without a matching valid Bearer token is immediately rejected (`401 Unauthorized`). If no token is configured on the server, requests are unconditionally blocked.
* **Progressive Exponential Backoff per IP:** The authentication layer tracks consecutive failed attempts per client IP. Failures 1–4 return standard `401 Unauthorized`. Starting at 5 consecutive failures, a progressive backoff delay of $2^{(failures - 5)}$ seconds (capped at 60s) is enforced, returning `429 TooManyRequests`. A valid Bearer token immediately resets the failure counter. Lockout memory is bounded to 1,000 active IP records with automated TTL expiry cleanup.
* **Timing Attack Mitigation:** All token comparisons **must** use `secrets.compare_digest(provided_token, expected_token)` (never plain `==`).
* **Tool-Level Authorization:** All MCP tools are gated with `@require_module("<module_name>")` to verify active module state before execution.
* **Strict CORS & Preflight:** CORS `allow_headers` lists explicitly allowed headers (`Authorization`, `Content-Type`, `Accept`, `X-Request-ID`, `Origin`, `User-Agent`). HTTP `OPTIONS` preflight requests bypass token authentication to ensure standard browser CORS handshakes succeed.
* **Response Security Headers:** All responses include `Cache-Control: no-store, no-cache, must-revalidate, private`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `X-XSS-Protection: 1; mode=block`.
* **Zero Production Body Dumping:** Middleware logs only method and path (`[MCP ACCESS] GET /sse`). Request and response JSON payload bodies are never printed to console or files to prevent leaking passwords, keys, and memory rows.

---

## 📁 2. File Operations & Path Sandboxing (Fail-Closed)
* **Fail-Closed Workspace Sandbox:** `_get_sandbox_config()` always defaults to `enforce_sandbox = True` if `config.json` is missing or corrupted.
* **Path Canonicalization:** Input paths are normalized to strip UNC namespaces (`\\?\`, `\\.\`, `\\?\UNC\`), resolve DOS 8.3 short names via `GetLongPathNameW`, and resolve symlinks/junctions via `os.path.realpath`. All boundary containment checks use casefolded path strings (`.casefold()`).
* **System & Credential Directory Write Guards:** Direct write operations into Windows operating system directories (`C:\Windows`, `C:\Program Files`, `C:\ProgramData`) and sensitive user credential directories (`.ssh`, `.aws`, `.azure`, `.kube`, `.gnupg`, `Startup`) are unconditionally prohibited.
* **Binary File Filtering:** Text search utilities (`file_search_text`) perform null-byte detection (`b'\x00' in chunk`) to skip binary files.
* **Null-Byte Protection:** All input paths reject null bytes (`\0`).

---

## 💻 3. Command Execution & Subprocesses (Read-Only Default & Path-Guarded)
* **Read-Only Allowlist Default:** By default (`allow_admin_shell: false`), only diagnostic commands and read-only cmdlets are permitted (`Get-*`, `Test-*`, `Measure-*`, `Select-*`, `Where-*`, `Out-*`, `Write-*`, `Format-*`, `whoami`, `ipconfig`, `tasklist`, `netstat`, `hostname`, `systeminfo`, `dir`, `echo`, `type`, `findstr`, `reg query`).
* **Read-Only Path Guard (R6-N1):** File-reading commands (`Get-Content`, `type`, `Get-Item`, `Get-ChildItem`, `Get-Acl`, `dir`, etc.) are inspected prior to execution. Access to credentials (`.ssh`, `.aws`, `.kube`, `.gnupg`, `id_rsa`, `*.pem`, `*.key`), local databases (`config.json`, `hosts.json`), system registry hives (`SAM`, `NTDS.dit`), and recursive root traversals (`Get-ChildItem C:\ -Recurse`, `dir C:\Windows /s`) raises `PermissionError`.
* **Admin-Plane Opt-In:** Modifying commands (`Set-*`, `New-*`, `Remove-*`, `Start-*`, `Stop-*`, `sc`, `wevtutil`, `schtasks`, `Set-MpPreference`) require explicit `allow_admin_shell: true` enabled via configuration or GUI confirmation dialog.
* **De-obfuscation & Anti-Bypass Guard:** All commands are normalized (stripping backticks, intra-word quote concatenation, and string addition) and checked against blocked destructive patterns.
* **Resource Limits:** Background processes are capped (`MAX_BACKGROUND_PROCESSES = 10`) to prevent fork-bomb resource exhaustion.
* **Parameterized Queries:** PowerShell diagnostics pass variables via script parameters (`param($log, $type, $num)`), never inline string interpolation.

---

## 🔑 4. Credential & Password Management
* **Hardware DPAPI Encryption:** Passwords in `hosts.json` and API tokens in `config.json` (`dpapi:<ciphertext>`) are encrypted using Windows DPAPI (`win32crypt.CryptProtectData`).
* **Zero Plaintext Fallback:** If DPAPI is unavailable, raise `RuntimeError`. Plaintext password fallback is strictly prohibited.
* **PuTTY `-pwfile` Temporary File Security:** PuTTY and PSCP tool executions never pass `-pw <password>` on the command line. Passwords are written to a temporary file passed via `-pwfile <path>`, protected with Owner-only Windows ACLs (`icacls`), and deleted immediately in `finally:` blocks.
* **Git & Release Protection:** `.gitignore` and `build.bat` unconditionally scrub `config.json` (`api_token: ""`), `hosts.json`, `*.db`, `*.log`, and `workspace/` from release packages.

---

## 🌐 5. Network & Public Exposure Safety
* **Opt-In Public Funnel:** `auto_tunnel` defaults to `false` in `config.json`. Public Internet exposure via Tailscale Funnel requires explicit user selection.
* **Transport-Level SSRF IP Pinning:** Outbound HTTP tools resolve hostnames once, strictly validate the IP against private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`) and cloud metadata endpoints (`169.254.169.254`), and pin the connection. Redirects are validated against the same rule.
* **Web Tools Disabled by Default:** `web_tools` is disabled by default in configuration.
* **Local LAN TLS Encryption:** Support for `ssl_certfile` / `ssl_keyfile` with automated self-signed certificate generation (`generate_self_signed_cert`) and GUI warning banners for unencrypted LAN exposure.

---

## 🎮 6. Unreal Engine Remote Bridge (Strict Import Allowlist & HMAC Handshake)
* **Strict Import Allowlist:** Replaced all module blacklists with a strict AST import allowlist:
  ```python
  ALLOWED_MODULES = {
      'unreal', 'math', 'string', 'enum', 'dataclasses', 'typing',
      'collections', 'functools', 'itertools', 'json',
      're', 'datetime', 'hashlib', 'random', 'uuid', 'decimal',
      'copy', 'statistics', 'time'
  }
  ```
  Any module import outside this allowlist (including `from` imports and relative imports) is unconditionally rejected by AST validation.
* **Dynamic Call & Dunder Blocks:** Direct calls to `open`, `exec`, `eval`, `compile`, `__import__`, `getattr` and access to `__class__`, `__bases__`, `__subclasses__`, `__globals__`, `__mro__`, `__members__` are blocked.
* **HMAC-SHA256 Challenge-Response Handshake:** UDP discovery and socket connections use cryptographic HMAC challenge-response verification with single-use nonces (30s TTL).
* **Loopback Socket Gate:** Socket listener enforces that connections originate strictly from loopback (`127.0.0.1`).
* **Console Command Filtering:** Semicolon-separated Unreal console commands are tokenized and validated against blocked administrative/crash commands (`quit`, `exit`, `crash`, `exec`, `open`, `travel`, `restart`, `debug`, `obj`, `python`, `py`).

---

## 👁️ 7. Desktop Vision & Consent Gate
* **Interactive Consent Gate (M-07):** Desktop screen capture requires explicit user consent (`require_consent: true` by default). Unapproved calls return `consent_required`.
* **Automated Retention Policy:** Saved screenshots auto-prune files older than 24 hours or exceeding 25 files (`max_keep=25`).
* **Rate-Limit Throttling:** `screen_capture` enforces a 0.5s minimum interval between captures to prevent abusive screen scraping.
* **Dimension Clamping:** Image capture widths are clamped to safe ranges (`320 <= max_width <= 7680`).
