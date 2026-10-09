import os
import re
import sys
import json
import base64
import shutil
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("mammouth_code")

# Standard install paths for Mammouth Code on Windows
DEFAULT_MAMMOUTH_INSTALL_DIR = Path.home() / ".mammouth" / "bin"
DEFAULT_MAMMOUTH_EXE = DEFAULT_MAMMOUTH_INSTALL_DIR / "mammouth.exe"
DEFAULT_OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
DEFAULT_OPENCODE_CONFIG_FILE = DEFAULT_OPENCODE_CONFIG_DIR / "opencode.json"

POWERSHELL_INSTALL_CMD = (
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
    "irm https://code.mammouth.ai/install.ps1 | iex"
)


def get_mammouth_executable() -> Optional[str]:
    """Find path to mammouth.exe binary on the host machine.
    
    Checks in order:
    1. Custom path in config.json
    2. %USERPROFILE%\\.mammouth\\bin\\mammouth.exe
    3. System PATH (shutil.which)
    """
    try:
        from config import load_config
        cfg = load_config()
        custom_path = cfg.get("mammouth_code", {}).get("binary_path", "")
        if custom_path and os.path.isfile(custom_path):
            return custom_path
    except Exception as ex:
        logger.debug(f"Failed to read custom mammouth_code path from config: {ex}")

    if DEFAULT_MAMMOUTH_EXE.is_file():
        return str(DEFAULT_MAMMOUTH_EXE)

    which_path = shutil.which("mammouth") or shutil.which("mammouth.exe")
    if which_path and os.path.isfile(which_path):
        return which_path

    # Check local app data WindowsApps fallback
    local_bin = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "mammouth" / "mammouth.exe"
    if local_bin.is_file():
        return str(local_bin)

    return None


DEFROSTER_TOKEN_ENV = "MAMMOUTH_DEFROSTER_TOKEN"


def _build_child_env(api_key: str) -> Dict[str, str]:
    """Environment for Mammouth Code child processes: API key + Defroster token (for {env:} refs)."""
    child_env = os.environ.copy()
    if api_key:
        child_env["MAMMOUTH_API_KEY"] = api_key
    try:
        from config import load_config
        token = load_config().get("server", {}).get("api_token", "")
        if token:
            child_env[DEFROSTER_TOKEN_ENV] = token
    except Exception:
        pass
    return child_env


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas (JSONC, as allowed by opencode) — string-aware."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _merge_opencode_mcp_entry(config_file: Path, entry: Dict[str, Any]) -> None:
    """Merge the Defroster MCP entry into an opencode config without ever losing the user's settings.

    Unparseable files are left untouched (raises instead of overwriting with an almost empty file),
    a .bak copy is kept, and the write is atomic.
    """
    config_data: Dict[str, Any] = {}
    original_text = None
    if config_file.is_file():
        original_text = config_file.read_text(encoding="utf-8-sig")
        if original_text.strip():
            try:
                config_data = json.loads(original_text)
            except json.JSONDecodeError:
                try:
                    config_data = json.loads(_strip_jsonc(original_text))
                except json.JSONDecodeError as ex:
                    raise ValueError(f"cannot parse existing file, left unchanged ({ex})")
        if not isinstance(config_data, dict):
            raise ValueError("existing file is not a JSON object, left unchanged")

    config_data.setdefault("$schema", "https://opencode.ai/config.json")
    if not isinstance(config_data.get("mcp"), dict):
        config_data["mcp"] = {}
    config_data["mcp"]["mammouth-defroster-9000"] = entry

    if original_text is not None:
        try:
            config_file.with_name(config_file.name + ".bak").write_text(original_text, encoding="utf-8")
        except Exception as ex:
            logger.debug(f"Could not write backup of {config_file}: {ex}")
    tmp_file = config_file.with_name(config_file.name + ".tmp")
    tmp_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    os.replace(tmp_file, config_file)


