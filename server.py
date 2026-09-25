import os
import sys
import json
import html
import secrets
import functools
import re
import time
import hashlib
from pathlib import Path
from typing import Optional, AsyncGenerator, Any, Dict, List

import base64
import sqlite3
import urllib.parse
from urllib.parse import parse_qs, urlencode, quote
import subprocess
import uvicorn
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, HTMLResponse, RedirectResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

# Fix sys.path and application root for standalone bundled environment
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

ROOT_DIR = BASE_DIR
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastmcp import FastMCP
try:
    from fastmcp.server.http import (
        StreamableHTTPASGIApp,
        FastMCPStreamableHTTPSessionManager,
        create_base_app
    )
except ImportError:
    try:
        from fastmcp.server.asgi import (
            StreamableHTTPASGIApp,
            FastMCPStreamableHTTPSessionManager,
            create_base_app
        )
    except ImportError:
        from fastmcp.server import (
            StreamableHTTPASGIApp,
            FastMCPStreamableHTTPSessionManager,
            create_base_app
        )

from config import load_config

# Import modular capabilities
from modules.memory import memory_save, memory_recall, memory_get, memory_delete, memory_list
from modules.tasks_kanban import task_create, task_update, task_list, task_delete
from modules.file_ops import (
    file_read,
    file_write,
    file_replace_chunk,
    file_search_text,
    directory_list,
    directory_tree
)
from modules.shell_processes import (
    command_run,
    powershell_exec,
    cmd_exec,
    desktop_open,
    process_start_background,
    process_list_background,
    process_get_output,
    process_kill_background
)
from modules.putty_ssh import (
    ssh_exec_command,
    ssh_open_putty_window,
    ssh_transfer_file,
    ssh_list_saved_hosts,
    ssh_save_host,
    ssh_list_putty_registry_sessions
)
from modules.system_monitor import (
    system_get_specs,
    system_get_processes,
    system_get_gpu_info,
    system_get_event_logs
)
from modules.screen_capture import (
    screen_capture,
    screen_list_monitors,
    screen_grant_consent,
    screen_revoke_consent
)
from modules.web_tools import (
    web_fetch_url,
    web_check_status
)
from modules.desktop_input import (
    desktop_get_screen_info,
    mouse_move,
    mouse_click,
    mouse_drag,
    mouse_scroll,
    mouse_get_position,
    keyboard_type,
    keyboard_press,
    keyboard_hotkey
)
from modules.unreal_engine import (
    unreal_ping,
    unreal_get_project_info,
    unreal_execute_python,
    unreal_execute_console_command,
    unreal_get_actors,
    unreal_spawn_actor,
    unreal_spawn_shape_actor,
    unreal_set_actor_transform,
    unreal_delete_actor,
    unreal_get_selected_actors,
    unreal_set_selected_actors,
    unreal_focus_actor,
    unreal_get_current_level,
    unreal_load_level,
    unreal_save_current_level,
    unreal_new_level,
    unreal_list_assets,
    unreal_get_asset_info,
    unreal_create_material,
    unreal_assign_material_to_actor,
    unreal_delete_asset,
    unreal_spawn_light,
    unreal_take_screenshot,
)
from modules.google_drive import (
    gdrive_status,
    gdrive_list_files,
    gdrive_search_files,
    gdrive_get_metadata,
    gdrive_read_file,
    gdrive_download_to_workspace,
    gdrive_upload_from_workspace,
    gdrive_write_file,
    gdrive_update_file,
    gdrive_create_folder,
    gdrive_delete_file
)

# Initialize FastMCP Server with Mammouth Defroster 9000, Google Drive & Unreal Engine capabilities
mcp = FastMCP(
    name="Mammouth-Defroster-9000",
    instructions="""
    Mammouth Defroster 9000 (v0.4.1): Sovereign Windows 11 Desktop Cockpit, Vision, Google Drive & Unreal Engine 5 Automation Platform.
    Provides sandboxed long-term memory, tasks, file operations, hardware diagnostics, desktop vision, Google Drive cloud integration, and Unreal Engine automation exclusively for Mammouth.ai.
    Always prioritize safety, sandboxing, and precision.
    """
)


