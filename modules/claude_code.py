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

logger = logging.getLogger("claude_code")

# Fix BASE_DIR resolution
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DEFAULT_CLAUDE_CONFIG_FILE = Path.home() / ".claude.json"
DEFAULT_MCP_CONFIG_FILENAME = ".mcp.json"
DEFROSTER_TOKEN_ENV = "MAMMOUTH_DEFROSTER_TOKEN"
SERVER_NAME = "mammouth-defroster-9000"
TUNNEL_INFO_FILE = BASE_DIR / "data" / "tunnel_info.json"


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas from JSONC string safely without altering string literals."""
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
        elif ch == ",":
            # Look ahead outside string: if next non-whitespace / non-comment char is '}' or ']', drop the comma
            j = i + 1
            is_trailing = False
            while j < n:
                if text.startswith("//", j):
                    nl = text.find("\n", j)
                    j = n if nl == -1 else nl
                elif text.startswith("/*", j):
                    end = text.find("*/", j + 2)
                    j = n if end == -1 else end + 2
                elif text[j].isspace():
                    j += 1
                elif text[j] in ("}", "]"):
                    is_trailing = True
                    break
                else:
                    break
            if not is_trailing:
                out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _merge_claude_mcp_entry(config_file: Path, entry: Dict[str, Any], server_name: str = SERVER_NAME) -> None:
    """Merge an MCP server entry into a Claude Code configuration file (.mcp.json or ~/.claude.json).
    
    Preserves all existing user configurations and other MCP servers.
    Creates a .bak backup and performs atomic replacement via temporary file.
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
                    raise ValueError(f"Cannot parse existing configuration at {config_file} ({ex})")
        if not isinstance(config_data, dict):
            raise ValueError(f"Existing file {config_file} is not a valid JSON object")

    # Only project-scoped .mcp.json should include the MCP schema; ~/.claude.json is Claude's general CLI config
    if config_file.name == DEFAULT_MCP_CONFIG_FILENAME:
        config_data.setdefault("$schema", "https://json.schemastore.org/mcp.json")
    if not isinstance(config_data.get("mcpServers"), dict):
        config_data["mcpServers"] = {}
    
    config_data["mcpServers"][server_name] = entry

    config_file.parent.mkdir(parents=True, exist_ok=True)
    if original_text is not None:
        try:
            bak_file = config_file.with_name(config_file.name + ".bak")
            if not bak_file.exists():
                bak_file.write_text(original_text, encoding="utf-8")
        except Exception as ex:
            logger.debug(f"Could not create backup for {config_file}: {ex}")

    tmp_file = config_file.with_name(config_file.name + ".tmp")
    tmp_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    os.replace(tmp_file, config_file)