def get_configured_api_key() -> str:
    """Retrieve Mammouth API Key from config or environment."""
    api_key = os.environ.get("MAMMOUTH_API_KEY", "")
    if api_key:
        return api_key

    try:
        from config import load_config
        cfg = load_config()
        api_key = cfg.get("mammouth_code", {}).get("api_key", "")
    except Exception as ex:
        logger.debug(f"Could not load api_key from config: {ex}")

    return api_key


def get_mammouth_code_status() -> Dict[str, Any]:
    """Inspect and return current installation, version, and bridge status of Mammouth Code."""
    exe = get_mammouth_executable()
    installed = exe is not None and os.path.isfile(exe)
    version = ""
    active_processes = 0

    if installed and exe:
        try:
            # Query version (mammouth --version)
            res = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            version = res.stdout.strip() or res.stderr.strip()
        except Exception as ex:
            logger.debug(f"Failed to query mammouth version: {ex}")
            version = "Installed (Version check timed out)"

        # Count running processes
        try:
            cmd = 'Get-Process mammouth -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count'
            ps_res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            count_str = ps_res.stdout.strip()
            if count_str.isdigit():
                active_processes = int(count_str)
        except Exception:
            pass

    # Check if MCP config is synced
    mcp_synced = False
    if DEFAULT_OPENCODE_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_OPENCODE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "mammouth-defroster-9000" in data.get("mcp", {}):
                    mcp_synced = True
        except Exception:
            pass

    api_key = get_configured_api_key()

    return {
        "installed": installed,
        "executable_path": exe or "",
        "version": version,
        "api_key_configured": bool(api_key),
        "mcp_bridge_synced": mcp_synced,
        "active_processes": active_processes
    }


def install_or_update_mammouth_code() -> Dict[str, Any]:
    """Execute official PowerShell installer for Mammouth Code."""
    exe = get_mammouth_executable()
    start_time = time.time()

    if exe and os.path.isfile(exe):
        # Already installed, try upgrade first
        try:
            logger.info("Executing 'mammouth upgrade'...")
            proc = subprocess.run(
                [exe, "upgrade"],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            duration = round(time.time() - start_time, 2)
            return {
                "success": proc.returncode == 0,
                "action": "upgrade",
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "duration_seconds": duration,
                "path": exe
            }
        except Exception as ex:
            logger.warning(f"Upgrade failed, attempting reinstall: {ex}")

    # Run PowerShell installer
    try:
        logger.info("Running PowerShell installer for Mammouth Code...")
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", POWERSHELL_INSTALL_CMD
            ],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        duration = round(time.time() - start_time, 2)
        new_exe = get_mammouth_executable()
        return {
            "success": proc.returncode == 0 and bool(new_exe),
            "action": "install",
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "duration_seconds": duration,
            "path": new_exe or ""
        }
    except Exception as ex:
        return {
            "success": False,
            "action": "install",
            "stdout": "",
            "stderr": str(ex),
            "duration_seconds": round(time.time() - start_time, 2),
            "path": ""
        }


