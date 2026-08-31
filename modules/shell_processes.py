import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

LOGS_DIR = Path(__file__).parent.parent / "process_logs"
LOGS_DIR.mkdir(exist_ok=True)

# In-memory registry of background processes
BACKGROUND_PROCESSES: Dict[str, Dict[str, Any]] = {}
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
    r'\b(Start-Process|saps)\b',
    r'\b(DownloadString|DownloadFile|DownloadData)\b',
    r'\b(System\.Net\.WebClient|WebClient|HttpClient)\b',
    r'\b(Net\.Sockets|System\.Net\.Sockets|TcpClient|Socket|UdpClient)\b',
    r'\b(Start-BitsTransfer|bitsadmin|certutil)\b',
    r'\b(Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b',
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
]


SENSITIVE_PATH_DENYLIST_PATTERNS = [
    r'(\.ssh|\.aws|\.azure|\.kube|\.gnupg)\b',
    r'\b(id_rsa|id_ed25519|id_dsa|id_ecdsa)\b',
    r'\.(pem|key|pfx|p12|kdbx)\b',
    r'\b(SAM|NTDS\.dit)\b',
    r'\\system32\\config\\(system|security|sam)',
    r'\b(config\.json|hosts\.json)\b',
]


READONLY_FILE_COMMANDS = {
    "get-content", "gc", "cat", "type",
    "get-item", "gi",
    "get-childitem", "gci", "dir", "ls",
    "get-acl"
}


def _get_workspace_root_resolved() -> str:
    """Retrieve normalized, casefolded absolute workspace root path."""
    try:
        from config import load_config
        cfg = load_config()
        ws = cfg.get("server", {}).get("workspace_root", "./workspace")
    except Exception:
        ws = "./workspace"
    return os.path.realpath(os.path.abspath(ws)).casefold()


def _check_readonly_path_guard(raw_cmd: str) -> None:
    """R7-N1 & R7-N2: Enforce path extraction, resolution against workspace sandbox, and root-recurse blocking."""
    # 1. Regex check on raw command for sensitive credential/configuration names
    for pat in SENSITIVE_PATH_DENYLIST_PATTERNS:
        if re.search(pat, raw_cmd, re.IGNORECASE):
            raise PermissionError(f"Path Guard: Access to sensitive credential store or configuration file matching '{pat}' is blocked in Read-Only mode.")

    # 2. R7-N2: Root-Recurse check with lookahead (blocking drive/system root recursive scans)
    if (re.search(r'\b(get-childitem|gci|dir|ls)\b.*-[rR](ecurse)?\s+[a-zA-Z]:[\\/](?=[\s"\'\\/a-zA-Z0-9_-]|$)', raw_cmd, re.IGNORECASE) or
        re.search(r'\b(get-childitem|gci|dir|ls)\b\s+[a-zA-Z]:[\\/][^\s|;]*\s+-[rR](ecurse)?(?=[\s"\']|$)', raw_cmd, re.IGNORECASE) or
        re.search(r'\b(get-childitem|gci|dir|ls)\b.*-[rR](ecurse)?\s+[cC]:\\?(windows)?(?=[\s"\'\\]|$)', raw_cmd, re.IGNORECASE) or
        re.search(r'\bdir\s+[a-zA-Z]:[\\/]\s*/[sS](?=[\s"\']|$)', raw_cmd, re.IGNORECASE) or
        re.search(r'\bdir\s+/[sS]\s+[a-zA-Z]:[\\/](?=[\s"\']|$)', raw_cmd, re.IGNORECASE)):
        raise PermissionError("Path Guard: Recursive directory traversal of root or non-workspace drive path is blocked in Read-Only mode.")

    # 3. R7-N1: Path Argument Extraction & Resolution against workspace
    workspace_root = _get_workspace_root_resolved()
    segments = re.split(r'\||;', raw_cmd)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        tokens = re.findall(r'--?[a-zA-Z0-9_-]+|"[^"]*"|\'[^\']*\'|[^\s]+', seg)
        if not tokens:
            continue
        first_token = tokens[0].lower().strip("&.").rstrip(".exe")
        if first_token in READONLY_FILE_COMMANDS:
            for tok in tokens[1:]:
                # Ignore parameter switches (e.g. -Path, -Filter, -Recurse, /s, /a)
                if tok.startswith("-") or tok.startswith("/"):
                    continue
                arg_val = tok.strip('\'"')
                if not arg_val:
                    continue
                # Resolve relative or absolute path
                resolved = os.path.realpath(os.path.abspath(arg_val)).casefold()

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
                        f"Access is blocked in Read-Only mode."
                    )


READONLY_CMDLET_PREFIXES = (
    "get-", "test-", "measure-", "select-", "where-", "out-", "write-", "format-", "find-"
)

