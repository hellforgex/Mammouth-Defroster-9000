import os
import re
import subprocess
import threading
import time
import uuid
import sys
from collections import deque
from pathlib import Path
from typing import Any, Literal

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

LOGS_DIR = BASE_DIR / "process_logs"
LOGS_DIR.mkdir(exist_ok=True)

# In-memory registry of background processes
BACKGROUND_PROCESSES: dict[str, dict[str, Any]] = {}
MAX_BACKGROUND_PROCESSES = 10

# Prohibited destructive / high-risk commands for shell safety
BLOCKED_COMMAND_PATTERNS = [
    r'-(enc|encodedcommand|e|ec|eco|encoded)\b',
    r'\b(invoke-expression|iex)\b',
    r'\bAdd-Type\b',
    r'-(MemberDefinition|TypeDefinition)\b',
    r'\[ScriptBlock\]',
    r'\[System\.Management\.Automation',
    r'\[System\.Diagnostics\.Process\]',
    r'\b(Net\.Sockets|System\.Net\.Sockets|TcpClient|Socket|UdpClient)\b',
    r'\b(bitsadmin|certutil)\b',
    r'\brundll32(\.exe)?\b',
    r'\bcmd(\.exe)?\s+/[ck]\b',
    r'-\s*File\b',
    r'\bpowershell(\.exe)?\s+.*-(File|Command|c)\b',
    r'\bRemove-Item\b.*-(Recurse|r)\b',
    r'\b(del|erase|rd|rmdir)\s+/[fFqQsS]',
    r'\bformat\s+[a-zA-Z]:',
    r'\b(diskpart|format-volume)\b',
    r'\b(rd|rmdir)\s+/[sS]',
    r'\bSet-ExecutionPolicy\s+(Unrestricted|Bypass)',
    r'-(executionpolicy|ep)\s+(bypass|unrestricted)',
    r'\b(New-LocalUser|Add-LocalGroupMember)\b',
    r'\bnet\s+(user|localgroup)\b.*(/add|/delete)',
    r'\breg\s+(delete|add)\b',
    r'\bbcdedit\b',
    r'\bvssadmin\s+delete',
    r'\|\s*(powershell|pwsh|cmd|iex|invoke-expression)\b',
    r'(&|\.)\s*[\(\$]',
    r'\bwmic(\.exe)?\s+process\b',
    r'\bmshta(\.exe)?\b',
    r'\bregsvr32(\.exe)?\b',
    r'\bcscript(\.exe)?\b',
    r'\bwscript(\.exe)?\b',
    r'\bSet-MpPreference\b',
    r'-(DisableRealtimeMonitoring|DisableIOAVProtection)\b',
    r'\bsc(\.exe)?\s+(config|create|delete|start|stop)\b',
    r'\bwevtutil(\.exe)?\s+(cl|clear-log)\b',
    r'\bschtasks(\.exe)?\s+/(create|delete|change|run)\b',
    r'\b(Start-Process|saps)\b',
    r'\b(powershell|pwsh)(\.exe)?\s+.*-(File|Command|c)\b',
    r'\b(python|python3|py)(\.exe)?\s+.*-(c|m)\b',
    r'\bInvoke-Command\b.*-ScriptBlock\b',
]

# Network/HTTP download patterns: blocked by default (even with allow_admin_shell=true).
# Permitted only when BOTH server.allow_admin_shell=true AND server.allow_shell_downloads=true.
SHELL_DOWNLOAD_PATTERNS = [
    r'\b(DownloadString|DownloadFile|DownloadData)\b',
    r'\b(System\.Net\.WebClient|WebClient|HttpClient)\b',
    r'\bStart-BitsTransfer\b',
    r'\b(Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b',
    r'\b(curl|wget)(\.exe)?\b',
]


SENSITIVE_PATH_DENYLIST_PATTERNS = [
    r'(\.ssh|\.aws|\.azure|\.kube|\.gnupg)\b',
    r'\b(id_rsa|id_ed25519|id_dsa|id_ecdsa)\b',
    r'\.(pem|key|pfx|p12|kdbx)\b',
    r'\b(SAM|NTDS\.dit)\b',
    r'\\system32\\config\\(system|security|sam)',
    r'\b(config|conf.?g)\.json\b',
    r'\b(hosts|host.?)\.json\b',
    r'\b(credentials|credent.?als)\.json\b',
    r'\b(oauth|tasks|memory)\.db\b',
    r'\bgdrive_token\.json\b',
    r'(^|[\\/])\.env\b',
]


READONLY_FILE_COMMANDS = {
    "get-content", "gc", "cat", "type",
    "get-item", "gi",
    "get-childitem", "gci", "dir", "ls",
    "get-acl", "findstr",
    "select-string", "sls",
    "get-filehash",
    "get-authenticodesignature",
    "get-winevent",
    "get-itemproperty", "gp",
    "test-path"
}