def _find_windows_terminal() -> Optional[str]:
    """Locate wt.exe (Windows Terminal)."""
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if wt:
        return wt
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidate = Path(local_app_data) / "Microsoft" / "WindowsApps" / "wt.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def launch_mammouth_terminal(
    workspace_path: Optional[str] = None,
    continue_session: bool = False,
    preferred_terminal: Optional[str] = None
) -> Dict[str, Any]:
    """Launch an interactive Mammouth Code terminal session in a new desktop window."""
    exe = get_mammouth_executable()
    if not exe:
        return {
            "success": False,
            "error": "Mammouth Code is not installed. Please run installation first."
        }

    # Resolve workspace directory
    if not workspace_path:
        try:
            from config import load_config, BASE_DIR
            cfg = load_config()
            rel_ws = cfg.get("server", {}).get("workspace_root", "./workspace")
            target_dir = Path(rel_ws)
            if not target_dir.is_absolute():
                target_dir = (BASE_DIR / target_dir).resolve()
            workspace_path = str(target_dir)
        except Exception:
            workspace_path = os.getcwd()

    if not os.path.isdir(workspace_path):
        os.makedirs(workspace_path, exist_ok=True)

    api_key = get_configured_api_key()

    # Build the PowerShell command cleanly using Base64 encoding (-EncodedCommand)
    # This prevents Windows Terminal (wt.exe) from interpreting semicolons as sub-command delimiters
    # which previously caused Win32 error 0x80070002 when attempting to execute '& ...'.
    if not preferred_terminal:
        try:
            from config import load_config
            cfg = load_config()
            preferred_terminal = cfg.get("mammouth_code", {}).get("default_terminal", "powershell")
        except Exception:
            preferred_terminal = "powershell"

    args_flag = " -c" if continue_session else ""
    safe_ws = str(workspace_path).replace("'", "''")
    safe_exe = str(exe).replace("'", "''")

    pwsh_statements = [
        f"Set-Location -LiteralPath '{safe_ws}'",
        "[System.Console]::Title = 'Mammouth Code'"
    ]
    # The API key is passed only via the child environment (child_env below). Embedding it in the
    # script would put it into the process command line (-EncodedCommand is just base64), which is
    # readable by every process of the user and ends up in process-creation / ScriptBlock logs.
    pwsh_statements.append(f"& '{safe_exe}'{args_flag}")

    full_script = "; ".join(pwsh_statements)
    encoded_cmd = base64.b64encode(full_script.encode("utf-16le")).decode("ascii")

    child_env = _build_child_env(api_key)

    try:
        wt_exe = _find_windows_terminal() if (preferred_terminal == "wt") else None

        if preferred_terminal == "wt" and wt_exe:
            # Spawn in Windows Terminal using start to ensure top-level window focus
            cmd = [
                "cmd.exe", "/c", "start", "",
                wt_exe,
                "--title", "Mammouth Code",
                "-d", workspace_path,
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", encoded_cmd
            ]
            term_name = "Windows Terminal (wt.exe)"
        else:
            # Default & Highly Reliable: Dedicated PowerShell window with start command
            cmd = [
                "cmd.exe", "/c", "start", "Mammouth Code",
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", encoded_cmd
            ]
            term_name = "PowerShell Console"

        subprocess.Popen(
            cmd,
            cwd=workspace_path,
            env=child_env
        )
        return {
            "success": True,
            "terminal": term_name,
            "workspace": workspace_path,
            "continued_session": continue_session
        }
    except Exception as ex:
        logger.error(f"Failed to launch Mammouth Code terminal: {ex}")
        return {
            "success": False,
            "error": str(ex),
            "workspace": workspace_path
        }


def run_mammouth_task(
    prompt: str,
    workspace_path: Optional[str] = None,
    timeout_seconds: int = 180,
    auto_approve: bool = True
) -> Dict[str, Any]:
    """Execute a coding task headless via Mammouth Code CLI ('mammouth run') and return output."""
    exe = get_mammouth_executable()
    if not exe:
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": "Mammouth Code executable not found on host. Run installation first."
        }

    if not prompt or not prompt.strip():
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": "Prompt must not be empty."
        }

    # Resolve workspace
    if not workspace_path:
        try:
            from config import load_config, BASE_DIR
            cfg = load_config()
            rel_ws = cfg.get("server", {}).get("workspace_root", "./workspace")
            target_dir = Path(rel_ws)
            if not target_dir.is_absolute():
                target_dir = (BASE_DIR / target_dir).resolve()
            workspace_path = str(target_dir)
        except Exception:
            workspace_path = os.getcwd()

    if not os.path.isdir(workspace_path):
        os.makedirs(workspace_path, exist_ok=True)

    # A .cmd/.bat shim (e.g. npm install) is executed through cmd.exe, which re-parses the
    # arguments: '&', '|', '>' … inside the prompt would run arbitrary commands ("BatBadBut").
    if str(exe).lower().endswith((".cmd", ".bat")) and re.search(r'[&|<>^%!"\r\n]', prompt):
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": "Mammouth Code is installed as a .cmd/.bat shim; prompts containing & | < > ^ % ! \" or line breaks "
                     "are refused to prevent command injection. Install the native mammouth.exe or rephrase the prompt."
        }

    # Build headless CLI command. A prompt starting with '-' would be parsed as a CLI option.
    safe_prompt = (" " + prompt) if prompt.startswith("-") else prompt
    cmd = [exe, "run"]
    if auto_approve:
        cmd.append("--auto")
    cmd.append(safe_prompt)

    # Prepare child environment with API Key and Defroster token
    child_env = _build_child_env(get_configured_api_key())

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace_path,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        duration = round(time.time() - start_time, 2)
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": out,
            "error": err if proc.returncode != 0 else "",
            "duration_seconds": duration,
            "workspace": workspace_path
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 2)
        return {
            "success": False,
            "returncode": -2,
            "output": "",
            "error": f"Execution timed out after {timeout_seconds} seconds.",
            "duration_seconds": duration,
            "workspace": workspace_path
        }
    except Exception as ex:
        duration = round(time.time() - start_time, 2)
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": str(ex),
            "duration_seconds": duration,
            "workspace": workspace_path
        }