READONLY_BINARIES = {
    "whoami", "ipconfig", "tasklist", "netstat", "hostname",
    "systeminfo", "dir", "echo", "type", "findstr", "ver",
    "ping", "tracert", "nslookup", "route", "arp",
    "cat", "gc", "gci", "gi", "ls"
}


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


def _is_admin_shell_allowed() -> bool:
    try:
        from config import load_config
        cfg = load_config()
        return bool(cfg.get("server", {}).get("allow_admin_shell", False))
    except Exception:
        return False


def _validate_shell_command(command: str, allow_admin: Optional[bool] = None) -> str:
    """Validate shell command against dangerous patterns and read-only allowlist."""
    clean = str(command).strip()
    if not clean:
        raise ValueError("Command cannot be empty.")

    s_deobf, s_no_quotes = _deobfuscate_powershell(clean)

    # 1. Always run defense-in-depth blacklist
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if (re.search(pattern, clean, re.IGNORECASE) or
            re.search(pattern, s_deobf, re.IGNORECASE) or
            re.search(pattern, s_no_quotes, re.IGNORECASE)):
            raise PermissionError(f"Security Shield: Dangerous command pattern detected and blocked: '{pattern}'")

    # 2. Check Read-Only Allowlist if admin shell is not enabled
    admin_enabled = allow_admin if allow_admin is not None else _is_admin_shell_allowed()
    if not admin_enabled:
        pipeline_segments = re.split(r'\||;', s_no_quotes)
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
        _check_readonly_path_guard(clean)

    return clean


def command_run(command: str, cwd: Optional[str] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Execute a local PowerShell command synchronously and return stdout and stderr.
    
    Args:
        command: PowerShell command to run.
        cwd: Working directory (optional).
        timeout_seconds: Timeout in seconds (default 60).
    """
    try:
        clean_cmd = _validate_shell_command(command)
    except Exception as ex:
        return {"exit_code": -1, "stdout": "", "stderr": f"Security Error: {ex}"}

    work_dir = cwd if cwd and os.path.exists(cwd) else os.getcwd()
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", clean_cmd],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds} seconds."
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }


def process_start_background(command: str, cwd: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """Start a long-running process in the background (e.g. dev server, script).
    
    Args:
        command: The command line to execute.
        cwd: Working directory (optional).
        name: Short descriptive name for this background task.
    """
    active_count = sum(1 for info in BACKGROUND_PROCESSES.values() if info["proc"].poll() is None)
    if active_count >= MAX_BACKGROUND_PROCESSES:
        return {"error": f"Resource Limit Exceeded: Maximum active background tasks ({MAX_BACKGROUND_PROCESSES}) reached. Stop finished tasks before launching more."}

    try:
        clean_cmd = _validate_shell_command(command)
    except Exception as ex:
        return {"error": f"Security Error: {ex}"}

    task_id = str(uuid.uuid4())[:8]
    task_name = name or f"task-{task_id}"
    log_file = LOGS_DIR / f"{task_id}.log"
    work_dir = cwd if cwd and os.path.exists(cwd) else os.getcwd()
    
    try:
        log_handle = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", clean_cmd],
            cwd=work_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        BACKGROUND_PROCESSES[task_id] = {
            "id": task_id,
            "name": task_name,
            "command": clean_cmd,
            "pid": proc.pid,
            "proc": proc,
            "log_file": str(log_file),
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return {
            "task_id": task_id,
            "name": task_name,
            "pid": proc.pid,
            "status": "running",
            "log_file": str(log_file)
        }
    except Exception as e:
        return {"error": f"Failed to start background process: {e}"}


def process_list_background() -> List[Dict[str, Any]]:
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


def process_get_output(task_id: str, tail_lines: int = 100) -> Dict[str, Any]:
    """Retrieve output log content from a background task."""
    if task_id not in BACKGROUND_PROCESSES:
        return {"error": f"Task '{task_id}' not found."}
    
    log_path = Path(BACKGROUND_PROCESSES[task_id]["log_file"])
    if not log_path.exists():
        return {"output": "", "status": "no log file found"}
    
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
        proc = BACKGROUND_PROCESSES[task_id]["proc"]
        poll = proc.poll()
        return {
            "task_id": task_id,
            "status": "running" if poll is None else f"finished (code {poll})",
            "lines": "".join(tail)
        }
    except Exception as e:
        return {"error": f"Failed to read process log: {e}"}


def process_kill_background(task_id: str) -> Dict[str, Any]:
    """Terminate a running background process."""
    if task_id not in BACKGROUND_PROCESSES:
        return {"error": f"Task '{task_id}' not found."}
    
    proc = BACKGROUND_PROCESSES[task_id]["proc"]
    try:
        proc.terminate()
        time.sleep(0.5)
        if proc.poll() is None:
            proc.kill()
        return {"task_id": task_id, "status": "terminated"}
    except Exception as e:
        return {"error": f"Failed to kill process: {e}"}