def require_module(mod_name: str):
    """Tool-level authorization check against dynamic module configuration."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cfg = load_config()
            enabled = cfg.get("modules", {}).get(mod_name, {}).get("enabled", False)
            if not enabled:
                raise PermissionError(f"Tool '{fn.__name__}' is disabled because module '{mod_name}' is currently turned off.")
            res = fn(*args, **kwargs)
            # Ensure empty lists emit valid TextContent to prevent MCP client IndexError crashes
            if isinstance(res, list) and len(res) == 0:
                from mcp.types import TextContent
                return [TextContent(type="text", text="[]")]
            return res
        return wrapper
    return decorator


@mcp.tool()
def local_exec_command(command: str, cwd: str = "", timeout: int = 600) -> dict:
    """Run a shell command on this Windows host, scoped to the configured workspace root.

    Executes the command via cmd.exe /c and captures stdout, stderr, and exit code.
    The cwd is whitelisted to only allow directories under the configured workspace root.
    Commands are validated against the same security blocklist as powershell_exec/cmd_exec.
    """
    # --- Security Gate: validate command against shell blocklist (C-2 fix) ---
    try:
        from modules.shell_processes import _validate_shell_command
        clean_command = _validate_shell_command(command)
    except PermissionError as ex:
        return {
            "stdout": "",
            "stderr": f"Security Error: {ex}",
            "exit_code": -1,
            "error": str(ex)
        }
    except Exception as ex:
        return {
            "stdout": "",
            "stderr": f"Command validation error: {ex}",
            "exit_code": -1,
            "error": str(ex)
        }

    # --- Dynamic cwd whitelist: read from config with D:\Ai-Workdir fallback ---
    cfg = load_config()
    raw_root = cfg.get("server", {}).get("workspace_root") or r"D:\Ai-Workdir"
    workdir_root = os.path.realpath(os.path.abspath(raw_root))
    target_cwd = cwd if cwd and cwd.strip() else workdir_root
    resolved_cwd = os.path.realpath(os.path.abspath(target_cwd))

    if not (resolved_cwd == workdir_root or resolved_cwd.startswith(workdir_root + os.sep)):
        return {
            "stdout": "",
            "stderr": f"Security: cwd '{cwd}' resolves to '{resolved_cwd}' which is outside the allowed workspace '{workdir_root}'.",
            "exit_code": -1,
            "error": f"cwd not in {workdir_root} scope"
        }

    try:
        proc = subprocess.run(
            clean_command,
            shell=True,
            cwd=resolved_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "exit_code": proc.returncode,
            "error": None
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "exit_code": -1,
            "error": f"TimeoutExpired({timeout}s)"
        }
    except Exception as ex:
        return {
            "stdout": "",
            "stderr": str(ex),
            "exit_code": -1,
        }


def register_active_tools():
    """Register tools dynamically based on enabled modules in config.json."""
    cfg = load_config()
    mods = cfg.get("modules", {})

    if mods.get("memory", {}).get("enabled", True):
        mcp.tool()(require_module("memory")(memory_save))
        mcp.tool()(require_module("memory")(memory_recall))
        mcp.tool()(require_module("memory")(memory_get))
        mcp.tool()(require_module("memory")(memory_delete))
        mcp.tool()(require_module("memory")(memory_list))

    if mods.get("tasks_kanban", {}).get("enabled", True):
        mcp.tool()(require_module("tasks_kanban")(task_create))
        mcp.tool()(require_module("tasks_kanban")(task_update))
        mcp.tool()(require_module("tasks_kanban")(task_list))
        mcp.tool()(require_module("tasks_kanban")(task_delete))

    if mods.get("file_ops", {}).get("enabled", True):
        mcp.tool()(require_module("file_ops")(file_read))
        mcp.tool()(require_module("file_ops")(file_write))
        mcp.tool()(require_module("file_ops")(file_replace_chunk))
        mcp.tool()(require_module("file_ops")(file_search_text))
        mcp.tool()(require_module("file_ops")(directory_list))
        mcp.tool()(require_module("file_ops")(directory_tree))

    if mods.get("shell_processes", {}).get("enabled", False):
        mcp.tool()(require_module("shell_processes")(command_run))
        mcp.tool()(require_module("shell_processes")(powershell_exec))
        mcp.tool()(require_module("shell_processes")(cmd_exec))
        mcp.tool()(require_module("shell_processes")(desktop_open))
        mcp.tool()(require_module("shell_processes")(process_start_background))
        mcp.tool()(require_module("shell_processes")(process_list_background))
        mcp.tool()(require_module("shell_processes")(process_get_output))
        mcp.tool()(require_module("shell_processes")(process_kill_background))

    if mods.get("putty_ssh", {}).get("enabled", True):
        mcp.tool()(require_module("putty_ssh")(ssh_exec_command))
        mcp.tool()(require_module("putty_ssh")(ssh_open_putty_window))
        mcp.tool()(require_module("putty_ssh")(ssh_transfer_file))
        mcp.tool()(require_module("putty_ssh")(ssh_list_saved_hosts))
        mcp.tool()(require_module("putty_ssh")(ssh_save_host))
        mcp.tool()(require_module("putty_ssh")(ssh_list_putty_registry_sessions))

    if mods.get("system_monitor", {}).get("enabled", True):
        mcp.tool()(require_module("system_monitor")(system_get_specs))
        mcp.tool()(require_module("system_monitor")(system_get_processes))
        mcp.tool()(require_module("system_monitor")(system_get_gpu_info))
        mcp.tool()(require_module("system_monitor")(system_get_event_logs))

    if mods.get("screen_capture", {}).get("enabled", True):
        mcp.tool()(require_module("screen_capture")(screen_capture))
        mcp.tool()(require_module("screen_capture")(screen_list_monitors))
        mcp.tool()(require_module("screen_capture")(screen_grant_consent))
        mcp.tool()(require_module("screen_capture")(screen_revoke_consent))

    if mods.get("web_tools", {}).get("enabled", True):
        mcp.tool()(require_module("web_tools")(web_fetch_url))
        mcp.tool()(require_module("web_tools")(web_check_status))

    if mods.get("unreal_engine", {}).get("enabled", True):
        mcp.tool()(require_module("unreal_engine")(unreal_ping))
        mcp.tool()(require_module("unreal_engine")(unreal_get_project_info))
        mcp.tool()(require_module("unreal_engine")(unreal_execute_python))
        mcp.tool()(require_module("unreal_engine")(unreal_execute_console_command))
        mcp.tool()(require_module("unreal_engine")(unreal_get_actors))
        mcp.tool()(require_module("unreal_engine")(unreal_spawn_actor))
        mcp.tool()(require_module("unreal_engine")(unreal_spawn_shape_actor))
        mcp.tool()(require_module("unreal_engine")(unreal_set_actor_transform))
        mcp.tool()(require_module("unreal_engine")(unreal_delete_actor))
        mcp.tool()(require_module("unreal_engine")(unreal_get_selected_actors))
        mcp.tool()(require_module("unreal_engine")(unreal_set_selected_actors))
        mcp.tool()(require_module("unreal_engine")(unreal_focus_actor))
        mcp.tool()(require_module("unreal_engine")(unreal_get_current_level))
        mcp.tool()(require_module("unreal_engine")(unreal_load_level))
        mcp.tool()(require_module("unreal_engine")(unreal_save_current_level))
        mcp.tool()(require_module("unreal_engine")(unreal_new_level))
        mcp.tool()(require_module("unreal_engine")(unreal_list_assets))
        mcp.tool()(require_module("unreal_engine")(unreal_get_asset_info))
        mcp.tool()(require_module("unreal_engine")(unreal_create_material))
        mcp.tool()(require_module("unreal_engine")(unreal_assign_material_to_actor))
        mcp.tool()(require_module("unreal_engine")(unreal_delete_asset))
        mcp.tool()(require_module("unreal_engine")(unreal_spawn_light))
        mcp.tool()(require_module("unreal_engine")(unreal_take_screenshot))

    if mods.get("desktop_input", {}).get("enabled", True):
        mcp.tool()(require_module("desktop_input")(desktop_get_screen_info))
        mcp.tool()(require_module("desktop_input")(mouse_move))
        mcp.tool()(require_module("desktop_input")(mouse_click))
        mcp.tool()(require_module("desktop_input")(mouse_drag))
        mcp.tool()(require_module("desktop_input")(mouse_scroll))
        mcp.tool()(require_module("desktop_input")(mouse_get_position))
        mcp.tool()(require_module("desktop_input")(keyboard_type))
        mcp.tool()(require_module("desktop_input")(keyboard_press))
        mcp.tool()(require_module("desktop_input")(keyboard_hotkey))

    if mods.get("google_drive", {}).get("enabled", True):
        mcp.tool()(require_module("google_drive")(gdrive_status))
        mcp.tool()(require_module("google_drive")(gdrive_list_files))
        mcp.tool()(require_module("google_drive")(gdrive_search_files))
        mcp.tool()(require_module("google_drive")(gdrive_get_metadata))
        mcp.tool()(require_module("google_drive")(gdrive_read_file))
        mcp.tool()(require_module("google_drive")(gdrive_download_to_workspace))
        mcp.tool()(require_module("google_drive")(gdrive_upload_from_workspace))
        mcp.tool()(require_module("google_drive")(gdrive_write_file))
        mcp.tool()(require_module("google_drive")(gdrive_update_file))
        mcp.tool()(require_module("google_drive")(gdrive_create_folder))
        mcp.tool()(require_module("google_drive")(gdrive_delete_file))


register_active_tools()

# ==========================================
# AUTHENTICATION & SECURITY MIDDLEWARE
# ==========================================

# Persistent log path for server operations
log_path = BASE_DIR / "server.log"

_failed_ip_attempts: Dict[str, Dict[str, Any]] = {}
MAX_LOCKOUT_ENTRIES = 1000


def _is_ip_locked_out(client_ip: str, now: float) -> tuple:
    """Check if client IP is currently locked out under progressive exponential backoff.
    
    Returns (is_locked_out: bool, remaining_seconds: float).
    """
    entry = _failed_ip_attempts.get(client_ip)
    if not entry:
        return False, 0.0
    lockout_until = entry.get("lockout_until", 0.0)
    if now < lockout_until:
        return True, lockout_until - now
    return False, 0.0


def _record_failed_auth(client_ip: str, now: float) -> float:
    """Record consecutive 401 failure for client IP and calculate progressive backoff.
    
    From 5 consecutive failures, delay increases exponentially: 2^n seconds (capped at 60s).
    Returns active delay in seconds.
    """
    if len(_failed_ip_attempts) >= MAX_LOCKOUT_ENTRIES:
        # Prune inactive / expired entries
        expired = [k for k, v in _failed_ip_attempts.items() if now - v.get("last_attempt", 0) > 300 and now >= v.get("lockout_until", 0)]
        for k in expired:
            _failed_ip_attempts.pop(k, None)
        while len(_failed_ip_attempts) >= MAX_LOCKOUT_ENTRIES:
            _failed_ip_attempts.pop(next(iter(_failed_ip_attempts)), None)

    entry = _failed_ip_attempts.get(client_ip, {"consecutive_failures": 0, "lockout_until": 0.0, "last_attempt": now})
    consecutive = entry.get("consecutive_failures", 0) + 1
    lockout_until = 0.0
    delay = 0.0

    if consecutive >= 5:
        n = consecutive - 5
        delay = min(60.0, float(2 ** n))
        lockout_until = now + delay

    _failed_ip_attempts[client_ip] = {
        "consecutive_failures": consecutive,
        "lockout_until": lockout_until,
        "last_attempt": now
    }
    return delay


def _record_successful_auth(client_ip: str) -> None:
    """Reset failed attempts and cooldown for client IP upon successful token authentication."""
    _failed_ip_attempts.pop(client_ip, None)


# ==========================================
# OAUTH 2.0 & RFC 7591 AUTHENTICATION SERVER
# ==========================================

OAUTH_DB_PATH = ROOT_DIR / "oauth.db"

def _init_oauth_db():
    """Initialize SQLite tables for OAuth 2.0 dynamic clients, codes, and tokens."""
    try:
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_secret TEXT,
                    client_name TEXT,
                    redirect_uris TEXT,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_codes (
                    code TEXT PRIMARY KEY,
                    client_id TEXT,
                    redirect_uri TEXT,
                    code_challenge TEXT,
                    code_challenge_method TEXT,
                    expires_at REAL,
                    used INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    access_token TEXT PRIMARY KEY,
                    refresh_token TEXT,
                    client_id TEXT,
                    expires_at REAL,
                    created_at REAL
                )
            """)
    except Exception as exc:
        print(f"[OAUTH] DB Init error: {exc}", file=sys.stderr)