def resolve_workspace_root() -> str:
    """Absolute workspace root. Relative config values are anchored to the application directory
    (BASE_DIR), never to the process cwd, so every module sandboxes against the same folder."""
    try:
        from config import load_config
        ws = load_config().get("server", {}).get("workspace_root") or "./workspace"
    except Exception:
        ws = "./workspace"
    ws = os.path.expandvars(os.path.expanduser(str(ws)))
    if not os.path.isabs(ws):
        ws = os.path.join(str(BASE_DIR), ws)
    return os.path.realpath(os.path.abspath(ws))


def _get_workspace_root_resolved() -> str:
    """Retrieve normalized, casefolded absolute workspace root path."""
    return resolve_workspace_root().casefold()


# Forces UTF-8 on Windows PowerShell 5.1 output pipes (default is the OEM codepage, e.g. cp850),
# so umlauts survive when we decode stdout/stderr as UTF-8.
POWERSHELL_UTF8_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $OutputEncoding=[System.Text.Encoding]::UTF8; "


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminate a process together with all of its children (Windows: taskkill /T)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.kill()
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_process_tree(args: list[str], cwd: str | None, timeout: float, encoding: str = "utf-8") -> tuple:
    """Run a command and capture output; on timeout the whole process tree is killed.

    subprocess.run() only kills the direct child on timeout, so a grandchild holding the
    inherited pipes (e.g. `ping -n 100000`) would keep the call blocked until it exits.
    Returns (stdout, stderr, returncode). Raises subprocess.TimeoutExpired on timeout.
    """
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding=encoding,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise
    return stdout, stderr, proc.returncode


def _check_readonly_path_guard(raw_cmd: str, cwd: str | None = None) -> None:
    """R7-N1 & R7-N2: Enforce path extraction, resolution against workspace sandbox, and root-recurse blocking."""
    # 1. Regex check on raw command for sensitive credential/configuration names
    for pat in SENSITIVE_PATH_DENYLIST_PATTERNS:
        if re.search(pat, raw_cmd, re.IGNORECASE):
            raise PermissionError(f"Path Guard: Access to sensitive credential store or configuration file matching '{pat}' is blocked in Read-Only mode.")

    # Normalize colon/equals parameter syntax: e.g. -Path:C:\... -> -Path C:\...
    norm_cmd = re.sub(r'-(Path|LiteralPath|FilePath|Filter)[:=]', r'-\1 ', raw_cmd, flags=re.IGNORECASE)

    # 2. R7-N2: Root-Recurse check with lookahead (blocking drive/system root recursive scans)
    recurse_patterns = [
        r"\b(get-childitem|gci|dir|ls)\b.*-[rR](ecurse)?\s+[a-zA-Z]:[\\/]",
        r"\b(get-childitem|gci|dir|ls)\b\s+[a-zA-Z]:[\\/][^\s|;]*\s+-[rR](ecurse)?",
        r"\b(get-childitem|gci|dir|ls)\b.*-[rR](ecurse)?\s+[cC]:\\?(windows)?",
        r"\b(get-childitem|gci|dir|ls)\b.*-[rR](ecurse)?.*[a-zA-Z]:[\\/]",
        r"\bdir\s+[a-zA-Z]:[\\/]\s*/[sS]",
        r"\bdir\s+/[sS]\s+[a-zA-Z]:[\\/]",
    ]
    if any(re.search(p, norm_cmd, re.IGNORECASE) for p in recurse_patterns):
        raise PermissionError("Path Guard: Recursive directory traversal of root or non-workspace drive path is blocked in Read-Only mode.")

    # 3. R7-N1: Path Argument Extraction & Resolution against workspace
    workspace_root = _get_workspace_root_resolved()
    segments = re.split(r'\||;|&|&&|\|\||[\r\n]+', norm_cmd)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        tokens = re.findall(r"""--?[a-zA-Z0-9_-]+|"[^"]*"|'[^']*'|[^\s]+""", seg)
        if not tokens:
            continue
        first_token = tokens[0].lower().strip("&.").removesuffix(".exe")
        if first_token in READONLY_FILE_COMMANDS:
            for tok in tokens[1:]:
                # UNC paths are strictly prohibited in read-only mode
                if tok.startswith("//") or tok.startswith("\\\\"):
                    raise PermissionError("Path Guard: UNC network paths ('//' or '\\\\') are blocked in Read-Only mode.")

                # Ignore parameter switches (e.g. -Path, -Filter, -Recurse)
                if tok.startswith("-"):
                    continue

                # Ignore short cmd switches (e.g. /s, /a, /q, /w), but do NOT ignore path tokens starting with /
                if tok.startswith("/"):
                    if re.match(r'^/[a-zA-Z0-9_-]{1,2}(?::.*)?$', tok) and "/" not in tok[1:]:
                        continue

                arg_val = tok.strip("'\"")
                if not arg_val:
                    continue
                # Strip leading colon if left over from colon parameter syntax
                if arg_val.startswith(":"):
                    arg_val = arg_val[1:]
                if not arg_val:
                    continue

                # Check for workspace alias prefix (workspace:/..., workspace:\..., @workspace/...)
                arg_lower = arg_val.lower()
                alias_prefix = None
                for pfx in ("workspace:/", "workspace:\\", "workspace:", "@workspace/", "@workspace\\", "@workspace"):
                    if arg_lower.startswith(pfx):
                        alias_prefix = pfx
                        break

                if alias_prefix:
                    rel_part = arg_val[len(alias_prefix):].lstrip("/\\")
                    candidate = os.path.join(workspace_root, rel_part)
                else:
                    # Resolve relative paths against the directory the command will actually run in
                    base_dir = cwd or str(BASE_DIR)
                    is_abs = os.path.isabs(arg_val) or (len(arg_val) >= 2 and arg_val[1] == ":") or arg_val.startswith(("/", "\\\\"))
                    candidate = arg_val if is_abs else os.path.join(base_dir, arg_val)

                resolved = os.path.realpath(os.path.abspath(candidate)).casefold()

                # Denylist check on resolved path
                for pat in SENSITIVE_PATH_DENYLIST_PATTERNS:
                    if re.search(pat, resolved, re.IGNORECASE):
                        raise PermissionError(f"Path Guard: Resolved path '{resolved}' matches sensitive credential denylist '{pat}'.")

                # Verify workspace boundary containment
                is_in_workspace = (
                    resolved == workspace_root or
                    resolved.startswith(workspace_root + os.sep) or
                    resolved.startswith(workspace_root + "/")
                )
                if not is_in_workspace:
                    raise PermissionError(
                        f"Path Guard: Path '{arg_val}' resolves to '{resolved}' which is outside the workspace sandbox '{workspace_root}'. "
                        f"Tip: Explore files inside workspace using 'directory_list', or use relative paths / 'workspace:/<path>'."
                    )