def find_tailscale_binary(tailscale_path: str = "") -> Optional[str]:
    """Find the Tailscale binary path across multiple standard Windows locations."""
    candidates = [
        tailscale_path,
        shutil.which("tailscale"),
        shutil.which("tailscale.exe"),
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        os.path.expandvars(r"%PROGRAMFILES%\Tailscale\tailscale.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tailscale\tailscale.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return str(Path(c).resolve())
    return None


def get_tailscale_public_domain(tailscale_path: str = "") -> Optional[str]:
    """Attempt to detect the machine's Tailscale public domain name."""
    ts_bin = find_tailscale_binary(tailscale_path)
    if not ts_bin:
        return None
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run([ts_bin, "status", "--json"], capture_output=True, text=True, timeout=5, creationflags=flags)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            cert_domains = data.get("CertDomains")
            if cert_domains and isinstance(cert_domains, list) and len(cert_domains) > 0:
                return f"https://{cert_domains[0]}"
            self_node = data.get("Self", {})
            dns_name = self_node.get("DNSName", "").rstrip(".")
            if dns_name:
                return f"https://{dns_name}"
            magic = data.get("MagicDNSSuffix", "").rstrip(".")
            host = self_node.get("HostName", "").lower()
            if host and magic:
                return f"https://{host}.{magic}"
    except Exception as ex:
        logger.debug(f"Failed to query Tailscale domain: {ex}")
    return None


def save_active_tunnel_info(tunnel_url: Optional[str], tunnel_mode: str = "") -> None:
    """Persist active tunnel information so other processes/tools can access live tunnel URL."""
    try:
        TUNNEL_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tunnel_url": tunnel_url,
            "tunnel_mode": tunnel_mode,
            "updated_at": time.time()
        }
        TUNNEL_INFO_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as ex:
        logger.debug(f"Failed to save tunnel info: {ex}")


def get_active_tunnel_info() -> Dict[str, Any]:
    """Retrieve persisted active tunnel information."""
    if TUNNEL_INFO_FILE.is_file():
        try:
            return json.loads(TUNNEL_INFO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tunnel_url": None, "tunnel_mode": "", "updated_at": 0.0}


def resolve_public_tunnel_url(endpoint_path: str = "/mcp") -> Optional[str]:
    """Determine the active or configured public tunnel endpoint for Claude Code Cloud Sessions."""
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path

    # 1. Check live active tunnel file (written by GUI when tunnel is established)
    info = get_active_tunnel_info()
    live_url = info.get("tunnel_url")
    if live_url and isinstance(live_url, str) and live_url.startswith("http"):
        clean_base = re.sub(r"/(mcp|sse|messages)?/?$", "", live_url.strip())
        return f"{clean_base}{endpoint_path}"

    # 2. Check configuration file for custom public URLs or tunnel configurations
    try:
        from config import load_config
        cfg = load_config()
        server_cfg = cfg.get("server", {})

        # Custom Domain
        custom_url = server_cfg.get("custom_public_url", "").strip()
        if custom_url and custom_url.startswith("http"):
            clean_base = re.sub(r"/(mcp|sse|messages)?/?$", "", custom_url)
            return f"{clean_base}{endpoint_path}"

        # Cloudflare Custom URL
        cf_custom = server_cfg.get("cloudflare_custom_url", "").strip()
        if cf_custom and cf_custom.startswith("http"):
            clean_base = re.sub(r"/(mcp|sse|messages)?/?$", "", cf_custom)
            return f"{clean_base}{endpoint_path}"

        # ngrok Custom URL
        ng_custom = server_cfg.get("ngrok_custom_url", "").strip()
        if ng_custom and ng_custom.startswith("http"):
            clean_base = re.sub(r"/(mcp|sse|messages)?/?$", "", ng_custom)
            return f"{clean_base}{endpoint_path}"

        # Tailscale Funnel
        mode = server_cfg.get("tunnel_mode", "Tailscale Funnel")
        if mode == "Tailscale Funnel":
            ts_domain = get_tailscale_public_domain(server_cfg.get("tailscale_path", ""))
            if ts_domain:
                return f"{ts_domain.rstrip('/')}{endpoint_path}"

    except Exception as ex:
        logger.debug(f"Failed to inspect config for tunnel URL: {ex}")

    return None


def resolve_active_server_url(target_cloud: bool = True, endpoint_path: str = "/mcp") -> str:
    """Resolve active MCP server URL for Claude Code.
    
    If target_cloud is True, strictly prioritizes the public exposure tunnel URL.
    If target_cloud is False, uses local connection address (127.0.0.1).
    """
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path

    if target_cloud:
        pub_url = resolve_public_tunnel_url(endpoint_path=endpoint_path)
        if pub_url:
            return pub_url

    # Fallback to local bind address
    try:
        from config import load_config
        server_cfg = load_config().get("server", {})
        host = server_cfg.get("host", "127.0.0.1")
        port = server_cfg.get("port", 8000)
    except Exception:
        host, port = "127.0.0.1", 8000

    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"

    return f"http://{host}:{port}{endpoint_path}"


def get_claude_executable() -> Optional[str]:
    """Find path to claude CLI executable on the host machine.
    
    Checks in order:
    1. Custom path in config.json under claude_code.binary_path
    2. System PATH (shutil.which for claude, claude.cmd, claude.exe)
    3. npm global prefix directory (npm prefix -g)
    4. Common Windows npm global / AppData paths
    """
    try:
        from config import load_config
        cfg = load_config()
        custom_path = cfg.get("claude_code", {}).get("binary_path", "")
        if custom_path and os.path.isfile(custom_path):
            return custom_path
    except Exception as ex:
        logger.debug(f"Failed to read custom claude_code path from config: {ex}")

    for cmd_name in ("claude", "claude.cmd", "claude.exe"):
        which_path = shutil.which(cmd_name)
        if which_path and os.path.isfile(which_path):
            return which_path

    # Dynamic check for npm global prefix (handles custom npm installations, e.g. D:\hermes\node)
    npm_exe = shutil.which("npm") or shutil.which("npm.cmd")
    if npm_exe:
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            res = subprocess.run([npm_exe, "prefix", "-g"], capture_output=True, text=True, timeout=2, creationflags=flags)
            if res.returncode == 0 and res.stdout.strip():
                prefix = Path(res.stdout.strip().splitlines()[-1].strip())
                for cand in (prefix / "claude.cmd", prefix / "claude", prefix / "bin" / "claude"):
                    if cand.is_file():
                        return str(cand.resolve())
        except Exception:
            pass

    # Common Windows npm and app paths
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
        Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".local" / "bin" / "claude.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)

    return None


def get_claude_code_status(workspace_path: Optional[str] = None) -> Dict[str, Any]:
    """Inspect and return current installation, version, and MCP bridge status for Claude Code."""
    exe = get_claude_executable()
    installed = exe is not None and os.path.isfile(exe)
    version = ""

    if installed and exe:
        try:
            # Query version (claude --version) with explicit UTF-8 encoding
            res = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            version = (res.stdout or "").strip() or (res.stderr or "").strip()
        except Exception as ex:
            logger.debug(f"Failed to query claude version: {ex}")
            version = "Installed (Version check timed out)"

    # Resolve workspace folder
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

    ws_mcp_file = Path(workspace_path) / DEFAULT_MCP_CONFIG_FILENAME
    ws_synced = False
    cloud_ready = False
    configured_url = ""

    if ws_mcp_file.is_file():
        try:
            raw_text = ws_mcp_file.read_text(encoding="utf-8-sig")
            clean_text = _strip_jsonc(raw_text)
            data = json.loads(clean_text)
            servers = data.get("mcpServers", {})
            entry = servers.get(SERVER_NAME) or servers.get("MammouthDefroster9000")
            if entry and isinstance(entry, dict):
                ws_synced = True
                configured_url = entry.get("url", "")
                # Cloud-ready requires an HTTPS public URL (not localhost or 127.0.0.1)
                is_local = "127.0.0.1" in configured_url or "localhost" in configured_url
                has_auth = (
                    bool(entry.get("headers", {}).get("Authorization"))
                    or entry.get("auth_mode") == "oauth"
                    or "oauth" in str(entry).lower()
                    or ("headers" not in entry and not is_local)
                )
                if not is_local and configured_url.startswith("https://") and has_auth:
                    cloud_ready = True
        except Exception as ex:
            logger.debug(f"Error inspecting workspace .mcp.json: {ex}")

    # Inspect global ~/.claude.json
    global_synced = False
    if DEFAULT_CLAUDE_CONFIG_FILE.is_file():
        try:
            raw_text = DEFAULT_CLAUDE_CONFIG_FILE.read_text(encoding="utf-8-sig")
            data = json.loads(_strip_jsonc(raw_text))
            servers = data.get("mcpServers", {})
            if SERVER_NAME in servers or "MammouthDefroster9000" in servers:
                global_synced = True
        except Exception:
            pass

    active_public_url = resolve_public_tunnel_url() or ""

    return {
        "installed": installed,
        "executable_path": exe or "",
        "version": version,
        "workspace_path": workspace_path,
        "workspace_mcp_synced": ws_synced,
        "workspace_mcp_file": str(ws_mcp_file),
        "global_mcp_synced": global_synced,
        "global_mcp_file": str(DEFAULT_CLAUDE_CONFIG_FILE),
        "cloud_ready": cloud_ready,
        "configured_url": configured_url,
        "active_public_url": active_public_url,
    }


def update_workspace_claude_md(workspace_path: Path) -> bool:
    """Ensure workspace contains instructions for Claude Code on how to use Mammouth Defroster 9000."""
    try:
        claude_md = workspace_path / "CLAUDE.md"
        header_tag = "## Mammouth Defroster 9000 (MCP Tools)"
        snippet = (
            f"\n{header_tag}\n"
            "- Connected via `.mcp.json` (`mammouth-defroster-9000`)\n"
            "- Tools: workspace file editing, command execution, browser automation, desktop vision, long-term memory, system diagnostics\n"
            "- Core Router: Use `defroster_catalog` to discover tools or switch profiles (e.g. `defroster_catalog(switch_profile='all')`)\n"
        )
        if claude_md.is_file():
            content = claude_md.read_text(encoding="utf-8")
            if "Mammouth Defroster" not in content and "mammouth-defroster" not in content:
                claude_md.write_text(content.rstrip() + "\n" + snippet, encoding="utf-8")
                return True
        else:
            claude_md.write_text(f"# CLAUDE.md\n{snippet}", encoding="utf-8")
            return True
    except Exception as ex:
        logger.debug(f"Could not update CLAUDE.md in workspace: {ex}")
    return False


def sync_claude_code_mcp(
    workspace_path: Optional[str] = None,
    server_url: Optional[str] = None,
    api_token: Optional[str] = None,
    target_cloud: bool = True,
    use_env_var: bool = False,
    sync_global: bool = True,
    update_claude_md: bool = True,
    use_oauth: bool = False
) -> Dict[str, Any]:
    """Write/merge Mammouth Defroster 9000 MCP server entry into Claude Code configurations (.mcp.json and ~/.claude.json).
    
    When target_cloud=True (recommended for Claude Code Cloud Sessions):
    - Prioritizes public tunnel URL (Cloudflare Tunnel, Tailscale Funnel, Serveo, ngrok, Custom Domain).
    - Sets transport type to 'http' (Streamable HTTP, the standard for modern Claude Code remote servers).
    - Writes the project-scoped .mcp.json file so it can be committed to Git and automatically loaded in cloud sessions.
    - Preserves local ~/.claude.json pointing to the stable local server endpoint so local sessions never break when tunnels close.
    - When use_oauth=True, omits static Authorization headers so Claude Code performs the standard OAuth 2.1 handshake.
    """
    # 1. Resolve API Token
    try:
        from config import load_config
        cfg = load_config()
        if not api_token:
            api_token = cfg.get("server", {}).get("api_token", "") or os.environ.get("MCP_API_TOKEN", "")
    except Exception:
        if not api_token:
            api_token = os.environ.get("MCP_API_TOKEN", "")

    # 2. Resolve Server URL
    public_tunnel_detected = False
    if not server_url:
        if target_cloud:
            pub_url = resolve_public_tunnel_url(endpoint_path="/mcp")
            if pub_url:
                server_url = pub_url
                public_tunnel_detected = True
            else:
                # Provide warning but compute local URL fallback
                server_url = resolve_active_server_url(target_cloud=False, endpoint_path="/mcp")
        else:
            server_url = resolve_active_server_url(target_cloud=False, endpoint_path="/mcp")
    else:
        # User explicitly supplied server_url
        if not server_url.endswith(("/mcp", "/sse")):
            server_url = server_url.rstrip("/") + "/mcp"
        if not ("127.0.0.1" in server_url or "localhost" in server_url):
            public_tunnel_detected = True

    # 3. Clean up bind address if needed
    server_url = re.sub(r"^(https?://)(0\.0\.0\.0|\[::\])(?=[:/])", r"\g<1>127.0.0.1", server_url)

    # 4. Resolve workspace directory
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

    ws_dir = Path(workspace_path)
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_file = ws_dir / DEFAULT_MCP_CONFIG_FILENAME

    # 5. Build MCP entries
    # In .mcp.json, Claude Code uses type: "http" for Streamable HTTP remote endpoints
    auth_header_val = f"Bearer {api_token}" if not use_env_var else f"Bearer ${{MAMMOUTH_DEFROSTER_TOKEN}}"
    
    workspace_entry: Dict[str, Any] = {
        "type": "http",
        "url": server_url
    }
    if not use_oauth and (api_token or use_env_var):
        workspace_entry["headers"] = {"Authorization": auth_header_val}

    updated_files = []
    errors = []

    # Write workspace .mcp.json
    try:
        _merge_claude_mcp_entry(ws_file, workspace_entry, server_name=SERVER_NAME)
        updated_files.append(str(ws_file))
    except Exception as ex:
        logger.error(f"Failed to update workspace {ws_file}: {ex}")
        errors.append(f"{ws_file}: {ex}")

    # Optionally update global user config (~/.claude.json) for local sessions
    if sync_global:
        try:
            DEFAULT_CLAUDE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Global config is on the local user machine; always use local server URL for local sessions
            local_url = resolve_active_server_url(target_cloud=False, endpoint_path="/mcp")
            global_entry: Dict[str, Any] = {
                "type": "http",
                "url": local_url
            }
            if not use_oauth and api_token:
                global_entry["headers"] = {"Authorization": f"Bearer {api_token}"}
            _merge_claude_mcp_entry(DEFAULT_CLAUDE_CONFIG_FILE, global_entry, server_name=SERVER_NAME)
            updated_files.append(str(DEFAULT_CLAUDE_CONFIG_FILE))
        except Exception as ex:
            logger.error(f"Failed to update global {DEFAULT_CLAUDE_CONFIG_FILE}: {ex}")
            errors.append(f"{DEFAULT_CLAUDE_CONFIG_FILE}: {ex}")

    # Optionally ensure workspace has instructions in CLAUDE.md
    if update_claude_md:
        try:
            if update_workspace_claude_md(ws_dir):
                updated_files.append(str(ws_dir / "CLAUDE.md"))
        except Exception as ex:
            logger.debug(f"CLAUDE.md update notice: {ex}")

    is_cloud_ready = bool(public_tunnel_detected and ("https://" in server_url))
    warning_list = []
    if target_cloud and not is_cloud_ready:
        warning_list.append(
            "Notice: Configured server URL is local (127.0.0.1 or HTTP). "
            "Claude Code Cloud Sessions run in Anthropic's cloud and require a public HTTPS tunnel "
            "(e.g. Tailscale Funnel, Cloudflare Tunnel, Serveo, or ngrok). "
            "Please start a public tunnel in the Dashboard to make Defroster reachable in the cloud."
        )
    if target_cloud and not use_oauth and not use_env_var and api_token:
        warning_list.append(
            "Security Notice: Committing plaintext tokens to version control carries security risks. "
            "For public or shared Git repositories, consider 'use_env_var=True' or 'use_oauth=True'."
        )

    warning = "\n\n".join(warning_list)

    auth_mode_str = "oauth" if use_oauth else ("env_var" if use_env_var else "token")

    return {
        "success": len(updated_files) > 0,
        "updated_configs": updated_files,
        "server_url": server_url,
        "target_cloud": target_cloud,
        "cloud_ready": is_cloud_ready,
        "auth_mode": auth_mode_str,
        "warning": warning,
        "errors": errors if errors else None
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


def launch_claude_terminal(
    workspace_path: Optional[str] = None,
    cloud: bool = True,
    continue_session: bool = False,
    preferred_terminal: Optional[str] = None,
    prompt: Optional[str] = None
) -> Dict[str, Any]:
    """Launch an interactive Claude Code terminal session (local or cloud) in a new desktop window."""
    try:
        from config import load_config
        cfg = load_config()
        allow_admin = bool(cfg.get("server", {}).get("allow_admin_shell", False))
    except Exception:
        allow_admin = False

    if not allow_admin:
        raise PermissionError(
            "Admin shell required: Launching an interactive Claude Code terminal session is blocked in Read-Only mode. "
            "Enable 'server.allow_admin_shell=true' in configuration."
        )

    exe = get_claude_executable()
    if not exe:
        return {
            "success": False,
            "error": (
                "Claude Code CLI is not installed on this machine. "
                "You can install it with: npm install -g @anthropic-ai/claude-code"
            )
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

    # Ensure .mcp.json is synced in workspace
    try:
        sync_claude_code_mcp(workspace_path=workspace_path, target_cloud=cloud)
    except Exception as ex:
        logger.debug(f"Pre-launch MCP sync notice: {ex}")

    # Build child environment with API token
    child_env = os.environ.copy()
    try:
        from config import load_config
        token = load_config().get("server", {}).get("api_token", "")
        if token:
            child_env[DEFROSTER_TOKEN_ENV] = token
    except Exception:
        pass

    if not preferred_terminal:
        try:
            from config import load_config
            cfg = load_config()
            preferred_terminal = cfg.get("claude_code", {}).get("default_terminal", "powershell")
        except Exception:
            preferred_terminal = "powershell"

    safe_ws = str(workspace_path).replace("'", "''")
    safe_exe = str(exe).replace("'", "''")

    args_list = []
    if cloud:
        args_list.append("--cloud")
    if continue_session:
        args_list.append("-c")
    if prompt and prompt.strip():
        safe_p = prompt.strip().replace("'", "''")
        args_list.append(f"-p '{safe_p}'")

    args_str = " " + " ".join(args_list) if args_list else ""
    title_str = "Claude Code (Cloud Session)" if cloud else "Claude Code"

    pwsh_statements = [
        f"Set-Location -LiteralPath '{safe_ws}'",
        f"[System.Console]::Title = '{title_str}'",
        f"& '{safe_exe}'{args_str}"
    ]

    full_script = "; ".join(pwsh_statements)
    encoded_cmd = base64.b64encode(full_script.encode("utf-16le")).decode("ascii")

    try:
        wt_exe = _find_windows_terminal() if (preferred_terminal == "wt") else None

        if preferred_terminal == "wt" and wt_exe:
            cmd = [
                "cmd.exe", "/c", "start", "",
                wt_exe,
                "--title", title_str,
                "-d", workspace_path,
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", encoded_cmd
            ]
            term_name = "Windows Terminal (wt.exe)"
        else:
            cmd = [
                "cmd.exe", "/c", "start", "",
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
            "cloud_mode": cloud,
            "continued_session": continue_session
        }
    except Exception as ex:
        logger.error(f"Failed to launch Claude Code terminal: {ex}")
        return {
            "success": False,
            "error": str(ex),
            "workspace": workspace_path
        }


def run_claude_task(
    prompt: str,
    workspace_path: Optional[str] = None,
    cloud: bool = True,
    timeout_seconds: int = 180
) -> Dict[str, Any]:
    """Execute a task non-interactively via Claude Code CLI ('claude -p' or 'claude --cloud -p')."""
    try:
        from config import load_config
        cfg = load_config()
        allow_admin = bool(cfg.get("server", {}).get("allow_admin_shell", False))
    except Exception:
        allow_admin = False

    if not allow_admin:
        raise PermissionError(
            "Admin shell required: 'claude_code_run_task' can modify files and execute commands on the host, "
            "which is blocked in Read-Only mode. Enable 'server.allow_admin_shell=true' in configuration."
        )

    exe = get_claude_executable()
    if not exe:
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": "Claude Code executable not found on host. Run 'npm install -g @anthropic-ai/claude-code' first."
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

    # Ensure .mcp.json is synced in workspace
    try:
        sync_claude_code_mcp(workspace_path=workspace_path, target_cloud=cloud)
    except Exception:
        pass

    cmd = [exe]
    if cloud:
        cmd.append("--cloud")
    cmd.extend(["-p", prompt.strip()])

    child_env = os.environ.copy()
    try:
        from config import load_config
        token = load_config().get("server", {}).get("api_token", "")
        if token:
            child_env[DEFROSTER_TOKEN_ENV] = token
    except Exception:
        pass

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace_path,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        duration = round(time.time() - start_time, 2)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": out,
            "error": err if proc.returncode != 0 else "",
            "duration_seconds": duration,
            "workspace": workspace_path,
            "cloud_mode": cloud
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 2)
        return {
            "success": False,
            "returncode": -2,
            "output": "",
            "error": f"Execution timed out after {timeout_seconds} seconds.",
            "duration_seconds": duration,
            "workspace": workspace_path,
            "cloud_mode": cloud
        }
    except Exception as ex:
        duration = round(time.time() - start_time, 2)
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": str(ex),
            "duration_seconds": duration,
            "workspace": workspace_path,
            "cloud_mode": cloud
        }