_init_oauth_db()

# H-1: Rate limiting for OAuth dynamic client registration
_oauth_register_attempts: Dict[str, List[float]] = {}
OAUTH_REGISTER_MAX_PER_HOUR = 5

def _check_oauth_register_rate_limit(client_ip: str) -> bool:
    """Return True if registration is allowed, False if rate-limited."""
    now = time.time()
    window = 3600.0  # 1 hour
    attempts = _oauth_register_attempts.get(client_ip, [])
    # Prune entries older than 1 hour
    attempts = [t for t in attempts if now - t < window]
    _oauth_register_attempts[client_ip] = attempts
    if len(attempts) >= OAUTH_REGISTER_MAX_PER_HOUR:
        return False
    attempts.append(now)
    return True

# M-2: Cleanup expired OAuth codes and tokens
def _cleanup_expired_oauth_entries():
    """Remove expired authorization codes and tokens from oauth.db."""
    now = time.time()
    try:
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            conn.execute("DELETE FROM oauth_codes WHERE expires_at < ? OR used = 1", (now,))
            conn.execute("DELETE FROM oauth_tokens WHERE expires_at < ?", (now,))
            conn.commit()
    except Exception:
        pass

def _save_oauth_client(client_id: str, client_secret: str, client_name: str, redirect_uris: List[str]):
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_clients (client_id, client_secret, client_name, redirect_uris, created_at) VALUES (?, ?, ?, ?, ?)",
            (client_id, client_secret, client_name, json.dumps(redirect_uris), now)
        )
        conn.commit()