READONLY_CMDLET_PREFIXES = (
    "get-", "test-", "measure-", "select-", "where-", "format-", "find-", "write-"
)

READONLY_BINARIES = {
    "whoami", "ipconfig", "tasklist", "netstat", "hostname",
    "systeminfo", "dir", "echo", "type", "findstr", "ver",
    "ping", "tracert", "nslookup", "route", "arp",
    "cat", "gc", "gci", "gi", "ls",
    "qwinsta", "query"
}


def _unwrap_powershell_wrapper(cmd: str) -> str:
    """Unwrap outer powershell.exe -Command wrapper if invoked redundantly by LLM client."""
    m = re.match(
        r'^\s*powershell(?:\.exe)?\s+(?:-NoProfile\s+)?(?:-NonInteractive\s+)?(?:-ExecutionPolicy\s+\S+\s+)?-(?:Command|c)\s+(.+)$',
        cmd,
        re.IGNORECASE | re.DOTALL
    )
    if m:
        inner = m.group(1).strip()
        if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
            inner = inner[1:-1].strip()
        return inner
    return cmd


def _deobfuscate_powershell(cmd: str) -> tuple:
    """Normalize and de-obfuscate PowerShell command string."""
    # Remove backticks used for cmdlet escaping (e.g. I`e`x)
    s = cmd.replace("`", "")
    # Remove internal quotes within alphanumeric tokens (e.g. I"e"x -> Iex, 'Inv'+'oke' -> Invoke)
    s = re.sub(r'(?<=\w)[\'"](?=\w)', '', s)
    s = re.sub(r'[\'"]\s*\+\s*[\'"]', '', s)
    # Strip standalone quotes
    s_no_quotes = re.sub(r'[\'"]', '', s)
    return s, s_no_quotes


# Constructs that let a "read-only" first token run arbitrary nested commands, e.g.
#   Get-ChildItem | Where-Object { Stop-Process ... }     (script block)
#   Write-Output (Remove-Item x)  /  "$(Stop-Computer)"  (sub-expression)
#   Select-Object @{e={Set-Content ...}}                  (calculated property)
#   echo x > C:\file                                       (redirection writes to disk)
#   dir & calc                                             (cmd.exe command separator)
READONLY_FORBIDDEN_CONSTRUCTS = [
    (r'[{}]', "script blocks '{ }'"),
    (r'[()]', "sub-expressions '( )'"),
    (r'\$\(', "sub-expressions '$( )'"),
    (r'@\{', "hashtables / calculated properties '@{ }'"),
    (r'(?<![-\w])\d?>{1,2}', "output redirection '>'"),
    (r'<', "input redirection '<'"),
    (r'(?<!&)&(?!&)', "command separator '&'"),
    (r'`', "escape character '`'"),
    (r'%', "ForEach-Object alias / environment expansion '%'"),
]