def sync_opencode_mcp_config(
    workspace_path: Optional[str] = None,
    server_url: Optional[str] = None,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """Write/merge Mammouth Defroster 9000 MCP server entry into opencode.json configurations."""
    # Determine server URL and API Token
    try:
        from config import load_config
        cfg = load_config()
        if not server_url:
            host = cfg.get("server", {}).get("host", "127.0.0.1")
            port = cfg.get("server", {}).get("port", 8000)
            ep = cfg.get("server", {}).get("endpoint_path", "/sse")
            server_url = f"http://{host}:{port}{ep}"
        if not api_token:
            api_token = cfg.get("server", {}).get("api_token", "")
    except Exception:
        if not server_url:
            server_url = "http://127.0.0.1:8000/sse"
        if not api_token:
            api_token = ""

    # 0.0.0.0 is a bind address, not a connect address on Windows
    server_url = re.sub(r"^(https?://)(0\.0\.0\.0|\[::\])(?=[:/])", r"\g<1>127.0.0.1", server_url)

    global_entry: Dict[str, Any] = {
        "type": "remote",
        "url": server_url,
        "enabled": True
    }
    workspace_entry: Dict[str, Any] = dict(global_entry)
    if api_token:
        # Global config lives in the user profile: real token is acceptable there.
        global_entry["headers"] = {"Authorization": f"Bearer {api_token}"}
        # The workspace is typically a git repo: never write the secret there, reference an
        # environment variable instead (set by Defroster for every Mammouth Code launch).
        workspace_entry["headers"] = {"Authorization": "Bearer {env:" + DEFROSTER_TOKEN_ENV + "}"}

    updated_files = []
    errors = []

    # 1. Global config (~/.config/opencode/opencode.json)
    try:
        DEFAULT_OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _merge_opencode_mcp_entry(DEFAULT_OPENCODE_CONFIG_FILE, global_entry)
        updated_files.append(str(DEFAULT_OPENCODE_CONFIG_FILE))
    except Exception as ex:
        logger.error(f"Failed to update global opencode.json: {ex}")
        errors.append(f"{DEFAULT_OPENCODE_CONFIG_FILE}: {ex}")

    # 2. Local workspace config if provided
    if workspace_path and os.path.isdir(workspace_path):
        ws_file = Path(workspace_path) / "opencode.json"
        try:
            _merge_opencode_mcp_entry(ws_file, workspace_entry)
            updated_files.append(str(ws_file))
        except Exception as ex:
            logger.error(f"Failed to update workspace opencode.json: {ex}")
            errors.append(f"{ws_file}: {ex}")

    result = {
        "success": len(updated_files) > 0,
        "updated_configs": updated_files,
        "server_url": server_url
    }
    if errors:
        result["errors"] = errors
    return result