def _get_oauth_client(client_id: str) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM oauth_clients WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["redirect_uris"] = json.loads(data.get("redirect_uris", "[]"))
        except Exception:
            data["redirect_uris"] = []
        return data


def _save_oauth_code(code: str, client_id: str, redirect_uri: str, code_challenge: str, code_challenge_method: str, expires_at: float):
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO oauth_codes (code, client_id, redirect_uri, code_challenge, code_challenge_method, expires_at, used) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (code, client_id, redirect_uri, code_challenge, code_challenge_method, expires_at)
        )
        conn.commit()


def _get_and_consume_oauth_code(code: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM oauth_codes WHERE code = ? AND used = 0", (code,))
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        if now > data["expires_at"]:
            return None
        cur.execute("UPDATE oauth_codes SET used = 1 WHERE code = ?", (code,))
        conn.commit()
        return data


def _save_oauth_token(access_token: str, refresh_token: str, client_id: str, expires_at: float):
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO oauth_tokens (access_token, refresh_token, client_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (access_token, refresh_token, client_id, expires_at, now)
        )
        conn.commit()


def _is_valid_oauth_token(token: str) -> bool:
    if not token or not token.startswith("mcp_at_"):
        return False
    now = time.time()
    try:
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT expires_at FROM oauth_tokens WHERE access_token = ?", (token,))
            row = cur.fetchone()
            if row and now < row[0]:
                return True
    except Exception:
        pass
    return False


def _refresh_oauth_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    if not refresh_token:
        return None
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM oauth_tokens WHERE refresh_token = ?", (refresh_token,))
        row = cur.fetchone()
        if not row:
            return None
        new_access_token = f"mcp_at_{secrets.token_urlsafe(32)}"
        new_refresh_token = f"mcp_rt_{secrets.token_urlsafe(32)}"  # H-3: Rotate refresh token
        new_expires_at = now + 2592000
        cur.execute("UPDATE oauth_tokens SET access_token = ?, refresh_token = ?, expires_at = ? WHERE refresh_token = ?",
                    (new_access_token, new_refresh_token, new_expires_at, refresh_token))
        conn.commit()
        # M-2: Opportunistic cleanup of expired entries
        _cleanup_expired_oauth_entries()
        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,  # H-3: Return new refresh token
            "expires_in": 2592000,
            "token_type": "Bearer"
        }