def _is_admin_shell_allowed() -> bool:
    try:
        from config import load_config
        cfg = load_config()
        return bool(cfg.get("server", {}).get("allow_admin_shell", False))
    except Exception:
        return False


def _is_shell_downloads_allowed() -> bool:
    """Return True only when BOTH allow_admin_shell and allow_shell_downloads are enabled (fails closed)."""
    try:
        from config import load_config
        cfg = load_config()
        server_cfg = cfg.get("server", {})
        return bool(server_cfg.get("allow_admin_shell", False) and server_cfg.get("allow_shell_downloads", False))
    except Exception:
        return False


def _validate_shell_command(
    command: str,
    allow_admin: bool | None = None,
    cwd: str | None = None,
    allow_downloads: bool | None = None,
) -> str:
    """Validate shell command against dangerous patterns, download policy, and read-only allowlist."""
    clean = str(command).strip()
    clean = _unwrap_powershell_wrapper(clean)
    if not clean:
        raise ValueError("Command cannot be empty.")

    s_deobf, s_no_quotes = _deobfuscate_powershell(clean)

    # 1. Always run defense-in-depth blacklist (stagers, obfuscation, destructive commands)
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if (re.search(pattern, clean, re.IGNORECASE) or
            re.search(pattern, s_deobf, re.IGNORECASE) or
            re.search(pattern, s_no_quotes, re.IGNORECASE)):
            raise PermissionError(f"Security Shield: Dangerous command pattern detected and blocked: '{pattern}'")

    # 1b. Network / HTTP download patterns (opt-in only when BOTH admin shell and allow_shell_downloads are enabled)
    admin_enabled = allow_admin if allow_admin is not None else _is_admin_shell_allowed()
    downloads_enabled = admin_enabled and (
        allow_downloads if allow_downloads is not None else _is_shell_downloads_allowed()
    )
    if not downloads_enabled:
        for pattern in SHELL_DOWNLOAD_PATTERNS:
            if (re.search(pattern, clean, re.IGNORECASE) or
                re.search(pattern, s_deobf, re.IGNORECASE) or
                re.search(pattern, s_no_quotes, re.IGNORECASE)):
                raise PermissionError(
                    f"Security Shield: Network/download command pattern detected and blocked: '{pattern}'. "
                    "Enable 'server.allow_shell_downloads=true' (with elevated shell permissions) to permit Invoke-RestMethod, Invoke-WebRequest, curl, and wget."
                )

    # 2. Check Read-Only Allowlist if admin shell is not enabled
    if not admin_enabled:
        # Quoted literals cannot execute anything: drop single-quoted strings and double-quoted
        # strings without '$' (PowerShell only expands $ inside double quotes) before scanning.
        literal_free = re.sub(r"'[^']*'", "''", clean)
        literal_free = re.sub(r'"[^"$`]*"', '""', literal_free)
        for construct_pattern, construct_name in READONLY_FORBIDDEN_CONSTRUCTS:
            if re.search(construct_pattern, literal_free):
                raise PermissionError(
                    f"Read-Only Shell: {construct_name} are not allowed in Read-Only mode because they can execute nested commands. "
                    f"Enable 'server.allow_admin_shell=true' in configuration for full PowerShell syntax."
                )

        # Block PowerShell PSDrives, environment variable expansion, registry hives, and home directory expansion
        psdrive_guards = [
            (r'\b(env:|hkcu:|hklm:|cert:|variable:|wsman:)', "PowerShell PSDrives (env:, registry, cert:, variable:)"),
            (r'\$env:\w+', "Environment variable expansion ($env:)"),
            (r'\bGet-Clipboard\b', "Clipboard reading cmdlet (Get-Clipboard)"),
            (r"""(^|[\s"'\\/])~([\\/\s"'$]|$)""", "Home directory expansion (~)"),
        ]
        for pat, desc in psdrive_guards:
            if re.search(pat, clean, re.IGNORECASE) or re.search(pat, s_no_quotes, re.IGNORECASE):
                raise PermissionError(f"Read-Only Shell: Access to {desc} is blocked in Read-Only mode to prevent host enumeration and credential exposure.")
        pipeline_segments = re.split(r'\||;|&&|\|\||&|[\r\n]+', s_no_quotes)
        for seg in pipeline_segments:
            seg_tokens = seg.strip().split()
            if not seg_tokens:
                continue
            first_token = seg_tokens[0].lower().strip("&.")
            if first_token == "reg" or first_token == "reg.exe":
                subcmd = seg_tokens[1].lower() if len(seg_tokens) > 1 else ""
                if subcmd != "query":
                    raise PermissionError("Admin shell required: 'reg' command is only allowed with 'query' in Read-Only mode.")
                continue

            if first_token in ("route", "route.exe"):
                # Only 'route print' is permitted in Read-Only mode
                has_modifying = any(tok.lower() in ("add", "delete", "change") for tok in seg_tokens[1:])
                if has_modifying:
                    raise PermissionError("Admin shell required: 'route' command with state-modifying arguments (add, delete, change) is blocked in Read-Only mode.")

            if first_token in ("ipconfig", "ipconfig.exe"):
                # Block release, renew, and flushdns in Read-Only mode
                for tok in seg_tokens[1:]:
                    low = tok.lower()
                    if low.startswith(("/release", "/renew", "/flushdns", "-release", "-renew", "-flushdns")):
                        raise PermissionError(f"Admin shell required: 'ipconfig' with network-reset switches ({tok}) is blocked in Read-Only mode.")

            if first_token in ("out-file", "tee-object", "tee"):
                raise PermissionError(f"Admin shell required: '{first_token}' modifies disk and is blocked in Read-Only mode.")

            is_allowed_prefix = any(first_token.startswith(pref) for pref in READONLY_CMDLET_PREFIXES)
            is_allowed_binary = (
                first_token in READONLY_BINARIES or
                (first_token.endswith(".exe") and first_token[:-4] in READONLY_BINARIES)
            )

            if not (is_allowed_prefix or is_allowed_binary):
                raise PermissionError(
                    f"Read-Only Shell: Command '{first_token}' is not in the read-only allowlist. "
                    f"Enable 'server.allow_admin_shell=true' in configuration to execute administrative or modifying commands."
                )

        # R7-N1 / R7-N2: Path Guard for Read-Only commands accessing files
        _check_readonly_path_guard(clean, cwd=cwd)

    return clean