def _verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    if not code_challenge or not code_verifier:
        return False
    # Enforce S256 only per RFC 7636 / OAuth 2.1 best practices (plain is deprecated and insecure)
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return secrets.compare_digest(computed, code_challenge.rstrip("="))
    return False


def _get_base_url(request: Request) -> str:
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    custom = server_cfg.get("custom_public_url", "").strip() or server_cfg.get("cloudflare_custom_url", "").strip() or server_cfg.get("ngrok_custom_url", "").strip()
    if custom:
        return custom.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", f"{request.url.hostname}:{request.url.port}"))
    if ".ts.net" in host or ".trycloudflare.com" in host or ".serveousercontent.com" in host or "ngrok" in host:
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


async def oauth_protected_resource(request: Request):
    base_url = _get_base_url(request).rstrip("/")
    return JSONResponse({
        "resource": base_url,
        "authorization_servers": [base_url]
    })


async def oauth_authorization_server(request: Request):
    base_url = _get_base_url(request).rstrip("/")
    return JSONResponse({
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"]
    })


async def oauth_register(request: Request):
    # H-1: Rate limiting — max 5 registrations per hour per IP
    client_ip = request.client.host if request.client else "unknown"
    if not _check_oauth_register_rate_limit(client_ip):
        return JSONResponse(
            {"error": "too_many_requests", "error_description": "Registration rate limit exceeded. Try again later."},
            status_code=429
        )

    # H-1b: Optional registration_token gate — if configured, only bearers of this token may register
    cfg = load_config()
    reg_token = cfg.get("server", {}).get("registration_token", "").strip()
    if reg_token:
        auth_header = request.headers.get("authorization", "")
        provided = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        if not provided or not secrets.compare_digest(provided, reg_token):
            return JSONResponse(
                {"error": "unauthorized", "error_description": "Valid registration_token required for dynamic client registration."},
                status_code=401
            )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request", "error_description": "Invalid JSON body"}, status_code=400)
    client_name = body.get("client_name", "Mammouth AI")
    redirect_uris = body.get("redirect_uris", [])
    if isinstance(redirect_uris, str):
        redirect_uris = [redirect_uris]
    client_id = f"mcp_{secrets.token_hex(16)}"
    client_secret = secrets.token_urlsafe(32)
    _save_oauth_client(client_id, client_secret, client_name, redirect_uris)
    return JSONResponse({
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"]
    }, status_code=201)