def _resolve_work_dir(cwd: str | None, working_directory: str | None) -> str:
    work_dir = cwd if cwd and os.path.exists(cwd) else working_directory
    if not work_dir or not os.path.exists(work_dir):
        work_dir = "C:\\" if os.path.exists("C:\\") else os.getcwd()
    return os.path.realpath(os.path.abspath(work_dir))


_BACKGROUND_LOCK = threading.Lock()
_FINISHED_RETENTION_SECONDS = 3600


def _prune_finished_background_processes() -> None:
    """Drop registry entries of processes that finished more than an hour ago (log files stay on disk)."""
    now = time.time()
    with _BACKGROUND_LOCK:
        for tid, info in list(BACKGROUND_PROCESSES.items()):
            if info["proc"].poll() is None:
                continue
            if not info.get("finished_at"):
                info["finished_at"] = now
            elif now - info["finished_at"] > _FINISHED_RETENTION_SECONDS:
                BACKGROUND_PROCESSES.pop(tid, None)


def powershell_exec(
    command: str,
    working_directory: str = "C:\\",
    cwd: str | None = None,
    timeout_seconds: int = 120,
    shell: Literal["powershell", "cmd"] = "powershell"
) -> dict[str, Any]:
    """Execute a PowerShell or CMD command on the Windows host and return stdout, stderr, and exit_code.

    Args:
        command: Command to execute.
        working_directory: Working directory path (defaults to C:\\ or current directory).
        cwd: Optional alias for working_directory.
        timeout_seconds: Execution timeout in seconds (default 120).
        shell: 'powershell' (default) or 'cmd'.
    """
    if str(shell or "powershell").strip().lower() == "cmd":
        return cmd_exec(command=command, working_directory=working_directory, cwd=cwd, timeout_seconds=timeout_seconds)
    t0 = time.perf_counter()
    work_dir = _resolve_work_dir(cwd, working_directory)
    try:
        clean_cmd = _validate_shell_command(command, cwd=work_dir)
    except Exception as ex:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        is_ro = "read-only" in str(ex).lower() or "admin" in str(ex).lower()
        err_code = "ERR_SECURITY_READONLY" if is_ro else "ERR_SECURITY_SHIELD"
        return {
            "status": "permission_denied",
            "error_code": err_code,
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Security Error: {ex}",
            "exit_code": -1,
            "error": str(ex)
        }

    try:
        stdout, stderr, returncode = run_process_tree(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_UTF8_PREFIX + clean_cmd],
            cwd=work_dir,
            timeout=timeout_seconds,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "success" if returncode == 0 else "error",
            "error_code": None if returncode == 0 else "ERR_COMMAND_FAILED",
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "timeout",
            "error_code": "ERR_TIMEOUT",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_seconds}s",
            "exit_code": -1,
            "error": f"Execution timed out after {timeout_seconds}s"
        }
    except Exception as e:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "error",
            "error_code": "ERR_PROCESS_ERROR",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "error": str(e)
        }