async def oauth_authorize(request: Request):
    if request.method == "GET":
        params = request.query_params
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        response_type = params.get("response_type", "code")
        state = params.get("state", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "S256")

        client_info = _get_oauth_client(client_id) if client_id else None
        client_name = client_info.get("client_name", "Mammouth AI") if client_info else "Mammouth AI"

        consent_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mammouth Defroster 9000 — Autorisierung</title>
    <style>
        body {{
            background-color: #0B0D13;
            color: #E2E8F0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
        }}
        .card {{
            background: #141721;
            border: 1px solid #232936;
            border-radius: 16px;
            width: 100%;
            max-width: 460px;
            padding: 32px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
            text-align: center;
        }}
        .logo {{
            font-size: 38px;
            margin-bottom: 12px;
        }}
        h2 {{
            font-size: 22px;
            margin: 0 0 6px 0;
            color: #F8FAFC;
        }}
        .subtitle {{
            font-size: 14px;
            color: #94A3B8;
            margin-bottom: 20px;
        }}
        .badge {{
            display: inline-block;
            background: rgba(16, 185, 129, 0.15);
            color: #10B981;
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 20px;
        }}
        .info-box {{
            background: #1A1F2C;
            border: 1px solid #2D3748;
            border-radius: 10px;
            padding: 16px;
            text-align: left;
            font-size: 13px;
            color: #CBD5E1;
            margin-bottom: 24px;
            line-height: 1.5;
        }}
        .buttons {{
            display: flex;
            gap: 12px;
        }}
        button {{
            flex: 1;
            padding: 12px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }}
        .btn-allow {{
            background: #10B981;
            color: #FFFFFF;
        }}
        .btn-allow:hover {{
            background: #059669;
        }}
        .btn-deny {{
            background: #232936;
            color: #94A3B8;
        }}
        .btn-deny:hover {{
            background: #2D3748;
            color: #E2E8F0;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">🦣 ⚡</div>
        <h2>Mammouth Defroster 9000</h2>
        <div class="subtitle">MCP Verbindungsanfrage</div>
        <div class="badge">● Sicherer MCP OAuth 2.0 Flow</div>
        <div class="info-box">
            <strong>{html.escape(client_name)}</strong> möchte sich mit deinem lokalen Defroster 9000 verbinden.<br><br>
            Dies gewährt Zugriff auf sandboxed MCP-Tools (Dateien, Desktop, Google Drive, Aufgaben & Automatisierung) auf diesem Host.
        </div>
        <form method="POST" action="/oauth/authorize">
            <input type="hidden" name="client_id" value="{html.escape(client_id)}">
            <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}">
            <input type="hidden" name="response_type" value="{html.escape(response_type)}">
            <input type="hidden" name="state" value="{html.escape(state)}">
            <input type="hidden" name="code_challenge" value="{html.escape(code_challenge)}">
            <input type="hidden" name="code_challenge_method" value="{html.escape(code_challenge_method)}">
            <div class="buttons">
                <button type="submit" name="action" value="deny" class="btn-deny">Ablehnen</button>
                <button type="submit" name="action" value="allow" class="btn-allow">Zugriff erlauben</button>
            </div>
        </form>
    </div>
</body>
</html>"""
        return HTMLResponse(consent_html)

    elif request.method == "POST":
        form = await request.form()
        action = form.get("action", "deny")
        client_id = form.get("client_id", "")
        redirect_uri = form.get("redirect_uri", "")
        state = form.get("state", "")
        code_challenge = form.get("code_challenge", "")
        code_challenge_method = form.get("code_challenge_method", "S256")

        if not redirect_uri:
            redirect_uri = "https://mammouth.ai/api/mcp/oauth/callback"

        # H-2: Validate redirect_uri against registered client URIs (normalized without trailing slashes)
        if client_id:
            client_data = _get_oauth_client(client_id)
            if client_data:
                registered_uris = client_data.get("redirect_uris", [])
                norm_redirect = redirect_uri.rstrip("/")
                norm_registered = [u.rstrip("/") for u in registered_uris]
                if registered_uris and norm_redirect not in norm_registered:
                    return JSONResponse(
                        {"error": "invalid_request", "error_description": "redirect_uri does not match any registered URI for this client."},
                        status_code=400
                    )

        delim = "&" if "?" in redirect_uri else "?"

        if action == "allow":
            code = f"mc_{secrets.token_urlsafe(32)}"
            _save_oauth_code(code, client_id, redirect_uri, code_challenge, code_challenge_method, time.time() + 600)
            target = f"{redirect_uri}{delim}code={urllib.parse.quote(code)}"
            if state:
                target += f"&state={urllib.parse.quote(state)}"
            return RedirectResponse(target, status_code=302)
        else:
            target = f"{redirect_uri}{delim}error=access_denied&error_description=User+denied+authorization"
            if state:
                target += f"&state={urllib.parse.quote(state)}"
            return RedirectResponse(target, status_code=302)


async def oauth_token(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
    else:
        form = await request.form()
        body = dict(form)

    # Support HTTP Basic Auth for client credentials (RFC 6749 Section 2.3.1)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Basic "):
        try:
            creds = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            if ":" in creds:
                basic_cid, basic_csec = creds.split(":", 1)
                if not body.get("client_id"):
                    body["client_id"] = basic_cid
                if not body.get("client_secret"):
                    body["client_secret"] = basic_csec
        except Exception:
            pass

    grant_type = body.get("grant_type", "")

    if grant_type == "authorization_code":
        code = body.get("code", "")
        code_verifier = body.get("code_verifier", "")
        client_id = body.get("client_id", "")

        code_data = _get_and_consume_oauth_code(code)
        if not code_data:
            return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}, status_code=400)

        challenge = code_data.get("code_challenge", "")
        method = code_data.get("code_challenge_method", "S256")
        if challenge:
            if not _verify_pkce(code_verifier, challenge, method):
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

        access_token = f"mcp_at_{secrets.token_urlsafe(32)}"
        refresh_token = f"mcp_rt_{secrets.token_urlsafe(32)}"
        expires_in = 2592000  # 30 days
        _save_oauth_token(access_token, refresh_token, client_id or code_data.get("client_id", ""), time.time() + expires_in)

        return JSONResponse({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "refresh_token": refresh_token,
            "scope": "mcp"
        })

    elif grant_type == "refresh_token":
        refresh_token = body.get("refresh_token", "")
        new_tokens = _refresh_oauth_token(refresh_token)
        if not new_tokens:
            return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}, status_code=400)
        return JSONResponse(new_tokens)

    return JSONResponse({"error": "unsupported_grant_type", "error_description": f"Grant type '{grant_type}' not supported"}, status_code=400)


class SecurityAndAuthMiddleware:
    """Handles constant-time Bearer token authentication, progressive IP backoff, fail-closed enforcement, OPTIONS preflight, security headers, and safe logging."""
    def __init__(self, app: ASGIApp, token: str = "", enforce_auth: bool = True):
        self.app = app
        self.enforce_auth = enforce_auth
        self.token = str(token).strip()
        # H-1 Fix: Fail closed — if enforce_auth is True, ensure a non-empty token is present
        if self.enforce_auth and not self.token:
            import secrets
            self.token = f"mc_{secrets.token_urlsafe(32)}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            raw_headers = list(scope.get("headers", []))
            header_map = {k.decode("latin1").lower(): v.decode("latin1") for k, v in raw_headers}
            client_ip = scope.get("client", ("unknown", 0))[0]
            method = scope.get("method", "GET")
            path = scope.get("path", "/")
            clean_path = "/" + path.lstrip("/")

            # Wrapped send to inject standard security response headers (L-05)
            async def send_with_security_headers(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-content-type-options", b"nosniff"))
                    # Anti-clickjacking: DENY by default; for OAuth consent endpoints, restrict framing to mammouth.ai and self
                    if clean_path.startswith("/oauth/"):
                        headers.append((b"content-security-policy", b"frame-ancestors 'self' https://mammouth.ai"))
                    else:
                        headers.append((b"x-frame-options", b"DENY"))
                    headers.append((b"referrer-policy", b"no-referrer"))
                    headers.append((b"x-xss-protection", b"1; mode=block"))
                    headers.append((b"cache-control", b"no-store, no-cache, must-revalidate, private"))
                    headers.append((b"pragma", b"no-cache"))
                    # Support Chromium Private Network Access (PNA) for in-app browser & local network
                    headers.append((b"access-control-allow-private-network", b"true"))
                    if message.get("status") == 401:
                        proto = header_map.get("x-forwarded-proto", "https" if (".ts.net" in header_map.get("host", "") or ".trycloudflare.com" in header_map.get("host", "")) else "http")
                        host = header_map.get("x-forwarded-host", header_map.get("host", "127.0.0.1:8000"))
                        base_meta_url = f"{proto}://{host}".rstrip("/")
                        headers.append((b"www-authenticate", f'Bearer error="unauthorized", resource_metadata="{base_meta_url}/.well-known/oauth-protected-resource"'.encode("latin1")))
                    message["headers"] = headers
                await send(message)

            # L-03: CORS Preflight OPTIONS requests must bypass auth unconditionally
            if method == "OPTIONS":
                await self.app(scope, receive, send_with_security_headers)
                return

            # OAuth 2.0 Discovery & Endpoints bypass pre-authentication
            if clean_path.startswith("/.well-known/") or clean_path.startswith("/oauth/"):
                await self.app(scope, receive, send_with_security_headers)
                return

            # Fail-closed authentication check
            if self.enforce_auth:
                now = time.time()
                is_locked, remaining_delay = _is_ip_locked_out(client_ip, now)
                if is_locked:
                    response = JSONResponse(
                        {"error": "TooManyRequests", "message": f"Too many failed authentication attempts. Progressive cooldown active ({int(remaining_delay) + 1}s remaining)."},
                        status_code=429
                    )
                    await response(scope, receive, send_with_security_headers)
                    return

                auth_header = header_map.get("authorization", "")
                provided_token = ""
                if auth_header.startswith("Bearer "):
                    provided_token = auth_header[7:].strip()
                elif not provided_token:
                    qs = scope.get("query_string", b"").decode("latin1")
                    if "token=" in qs:
                        from urllib.parse import parse_qs
                        q_map = parse_qs(qs)
                        if "token" in q_map and q_map["token"]:
                            provided_token = q_map["token"][0].strip()

                is_valid = False
                if provided_token:
                    if self.token and secrets.compare_digest(provided_token, self.token):
                        is_valid = True
                    elif _is_valid_oauth_token(provided_token):
                        is_valid = True

                if not is_valid:
                    _record_failed_auth(client_ip, now)
                    response = JSONResponse(
                        {"error": "Unauthorized", "message": "Invalid or missing Bearer API authentication token."},
                        status_code=401
                    )
                    await response(scope, receive, send_with_security_headers)
                    return
                else:
                    # Successful auth: reset failure counter for IP
                    _record_successful_auth(client_ip)

            # Header normalization for MCP cloud compatibility
            accept = header_map.get("accept", "")
            if not accept or accept == "*/*" or "application/json" not in accept:
                new_headers = [(k, v) for k, v in raw_headers if k.lower() != b"accept"]
                new_headers.append((b"accept", b"application/json, text/event-stream, */*"))
                scope["headers"] = new_headers

            await self.app(scope, receive, send_with_security_headers)
        else:
            await self.app(scope, receive, send)


def build_app(token: Optional[str] = None):
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    enforce_auth = server_cfg.get("enforce_auth", True)
    
    # Determine effective token
    effective_token = token
    if effective_token is None:
        if enforce_auth:
            effective_token = server_cfg.get("api_token", "") or os.environ.get("MCP_API_TOKEN", "")
            if not effective_token:
                import secrets
                effective_token = f"mc_{secrets.token_urlsafe(32)}"
                server_cfg["api_token"] = effective_token
                try:
                    from config import save_config
                    save_config(cfg)
                except Exception:
                    pass
        else:
            effective_token = ""
    elif enforce_auth and not effective_token:
        import secrets
        effective_token = f"mc_{secrets.token_urlsafe(32)}"

    streamable_http_app = StreamableHTTPASGIApp(None)
    
    routes = [
        Route("/", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/mcp", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/sse", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/messages", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/.well-known/oauth-authorization-server", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/oauth/register", endpoint=oauth_register, methods=["POST", "OPTIONS"]),
        Route("/oauth/authorize", endpoint=oauth_authorize, methods=["GET", "POST", "OPTIONS"]),
        Route("/oauth/token", endpoint=oauth_token, methods=["POST", "OPTIONS"]),
    ]

    @asynccontextmanager
    async def lifespan(app) -> AsyncGenerator[None, None]:
        streamable_http_app.session_manager = FastMCPStreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=True,
            stateless=True,
        )
        async with mcp._lifespan_manager(), streamable_http_app.session_manager.run():
            yield

    # Stricter CORS settings: Restrict origins to Mammouth and localhost
    configured_origins = server_cfg.get("allowed_origins", [
        "https://mammouth.ai",
        "https://app.mammouth.ai",
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://localhost:8000"
    ])

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=configured_origins,
            allow_origin_regex=r"^https://([a-zA-Z0-9-]+\.)?mammouth\.ai$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
            allow_methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
            allow_headers=["*"],
            expose_headers=["*"],
            allow_credentials=True,
            allow_private_network=True,
        ),
        Middleware(SecurityAndAuthMiddleware, token=effective_token or "", enforce_auth=enforce_auth),
    ]

    return create_base_app(routes=routes, middleware=middleware, lifespan=lifespan)


def generate_self_signed_cert(cert_path: str, key_path: str, hostname: str = "localhost") -> bool:
    """Generate self-signed SSL certificate for local LAN development."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime
        import ipaddress

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mammouth Defroster 9000 Local TLS"),
        ])
        alt_names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan_ip = ipaddress.IPv4Address(hostname)
            alt_names.append(x509.IPAddress(lan_ip))
        except Exception:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
            .sign(key, hashes.SHA256())
        )
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception:
        return False