def cmd_exec(
    command: str,
    working_directory: str = "C:\\",
    cwd: str | None = None,
    timeout_seconds: int = 120
) -> dict[str, Any]:
    """Execute a Windows Command Prompt (CMD) command and return stdout, stderr, and exit_code.
    
    Args:
        command: Command prompt command to execute.
        working_directory: Working directory path (defaults to C:\\ or current directory).
        cwd: Optional alias for working_directory.
        timeout_seconds: Execution timeout in seconds (default 120).
    """
    t0 = time.perf_counter()
    work_dir = _resolve_work_dir(cwd, working_directory)
    try:
        clean_cmd = _validate_shell_command(command, cwd=work_dir)
    except Exception as ex:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        is_ro = "read-only" in str(ex).lower() or "admin" in str(ex).lower()
        err_code = "ERR_SECURITY_READONLY" if is_ro else "ERR_SECURITY_SHIELD"
        return {
            "status": "permission_denied",
            "error_code": err_code,
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Security Error: {ex}",
            "exit_code": -1,
            "error": str(ex)
        }

    try:
        # cmd.exe writes piped output in the OEM codepage (cp850 on German systems)
        stdout, stderr, returncode = run_process_tree(
            ["cmd.exe", "/d", "/c", clean_cmd],
            cwd=work_dir,
            timeout=timeout_seconds,
            encoding="oem" if os.name == "nt" else "utf-8",
        )
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "success" if returncode == 0 else "error",
            "error_code": None if returncode == 0 else "ERR_COMMAND_FAILED",
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "timeout",
            "error_code": "ERR_TIMEOUT",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_seconds}s",
            "exit_code": -1,
            "error": f"Execution timed out after {timeout_seconds}s"
        }
    except Exception as e:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "error",
            "error_code": "ERR_PROCESS_ERROR",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "error": str(e)
        }


def command_run(command: str, cwd: str | None = None, timeout_seconds: int = 60) -> dict[str, Any]:
    """Execute a local PowerShell command synchronously (backward-compatible alias for powershell_exec)."""
    return powershell_exec(command=command, working_directory=cwd or "C:\\", cwd=cwd, timeout_seconds=timeout_seconds)


def process_spawn(
    command: str,
    working_directory: str = "C:\\",
    cwd: str | None = None,
    name: str | None = None
) -> dict[str, Any]:
    """Spawn a detached background process on the Windows host and track it.
    
    Args:
        command: The command line to execute.
        working_directory: Working directory path (defaults to C:\\ or current directory).
        cwd: Optional alias for working_directory.
        name: Short descriptive name for this background task.
    """
    with _BACKGROUND_LOCK:
        active_count = sum(1 for info in BACKGROUND_PROCESSES.values() if info["proc"].poll() is None)
    if active_count >= MAX_BACKGROUND_PROCESSES:
        return {"error": f"Resource Limit Exceeded: Maximum active background tasks ({MAX_BACKGROUND_PROCESSES}) reached. Stop finished tasks before launching more."}

    work_dir = _resolve_work_dir(cwd, working_directory)
    try:
        clean_cmd = _validate_shell_command(command, cwd=work_dir)
    except Exception as ex:
        return {"error": f"Security Error: {ex}"}

    _prune_finished_background_processes()
    task_id = str(uuid.uuid4())[:8]
    task_name = name or f"task-{task_id}"
    log_file = LOGS_DIR / f"{task_id}.log"
    
    try:
        creation_flags = 0
        if os.name == 'nt':
            no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | no_window

        with open(log_file, "w", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_UTF8_PREFIX + clean_cmd],
                cwd=work_dir,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags
            )
        
        with _BACKGROUND_LOCK:
            BACKGROUND_PROCESSES[task_id] = {
                "id": task_id,
                "name": task_name,
                "command": clean_cmd,
                "pid": proc.pid,
                "proc": proc,
                "log_file": str(log_file),
                "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None
            }
        
        return {
            "status": "started",
            "pid": proc.pid,
            "task_id": task_id,
            "name": task_name,
            "log_file": str(log_file)
        }
    except Exception as e:
        return {"error": f"Failed to spawn background process: {e}"}


def process_start_background(command: str, cwd: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Start a long-running process in the background (backward-compatible alias for process_spawn)."""
    res = process_spawn(command=command, working_directory=cwd or "C:\\", cwd=cwd, name=name)
    if "status" in res and res["status"] == "started":
        res["status"] = "running"
    return res


def process_list_background() -> list[dict[str, Any]]:
    """List all running and finished background processes managed by the MCP server."""
    result = []
    for tid, info in list(BACKGROUND_PROCESSES.items()):
        proc = info["proc"]
        poll = proc.poll()
        status = "running" if poll is None else f"finished (code {poll})"
        result.append({
            "task_id": tid,
            "name": info["name"],
            "command": info["command"],
            "pid": info["pid"],
            "status": status,
            "start_time": info["start_time"],
            "log_file": info["log_file"]
        })
    return result


def process_get_output(task_id: str, tail_lines: int = 100) -> dict[str, Any]:
    """Retrieve output log content from a background task."""
    if task_id not in BACKGROUND_PROCESSES:
        return {"error": f"Task '{task_id}' not found."}
    
    log_path = Path(BACKGROUND_PROCESSES[task_id]["log_file"])
    if not log_path.exists():
        return {"output": "", "status": "no log file found"}
    
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=max(1, int(tail_lines)))
        proc = BACKGROUND_PROCESSES[task_id]["proc"]
        poll = proc.poll()
        return {
            "task_id": task_id,
            "status": "running" if poll is None else f"finished (code {poll})",
            "lines": "".join(tail)
        }
    except Exception as e:
        return {"error": f"Failed to read process log: {e}"}


def process_kill_background(task_id: str) -> dict[str, Any]:
    """Terminate a running background process."""
    if task_id not in BACKGROUND_PROCESSES:
        return {"status": "error", "error_code": "ERR_TASK_NOT_FOUND", "error": f"Task '{task_id}' not found."}
    
    proc = BACKGROUND_PROCESSES[task_id]["proc"]
    try:
        # Kill the whole tree: terminating only powershell.exe would orphan its children
        _kill_process_tree(proc)
        BACKGROUND_PROCESSES[task_id]["finished_at"] = time.time()
        return {"task_id": task_id, "status": "terminated", "error_code": None}
    except Exception as e:
        return {"status": "error", "error_code": "ERR_PROCESS_KILL_FAILED", "error": f"Failed to kill process: {e}"}


def process_cancel(task_id: str) -> dict[str, Any]:
    """Cancel and terminate a running background process with standardized status."""
    res = process_kill_background(task_id)
    if res.get("status") == "terminated":
        res["status"] = "cancelled"
    return res


def process_tail_output(task_id: str, line_offset: int = 0, max_lines: int = 200) -> dict[str, Any]:
    """Retrieve output log content from a background task with line offset and pagination.
    
    Args:
        task_id: ID of the background task.
        line_offset: 0-based line index to start reading from.
        max_lines: Maximum number of lines to return (default 200).
    """
    if task_id not in BACKGROUND_PROCESSES:
        return {"status": "error", "error_code": "ERR_TASK_NOT_FOUND", "error": f"Task '{task_id}' not found."}

    info = BACKGROUND_PROCESSES[task_id]
    log_path = Path(info["log_file"])
    if not log_path.exists():
        return {
            "status": "success",
            "task_id": task_id,
            "lines": [],
            "total_lines": 0,
            "next_offset": 0,
            "is_running": info["proc"].poll() is None
        }

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        
        total = len(all_lines)
        start_idx = max(0, int(line_offset))
        end_idx = min(total, start_idx + max(1, int(max_lines)))
        selected = all_lines[start_idx:end_idx]
        poll = info["proc"].poll()
        return {
            "status": "success",
            "task_id": task_id,
            "lines": selected,
            "total_lines": total,
            "next_offset": end_idx,
            "is_running": poll is None,
            "exit_code": poll
        }
    except Exception as e:
        return {"status": "error", "error_code": "ERR_LOG_READ_FAILED", "error": f"Failed to read process log: {e}"}


def desktop_open(target: str, arguments: str | None = None) -> dict[str, Any]:
    """Open a URL in the default browser, or launch a file/application on the active Windows desktop.
    
    Uses Windows ShellExecute (equivalent to double-clicking in File Explorer or running via Start Menu).
    This reliably opens web links (e.g. YouTube, websites) in the user's default browser (such as Firefox)
    or launches desktop GUI applications directly in the user's interactive desktop session.
    
    Args:
        target: Web URL (e.g. 'https://www.youtube.com/results?search_query=chill+psydub') or path to an app/document.
        arguments: Optional command-line arguments to pass to the application.
    """
    clean_target = str(target).strip()
    if not clean_target:
        return {"status": "error", "error": "Target cannot be empty."}

    # Block potentially dangerous URI schemes
    lower_target = clean_target.lower()
    dangerous_schemes = ("javascript:", "data:", "vbscript:", "ms-msdt:", "search-ms:")
    if any(lower_target.startswith(ds) for ds in dangerous_schemes):
        return {"status": "error", "error": f"Blocked potentially hazardous target scheme: '{clean_target}'"}

    # B-08: Check admin mode permissions
    admin_allowed = _is_admin_shell_allowed()
    if not admin_allowed:
        clean_args = str(arguments).strip() if arguments else ""
        if clean_args:
            raise PermissionError("Admin shell required: Passing command-line arguments to desktop_open is blocked in Read-Only mode. Enable 'server.allow_admin_shell=true' in configuration.")

        if lower_target.startswith(("http://", "https://", "mailto:")):
            # Safe browser web link, permitted in Read-Only mode
            pass
        else:
            # Executables and script files are strictly blocked in Read-Only mode
            blocked_exts = (
                ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
                ".wsf", ".wsh", ".msc", ".cpl", ".com", ".scr", ".pif", ".hta",
                ".reg", ".lnk", ".bin", ".jar", ".py"
            )
            if any(lower_target.endswith(ext) for ext in blocked_exts):
                raise PermissionError(
                    f"Admin shell required: Launching executables or scripts ('{clean_target}') via desktop_open is blocked in Read-Only mode. "
                    f"Enable 'server.allow_admin_shell=true' in configuration."
                )

            # For non-executable documents, enforce workspace boundary containment
            ws_root = _get_workspace_root_resolved()
            cand = clean_target if os.path.isabs(clean_target) else os.path.join(str(BASE_DIR), clean_target)
            res_path = os.path.realpath(os.path.abspath(cand)).casefold()
            is_in_ws = res_path == ws_root or res_path.startswith(ws_root + os.sep) or res_path.startswith(ws_root + "/")
            if not is_in_ws:
                raise PermissionError(
                    f"Admin shell required: Opening file '{clean_target}' outside the workspace sandbox is blocked in Read-Only mode."
                )

    try:
        clean_args = str(arguments).strip() if arguments else ""
        if os.name == "nt":
            if clean_args:
                os.startfile(clean_target, "open", clean_args)
            else:
                os.startfile(clean_target)
            return {
                "status": "success",
                "message": f"Successfully launched '{clean_target}' on the interactive desktop.",
                "target": clean_target,
                "arguments": clean_args
            }
        else:
            import shutil
            opener = "xdg-open" if shutil.which("xdg-open") else "open"
            cmd = [opener, clean_target]
            if clean_args:
                cmd.extend(clean_args.split())
            subprocess.Popen(cmd)
            return {"status": "success", "message": f"Launched '{clean_target}' via {opener}."}
    except Exception as e:
        return {"status": "error", "error": f"Failed to open '{clean_target}': {e}"}


def process_manage(
    action: Literal["start", "list", "output", "kill"] = "list",
    task_id: str = "",
    command: str = "",
    cwd: str | None = None,
    name: str | None = None,
    line_offset: int = -1,
    max_lines: int = 100
) -> dict[str, Any] | list[dict[str, Any]]:
    """Start, list, read logs, or terminate managed background processes.

    Args:
        action: 'start', 'list', 'output', or 'kill'.
        task_id: Background task ID (required for 'output' and 'kill').
        command: Command line to run in background (required for 'start').
        cwd: Working directory for 'start'.
        name: Optional label for 'start'.
        line_offset: 0-based start line for paginated logs, or -1 (default) to read the last max_lines.
        max_lines: Maximum output lines to return (default 100).
    """
    act = str(action or "list").strip().lower()
    if act == "start":
        if not command or not str(command).strip():
            return {"status": "error", "error": "Parameter 'command' is required for action='start'."}
        return process_start_background(command=command, cwd=cwd, name=name)
    if act == "list":
        return process_list_background()
    if act == "output":
        if not task_id:
            return {"status": "error", "error": "Parameter 'task_id' is required for action='output'."}
        if int(line_offset) >= 0:
            return process_tail_output(task_id=task_id, line_offset=int(line_offset), max_lines=int(max_lines))
        return process_get_output(task_id=task_id, tail_lines=int(max_lines))
    if act == "kill":
        if not task_id:
            return {"status": "error", "error": "Parameter 'task_id' is required for action='kill'."}
        return process_cancel(task_id=task_id)
    return {"status": "error", "error": f"Unknown process_manage action '{action}'. Valid: 'start', 'list', 'output', 'kill'."}


def powershell_exec_clean(
    command: str,
    cwd: str = ".",
    shell: Literal["powershell", "cmd"] = "powershell",
    timeout_seconds: int = 120
) -> dict[str, Any]:
    """Execute a PowerShell or CMD command on Windows and return stdout, stderr, and exit_code.

    Args:
        command: Command to execute.
        cwd: Working directory (relative paths resolve against workspace root; default '.').
        shell: 'powershell' (default) or 'cmd'.
        timeout_seconds: Execution timeout in seconds (default 120).
    """
    clean_cwd = str(cwd or ".").strip().strip("'\"").strip()
    ws_root = resolve_workspace_root()
    if not clean_cwd or clean_cwd == ".":
        resolved_cwd = ws_root
    else:
        is_abs = os.path.isabs(clean_cwd) or (len(clean_cwd) >= 2 and clean_cwd[1] == ":")
        resolved_cwd = clean_cwd if is_abs else os.path.join(ws_root, clean_cwd.lstrip("/\\"))
    return powershell_exec(
        command=command,
        working_directory=resolved_cwd,
        cwd=resolved_cwd,
        timeout_seconds=timeout_seconds,
        shell=shell,
    )