app = build_app()

if __name__ == "__main__":
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    port = int(os.environ.get("PORT", server_cfg.get("port", 8000)))
    host = os.environ.get("HOST", server_cfg.get("host", "127.0.0.1"))
    enable_tls = server_cfg.get("enable_tls", False)
    cert_file = server_cfg.get("ssl_certfile")
    key_file = server_cfg.get("ssl_keyfile")

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if enable_tls and (not cert_file or not os.path.exists(str(cert_file))):
        default_cert = str(ROOT_DIR / "cert.pem")
        default_key = str(ROOT_DIR / "key.pem")
        if not os.path.exists(default_cert):
            print("[TLS] Generating self-signed TLS certificate for local network security...")
            generate_self_signed_cert(default_cert, default_key, host)
        cert_file = default_cert
        key_file = default_key

    proto = "https" if enable_tls else "http"
    print(f"Starting Mammouth Defroster 9000 on {proto}://{host}:{port}...")

    if not enable_tls and host not in ("127.0.0.1", "localhost"):
        print("\n=======================================================")
        print("[SECURITY NOTICE] Server is bound to external interface")
        print(f"   without TLS encryption ({host}:{port}).")
        print("   All traffic within your LAN will be transmitted in plaintext.")
        print("   Enable 'server.enable_tls: true' in config for HTTPS.")
        print("=======================================================\n")

    if server_cfg.get("enforce_auth", True):
        print("[AUTH] Token Authentication: ACTIVE (Secure by Default)")
    else:
        print("\n[WARNING] Authentication is DISABLED. Server is open to all clients on your network!")
        if host == "0.0.0.0":
            print("[CRITICAL WARNING] Binding to 0.0.0.0 without authentication is dangerous and exposes your machine!\n")

    uvicorn_kwargs = {
        "app": app,
        "host": host,
        "port": port,
        "log_level": "info",
        "use_colors": False
    }
    if enable_tls and cert_file and os.path.exists(cert_file):
        uvicorn_kwargs["ssl_certfile"] = cert_file
        uvicorn_kwargs["ssl_keyfile"] = key_file

    uvicorn.run(**uvicorn_kwargs)
