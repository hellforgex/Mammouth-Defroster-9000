import os
import sys
import shutil
import json
import html
import secrets
import functools
import re
import time
import hashlib
from pathlib import Path
from typing import Any
from collections.abc import AsyncGenerator

import asyncio
import base64
import logging
import sqlite3

logger = logging.getLogger("mammouth.server")
import urllib.parse
import subprocess
import threading
import uvicorn
from contextlib import asynccontextmanager
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, HTMLResponse, RedirectResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings

# Fix sys.path and application root for standalone bundled environment
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

ROOT_DIR = BASE_DIR
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastmcp import FastMCP, Context
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

from config import load_config, save_config, _encrypt_dpapi, _decrypt_dpapi, TOOL_PROFILES

# Import modular capabilities
from modules.memory import memory_save_clean, memory_recall_clean, memory_delete_clean
from modules.tasks_kanban import task_board
from modules.file_ops import (
    file_read_clean,
    file_write_clean,
    file_replace_chunk_clean,
    file_search_text_clean,
    directory_list_clean,
)
from modules.shell_processes import (
    powershell_exec_clean,
    powershell_exec,
    desktop_open,
    process_manage,
)
from modules.putty_ssh import (
    ssh_hosts,
    ssh_exec_command,
    ssh_transfer_file,
)
from modules.system_monitor import (
    system_specs_dispatch,
    system_get_processes,
    system_event_logs,
)
from modules.screen_capture import (
    screen_capture_dispatch,
    screen_windows,
)
from modules.workspace_indexer import workspace_code_search
from modules.smart_clipboard import clipboard_manage
from modules.web_tools import web_fetch
from modules.browser_agent import (
    browser_navigate,
    browser_inspect,
    browser_interact,
    browser_evaluate,
    browser_session,
    init_browser_agent
)
from modules.desktop_input import (
    desktop_get_screen_info,
    desktop_mouse,
    desktop_keyboard,
)
from modules.mammouth_code import mammouth_code_dispatch
from modules.claude_code import claude_code_dispatch, get_claude_code_status as claude_code_status
from modules.task_scheduler import (
    scheduler_create_task,
    scheduler_list_tasks,
    scheduler_update_task,
    scheduler_delete_task,
    scheduler_pause_task,
    scheduler_resume_task,
    scheduler_trigger_task_now,
    scheduler_get_presets,
    scheduler_get_history,
    task_schedule_manage,
)
from modules.google_drive import (
    gdrive_list,
    gdrive_read,
    gdrive_write,
    gdrive_manage,
)


# Initialize FastMCP Server with streamlined 42-tool capability surface
mcp = FastMCP(
    name="Mammouth-Defroster-9000",
    instructions="""Mammouth Defroster 9000 (v0.8.2): Streamlined Windows Cockpit & Tool Hub for ChatGPT, Claude, and Mammouth.ai.
Core capabilities (42 consolidated tools total across all 16 modules):
- Files & Code Search: 'file_read', 'file_write', 'file_replace_chunk', 'file_search_text', 'directory_list', 'workspace_code_search'
- Shell & Apps: 'powershell_exec' (PowerShell/CMD), 'desktop_open', 'process_manage'
- Desktop Vision & Input: 'screen_capture', 'screen_windows', 'desktop_get_screen_info', 'desktop_mouse', 'desktop_keyboard'
- Browser (Playwright): 'browser_navigate', 'browser_inspect', 'browser_interact', 'browser_evaluate', 'browser_session'
- System & Memory: 'system_get_specs', 'system_get_processes', 'system_event_logs', 'memory_save', 'memory_recall', 'memory_delete', 'clipboard_manage'
- Tasks & Cloud: 'task_board', 'task_schedule_create', 'task_schedule_manage', 'gdrive_*', 'ssh_*', 'mammouth_code', 'claude_code', 'web_fetch'

Use 'defroster_catalog' to inspect categories or switch profiles, and 'defroster_execute_tool' for on-demand profile execution.
Use 'system_get_specs' (field 'known_folders') to resolve the user's real Desktop/Documents/Downloads paths instead of guessing.
If AGENTS.md or SYSTEM.md exists in the workspace root, read it first when working on a project there.
'file_read' and 'file_search_text' skip credential files (.env, tokens, oauth.db) unless server.protect_secret_files is disabled.
Write scripts via 'file_write' and run them locally via 'powershell_exec' ($0 cost)."""
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


def local_exec_command(command: str, cwd: str = "", timeout: int = 600) -> dict:
    """Run a shell command on this Windows host, scoped to the configured workspace root.

    Executes the command via PowerShell (preserving quotes, backslashes, and multiline commands 1:1)
    and captures stdout, stderr, and exit code.
    The cwd is whitelisted to only allow directories under the configured workspace root (relative paths
    are anchored directly to the workspace root).
    Commands are validated against the security blocklist and read-only allowlist.
    """
    t0 = time.perf_counter()
    raw_cmd = str(command or "").strip()
    # Strip wrapping quotes if the whole command was accidentally quoted by the caller
    if (raw_cmd.startswith('"') and raw_cmd.endswith('"')) or (raw_cmd.startswith("'") and raw_cmd.endswith("'")):
        raw_cmd = raw_cmd[1:-1].strip()

    if not raw_cmd:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "error",
            "error_code": "ERR_EMPTY_COMMAND",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": "Command cannot be empty.",
            "exit_code": -1,
            "error": "Empty command"
        }

    # --- Security Gate: validate command against shell blocklist & allowlist ---
    try:
        from modules.shell_processes import _validate_shell_command
        # Execute exactly the command string that was validated
        raw_cmd = _validate_shell_command(raw_cmd)
    except PermissionError as ex:
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
    except Exception as ex:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "error",
            "error_code": "ERR_VALIDATION",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Command validation error: {ex}",
            "exit_code": -1,
            "error": str(ex)
        }

    # --- Dynamic cwd whitelist: anchor relative cwd to workspace root ---
    from modules.shell_processes import resolve_workspace_root
    workdir_root = resolve_workspace_root()
    timeout = max(1, min(int(timeout or 600), 600))

    clean_cwd = str(cwd or "").strip().strip("'\"").strip()
    if clean_cwd:
        is_abs = os.path.isabs(clean_cwd) or (len(clean_cwd) >= 2 and clean_cwd[1] == ':')
        if not is_abs:
            # Anchor relative cwd to workspace root
            clean_cwd = os.path.join(workdir_root, clean_cwd.lstrip("/\\"))
        resolved_cwd = os.path.realpath(os.path.abspath(clean_cwd))
    else:
        resolved_cwd = workdir_root

    # Enforce workspace root boundary
    if not (resolved_cwd == workdir_root or resolved_cwd.startswith(workdir_root + os.sep) or resolved_cwd.startswith(workdir_root + "/")):
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "permission_denied",
            "error_code": "ERR_SECURITY_PATH",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Security: cwd '{cwd}' resolves to '{resolved_cwd}' which is outside the allowed workspace '{workdir_root}'.",
            "exit_code": -1,
            "error": f"cwd not in {workdir_root} scope"
        }

    if not os.path.exists(resolved_cwd):
        if resolved_cwd == workdir_root:
            try:
                os.makedirs(resolved_cwd, exist_ok=True)
            except Exception:
                pass
        if not os.path.exists(resolved_cwd):
            duration_ms = round((time.perf_counter() - t0) * 1000)
            return {
                "status": "error",
                "error_code": "ERR_DIRECTORY_NOT_FOUND",
                "duration_ms": duration_ms,
                "stdout": "",
                "stderr": f"Directory not found: '{resolved_cwd}'",
                "exit_code": -1,
                "error": "DirectoryNotFound"
            }

    try:
        # Execute via PowerShell directly with shell=False to pass raw_cmd 1:1 including quotes and backslashes
        from modules.shell_processes import run_process_tree, POWERSHELL_UTF8_PREFIX
        stdout, stderr, returncode = run_process_tree(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_UTF8_PREFIX + raw_cmd],
            cwd=resolved_cwd,
            timeout=timeout,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "success" if returncode == 0 else "error",
            "error_code": None if returncode == 0 else "ERR_COMMAND_FAILED",
            "duration_ms": duration_ms,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "exit_code": returncode,
            "error": None
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "timeout",
            "error_code": "ERR_TIMEOUT",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "exit_code": -1,
            "error": f"TimeoutExpired({timeout}s)"
        }
    except Exception as ex:
        duration_ms = round((time.perf_counter() - t0) * 1000)
        return {
            "status": "error",
            "error_code": "ERR_PROCESS_ERROR",
            "duration_ms": duration_ms,
            "stdout": "",
            "stderr": str(ex),
            "exit_code": -1,
            "error": str(ex)
        }


def task_schedule_create(
    name: str,
    prompt: str,
    interval_minutes: float = 5.0,
    repeat_count: int = 0,
    target: str = "auto",
    start_immediately: bool = False
) -> dict[str, Any]:
    """Schedule a recurring task in Defroster GUI or CLI.

    Args:
        name: Short task title.
        prompt: Prompt or command to run on each trigger.
        interval_minutes: Minutes between runs (default 5.0, min 0.2).
        repeat_count: Max runs (0 = continuous).
        target: 'auto' (active web tab), 'chatgpt_web', 'claude_web', 'mammouth_web', 'mammouth_code', 'powershell', or 'notification'.
        start_immediately: Run first execution immediately (in ~1s) instead of waiting one interval.
    """
    resolved_target = str(target or "auto").strip().lower()
    if resolved_target in ("", "auto", "default", "web"):
        try:
            default_tab = str(load_config().get("embedded_browser", {}).get("default_chat_tab", "chatgpt")).strip().lower()
            if default_tab == "mammouth":
                resolved_target = "mammouth_web"
            elif default_tab == "claude":
                resolved_target = "claude_web"
            else:
                resolved_target = "chatgpt_web"
        except Exception:
            resolved_target = "chatgpt_web"
    interval_seconds = max(10, int(float(interval_minutes) * 60))
    return scheduler_create_task(
        name=name,
        prompt=prompt,
        interval_seconds=interval_seconds,
        repeat_count=repeat_count,
        target=resolved_target,
        auto_submit=True,
        switch_tab=True,
        start_immediately=start_immediately
    )


def task_schedule_list(status: str | None = None) -> list[dict[str, Any]]:
    """List all scheduled automation tasks (active, paused, completed)."""
    return scheduler_list_tasks(status=status)


def task_schedule_control(task_id: int, action: str) -> dict[str, Any]:
    """Control a scheduled task.

    Args:
        task_id: Scheduled task ID.
        action: 'pause', 'resume', 'trigger', 'stop', 'test_run', 'dry_run', or 'history'.
    """
    act = str(action).lower().strip()
    if act == "pause":
        return scheduler_pause_task(task_id)
    elif act == "resume":
        return scheduler_resume_task(task_id)
    elif act in ("trigger_now", "trigger"):
        return scheduler_trigger_task_now(task_id)
    elif act in ("stop", "abort"):
        return scheduler_update_task(task_id, status="stopped")
    elif act == "test_run":
        from modules.task_scheduler import scheduler_test_run
        return scheduler_test_run(task_id, dry_run=False)
    elif act in ("preview", "dry_run"):
        from modules.task_scheduler import scheduler_test_run
        return scheduler_test_run(task_id, dry_run=True)
    elif act == "history":
        from modules.task_scheduler import scheduler_get_history
        return {"status": "success", "task_id": task_id, "history": scheduler_get_history(task_id)}
    return {"error": f"Unknown action '{action}'. Valid: 'pause', 'resume', 'trigger', 'stop', 'test_run', 'dry_run', 'history'"}


def task_schedule_get_history(task_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Get past execution runs and logs for a scheduled task.
    
    Args:
        task_id: ID of the scheduled task.
        limit: Maximum number of execution records to return (default 20).
    """
    return scheduler_get_history(task_id=task_id, limit=limit)


def task_schedule_delete(task_id: int) -> str:
    """Delete a scheduled task by ID."""
    return scheduler_delete_task(task_id)


def task_schedule_get_presets() -> list[dict[str, Any]]:
    """Get available pre-configured task templates (e.g. football live ticker, crypto prices, system health)."""
    return scheduler_get_presets()



_DEFROSTER_MODULE_CATALOG: dict[str, dict[str, Any]] = {
    "files": {
        "module": "file_ops",
        "title": "File Operations & Workspace Sandbox",
        "description": "Read, write, edit, search, and list files inside the workspace sandbox.",
        "tools": [
            {"name": "file_read", "desc": "Read text file with optional line slicing."},
            {"name": "file_write", "desc": "Write or overwrite file content."},
            {"name": "file_replace_chunk", "desc": "Replace targeted text snippet in a file."},
            {"name": "file_search_text", "desc": "Search text or regex patterns across workspace files."},
            {"name": "directory_list", "desc": "List directory contents (flat or recursive tree)."}
        ]
    },
    "shell": {
        "module": "shell_processes",
        "title": "PowerShell & Shell Execution",
        "description": "Execute local PowerShell/CMD commands, launch desktop targets, manage background processes.",
        "tools": [
            {"name": "powershell_exec", "desc": "Execute PowerShell or cmd.exe command inside workspace."},
            {"name": "desktop_open", "desc": "Open a file, folder, or URL with default Windows app."},
            {"name": "process_manage", "desc": "Start, list, inspect output, or kill background processes."}
        ]
    },
    "browser": {
        "module": "browser_agent",
        "title": "Autonomous Browser Agent",
        "description": "Playwright web automation: navigate, inspect DOM/screenshots, interact, evaluate JS, manage tabs.",
        "tools": [
            {"name": "browser_navigate", "desc": "Navigate browser to a URL."},
            {"name": "browser_inspect", "desc": "Inspect page (snapshot, screenshot, markdown, text, html)."},
            {"name": "browser_interact", "desc": "Interact with page (click, double_click, right_click, fill, press_key, hover, scroll)."},
            {"name": "browser_evaluate", "desc": "Execute JavaScript in browser context."},
            {"name": "browser_session", "desc": "Check status, manage tabs, restart, or close browser."}
        ]
    },
    "screen": {
        "module": "screen_capture",
        "title": "Screen Capture & Desktop Vision",
        "description": "Capture desktop monitors or application windows and inspect window/display metadata.",
        "tools": [
            {"name": "screen_capture", "desc": "Capture screenshot of active_window, fullscreen monitor, tracked window, or title/handle."},
            {"name": "screen_windows", "desc": "List open windows, list monitors, or get/set tracked window."}
        ]
    },
    "desktop": {
        "module": "desktop_input",
        "title": "Desktop Mouse & Keyboard Input",
        "description": "Query display geometry/cursor coordinates and simulate hardware mouse and keyboard input.",
        "tools": [
            {"name": "desktop_get_screen_info", "desc": "Get display resolution and current cursor coordinates."},
            {"name": "desktop_mouse", "desc": "Perform mouse click, move, drag, or scroll."},
            {"name": "desktop_keyboard", "desc": "Type text, press keys, or trigger keyboard hotkeys."}
        ]
    },
    "system": {
        "module": "system_monitor",
        "title": "System Hardware & Process Monitor",
        "description": "Query CPU/RAM/GPU specs, top processes, and Windows event logs.",
        "tools": [
            {"name": "system_get_specs", "desc": "Get CPU, RAM, storage, OS, and optional GPU specs."},
            {"name": "system_get_processes", "desc": "List top running processes by CPU or memory."},
            {"name": "system_event_logs", "desc": "Query Windows event logs or list available event channels."}
        ]
    },
    "scheduler": {
        "module": "task_scheduler",
        "title": "Task Scheduler & Automation Engine",
        "description": "Schedule recurring prompts (ChatGPT Web / Claude Web / Mammouth Web) or scripts and manage scheduled jobs.",
        "tools": [
            {"name": "task_schedule_create", "desc": "Create recurring task (interval_minutes, prompt, target='auto'|'chatgpt_web'|'claude_web'|'mammouth_web'|'powershell')."},
            {"name": "task_schedule_manage", "desc": "List, presets, pause, resume, trigger, stop, test_run, dry_run, history, or delete tasks."}
        ]
    },
    "gdrive": {
        "module": "google_drive",
        "title": "Google Drive Cloud Integration",
        "description": "List, search, read, download, write, upload, and manage Google Drive files.",
        "tools": [
            {"name": "gdrive_list", "desc": "List folder contents or search Google Drive globally."},
            {"name": "gdrive_read", "desc": "Read text/Docs/Sheets content, fetch metadata, or download to workspace."},
            {"name": "gdrive_write", "desc": "Create, update, upload from workspace, or create Drive folders."},
            {"name": "gdrive_manage", "desc": "Check Google Drive auth status or trash/delete files."}
        ]
    },
    "clipboard": {
        "module": "smart_clipboard",
        "title": "Smart Clipboard",
        "description": "Read, update, and clean/format system clipboard text.",
        "tools": [
            {"name": "clipboard_manage", "desc": "Get, set, or clean/format clipboard text."}
        ]
    },
    "memory": {
        "module": "memory",
        "title": "Sovereign Long-Term Memory & RAG",
        "description": "Persistent key-value and semantic memory storage across sessions.",
        "tools": [
            {"name": "memory_save", "desc": "Save or update a persistent memory entry."},
            {"name": "memory_recall", "desc": "Search memories semantically, fetch by key, or list entries."},
            {"name": "memory_delete", "desc": "Delete a memory entry by key."}
        ]
    },
    "tasks": {
        "module": "tasks_kanban",
        "title": "Local Kanban Task Board",
        "description": "Track local project tasks and status in SQLite Kanban storage.",
        "tools": [
            {"name": "task_board", "desc": "List, create, update, or delete local Kanban tasks."}
        ]
    },
    "workspace": {
        "module": "workspace_memory",
        "title": "Workspace Code Index & RAG",
        "description": "Full-text SQLite FTS5 code search and Python AST symbol extraction.",
        "tools": [
            {"name": "workspace_code_search", "desc": "Search code, find symbols, re-index workspace, or check index stats."}
        ]
    },
    "ssh": {
        "module": "putty_ssh",
        "title": "PuTTY & SSH Remote Management",
        "description": "Manage saved SSH profiles and execute remote commands or SFTP/SCP transfers.",
        "tools": [
            {"name": "ssh_hosts", "desc": "List saved SSH profiles, list PuTTY registry sessions, save host, or open PuTTY."},
            {"name": "ssh_exec_command", "desc": "Execute a shell command over SSH on a remote host."},
            {"name": "ssh_transfer_file", "desc": "Upload or download files over SCP/SFTP."}
        ]
    },
    "mammouth": {
        "module": "mammouth_code",
        "title": "Mammouth Code CLI Agent",
        "description": "Check status, install/update, sync MCP config, launch terminal, or run tasks via Mammouth Code.",
        "tools": [
            {"name": "mammouth_code", "desc": "Manage or execute Mammouth Code CLI (status, install, sync_mcp, launch_terminal, run_task)."}
        ]
    },
    "claude": {
        "module": "claude_code",
        "title": "Claude Code CLI & Cloud Sessions",
        "description": "Check Claude Code status, sync .mcp.json, launch terminal, or execute CLI/cloud tasks.",
        "tools": [
            {"name": "claude_code", "desc": "Manage or run Claude Code CLI & cloud sessions (status, sync_mcp, launch_terminal, run_task)."}
        ]
    },
    "web": {
        "module": "web_tools",
        "title": "SSRF-Shielded Web Fetch",
        "description": "Fetch public web page text/markdown or inspect HTTP status safely.",
        "tools": [
            {"name": "web_fetch", "desc": "Fetch public URL readable content or check HTTP status (SSRF shielded)."}
        ]
    }
}



def defroster_health_check() -> dict[str, Any]:
    """Execute read-only self-test and dependency probe (Python, DPAPI, databases, PowerShell, sandbox)."""
    t0 = time.perf_counter()
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    issues = []

    # 1. Runtime
    runtime_info = {
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "is_frozen": getattr(sys, "frozen", False),
        "executable": sys.executable
    }

    # 2. Security & Sandbox
    from modules.shell_processes import resolve_workspace_root, _is_admin_shell_allowed
    ws_root = resolve_workspace_root()
    ws_exists = os.path.exists(ws_root)
    if not ws_exists:
        issues.append(f"Workspace directory does not exist: {ws_root}")

    # DPAPI probe
    dpapi_ok = False
    try:
        from config import _encrypt_dpapi, _decrypt_dpapi
        test_val = "defroster_health_probe"
        enc = _encrypt_dpapi(test_val)
        dec = _decrypt_dpapi(enc)
        dpapi_ok = (dec == test_val)
    except Exception as e:
        issues.append(f"DPAPI encryption probe failed: {e}")

    security_info = {
        "workspace_root": ws_root,
        "workspace_exists": ws_exists,
        "workspace_sandbox_enforced": server_cfg.get("enforce_workspace_sandbox", True),
        "admin_shell_allowed": _is_admin_shell_allowed(),
        "dpapi_available": dpapi_ok
    }

    # 3. Databases
    db_status = {}
    for db_name in ("tasks.db", "memory.db", "oauth.db"):
        db_path = BASE_DIR / db_name
        exists = db_path.exists()
        can_read = False
        if exists:
            try:
                import sqlite3
                conn = sqlite3.connect(db_path, timeout=2.0)
                cur = conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                row = cur.fetchone()
                can_read = bool(row and row[0] == "ok")
                conn.close()
            except Exception:
                can_read = False
        db_status[db_name] = {"exists": exists, "integrity_ok": can_read}

    # 4. Dependencies
    playwright_installed = False
    try:
        import playwright  # noqa: F401
        playwright_installed = True
    except ImportError:
        pass

    cloudflared_path = BASE_DIR / "cloudflared.exe"
    cloudflared_present = cloudflared_path.exists()

    powershell_available = False
    try:
        import subprocess
        res = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                             capture_output=True, text=True, timeout=5)
        powershell_available = (res.returncode == 0)
    except Exception:
        pass

    deps_info = {
        "playwright_installed": playwright_installed,
        "powershell_available": powershell_available,
        "cloudflared_present": cloudflared_present
    }
    if not powershell_available:
        issues.append("PowerShell is not accessible or failed execution probe.")

    # 5. MCP Profile Status
    active_profile_key = str(server_cfg.get("tool_profile", "mammouth_safe")).strip().lower()
    prof_info = TOOL_PROFILES.get(active_profile_key, TOOL_PROFILES.get("mammouth_safe", {}))
    profile_status = {
        "id": active_profile_key,
        "name": prof_info.get("name", "Unknown"),
        "promoted_tools_count": len(prof_info.get("tools", [])),
        "token_estimate": prof_info.get("token_estimate", 0)
    }

    duration_ms = round((time.perf_counter() - t0) * 1000)
    overall = "healthy"
    if issues:
        overall = "degraded" if (ws_exists and powershell_available) else "error"

    return {
        "status": overall,
        "duration_ms": duration_ms,
        "issues": issues,
        "runtime": runtime_info,
        "security": security_info,
        "storage": db_status,
        "dependencies": deps_info,
        "profile": profile_status
    }


def _extract_tool_schema_def(tool_name: str) -> dict[str, Any] | None:
    """Extract registered parameter schema for a tool synchronously from local_provider components."""
    try:
        if hasattr(mcp, "local_provider") and hasattr(mcp.local_provider, "_components"):
            comp = mcp.local_provider._components.get(f"tool:{tool_name}@")
            if comp:
                params = getattr(comp, "parameters", None) or getattr(comp, "inputSchema", None)
                return {
                    "name": tool_name,
                    "description": getattr(comp, "description", ""),
                    "parameters": params
                }
    except Exception:
        pass
    return None


def defroster_catalog(
    category: str | None = None,
    search: str | None = None,
    switch_profile: str | None = None,
    tool_schema: str | None = None,
    include_schemas: bool = False,
    detailed: bool = False,
    ctx: Context | None = None
) -> dict[str, Any]:
    """Mammouth Defroster Core Skill Directory & Capability Router (defrost / defroster main hub).

    Lists Defroster tools by category, reports active tool profile, promoted tools, and schemas.
    Differentiates clearly between:
      1. loaded_in_profile (directly callable right now)
      2. activated_in_config (module enabled in config.json)
      3. catalog_available (total Defroster suite tools)

    Args:
        category: Optional category filter ('files', 'shell', 'browser', 'screen', 'desktop', 'system', 'scheduler', 'gdrive', 'clipboard', 'memory', 'tasks', 'workspace', 'ssh', 'mammouth', 'claude', 'web', 'all').
        search: Optional search keyword (e.g. 'pdf', 'click', 'window').
        switch_profile: Optional profile switch ('mammouth_safe', 'developer', 'web_vision', 'automation', 'all', 'custom').
        tool_schema: Optional tool name to retrieve full machine-readable JSON schema (e.g. 'powershell_exec', 'browser_interact').
        include_schemas: Whether to include parameter schemas for all returned tools (default False for token safety).
        detailed: Optional flag to return full descriptions in overview mode (default False for token safety).
    """
    cfg = load_config()
    profile_switch_msg = None
    tools_auto_refreshed = False
    if switch_profile:
        target_p = str(switch_profile).strip().lower()
        if target_p in TOOL_PROFILES:
            cfg.setdefault("server", {})["tool_profile"] = target_p
            save_config(cfg)
            if ctx and getattr(ctx, "session", None):
                register_active_mcp_session(ctx.session)
            try:
                broadcast_tool_list_changed()
                tools_auto_refreshed = True
            except Exception as notif_err:
                logger.debug(f"Tool list change broadcast notice: {notif_err}")

            profile_switch_msg = f"Tool profile successfully switched to '{target_p}' ({TOOL_PROFILES[target_p]['name']})."
            if tools_auto_refreshed:
                profile_switch_msg += " Sent tools/list_changed notification: connected client will auto-refresh active tools."
        else:
            profile_switch_msg = f"Unknown profile '{switch_profile}'. Available: {list(TOOL_PROFILES.keys())}"

    active_profile_key = str(cfg.get("server", {}).get("tool_profile", "mammouth_safe")).strip().lower()
    profile_info = TOOL_PROFILES.get(active_profile_key, TOOL_PROFILES["mammouth_safe"])
    promoted_names = set(profile_info.get("tools", [])) | {"defroster_catalog", "defroster_health_check", "defroster_execute_tool"}
    mods = cfg.get("modules", {})

    # Single tool schema request (on-demand machine-readable inspection)
    if tool_schema:
        target_tool = str(tool_schema).strip()
        schema_def = _extract_tool_schema_def(target_tool)
        target_cat = None
        target_mod = _DEFROSTER_TOOL_TO_MODULE.get(target_tool, "unknown")
        reqs = {}
        for ck, cdata in _DEFROSTER_MODULE_CATALOG.items():
            for t in cdata["tools"]:
                if t["name"] == target_tool:
                    target_cat = ck
                    reqs = t.get("requirements", cdata.get("requirements", {}))
                    break
        
        # Determine recommended profile to switch to
        rec_prof = None
        for pid, pdata in TOOL_PROFILES.items():
            if target_tool in pdata.get("tools", []):
                rec_prof = pid
                break

        is_mod_enabled = target_mod == "core" or mods.get(target_mod, {}).get("enabled", False)
        is_registered = schema_def is not None
        is_loaded = is_registered and is_mod_enabled and (target_tool in promoted_names or active_profile_key == "all")

        return {
            "status": "success" if schema_def else "not_found",
            "tool_name": target_tool,
            "status_in_active_profile": ("disabled" if not is_mod_enabled else "not_registered" if not is_registered else "loaded" if is_loaded else "available"),
            "category": target_cat,
            "module": target_mod,
            "module_enabled": is_mod_enabled,
            "requirements": reqs,
            "recommended_profile": rec_prof or "all",
            "execution_syntax": f"defroster_execute_tool(tool_name='{target_tool}', arguments={{...}})",
            "schema": schema_def or {"error": f"Tool '{target_tool}' schema not found or not registered."}
        }

    target_category = str(category or "").strip().lower()
    search_term = str(search or "").strip().lower()

    is_filtered_category = bool(target_category and target_category not in ("all", "*"))
    is_search = bool(search_term)
    include_tool_details = is_filtered_category or is_search or bool(detailed)

    filtered_categories: dict[str, Any] = {}
    total_catalog_count = 0
    activated_in_config_count = 0

    for cat_key, cat_data in _DEFROSTER_MODULE_CATALOG.items():
        total_catalog_count += len(cat_data["tools"])
        mod_name = cat_data["module"]
        mod_enabled = mods.get(mod_name, {}).get("enabled", True)
        if mod_enabled:
            activated_in_config_count += len(cat_data["tools"])

        if target_category and target_category not in ("all", "*") and cat_key != target_category:
            continue

        matched_tools = []
        for t in cat_data["tools"]:
            if search_term:
                if (search_term in t["name"].lower()) or (search_term in t["desc"].lower()) or (search_term in cat_data["title"].lower()):
                    matched_tools.append(t)
            else:
                matched_tools.append(t)

        if matched_tools or (not search_term and target_category in (cat_key, "all", "*")):
            if include_tool_details:
                tools_repr = []
                for t in matched_tools:
                    t_name = t["name"]
                    is_registered = _extract_tool_schema_def(t_name) is not None
                    is_loaded = is_registered and mod_enabled and (t_name in promoted_names or active_profile_key == "all")
                    t_status = "disabled" if not mod_enabled else "not_registered" if not is_registered else "loaded" if is_loaded else "available"
                    
                    rec_p = None
                    for pid, pdata in TOOL_PROFILES.items():
                        if t_name in pdata.get("tools", []):
                            rec_p = pid
                            break

                    t_dict = {
                        "name": t_name,
                        "status": t_status,
                        "recommended_profile": rec_p or "all",
                        "desc": t["desc"],
                        "requirements": t.get("requirements", cat_data.get("requirements", {}))
                    }
                    if include_schemas:
                        t_dict["schema"] = _extract_tool_schema_def(t_name)
                    tools_repr.append(t_dict)
            else:
                tools_repr = [{"name": t["name"]} for t in matched_tools]

            cat_dict: dict[str, Any] = {
                "title": cat_data["title"],
                "module_name": mod_name,
                "module_enabled": mod_enabled,
                "tools_count": len(matched_tools),
                "tools": tools_repr
            }
            if include_tool_details:
                cat_dict["requirements"] = cat_data.get("requirements", {})
            if include_tool_details:
                cat_dict["description"] = cat_data["description"]
            filtered_categories[cat_key] = cat_dict

    token_est = profile_info.get("token_estimate", 0)
    MAX_SCHEMA_BUDGET = 7719
    if token_est <= 4000:
        budget_status = f"Safe (~{token_est:,} / {MAX_SCHEMA_BUDGET:,} tokens - optimal for Mammouth AI Chat)"
    elif token_est <= MAX_SCHEMA_BUDGET:
        budget_status = f"Safe (~{token_est:,} / {MAX_SCHEMA_BUDGET:,} tokens - within platform limit)"
    else:
        budget_status = f"Warning (~{token_est:,} / {MAX_SCHEMA_BUDGET:,} tokens - exceeds platform limit, promotion may fail)"

    # Three-Tier tool metrics
    loaded_tools_count = sum(
        1 for cat in _DEFROSTER_MODULE_CATALOG.values()
        if mods.get(cat["module"], {}).get("enabled", True)
        for tool in cat["tools"]
        if (active_profile_key == "all" or tool["name"] in promoted_names)
        and _extract_tool_schema_def(tool["name"]) is not None
    )

    res = {
        "status": "success",
        "active_tool_profile": {
            "id": active_profile_key,
            "name": profile_info["name"],
            "token_estimate": token_est,
            "schema_budget_status": budget_status,
            "promoted_tools_count": len(profile_info.get("tools", [])) if profile_info.get("tools") else "all enabled",
            "promoted_tools": profile_info.get("tools", ["all"])
        },
        "tool_inventory_metrics": {
            "loaded_in_profile": loaded_tools_count,
            "activated_in_config": activated_in_config_count,
            "total_catalog_suite": total_catalog_count
        },
        "available_profiles": [p["id"] for p in TOOL_PROFILES.values()],
        "total_categories": len(filtered_categories),
        "available_categories": list(_DEFROSTER_MODULE_CATALOG.keys()),
        "categories": filtered_categories,
        "execution_guidance": "Execute tools in the active profile directly or via 'defroster_execute_tool(tool_name, arguments)'. Switch profiles with 'defroster_catalog(switch_profile=\"<name>\")'.",
        "dynamic_tooling_advice": "Run local scripts via powershell_exec ($0 cost)."
    }
    if not include_tool_details and not include_schemas:
        res["hint"] = "Execute tools in your active profile via defroster_execute_tool(tool_name='<name>', arguments={...}). Call defroster_catalog(tool_schema='<name>') for schemas."
    if profile_switch_msg:
        res["profile_switch_status"] = profile_switch_msg
    if tools_auto_refreshed:
        res["tools_auto_refreshed"] = True
    return res

_LEGACY_TOOL_ALIASES: dict[str, tuple[str, Any]] = {
    # File ops
    "directory_tree": ("directory_list", lambda a: {**a, "recursive": True}),
    # Shell & processes
    "cmd_exec": ("powershell_exec", lambda a: {("cwd" if k == "working_directory" else k): v for k, v in a.items() if k != "shell"} | {"shell": "cmd"}),
    "command_run": ("powershell_exec", lambda a: {("cwd" if k == "working_directory" else k): v for k, v in a.items()}),
    "local_exec_command": ("powershell_exec", lambda a: {("timeout_seconds" if k == "timeout" else k): v for k, v in a.items()}),
    "process_start_background": ("process_manage", lambda a: {**a, "action": "start"}),
    "process_list_background": ("process_manage", lambda a: {**a, "action": "list"}),
    "process_get_output": ("process_manage", lambda a: {("max_lines" if k == "tail_lines" else "task_id" if k == "process_id" else k): v for k, v in a.items()} | {"action": "output"}),
    "process_kill_background": ("process_manage", lambda a: {("task_id" if k == "process_id" else k): v for k, v in a.items()} | {"action": "kill"}),
    "process_cancel": ("process_manage", lambda a: {("task_id" if k == "process_id" else k): v for k, v in a.items()} | {"action": "kill"}),
    "process_tail_output": ("process_manage", lambda a: {("task_id" if k == "process_id" else k): v for k, v in a.items()} | {"action": "output"}),
    # Desktop input (note: mouse_get_position stays unaliased so profile gating stays strict)
    "mouse_click": ("desktop_mouse", lambda a: {k: v for k, v in a.items() if k != "interval"} | {"action": "click"}),
    "mouse_move": ("desktop_mouse", lambda a: {k: v for k, v in a.items() if k != "smooth"} | {"action": "move"}),
    "mouse_drag": ("desktop_mouse", lambda a: {
        "action": "drag",
        **{k: v for k, v in a.items() if k in ("end_x", "end_y", "button", "duration")},
        **({"x": a.get("x", a.get("start_x"))} if ("x" in a or "start_x" in a) else {}),
        **({"y": a.get("y", a.get("start_y"))} if ("y" in a or "start_y" in a) else {}),
    }),
    "mouse_scroll": ("desktop_mouse", lambda a: {k: v for k, v in a.items() if k != "clicks"} | {"action": "scroll", "amount": a.get("amount", a.get("clicks", 0))}),
    "keyboard_type": ("desktop_keyboard", lambda a: {**a, "action": "type"}),
    "keyboard_press": ("desktop_keyboard", lambda a: {k: v for k, v in a.items() if k != "interval"} | {"action": "press", **({"delay": a["interval"]} if "interval" in a and "delay" not in a else {})}),
    "keyboard_hotkey": ("desktop_keyboard", lambda a: {"action": "hotkey", "key": "+".join(a["keys"]) if isinstance(a.get("keys"), list) else str(a.get("keys", a.get("key", "")))}),
    # Screen capture
    "screen_capture_active_window": ("screen_capture", lambda a: {"target": "active_window", **{k: v for k, v in a.items() if k in ("monitor", "max_width", "quality", "include_metadata", "save_to_workspace")}}),
    "screen_capture_window": ("screen_capture", lambda a: {"target": str(a.get("target") or a.get("target_hwnd") or a.get("window_title") or "active_window"), **{k: v for k, v in a.items() if k in ("monitor", "max_width", "quality", "include_metadata", "save_to_workspace")}}),
    "screen_list_windows": ("screen_windows", lambda a: {"action": "list", **{k: v for k, v in a.items() if k in ("include_minimized", "exclude_self")}}),
    "screen_list_monitors": ("screen_windows", lambda a: {"action": "monitors"}),
    "screen_set_tracked_window": ("screen_windows", lambda a: {"action": "set_tracked", "target": str(a.get("target") or a.get("window_title") or "auto")}),
    "screen_get_tracked_window": ("screen_windows", lambda a: {"action": "get_tracked"}),
    # Browser agent
    "browser_snapshot": ("browser_inspect", lambda a: {**a, "mode": "snapshot"}),
    "browser_screenshot": ("browser_inspect", lambda a: {**a, "mode": "screenshot"}),
    "browser_get_content": ("browser_inspect", lambda a: {"mode": a.get("format", a.get("mode", "text")), **{k: v for k, v in a.items() if k != "format"}}),
    "browser_click": ("browser_interact", lambda a: {"action": "double_click" if a.get("double_click") else ("right_click" if a.get("button") == "right" else "click"), "target": str(a.get("target") or a.get("selector") or a.get("ref") or "")}),
    "browser_fill": ("browser_interact", lambda a: {"action": "fill", "target": str(a.get("target") or a.get("selector") or a.get("ref") or ""), "text": str(a.get("text") if "text" in a else a.get("value", "")), **({"press_enter": a["press_enter"]} if "press_enter" in a else {})}),
    "browser_press_key": ("browser_interact", lambda a: {**a, "action": "press_key"}),
    "browser_hover": ("browser_interact", lambda a: {"action": "hover", "target": str(a.get("target") or a.get("selector") or a.get("ref") or "")}),
    "browser_scroll": ("browser_interact", lambda a: {**a, "action": "scroll"}),
    "browser_status": ("browser_session", lambda a: {**a, "action": "status"}),
    "browser_tabs": ("browser_session", lambda a: {"action": "tabs" if a.get("action", "list") in ("list", "") else a["action"], **{k: v for k, v in a.items() if k in ("tab_index", "url")}}),
    "browser_restart": ("browser_session", lambda a: {**a, "action": "restart"}),
    "browser_close": ("browser_session", lambda a: {**a, "action": "close"}),
    "browser_list_browsers": ("browser_session", lambda a: {"action": "status"}),
    # Google Drive
    "gdrive_list_files": ("gdrive_list", lambda a: {**a, "search_mode": "folder"}),
    "gdrive_search_files": ("gdrive_list", lambda a: {**a, "search_mode": "global"}),
    "gdrive_read_file": ("gdrive_read", lambda a: {**a, "mode": "text"}),
    "gdrive_get_metadata": ("gdrive_read", lambda a: {**a, "mode": "metadata"}),
    "gdrive_download_to_workspace": ("gdrive_read", lambda a: {**a, "mode": "download"}),
    "gdrive_write_file": ("gdrive_write", lambda a: {**a, "action": "create"}),
    "gdrive_update_file": ("gdrive_write", lambda a: {**a, "action": "update"}),
    "gdrive_upload_from_workspace": ("gdrive_write", lambda a: {**a, "action": "upload"}),
    "gdrive_create_folder": ("gdrive_write", lambda a: {"action": "mkdir", "name": a.get("name", a.get("folder_name", "")), "folder_id": a.get("folder_id", a.get("parent_id", "root"))}),
    "gdrive_status": ("gdrive_manage", lambda a: {**a, "action": "status"}),
    "gdrive_delete_file": ("gdrive_manage", lambda a: {**a, "action": "delete"}),
    # Memory
    "memory_get": ("memory_recall", lambda a: {"key": str(a.get("key") or a.get("name") or a.get("id") or "")}),
    "memory_list": ("memory_recall", lambda a: {k: v for k, v in a.items() if k in ("category", "limit")}),
    # Tasks Kanban
    "task_create": ("task_board", lambda a: {**a, "action": "create"}),
    "task_update": ("task_board", lambda a: {("task_id" if k == "id" else k): v for k, v in a.items()} | {"action": "update"}),
    "task_list": ("task_board", lambda a: {**a, "action": "list"}),
    "task_delete": ("task_board", lambda a: {("task_id" if k == "id" else k): v for k, v in a.items()} | {"action": "delete"}),
    # Task Scheduler
    "task_schedule_list": ("task_schedule_manage", lambda a: {**a, "action": "list"}),
    "task_schedule_control": ("task_schedule_manage", lambda a: {**a}),
    "task_schedule_delete": ("task_schedule_manage", lambda a: {**a, "action": "delete"}),
    "task_schedule_get_presets": ("task_schedule_manage", lambda a: {**a, "action": "presets"}),
    "task_schedule_get_history": ("task_schedule_manage", lambda a: {**a, "action": "history"}),
    # System Monitor
    "system_get_gpu_info": ("system_get_specs", lambda a: {"include_gpu": True}),
    "system_get_event_logs": ("system_event_logs", lambda a: {"action": "query", **{("log_name" if k == "channel" else "entry_type" if k == "level" else "event_id" if k == "id" else "count" if k == "limit" else k): v for k, v in a.items()}}),
    "system_list_event_channels": ("system_event_logs", lambda a: {"action": "list_channels", **{k: v for k, v in a.items() if k == "pattern"}}),
    # Workspace Code Search
    "workspace_search": ("workspace_code_search", lambda a: {**a, "action": "search"}),
    "workspace_find_symbols": ("workspace_code_search", lambda a: {("query" if k == "symbol_name" else k): v for k, v in a.items()} | {"action": "symbols"}),
    "workspace_index_directory": ("workspace_code_search", lambda a: {**a, "action": "index"}),
    "workspace_get_stats": ("workspace_code_search", lambda a: {"action": "stats"}),
    # Smart Clipboard
    "clipboard_get_text": ("clipboard_manage", lambda a: {"action": "get"}),
    "clipboard_set_text": ("clipboard_manage", lambda a: {**a, "action": "set"}),
    "clipboard_transform": ("clipboard_manage", lambda a: {"action": "format", **{k: v for k, v in a.items() if k in ("text", "update_clipboard")}}),
    # PuTTY SSH
    "ssh_list_saved_hosts": ("ssh_hosts", lambda a: {"action": "list"}),
    "ssh_list_putty_registry_sessions": ("ssh_hosts", lambda a: {"action": "list_putty"}),
    "ssh_save_host": ("ssh_hosts", lambda a: {k: v for k, v in a.items() if k != "clear_password"} | {"action": "save"}),
    "ssh_open_putty_window": ("ssh_hosts", lambda a: {("alias" if k == "host_or_alias" else k): v for k, v in a.items()} | {"action": "open_putty"}),
    # Mammouth Code CLI
    "mammouth_code_status": ("mammouth_code", lambda a: {"action": "status"}),
    "get_mammouth_code_status": ("mammouth_code", lambda a: {"action": "status"}),
    "mammouth_code_install_or_update": ("mammouth_code", lambda a: {"action": "install"}),
    "install_or_update_mammouth_code": ("mammouth_code", lambda a: {"action": "install"}),
    "mammouth_code_sync_mcp": ("mammouth_code", lambda a: {**a, "action": "sync_mcp"}),
    "sync_opencode_mcp_config": ("mammouth_code", lambda a: {**a, "action": "sync_mcp"}),
    "mammouth_code_launch_terminal": ("mammouth_code", lambda a: {k: v for k, v in a.items() if k != "preferred_terminal"} | {"action": "launch_terminal"}),
    "launch_mammouth_terminal": ("mammouth_code", lambda a: {k: v for k, v in a.items() if k != "preferred_terminal"} | {"action": "launch_terminal"}),
    "mammouth_code_run_task": ("mammouth_code", lambda a: {k: v for k, v in a.items() if k != "task_prompt"} | {"action": "run_task", "prompt": str(a.get("prompt") or a.get("task_prompt") or "")}),
    "run_mammouth_task": ("mammouth_code", lambda a: {k: v for k, v in a.items() if k != "task_prompt"} | {"action": "run_task", "prompt": str(a.get("prompt") or a.get("task_prompt") or "")}),
    # Claude Code CLI
    "claude_code_status": ("claude_code", lambda a: {k: v for k, v in a.items() if k == "workspace_path"} | {"action": "status"}),
    "get_claude_code_status": ("claude_code", lambda a: {k: v for k, v in a.items() if k == "workspace_path"} | {"action": "status"}),
    "claude_code_sync_mcp": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("workspace_path", "use_oauth")} | {"action": "sync_mcp"}),
    "sync_claude_code_mcp": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("workspace_path", "use_oauth")} | {"action": "sync_mcp"}),
    "claude_code_launch_terminal": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("workspace_path", "cloud", "continue_session", "prompt")} | {"action": "launch_terminal"}),
    "launch_claude_terminal": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("workspace_path", "cloud", "continue_session", "prompt")} | {"action": "launch_terminal"}),
    "claude_code_run_task": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("prompt", "workspace_path", "cloud", "timeout_seconds")} | {"action": "run_task", "prompt": str(a.get("prompt") or a.get("task_prompt") or "")}),
    "run_claude_task": ("claude_code", lambda a: {k: v for k, v in a.items() if k in ("prompt", "workspace_path", "cloud", "timeout_seconds")} | {"action": "run_task", "prompt": str(a.get("prompt") or a.get("task_prompt") or "")}),
    # Web Tools
    "web_fetch_url": ("web_fetch", lambda a: {**a, "mode": "content"}),
    "web_check_status": ("web_fetch", lambda a: {**a, "mode": "status"}),
}


async def defroster_execute_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    ctx: Context | None = None
) -> dict[str, Any]:
    """Execute a tool from the active Mammouth Defroster profile on demand.

    Args:
        tool_name: Name of the Defroster tool to execute (e.g. 'desktop_get_screen_info', 'system_get_specs').
        arguments: Key-value dictionary of arguments for the tool.
    """
    if not tool_name or not isinstance(tool_name, str):
        return {"status": "error", "error": "Invalid or missing 'tool_name' parameter."}

    t_name = tool_name.strip()
    if t_name in ("defroster_execute_tool", "defroster_call_tool"):
        return {"status": "error", "error": "Cannot execute execution meta-tool recursively."}

    args = arguments if isinstance(arguments, dict) else {}

    # Resolve retired legacy tool names transparently to canonical streamlined tools
    exec_name = t_name
    exec_args = args
    if t_name in _LEGACY_TOOL_ALIASES:
        canonical_name, mapper = _LEGACY_TOOL_ALIASES[t_name]
        exec_name = canonical_name
        exec_args = mapper(dict(args))

    cfg = load_config()
    server_cfg = cfg.get("server", {})
    profile_key = str(server_cfg.get("tool_profile", "mammouth_safe")).strip().lower()
    mods = cfg.get("modules", {})

    # 1. Enforce active profile allowlist against canonical target tool
    if profile_key == "all":
        is_profile_allowed = True
    elif profile_key == "custom":
        mod = _DEFROSTER_TOOL_TO_MODULE.get(exec_name, "")
        is_profile_allowed = exec_name in ("defroster_catalog", "defroster_health_check") or mods.get(mod, {}).get("enabled", True)
    else:
        profile_info = TOOL_PROFILES.get(profile_key, TOOL_PROFILES.get("mammouth_safe", {}))
        allowed_names = set(profile_info.get("tools", [])) | {"defroster_catalog", "defroster_health_check"}
        is_profile_allowed = exec_name in allowed_names

    if not is_profile_allowed:
        return {
            "status": "error",
            "tool": t_name,
            "error": "tool not in active profile"
        }

    # 2. Enforce module enabled status
    mod_name = _DEFROSTER_TOOL_TO_MODULE.get(exec_name) or _DEFROSTER_TOOL_TO_MODULE.get(t_name)
    if mod_name and mod_name != "core":
        if not mods.get(mod_name, {}).get("enabled", True):
            return {
                "status": "error",
                "tool": t_name,
                "error": f"Module '{mod_name}' for tool '{t_name}' is currently disabled in Defroster settings."
            }

    try:
        call_res = await mcp.call_tool(exec_name, exec_args)
        if hasattr(call_res, "is_error") and call_res.is_error:
            err_msg = ""
            if hasattr(call_res, "content") and call_res.content:
                err_msg = "\n".join(getattr(c, "text", str(c)) for c in call_res.content)
            return {"status": "error", "tool": t_name, "error": err_msg or "Tool execution reported error."}

        if hasattr(call_res, "structured_content") and call_res.structured_content is not None:
            return {"status": "success", "tool": t_name, "result": call_res.structured_content}

        if hasattr(call_res, "content") and call_res.content:
            raw_text = "\n".join(getattr(c, "text", str(c)) for c in call_res.content)
            try:
                parsed_json = json.loads(raw_text)
                return {"status": "success", "tool": t_name, "result": parsed_json}
            except Exception:
                return {"status": "success", "tool": t_name, "result": raw_text}

        return {"status": "success", "tool": t_name, "result": str(call_res)}
    except Exception as err:
        return {"status": "error", "tool": t_name, "error": f"Execution failed: {err}"}


STREAMLINED_MODULE_TOOL_COUNTS: dict[str, int] = {
    "memory": 3,
    "tasks_kanban": 1,
    "task_scheduler": 2,
    "file_ops": 5,
    "shell_processes": 3,
    "putty_ssh": 3,
    "system_monitor": 3,
    "screen_capture": 2,
    "web_tools": 1,
    "mammouth_code": 1,
    "claude_code": 1,
    "desktop_input": 3,
    "google_drive": 4,
    "browser_agent": 5,
    "workspace_memory": 1,
    "smart_clipboard": 1,
}
CORE_TOOL_COUNT = 3


def get_streamlined_tool_counts() -> tuple[dict[str, int], int]:
    """Return canonical per-module tool counts and total registered tool count (39 module + 3 core = 42)."""
    counts = dict(STREAMLINED_MODULE_TOOL_COUNTS)
    return counts, CORE_TOOL_COUNT + sum(counts.values())


_registered_tool_names: set[str] = set()


def register_active_tools():
    """Register newly enabled streamlined canonical tools; safe to call again on an in-process restart."""

    def register(name=None):
        def decorator(fn):
            tool_name = name or fn.__name__
            if tool_name not in _registered_tool_names:
                if name is None:
                    mcp.tool()(fn)
                else:
                    mcp.tool(name=name)(fn)
                _registered_tool_names.add(tool_name)
            return fn
        return decorator

    register()(defroster_catalog)
    register()(defroster_health_check)
    register()(defroster_execute_tool)
    cfg = load_config()
    mods = cfg.get("modules", {})

    if mods.get("memory", {}).get("enabled", True):
        register(name="memory_save")(require_module("memory")(memory_save_clean))
        register(name="memory_recall")(require_module("memory")(memory_recall_clean))
        register(name="memory_delete")(require_module("memory")(memory_delete_clean))

    if mods.get("tasks_kanban", {}).get("enabled", True):
        register()(require_module("tasks_kanban")(task_board))

    if mods.get("task_scheduler", {}).get("enabled", True):
        register()(require_module("task_scheduler")(task_schedule_create))
        register()(require_module("task_scheduler")(task_schedule_manage))

    if mods.get("file_ops", {}).get("enabled", True):
        register(name="file_read")(require_module("file_ops")(file_read_clean))
        register(name="file_write")(require_module("file_ops")(file_write_clean))
        register(name="file_replace_chunk")(require_module("file_ops")(file_replace_chunk_clean))
        register(name="file_search_text")(require_module("file_ops")(file_search_text_clean))
        register(name="directory_list")(require_module("file_ops")(directory_list_clean))

    if mods.get("shell_processes", {}).get("enabled", True):
        register(name="powershell_exec")(require_module("shell_processes")(powershell_exec_clean))
        register()(require_module("shell_processes")(desktop_open))
        register()(require_module("shell_processes")(process_manage))

    if mods.get("putty_ssh", {}).get("enabled", True):
        register()(require_module("putty_ssh")(ssh_hosts))
        register()(require_module("putty_ssh")(ssh_exec_command))
        register()(require_module("putty_ssh")(ssh_transfer_file))

    if mods.get("system_monitor", {}).get("enabled", True):
        register(name="system_get_specs")(require_module("system_monitor")(system_specs_dispatch))
        register()(require_module("system_monitor")(system_get_processes))
        register()(require_module("system_monitor")(system_event_logs))

    if mods.get("screen_capture", {}).get("enabled", True):
        register(name="screen_capture")(require_module("screen_capture")(screen_capture_dispatch))
        register()(require_module("screen_capture")(screen_windows))
        # screen_grant_consent / screen_revoke_consent are intentionally NOT exposed as MCP tools:
        # consent must come from the human via the GUI, never from the model itself.

    if mods.get("web_tools", {}).get("enabled", True):
        register()(require_module("web_tools")(web_fetch))

    if mods.get("mammouth_code", {}).get("enabled", True):
        register(name="mammouth_code")(require_module("mammouth_code")(mammouth_code_dispatch))

    if mods.get("claude_code", {}).get("enabled", True):
        register(name="claude_code")(require_module("claude_code")(claude_code_dispatch))

    if mods.get("desktop_input", {}).get("enabled", True):
        register()(require_module("desktop_input")(desktop_get_screen_info))
        register()(require_module("desktop_input")(desktop_mouse))
        register()(require_module("desktop_input")(desktop_keyboard))

    if mods.get("google_drive", {}).get("enabled", True):
        register()(require_module("google_drive")(gdrive_list))
        register()(require_module("google_drive")(gdrive_read))
        register()(require_module("google_drive")(gdrive_write))
        register()(require_module("google_drive")(gdrive_manage))

    if mods.get("browser_agent", {}).get("enabled", True):
        register()(require_module("browser_agent")(browser_navigate))
        register()(require_module("browser_agent")(browser_inspect))
        register()(require_module("browser_agent")(browser_interact))
        register()(require_module("browser_agent")(browser_evaluate))
        register()(require_module("browser_agent")(browser_session))

    if mods.get("workspace_memory", {}).get("enabled", True):
        register()(require_module("workspace_memory")(workspace_code_search))

    if mods.get("smart_clipboard", {}).get("enabled", True):
        register()(require_module("smart_clipboard")(clipboard_manage))


register_active_tools()

# ==========================================
# TOOL PROFILING & SCHEMA BUDGET MANAGEMENT
# ==========================================

_DEFROSTER_TOOL_TO_MODULE: dict[str, str] = {
    "defroster_catalog": "core",
    "defroster_health_check": "core",
    "defroster_execute_tool": "core",
    # Canonical streamlined tools + legacy alias routing
    "memory_save": "memory", "memory_recall": "memory", "memory_get": "memory", "memory_delete": "memory", "memory_list": "memory",
    "task_board": "tasks_kanban", "task_create": "tasks_kanban", "task_update": "tasks_kanban", "task_list": "tasks_kanban", "task_delete": "tasks_kanban",
    "task_schedule_create": "task_scheduler", "task_schedule_manage": "task_scheduler", "task_schedule_list": "task_scheduler", "task_schedule_control": "task_scheduler", "task_schedule_delete": "task_scheduler", "task_schedule_get_presets": "task_scheduler", "task_schedule_get_history": "task_scheduler",
    "file_read": "file_ops", "file_write": "file_ops", "file_replace_chunk": "file_ops", "file_search_text": "file_ops", "directory_list": "file_ops", "directory_tree": "file_ops",
    "powershell_exec": "shell_processes", "desktop_open": "shell_processes", "process_manage": "shell_processes", "local_exec_command": "shell_processes", "command_run": "shell_processes", "cmd_exec": "shell_processes", "process_start_background": "shell_processes", "process_list_background": "shell_processes", "process_get_output": "shell_processes", "process_kill_background": "shell_processes", "process_cancel": "shell_processes", "process_tail_output": "shell_processes",
    "ssh_hosts": "putty_ssh", "ssh_exec_command": "putty_ssh", "ssh_transfer_file": "putty_ssh", "ssh_open_putty_window": "putty_ssh", "ssh_list_saved_hosts": "putty_ssh", "ssh_save_host": "putty_ssh", "ssh_list_putty_registry_sessions": "putty_ssh",
    "system_get_specs": "system_monitor", "system_get_processes": "system_monitor", "system_event_logs": "system_monitor", "system_get_gpu_info": "system_monitor", "system_get_event_logs": "system_monitor", "system_list_event_channels": "system_monitor",
    "screen_capture": "screen_capture", "screen_windows": "screen_capture", "screen_list_monitors": "screen_capture", "screen_list_windows": "screen_capture", "screen_capture_active_window": "screen_capture", "screen_capture_window": "screen_capture", "screen_set_tracked_window": "screen_capture", "screen_get_tracked_window": "screen_capture",
    "web_fetch": "web_tools", "web_fetch_url": "web_tools", "web_check_status": "web_tools",
    "mammouth_code": "mammouth_code", "mammouth_code_status": "mammouth_code", "get_mammouth_code_status": "mammouth_code", "launch_mammouth_terminal": "mammouth_code", "mammouth_code_launch_terminal": "mammouth_code", "run_mammouth_task": "mammouth_code", "mammouth_code_run_task": "mammouth_code", "install_or_update_mammouth_code": "mammouth_code", "mammouth_code_install_or_update": "mammouth_code", "sync_opencode_mcp_config": "mammouth_code", "mammouth_code_sync_mcp": "mammouth_code",
    "claude_code": "claude_code", "claude_code_status": "claude_code", "get_claude_code_status": "claude_code", "launch_claude_terminal": "claude_code", "claude_code_launch_terminal": "claude_code", "run_claude_task": "claude_code", "claude_code_run_task": "claude_code", "sync_claude_code_mcp": "claude_code", "claude_code_sync_mcp": "claude_code",
    "desktop_get_screen_info": "desktop_input", "desktop_mouse": "desktop_input", "desktop_keyboard": "desktop_input", "mouse_move": "desktop_input", "mouse_click": "desktop_input", "mouse_drag": "desktop_input", "mouse_scroll": "desktop_input", "mouse_get_position": "desktop_input", "keyboard_type": "desktop_input", "keyboard_press": "desktop_input", "keyboard_hotkey": "desktop_input",
    "gdrive_list": "google_drive", "gdrive_read": "google_drive", "gdrive_write": "google_drive", "gdrive_manage": "google_drive", "gdrive_status": "google_drive", "gdrive_list_files": "google_drive", "gdrive_search_files": "google_drive", "gdrive_get_metadata": "google_drive", "gdrive_read_file": "google_drive", "gdrive_download_to_workspace": "google_drive", "gdrive_upload_from_workspace": "google_drive", "gdrive_write_file": "google_drive", "gdrive_update_file": "google_drive", "gdrive_create_folder": "google_drive", "gdrive_delete_file": "google_drive",
    "browser_navigate": "browser_agent", "browser_inspect": "browser_agent", "browser_interact": "browser_agent", "browser_evaluate": "browser_agent", "browser_session": "browser_agent", "browser_snapshot": "browser_agent", "browser_screenshot": "browser_agent", "browser_click": "browser_agent", "browser_fill": "browser_agent", "browser_press_key": "browser_agent", "browser_hover": "browser_agent", "browser_scroll": "browser_agent", "browser_get_content": "browser_agent", "browser_tabs": "browser_agent", "browser_status": "browser_agent", "browser_close": "browser_agent", "browser_restart": "browser_agent", "browser_list_browsers": "browser_agent",
    "workspace_code_search": "workspace_memory", "workspace_index_directory": "workspace_memory", "workspace_search": "workspace_memory", "workspace_find_symbols": "workspace_memory", "workspace_get_stats": "workspace_memory",
    "clipboard_manage": "smart_clipboard", "clipboard_get_text": "smart_clipboard", "clipboard_set_text": "smart_clipboard", "clipboard_transform": "smart_clipboard",
}


def _sanitize_schema_dict(schema: dict[str, Any]) -> None:
    """Recursively repair OpenAPI/JSON schema dictionary and strip redundant Pydantic title bloat."""
    if not isinstance(schema, dict):
        return

    schema.pop("title", None)
    if "type" not in schema:
        schema["type"] = "object"

    props = schema.get("properties")
    if not isinstance(props, dict):
        return

    for prop_name, prop_val in list(props.items()):
        if not isinstance(prop_val, dict):
            props[prop_name] = {"type": "string"}
            continue

        prop_val.pop("title", None)

        if not prop_val:
            prop_val["type"] = "string"
            continue

        if "anyOf" in prop_val and isinstance(prop_val["anyOf"], list):
            cleaned_anyof = []
            for sub in prop_val["anyOf"]:
                if isinstance(sub, dict):
                    sub_copy = dict(sub)
                    sub_copy.pop("title", None)
                    if not sub_copy:
                        cleaned_anyof.append({"type": "string"})
                    elif "type" not in sub_copy and "$ref" not in sub_copy:
                        sub_copy["type"] = "string"
                        cleaned_anyof.append(sub_copy)
                    else:
                        cleaned_anyof.append(sub_copy)
            prop_val["anyOf"] = cleaned_anyof

        if "type" not in prop_val and "anyOf" not in prop_val and "oneOf" not in prop_val and "$ref" not in prop_val:
            prop_val["type"] = "string"


_MULTILINGUAL_TOOL_HINTS: dict[str, str] = {
    # Core & Catalog
    "defroster_catalog": "Katalog, Profil wechseln, list tools",
    "defroster_health_check": "Selbsttest, Systemdiagnose, health check",
    "defroster_execute_tool": "Werkzeug ausführen, execute tool",
    # File Operations
    "file_read": "Datei lesen, lire fichier",
    "file_write": "Datei schreiben, speichern",
    "file_replace_chunk": "Code ersetzen, bearbeiten",
    "file_search_text": "Dateien durchsuchen, Grep",
    "directory_list": "Verzeichnis, Ordnerbaum",
    # Shell & Processes
    "powershell_exec": "PowerShell, CMD, Befehl ausführen",
    "desktop_open": "Datei/URL/App öffnen, launch app",
    "process_manage": "Hintergrundprozess, Logs, kill",
    # Browser Automation
    "browser_navigate": "Browser-Automatisierung, Webseite öffnen, URL aufrufen, naviguer page web",
    "browser_inspect": "DOM Snapshot, Screenshot, HTML",
    "browser_interact": "Klicken, Formular füllen, Scrollen",
    "browser_evaluate": "JavaScript im Browser ausführen",
    "browser_session": "Browser Status, Tabs, Restart",
    # Screen & Desktop Input
    "screen_capture": "Screenshot, Bildschirmfoto, Vision",
    "screen_windows": "Fenster/Monitore auflisten",
    "desktop_get_screen_info": "Auflösung, Mausposition",
    "desktop_mouse": "Mausklick, bewegen, ziehen, scrollen",
    "desktop_keyboard": "Tastatur tippen, Taste, Hotkey",
    # System, Memory & Clipboard
    "system_get_specs": "Hardware, CPU, RAM, GPU Infos",
    "system_get_processes": "Prozesse auflisten, Taskmanager",
    "system_event_logs": "Windows Event Logs, Kanäle",
    "memory_save": "Notiz speichern, Langzeitgedächtnis",
    "memory_recall": "Gedächtnis suchen, abrufen",
    "memory_delete": "Gedächtnis löschen",
    "clipboard_manage": "Zwischenablage lesen, setzen",
    # Tasks, Scheduler, Workspace, Drive, SSH, Coding & Web
    "task_board": "Kanban Aufgabe verwalten",
    "task_schedule_create": "Zeitplan, Cron erstellen",
    "task_schedule_manage": "Zeitplan Pause, Resume, Trigger, Verlauf",
    "gdrive_list": "Google Drive suchen, auflisten",
    "gdrive_read": "Google Drive lesen, laden",
    "gdrive_write": "Google Drive schreiben, hochladen",
    "gdrive_manage": "Google Drive Status, löschen",
    "workspace_code_search": "Code-Suche, Symbole, Index",
    "ssh_hosts": "SSH Hosts, PuTTY Sessions",
    "ssh_exec_command": "SSH Remote-Befehl ausführen",
    "ssh_transfer_file": "SSH Datei SFTP/SCP übertragen",
    "mammouth_code": "Mammouth Code CLI Agent",
    "claude_code": "Claude Code CLI, Cloud Sessions",
    "web_fetch": "URL lesen, HTTP Status prüfen",
    # Legacy aliases preserved for internal hint lookups
    "claude_code_status": "Claude Code Status prüfen, Claude CLI Version, Cloud Session MCP Bridge",
    "claude_code_sync_mcp": "Claude Code .mcp.json synchronisieren, Claude Cloud Session verbinden, MCP Server für Claude",
    "claude_code_launch_terminal": "Claude Code Terminal öffnen, Claude Cloud starten, claude --cloud ausführen",
    "claude_code_run_task": "Claude Code Aufgabe ausführen, claude task headless",
}


def _hint(read_only: bool = False, destructive: bool = False, idempotent: bool = False, open_world: bool = False) -> dict:
    """Build MCP tool annotation hints (destructive/idempotent hints only apply to non-read-only tools)."""
    hints = {"readOnlyHint": read_only, "openWorldHint": open_world}
    if not read_only:
        hints["destructiveHint"] = destructive
        hints["idempotentHint"] = idempotent
    return hints


# Behaviour hints per tool (MCP ToolAnnotations). Only advertised when server.expose_tool_annotations is true,
# because strict MCP 2024-11-05 clients may not expect the field. Clients such as Claude use them to tell
# read-only tools apart from destructive ones.
_TOOL_ANNOTATION_HINTS: dict[str, dict] = {
    # Local, read-only
    "file_read": _hint(read_only=True),
    "file_search_text": _hint(read_only=True),
    "directory_list": _hint(read_only=True),
    "workspace_code_search": _hint(read_only=True),
    "system_get_specs": _hint(read_only=True),
    "system_get_processes": _hint(read_only=True),
    "system_event_logs": _hint(read_only=True),
    "screen_capture": _hint(read_only=True),
    "screen_windows": _hint(read_only=True),
    "desktop_get_screen_info": _hint(read_only=True),
    "memory_recall": _hint(read_only=True),
    "ssh_hosts": _hint(read_only=True),
    "defroster_health_check": _hint(read_only=True),
    # Read-only, reaches outside the machine
    "web_fetch": _hint(read_only=True, open_world=True),
    "gdrive_list": _hint(read_only=True, open_world=True),
    "gdrive_read": _hint(read_only=True, open_world=True),
    "browser_inspect": _hint(read_only=True, open_world=True),
    # Writes, but additive / non-destructive
    "memory_save": _hint(),
    "task_board": _hint(),
    "task_schedule_create": _hint(),
    "clipboard_manage": _hint(),
    "defroster_catalog": _hint(idempotent=True),
    "browser_navigate": _hint(open_world=True),
    # Can modify or remove data, or act on the system
    "file_write": _hint(destructive=True, idempotent=True),
    "file_replace_chunk": _hint(destructive=True),
    "memory_delete": _hint(destructive=True, idempotent=True),
    "task_schedule_manage": _hint(destructive=True),
    "powershell_exec": _hint(destructive=True, open_world=True),
    "desktop_open": _hint(destructive=True, open_world=True),
    "process_manage": _hint(destructive=True),
    "desktop_mouse": _hint(destructive=True),
    "desktop_keyboard": _hint(destructive=True),
    "ssh_exec_command": _hint(destructive=True, open_world=True),
    "ssh_transfer_file": _hint(destructive=True, open_world=True),
    "gdrive_write": _hint(destructive=True, open_world=True),
    "gdrive_manage": _hint(destructive=True, open_world=True),
    "browser_interact": _hint(destructive=True, open_world=True),
    "browser_evaluate": _hint(destructive=True, open_world=True),
    "browser_session": _hint(destructive=True, open_world=True),
    "mammouth_code": _hint(destructive=True, open_world=True),
    "claude_code": _hint(destructive=True, open_world=True),
    "defroster_execute_tool": _hint(destructive=True, open_world=True),
}


def _annotation_hints_for(tool_name: Any) -> dict | None:
    """Return annotation hints for a tool when server.expose_tool_annotations is enabled, else None."""
    if not tool_name or tool_name not in _TOOL_ANNOTATION_HINTS:
        return None
    try:
        if not load_config().get("server", {}).get("expose_tool_annotations", False):
            return None
    except Exception:
        return None
    return dict(_TOOL_ANNOTATION_HINTS[tool_name])


def _make_tool_annotations(hints: dict) -> Any:
    """Build an mcp.types.ToolAnnotations instance, falling back to the plain dict."""
    try:
        from mcp.types import ToolAnnotations
        return ToolAnnotations(**hints)
    except Exception:
        return dict(hints)


def _sanitize_mcp_tool_schema(tool: Any) -> None:
    """Sanitize and repair OpenAPI / JSON schema constructs on mcp.types.Tool or FastMCP Tool."""
    if isinstance(tool, dict):
        schema = tool.get("input_schema") or tool.get("inputSchema")
        if isinstance(schema, dict):
            _sanitize_schema_dict(schema)
        for k in ("output_schema", "outputSchema", "meta", "_meta", "title", "icons", "annotations", "execution"):
            tool.pop(k, None)
        t_name = tool.get("name")
        _hints = _annotation_hints_for(t_name)
        if _hints:
            tool["annotations"] = _hints
        if t_name and t_name in _MULTILINGUAL_TOOL_HINTS:
            hint = _MULTILINGUAL_TOOL_HINTS[t_name]
            desc = tool.get("description", "") or ""
            marker = "[Keywords/Mots-clés:"
            if marker not in desc:
                tool["description"] = f"{desc}\n{marker} {hint}]" if desc else f"{marker} {hint}]"
        return

    schema = getattr(tool, "input_schema", None)
    if schema is None and not hasattr(tool, "input_schema"):
        if "inputSchema" in getattr(tool, "__dict__", {}) or "inputSchema" in getattr(type(tool), "model_fields", {}):
            schema = getattr(tool, "inputSchema", None)
    if isinstance(schema, dict):
        _sanitize_schema_dict(schema)
    if hasattr(tool, "parameters") and isinstance(tool.parameters, dict):
        _sanitize_schema_dict(tool.parameters)
    # Clear non-standard draft fields for strict MCP 2024-11-05 client compatibility
    for attr in ("output_schema", "meta", "_meta", "title", "icons", "annotations", "execution"):
        if hasattr(tool, attr):
            try:
                setattr(tool, attr, None)
            except Exception:
                pass
    _obj_hints = _annotation_hints_for(getattr(tool, "name", None))
    if _obj_hints and hasattr(tool, "annotations"):
        try:
            tool.annotations = _make_tool_annotations(_obj_hints)
        except Exception:
            pass
    # Avoid triggering FastMCPDeprecationWarning for outputSchema shim if output_schema is already handled
    if not hasattr(tool, "output_schema"):
        if "outputSchema" in getattr(tool, "__dict__", {}) or "outputSchema" in getattr(type(tool), "model_fields", {}):
            try:
                tool.outputSchema = None
            except Exception:
                pass
    # Multilingual Keyword Enrichment (DE / FR / EN) for Mammouth AI and international clients
    t_name = getattr(tool, "name", None)
    if t_name and t_name in _MULTILINGUAL_TOOL_HINTS:
        hint = _MULTILINGUAL_TOOL_HINTS[t_name]
        desc = getattr(tool, "description", "") or ""
        marker = "[Keywords/Mots-clés:"
        if marker not in desc:
            new_desc = f"{desc}\n{marker} {hint}]" if desc else f"{marker} {hint}]"
            try:
                tool.description = new_desc
            except Exception:
                pass


_orig_list_tools = mcp.list_tools


async def _profile_filtered_list_tools(*args, **kwargs) -> Any:
    """Filter and sanitize advertised tools dynamically based on active tool profile in config.json."""
    tools = await _orig_list_tools(*args, **kwargs)
    cfg = load_config()
    profile_key = str(cfg.get("server", {}).get("tool_profile", "mammouth_safe")).strip().lower()

    if profile_key == "all":
        filtered_tools = list(tools)
    elif profile_key == "custom":
        mods = cfg.get("modules", {})
        filtered_tools = [
            t for t in tools
            if t.name in ("defroster_catalog", "defroster_health_check") or mods.get(_DEFROSTER_TOOL_TO_MODULE.get(t.name, ""), {}).get("enabled", True)
        ]
    else:
        profile_info = TOOL_PROFILES.get(profile_key, TOOL_PROFILES["mammouth_safe"])
        allowed_names = set(profile_info.get("tools", [])) | {"defroster_catalog", "defroster_health_check", "defroster_execute_tool"}
        filtered_tools = [t for t in tools if t.name in allowed_names]

    # Sanitize each tool schema
    for t in filtered_tools:
        _sanitize_mcp_tool_schema(t)

    return filtered_tools


mcp.list_tools = _profile_filtered_list_tools

# Also wrap _list_tools_mcp if present (older FastMCP protocol handler)
if hasattr(mcp, "_list_tools_mcp"):
    _orig_list_tools_mcp = mcp._list_tools_mcp

    async def _profile_filtered_list_tools_mcp(request: Any = None) -> Any:
        result = await _orig_list_tools_mcp(request)
        cfg = load_config()
        profile_key = str(cfg.get("server", {}).get("tool_profile", "mammouth_safe")).strip().lower()
        if profile_key != "all":
            if profile_key == "custom":
                mods = cfg.get("modules", {})
                result.tools = [
                    t for t in result.tools
                    if t.name in ("defroster_catalog", "defroster_health_check") or mods.get(_DEFROSTER_TOOL_TO_MODULE.get(t.name, ""), {}).get("enabled", True)
                ]
            else:
                profile_info = TOOL_PROFILES.get(profile_key, TOOL_PROFILES["mammouth_safe"])
                allowed_names = set(profile_info.get("tools", [])) | {"defroster_catalog", "defroster_health_check", "defroster_execute_tool"}
                result.tools = [t for t in result.tools if t.name in allowed_names]
        for tool in result.tools:
            _sanitize_mcp_tool_schema(tool)
        return result

    mcp._list_tools_mcp = _profile_filtered_list_tools_mcp

_ACTIVE_MCP_SESSIONS = set()
_SERVER_EVENT_LOOP: asyncio.AbstractEventLoop | None = None
_AUTHENTICATED_SSE_SESSIONS: dict[str, float] = {}
_SSE_SESSION_LOCK = threading.Lock()

def record_authenticated_sse_session(session_id: str, ttl_seconds: float = 86400.0) -> None:
    if not session_id:
        return
    with _SSE_SESSION_LOCK:
        now = time.time()
        expired = [sid for sid, exp in _AUTHENTICATED_SSE_SESSIONS.items() if exp < now]
        for sid in expired:
            del _AUTHENTICATED_SSE_SESSIONS[sid]
        _AUTHENTICATED_SSE_SESSIONS[session_id] = now + ttl_seconds

def is_sse_session_authenticated(session_id: str) -> bool:
    if not session_id:
        return False
    with _SSE_SESSION_LOCK:
        exp = _AUTHENTICATED_SSE_SESSIONS.get(session_id)
        if exp is not None:
            if time.time() < exp:
                return True
            else:
                del _AUTHENTICATED_SSE_SESSIONS[session_id]
        return False

def register_active_mcp_session(session: Any):
    """Register an active MCP ServerSession to broadcast tool list updates."""
    if session:
        _ACTIVE_MCP_SESSIONS.add(session)

async def notify_all_mcp_sessions_tools_changed():
    """Broadcast notifications/tools/list_changed to all active MCP sessions."""
    import mcp.types as mcp_types
    dead = set()
    for s in list(_ACTIVE_MCP_SESSIONS):
        try:
            if hasattr(s, "send_tool_list_changed"):
                await s.send_tool_list_changed()
            elif hasattr(s, "send_notification"):
                await s.send_notification(mcp_types.ToolListChangedNotification())
        except Exception as err:
            logger.debug(f"Failed to notify session {s}: {err}")
            dead.add(s)
    _ACTIVE_MCP_SESSIONS.difference_update(dead)

def broadcast_tool_list_changed():
    """Safely dispatch notifications/tools/list_changed across thread and event loop boundaries."""
    if _SERVER_EVENT_LOOP and _SERVER_EVENT_LOOP.is_running():
        try:
            return asyncio.run_coroutine_threadsafe(notify_all_mcp_sessions_tools_changed(), _SERVER_EVENT_LOOP)
        except Exception as err:
            logger.debug(f"Cross-loop broadcast error: {err}")
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(notify_all_mcp_sessions_tools_changed())
    except RuntimeError:
        import threading
        threading.Thread(
            target=lambda: asyncio.run(notify_all_mcp_sessions_tools_changed()),
            daemon=True,
            name="BroadcastToolListChangedFallback"
        ).start()

# Wrap MCP server request_handlers for strict schema cleanliness, session tracking, and tool profile filtering
import mcp.types as mcp_types
if hasattr(mcp, "_mcp_server"):
    _srv = mcp._mcp_server
    _handlers_dict = getattr(_srv, "request_handlers", getattr(_srv, "_request_handlers", None))
    if isinstance(_handlers_dict, dict):
        # Locate ListTools handler (keyed by class mcp_types.ListToolsRequest or string "tools/list")
        _list_key = None
        for _k in (mcp_types.ListToolsRequest, "tools/list"):
            if _k in _handlers_dict:
                _list_key = _k
                break

        if _list_key is not None:
            _orig_tools_entry = _handlers_dict[_list_key]
            _orig_on_list = getattr(_orig_tools_entry, "handler", _orig_tools_entry)

            async def _profile_filtered_on_list_handler(req=None, *args, **kwargs):
                # Context-based session registration
                try:
                    from mcp.server.lowlevel.server import request_ctx
                    ctx = request_ctx.get()
                    if ctx and hasattr(ctx, "session") and ctx.session:
                        register_active_mcp_session(ctx.session)
                except Exception:
                    pass
                if req and hasattr(req, "session") and req.session:
                    register_active_mcp_session(req.session)
                for arg in args:
                    if hasattr(arg, "session") and arg.session:
                        register_active_mcp_session(arg.session)

                try:
                    if hasattr(_orig_tools_entry, "handler"):
                        result = await _orig_on_list(req, *args, **kwargs) if req is not None else await _orig_on_list(*args, **kwargs)
                    else:
                        result = await _orig_tools_entry(req, *args, **kwargs) if req is not None else await _orig_tools_entry(*args, **kwargs)
                except (TypeError, AttributeError):
                    raw_tools = await mcp.list_tools()
                    sdk_tools = [tool.to_mcp_tool(name=tool.name) if hasattr(tool, "to_mcp_tool") else tool for tool in raw_tools]
                    result = mcp_types.ListToolsResult(tools=sdk_tools)

                cfg = load_config()
                profile_key = str(cfg.get("server", {}).get("tool_profile", "mammouth_safe")).strip().lower()
                target_obj = None
                tools_list = None
                if hasattr(result, "root") and hasattr(result.root, "tools"):
                    target_obj = result.root
                    tools_list = result.root.tools
                elif hasattr(result, "tools"):
                    target_obj = result
                    tools_list = result.tools

                if tools_list is not None and target_obj is not None:
                    if profile_key == "all":
                        filtered = list(tools_list)
                    elif profile_key == "custom":
                        mods = cfg.get("modules", {})
                        filtered = [
                            t for t in tools_list
                            if getattr(t, "name", "") in ("defroster_catalog", "defroster_health_check") or mods.get(_DEFROSTER_TOOL_TO_MODULE.get(getattr(t, "name", ""), ""), {}).get("enabled", True)
                        ]
                    else:
                        profile_info = TOOL_PROFILES.get(profile_key, TOOL_PROFILES["mammouth_safe"])
                        allowed_names = set(profile_info.get("tools", [])) | {"defroster_catalog", "defroster_health_check", "defroster_execute_tool"}
                        filtered = [t for t in tools_list if getattr(t, "name", "") in allowed_names]

                    for tool in filtered:
                        _sanitize_mcp_tool_schema(tool)

                    target_obj.tools = filtered
                return result

            if hasattr(_orig_tools_entry, "handler"):
                _handlers_dict[_list_key] = _orig_tools_entry.__class__(
                    params_type=_orig_tools_entry.params_type,
                    handler=_profile_filtered_on_list_handler
                )
            else:
                _handlers_dict[_list_key] = _profile_filtered_on_list_handler

        # Locate CallTool handler
        _call_key = None
        for _k in (mcp_types.CallToolRequest, "tools/call"):
            if _k in _handlers_dict:
                _call_key = _k
                break

        if _call_key is not None:
            _orig_call_entry = _handlers_dict[_call_key]
            _orig_on_call = getattr(_orig_call_entry, "handler", _orig_call_entry)

            async def _session_tracking_on_call_handler(req=None, *args, **kwargs):
                try:
                    from mcp.server.lowlevel.server import request_ctx
                    ctx = request_ctx.get()
                    if ctx and hasattr(ctx, "session") and ctx.session:
                        register_active_mcp_session(ctx.session)
                except Exception:
                    pass
                if req and hasattr(req, "session") and req.session:
                    register_active_mcp_session(req.session)
                for arg in args:
                    if hasattr(arg, "session") and arg.session:
                        register_active_mcp_session(arg.session)

                if hasattr(_orig_call_entry, "handler"):
                    return await _orig_on_call(req, *args, **kwargs) if req is not None else await _orig_on_call(*args, **kwargs)
                else:
                    return await _orig_call_entry(req, *args, **kwargs) if req is not None else await _orig_call_entry(*args, **kwargs)

            if hasattr(_orig_call_entry, "handler"):
                _handlers_dict[_call_key] = _orig_call_entry.__class__(
                    params_type=_orig_call_entry.params_type,
                    handler=_session_tracking_on_call_handler
                )
            else:
                _handlers_dict[_call_key] = _session_tracking_on_call_handler


# ==========================================
# AUTHENTICATION & SECURITY MIDDLEWARE
# ==========================================

# Persistent log path for server operations
log_path = BASE_DIR / "server.log"

_failed_ip_attempts: dict[str, dict[str, Any]] = {}
MAX_LOCKOUT_ENTRIES = 1000


def _is_ip_locked_out(client_ip: str, now: float) -> tuple:
    """Check if client IP is currently locked out under progressive exponential backoff.
    
    Returns (is_locked_out: bool, remaining_seconds: float).
    """
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return False, 0.0
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
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return 0.0
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


_LOOPBACK_PEERS = ("127.0.0.1", "::1", "localhost")


def _resolve_client_ip(peer_ip: str, header_map: dict[str, str]) -> str:
    """Determine the real client IP behind a local tunnel (cloudflared, Tailscale Funnel, ngrok).

    Only a loopback peer (the local tunnel process) is trusted to supply forwarding headers.
    CF-Connecting-IP is set by Cloudflare itself; otherwise the LAST X-Forwarded-For entry is used,
    because that is the one appended by the tunnel — earlier entries are client-controlled and spoofable.
    A tunnelled request without a usable header is tagged so it never inherits the loopback exemption.
    """
    if peer_ip not in _LOOPBACK_PEERS:
        return peer_ip
    cf_ip = header_map.get("cf-connecting-ip", "").strip()
    if cf_ip:
        return cf_ip
    forwarded_for = header_map.get("x-forwarded-for", "").strip()
    if forwarded_for:
        last_hop = forwarded_for.split(",")[-1].strip()
        return last_hop or "tunnel-unknown"
    if header_map.get("x-forwarded-host") or header_map.get("x-forwarded-proto"):
        return "tunnel-unknown"
    return peer_ip


def _request_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return _resolve_client_ip(peer, {k.lower(): v for k, v in request.headers.items()})


# ==========================================
# OAUTH 2.0 & RFC 7591 AUTHENTICATION SERVER
# ==========================================

# F-01 Fix: In-memory CSRF token store for OAuth consent flow (token → {params, expires_at})
import threading
_oauth_csrf_tokens: dict[str, dict[str, Any]] = {}
_oauth_csrf_lock = threading.Lock()
_OAUTH_CSRF_TTL = 600  # 10 minutes

def _create_oauth_csrf_token(params: dict[str, str]) -> str:
    """Generate a cryptographic CSRF token bound to specific authorization request parameters."""
    csrf_token = secrets.token_urlsafe(32)
    now = time.time()
    with _oauth_csrf_lock:
        # Prune expired tokens
        expired = [k for k, v in _oauth_csrf_tokens.items() if v["expires_at"] < now]
        for k in expired:
            del _oauth_csrf_tokens[k]
        _oauth_csrf_tokens[csrf_token] = {
            "params": params,
            "expires_at": now + _OAUTH_CSRF_TTL,
        }
    return csrf_token

def _consume_oauth_csrf_token(csrf_token: str) -> dict[str, str] | None:
    """Validate and consume a CSRF token. Returns bound params if valid, None otherwise."""
    if not csrf_token:
        return None
    now = time.time()
    with _oauth_csrf_lock:
        entry = _oauth_csrf_tokens.pop(csrf_token, None)
    if not entry or entry["expires_at"] < now:
        return None
    return entry["params"]


def _resolve_oauth_db_path() -> Path:
    """Where OAuth clients and tokens live.

    The release build keeps them in %APPDATA%\\MammouthDefroster9000 so registered MCP
    connections survive updates (every release unpacks into its own folder). Source runs and
    tests keep using the local file; MAMMOUTH_DEFROSTER_OAUTH_DB overrides both.
    """
    override = os.environ.get("MAMMOUTH_DEFROSTER_OAUTH_DB", "").strip()
    if override:
        return Path(override)
    local_db = ROOT_DIR / "oauth.db"
    appdata = os.environ.get("APPDATA", "").strip()
    if not getattr(sys, "frozen", False) or not appdata:
        return local_db
    central_db = Path(appdata) / "MammouthDefroster9000" / "oauth.db"
    try:
        central_db.parent.mkdir(parents=True, exist_ok=True)
        if not central_db.exists() and local_db.exists():
            # One-time takeover of the connections registered with this install
            shutil.copy2(local_db, central_db)
    except Exception as exc:
        print(f"[OAUTH] Central DB unavailable, using local oauth.db: {exc}", file=sys.stderr)
        return local_db
    return central_db


OAUTH_DB_PATH = _resolve_oauth_db_path()


def _token_hash(token: str) -> str:
    """SHA-256 lookup key for high-entropy random tokens (no salt needed: tokens are 256-bit random)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

OAUTH_REFRESH_TTL = 7776000  # 90 days
OAUTH_REFRESH_EXTRA_LEGACY = 5184000  # rows from before refresh_expires_at: access expiry + 60 days


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
            # SHA-256 lookup columns: token validation becomes one indexed query instead of
            # DPAPI-decrypting every stored token on every request.
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(oauth_tokens)")}
            if "access_hash" not in existing_cols:
                conn.execute("ALTER TABLE oauth_tokens ADD COLUMN access_hash TEXT")
            if "refresh_hash" not in existing_cols:
                conn.execute("ALTER TABLE oauth_tokens ADD COLUMN refresh_hash TEXT")
            # Refresh tokens outlive their access token, otherwise a client idle past 30 days
            # can no longer refresh and has to go through the full OAuth flow again.
            if "refresh_expires_at" not in existing_cols:
                conn.execute("ALTER TABLE oauth_tokens ADD COLUMN refresh_expires_at REAL")
            conn.execute(
                "UPDATE oauth_tokens SET refresh_expires_at = expires_at + ? WHERE refresh_expires_at IS NULL",
                (OAUTH_REFRESH_EXTRA_LEGACY,)
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oauth_tokens_access_hash ON oauth_tokens(access_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_oauth_tokens_refresh_hash ON oauth_tokens(refresh_hash)")
            conn.commit()

            # Migrate legacy rows: encrypt plaintext tokens with DPAPI and backfill lookup hashes (one-time)
            try:
                cur = conn.cursor()
                cur.execute("SELECT rowid, access_token, refresh_token FROM oauth_tokens WHERE access_hash IS NULL")
                rows = cur.fetchall()
                for rowid, at, rt in rows:
                    try:
                        plain_at = _decrypt_dpapi(at) if at else ""
                        plain_rt = _decrypt_dpapi(rt) if rt else ""
                    except Exception:
                        # Undecryptable row (other user/machine): it can never validate again, drop it
                        cur.execute("DELETE FROM oauth_tokens WHERE rowid = ?", (rowid,))
                        continue
                    cur.execute(
                        "UPDATE oauth_tokens SET access_token = ?, refresh_token = ?, access_hash = ?, refresh_hash = ? WHERE rowid = ?",
                        (
                            _encrypt_dpapi(plain_at) if plain_at else "",
                            _encrypt_dpapi(plain_rt) if plain_rt else "",
                            _token_hash(plain_at) if plain_at else None,
                            _token_hash(plain_rt) if plain_rt else None,
                            rowid,
                        )
                    )
                conn.commit()
            except Exception as mig_err:
                print(f"[OAUTH] Token DPAPI migration notice: {mig_err}", file=sys.stderr)
    except Exception as exc:
        print(f"[OAUTH] DB Init error: {exc}", file=sys.stderr)

_init_oauth_db()

# H-1: Rate limiting for OAuth dynamic client registration
_oauth_register_attempts: dict[str, list[float]] = {}
OAUTH_REGISTER_MAX_PER_HOUR = 5

def _check_oauth_register_rate_limit(client_ip: str) -> bool:
    """Return True if registration is allowed, False if rate-limited."""
    # Loopback / local tunnel requests are trusted local traffic
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        max_attempts = 120
    else:
        max_attempts = 30
    now = time.time()
    window = 3600.0  # 1 hour
    attempts = _oauth_register_attempts.get(client_ip, [])
    # Prune entries older than 1 hour
    attempts = [t for t in attempts if now - t < window]
    _oauth_register_attempts[client_ip] = attempts
    if len(attempts) >= max_attempts:
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
            conn.execute(
                "DELETE FROM oauth_tokens WHERE expires_at < ? AND (refresh_expires_at IS NULL OR refresh_expires_at < ?)",
                (now, now)
            )
            conn.commit()
    except Exception:
        logger.warning("OAuth cleanup of expired entries failed", exc_info=True)

def _save_oauth_client(client_id: str, client_secret: str, client_name: str, redirect_uris: list[str]):
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_clients (client_id, client_secret, client_name, redirect_uris, created_at) VALUES (?, ?, ?, ?, ?)",
            (client_id, client_secret, client_name, json.dumps(redirect_uris), now)
        )
        conn.commit()


def _get_oauth_client(client_id: str) -> dict[str, Any] | None:
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


def _get_and_consume_oauth_code(code: str) -> dict[str, Any] | None:
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
    # DPAPI encrypt both access and refresh tokens (Fail-Closed: zero plaintext fallback)
    enc_access_token = _encrypt_dpapi(access_token)
    enc_refresh_token = _encrypt_dpapi(refresh_token) if refresh_token else ""
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO oauth_tokens (access_token, refresh_token, client_id, expires_at, created_at, access_hash, refresh_hash, refresh_expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (enc_access_token, enc_refresh_token, client_id, expires_at, now,
             _token_hash(access_token), _token_hash(refresh_token) if refresh_token else None,
             max(expires_at, now + OAUTH_REFRESH_TTL))
        )
        conn.commit()


# Short-lived in-memory cache of validated access tokens (hash -> expires_at) so steady MCP
# traffic does not hit SQLite on every request. Entries are re-checked against the DB after 60s.
_valid_token_cache: dict[str, float] = {}
_valid_token_cache_lock = threading.Lock()
_VALID_TOKEN_CACHE_TTL = 60.0


def _is_valid_oauth_token(token: str) -> bool:
    if not token or not token.startswith("mcp_at_"):
        return False
    now = time.time()
    token_key = _token_hash(token)
    with _valid_token_cache_lock:
        cached_until = _valid_token_cache.get(token_key)
    if cached_until and now < cached_until:
        return True
    try:
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            row = conn.execute(
                "SELECT expires_at FROM oauth_tokens WHERE access_hash = ? AND expires_at > ?",
                (token_key, now)
            ).fetchone()
    except Exception:
        return False
    if not row:
        return False
    with _valid_token_cache_lock:
        if len(_valid_token_cache) > 1000:
            _valid_token_cache.clear()
        _valid_token_cache[token_key] = min(row[0], now + _VALID_TOKEN_CACHE_TTL)
    return True


def _refresh_oauth_token(refresh_token: str) -> dict[str, Any] | None:
    if not refresh_token:
        return None
    now = time.time()
    with sqlite3.connect(OAUTH_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT rowid, client_id, expires_at FROM oauth_tokens WHERE refresh_hash = ? AND refresh_expires_at > ?",
            (_token_hash(refresh_token), now)
        )
        matching_row = cur.fetchone()

        if not matching_row:
            return None

        client_id = matching_row["client_id"]
        row_id = matching_row["rowid"]
        new_access_token = f"mcp_at_{secrets.token_urlsafe(32)}"
        new_refresh_token = f"mcp_rt_{secrets.token_urlsafe(32)}"  # H-3: Rotate refresh token
        new_expires_at = now + 2592000

        # Encrypt newly issued tokens with DPAPI (Fail-Closed: zero plaintext fallback)
        enc_new_access = _encrypt_dpapi(new_access_token)
        enc_new_refresh = _encrypt_dpapi(new_refresh_token)

        # Insert new token pair while maintaining grace period on previous refresh token
        cur.execute(
            "INSERT INTO oauth_tokens (access_token, refresh_token, client_id, expires_at, created_at, access_hash, refresh_hash, refresh_expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (enc_new_access, enc_new_refresh, client_id, new_expires_at, now,
             _token_hash(new_access_token), _token_hash(new_refresh_token), now + OAUTH_REFRESH_TTL)
        )
        # Give old refresh token a 10-minute grace period so network retries or concurrent requests don't fail
        cur.execute(
            "UPDATE oauth_tokens SET expires_at = MIN(expires_at, ?), refresh_expires_at = MIN(refresh_expires_at, ?) WHERE rowid = ?",
            (now + 600, now + 600, row_id)
        )
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


def _resolve_base_url(header_map: dict[str, str], default_scheme: str = "http", default_host: str = "127.0.0.1:8742") -> str:
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    custom = (
        server_cfg.get("custom_public_url", "").strip()
        or server_cfg.get("cloudflare_custom_url", "").strip()
        or server_cfg.get("ngrok_custom_url", "").strip()
    )
    if custom:
        return custom.rstrip("/")
    raw_host = header_map.get("x-forwarded-host", header_map.get("host", default_host))
    host = raw_host.split(",")[0].strip()
    raw_proto = header_map.get("x-forwarded-proto", "")
    proto = raw_proto.split(",")[0].strip() if raw_proto else ""
    if not proto:
        if header_map.get("x-forwarded-ssl", "").lower() == "on" or header_map.get("front-end-https", "").lower() == "on" or any(dom in host for dom in (".ts.net", ".trycloudflare.com", ".serveousercontent.com", "ngrok")):
            proto = "https"
        else:
            proto = default_scheme
    if proto == "https" and host.endswith(":443"):
        host = host[:-4]
    elif proto == "http" and host.endswith(":80"):
        host = host[:-3]
    return f"{proto}://{host}".rstrip("/")



def _get_base_url(request: Request) -> str:
    header_map = {k.lower(): v for k, v in request.headers.items()}
    default_host = f"{request.url.hostname}:{request.url.port}" if request.url.port else (request.url.hostname or "127.0.0.1:8742")
    return _resolve_base_url(header_map, default_scheme=request.url.scheme, default_host=default_host)


async def oauth_protected_resource(request: Request):
    base_url = _get_base_url(request).rstrip("/")
    resource_param = request.query_params.get("resource", "").strip()
    path = request.url.path.lower()
    if resource_param:
        resource_id = resource_param
    elif "/sse" in path:
        resource_id = f"{base_url}/sse"
    elif "/mcp" in path:
        resource_id = f"{base_url}/mcp"
    else:
        resource_id = f"{base_url}/mcp"
    return JSONResponse({
        "resource": resource_id,
        "authorization_servers": [base_url],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp", "openid", "profile", "offline_access"]
    })


async def oauth_authorization_server(request: Request):
    base_url = _get_base_url(request).rstrip("/")
    return JSONResponse({
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "scopes_supported": ["mcp", "openid", "profile", "offline_access"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True
    })


async def openid_configuration(request: Request):
    base_url = _get_base_url(request).rstrip("/")
    return JSONResponse({
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "scopes_supported": ["mcp", "openid", "profile", "offline_access"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"]
    })


def _is_trusted_oauth_redirect_uri(uri: str) -> bool:
    """Validate that redirect URI points strictly to trusted Mammouth AI, ChatGPT/OpenAI, Claude/Anthropic, or localhost domains/schemes."""
    if not uri:
        return False
    try:
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme in ("claude", "anthropic"):
            return True
        host = (parsed.hostname or "").lower()
        trusted_hosts = (
            "mammouth.ai",
            "chatgpt.com",
            "openai.com",
            "oaiusercontent.com",
            "claude.ai",
            "anthropic.com",
            "claude.com",
        )
        if host in trusted_hosts or host.endswith(tuple(f".{h}" for h in trusted_hosts)):
            return parsed.scheme == "https"
        if host in ("localhost", "127.0.0.1", "::1"):
            return parsed.scheme in ("http", "https")
    except Exception:
        return False
    return False


async def oauth_register(request: Request):
    # Rate limiting — max 120 per hour for loopback, 30 per hour for external
    client_ip = _request_client_ip(request)
    if not _check_oauth_register_rate_limit(client_ip):
        return JSONResponse(
            {"error": "too_many_requests", "error_description": "Registration rate limit exceeded. Try again later."},
            status_code=429
        )

    # Optional registration_token gate if explicitly configured by the user
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    reg_token = server_cfg.get("registration_token", "").strip()
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

    client_name = body.get("client_name") or ""
    redirect_uris = body.get("redirect_uris", [])
    if isinstance(redirect_uris, str):
        redirect_uris = [redirect_uris]

    if not redirect_uris:
        redirect_uris = ["https://mammouth.ai/api/mcp/oauth/callback"]

    if not client_name:
        is_chatgpt = any("chatgpt" in u.lower() or "openai" in u.lower() for u in redirect_uris)
        is_claude = any("claude" in u.lower() or "anthropic" in u.lower() for u in redirect_uris)
        client_name = "ChatGPT" if is_chatgpt else ("Claude" if is_claude else "Mammouth AI")

    # F-02 Hardening: Dynamic registration only allowed for trusted Mammouth AI, ChatGPT/OpenAI, Claude/Anthropic, or localhost redirect URIs
    for u in redirect_uris:
        if not _is_trusted_oauth_redirect_uri(u):
            return JSONResponse(
                {"error": "invalid_redirect_uri", "error_description": f"Redirect URI '{u}' is not allowed. Must belong to mammouth.ai, chatgpt.com, openai.com, claude.ai, anthropic.com, or localhost."},
                status_code=400
            )

    auth_method = body.get("token_endpoint_auth_method") or "client_secret_basic"
    client_id = body.get("client_id") or f"mcp_{secrets.token_hex(16)}"
    client_secret = secrets.token_urlsafe(32) if auth_method != "none" else ""
    _save_oauth_client(client_id, client_secret, client_name, redirect_uris)

    now = time.time()
    req_scope = str(body.get("scope", "mcp")).strip() or "mcp"
    grant_types = body.get("grant_types") if isinstance(body.get("grant_types"), list) and body.get("grant_types") else ["authorization_code", "refresh_token"]
    response_types = body.get("response_types") if isinstance(body.get("response_types"), list) and body.get("response_types") else ["code"]
    resp_data: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(now),
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": grant_types,
        "response_types": response_types,
        "scope": req_scope,
        "token_endpoint_auth_method": auth_method
    }
    if client_secret:
        resp_data["client_secret"] = client_secret
        resp_data["client_secret_expires_at"] = 0
    return JSONResponse(resp_data, status_code=201)



def _render_consent_page(request: Request, client_name: str, params: dict[str, str], error_msg: str = "") -> HTMLResponse:
    """Render the OAuth consent page with a fresh CSRF token bound to the authorization parameters."""
    csrf_token = _create_oauth_csrf_token(dict(params))
    error_html = f'<div class="error-box">{html.escape(error_msg)}</div>' if error_msg else ""
    server_cfg = load_config().get("server", {})
    enforce_auth = server_cfg.get("enforce_auth", True)

    is_claude = "claude" in client_name.lower() or "anthropic" in client_name.lower()
    is_chatgpt = "chatgpt" in client_name.lower() or "openai" in client_name.lower()
    logo_icon = "🦣 ⚡"
    if is_chatgpt:
        client_desc = "OpenAI ChatGPT wants to connect to your local Defroster 9000."
    elif is_claude:
        client_desc = "Anthropic Claude wants to connect to your local Defroster 9000.<br><span style='font-size:12px;color:#94A3B8;'>Tip: Leave OAuth Client ID &amp; Secret blank in Claude.ai — Defroster registers dynamically via OAuth 2.1 (PKCE S256).</span>"
    else:
        client_desc = f"<strong>{html.escape(client_name)}</strong> wants to connect to your local Defroster 9000."

    if enforce_auth:
        token_field_html = """
                <label class="owner-label" for="owner_token">Defroster Bearer API Token (Cockpit &rarr; Dashboard &rarr; Copy Key)</label>
                <input class="owner-input" type="password" id="owner_token" name="owner_token" autocomplete="off" placeholder="mc_..." autofocus>
        """
    else:
        token_field_html = """
                <div style="font-size: 12px; color: #10B981; margin-bottom: 16px; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px; padding: 10px; line-height: 1.4;">
                    ✓ Authentication enforcement is disabled in Server Settings. Click Allow Access to authorize immediately.
                </div>
        """

    page = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mammouth Defroster 9000 — Authorization</title>
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
                flex-direction: row-reverse;
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
            .owner-label {{
                display: block;
                text-align: left;
                font-size: 12px;
                color: #94A3B8;
                margin-bottom: 6px;
            }}
            .owner-input {{
                width: 100%;
                box-sizing: border-box;
                padding: 10px 12px;
                margin-bottom: 16px;
                border-radius: 8px;
                border: 1px solid #2D3748;
                background: #0B0D13;
                color: #E2E8F0;
                font-size: 14px;
            }}
            .error-box {{
                background: rgba(239, 68, 68, 0.12);
                border: 1px solid rgba(239, 68, 68, 0.35);
                color: #FCA5A5;
                border-radius: 8px;
                padding: 10px 12px;
                font-size: 13px;
                margin-bottom: 16px;
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
            <div class="logo">{logo_icon}</div>
            <h2>Mammouth Defroster 9000</h2>
            <div class="subtitle">MCP Connection Request</div>
            <div class="badge">● Secure MCP OAuth 2.0 Flow</div>
            <div class="info-box">
                {client_desc}<br><br>
                This grants access to sandboxed MCP tools (files, desktop, Google Drive, tasks & automation) on this host.
            </div>
            {error_html}
            <form method="POST" action="{html.escape(request.url.path or '/oauth/authorize')}">
                <input type="hidden" name="client_id" value="{html.escape(params.get("client_id", ""))}">
                <input type="hidden" name="redirect_uri" value="{html.escape(params.get("redirect_uri", ""))}">
                <input type="hidden" name="response_type" value="{html.escape(params.get("response_type", ""))}">
                <input type="hidden" name="state" value="{html.escape(params.get("state", ""))}">
                <input type="hidden" name="code_challenge" value="{html.escape(params.get("code_challenge", ""))}">
                <input type="hidden" name="code_challenge_method" value="{html.escape(params.get("code_challenge_method", ""))}">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                {token_field_html}
                <div class="buttons">
                    <button type="submit" name="action" value="allow" class="btn-allow">Allow Access</button>
                    <button type="submit" name="action" value="deny" class="btn-deny">Deny</button>
                </div>
            </form>
        </div>
    </body>
    </html>"""
    return HTMLResponse(page, status_code=403 if error_msg else 200)


async def oauth_authorize(request: Request):
    if request.method == "GET":
        params = request.query_params
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        response_type = params.get("response_type", "code")
        state = params.get("state", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "S256")

        # Validate client_id and redirect_uri
        if not redirect_uri:
            redirect_uri = "https://mammouth.ai/api/mcp/oauth/callback"

        client_info = _get_oauth_client(client_id) if client_id else None
        if not client_info:
            # If client_id is not yet in oauth.db but points to trusted callback, auto-register
            if _is_trusted_oauth_redirect_uri(redirect_uri):
                effective_cid = client_id or f"mcp_{secrets.token_hex(16)}"
                is_chatgpt = any(c in redirect_uri.lower() or c in effective_cid.lower() for c in ("chatgpt", "openai"))
                is_claude = any(c in redirect_uri.lower() or c in effective_cid.lower() for c in ("claude", "anthropic"))
                client_name = "ChatGPT" if is_chatgpt else ("Claude" if is_claude else "Mammouth AI")
                _save_oauth_client(effective_cid, "", client_name, [redirect_uri])
                client_id = effective_cid
                client_info = {"client_id": client_id, "client_name": client_name, "redirect_uris": [redirect_uri]}
            else:
                return JSONResponse({"error": "invalid_client", "error_description": "Unknown client_id for non-trusted redirect URI."}, status_code=400)
        else:
            client_name = client_info.get("client_name", "Mammouth AI")

        return _render_consent_page(request, client_name, {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": response_type,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": params.get("scope", "mcp"),
            "resource": params.get("resource", ""),
        })

    elif request.method == "POST":
        form = await request.form()
        action = form.get("action", "allow")
        csrf_token = form.get("csrf_token", "")

        # F-01 Fix: Validate and consume CSRF token — retrieve server-side stored authorization params
        # No fallback to form fields: without a valid CSRF token the consent is rejected.
        csrf_params = _consume_oauth_csrf_token(csrf_token)
        if not csrf_params:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Invalid or expired CSRF token. Please restart the authorization flow."},
                status_code=403
            )

        # Use server-side stored parameters (not attacker-controlled form fields)
        client_id = csrf_params.get("client_id", "")
        redirect_uri = csrf_params.get("redirect_uri", "")
        state = csrf_params.get("state", "")
        code_challenge = csrf_params.get("code_challenge", "")
        code_challenge_method = csrf_params.get("code_challenge_method", "S256")

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
        issuer_url = _get_base_url(request).rstrip("/")

        if action == "allow":
            # Proof of ownership: only someone who knows this Defroster's API token may grant access.
            # Without this check anyone who learns the public tunnel URL could approve their own client.
            client_ip = _request_client_ip(request)
            now = time.time()
            is_locked, remaining = _is_ip_locked_out(client_ip, now)
            client_name = (_get_oauth_client(client_id) or {}).get("client_name", "Mammouth AI") if client_id else "Mammouth AI"
            if is_locked:
                return _render_consent_page(request, client_name, csrf_params,
                                            f"Too many failed attempts. Please try again in {int(remaining) + 1}s.")
            owner_token = str(form.get("owner_token", "") or "").strip()
            server_cfg = load_config().get("server", {})
            enforce_auth = server_cfg.get("enforce_auth", True)
            expected_token = str(server_cfg.get("api_token", "") or "").strip()
            if enforce_auth:
                if not owner_token or not expected_token or not secrets.compare_digest(owner_token, expected_token):
                    _record_failed_auth(client_ip, now)
                    return _render_consent_page(request, client_name, csrf_params,
                                                "Incorrect or missing API token. You can find the token in the Defroster Cockpit.")
            _record_successful_auth(client_ip)
            code = f"mc_{secrets.token_urlsafe(32)}"
            _save_oauth_code(code, client_id, redirect_uri, code_challenge, code_challenge_method, time.time() + 600)
            target = f"{redirect_uri}{delim}code={urllib.parse.quote(code)}"
            if state:
                target += f"&state={urllib.parse.quote(state)}"
            if issuer_url:
                target += f"&iss={urllib.parse.quote(issuer_url, safe='')}"
            return RedirectResponse(target, status_code=302)
        else:
            target = f"{redirect_uri}{delim}error=access_denied&error_description=User+denied+authorization"
            if state:
                target += f"&state={urllib.parse.quote(state)}"
            if issuer_url:
                target += f"&iss={urllib.parse.quote(issuer_url, safe='')}"
            return RedirectResponse(target, status_code=302)


async def oauth_token(request: Request):
    content_type = request.headers.get("content-type", "")
    body: dict[str, Any] = {}
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
    else:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}

    # Support HTTP Basic Auth for client credentials (RFC 6749 Section 2.3.1)
    auth_header = request.headers.get("authorization", "")
    if auth_header[:6].lower() == "basic ":
        try:
            creds = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            if ":" in creds:
                basic_cid, basic_csec = creds.split(":", 1)
                basic_cid = urllib.parse.unquote_plus(basic_cid)
                basic_csec = urllib.parse.unquote_plus(basic_csec)
                if not body.get("client_id"):
                    body["client_id"] = basic_cid
                if not body.get("client_secret"):
                    body["client_secret"] = basic_csec
        except Exception:
            logger.debug("Ignoring malformed HTTP Basic credentials on /oauth/token", exc_info=True)


    grant_type = body.get("grant_type", "")

    if grant_type == "authorization_code":
        code = body.get("code", "")
        code_verifier = body.get("code_verifier", "")
        client_id = body.get("client_id", "")
        client_secret = body.get("client_secret", "")
        redirect_uri = body.get("redirect_uri", "")

        code_data = _get_and_consume_oauth_code(code)
        if not code_data:
            return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}, status_code=400)

        # F-09 Fix: Verify client_id matches the code's bound client_id
        code_client_id = code_data.get("client_id", "")
        if code_client_id and client_id and not secrets.compare_digest(client_id, code_client_id):
            return JSONResponse({"error": "invalid_grant", "error_description": "client_id does not match the authorization code"}, status_code=400)
        effective_client_id = client_id or code_client_id

        # Verify redirect_uri matches if provided
        code_redirect = code_data.get("redirect_uri", "")
        if redirect_uri and code_redirect:
            if redirect_uri.rstrip("/") != code_redirect.rstrip("/"):
                return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)

        # Verify client_secret only if supplied (confidential clients vs public PKCE clients)
        if client_secret and effective_client_id:
            client_info = _get_oauth_client(effective_client_id)
            if client_info and client_info.get("client_secret"):
                if not secrets.compare_digest(client_secret, client_info["client_secret"]):
                    return JSONResponse({"error": "invalid_client", "error_description": "Invalid client_secret"}, status_code=401)

        # F-01/F-09 Fix: PKCE is mandatory — reject codes without a challenge
        challenge = code_data.get("code_challenge", "")
        method = code_data.get("code_challenge_method", "S256")
        if not challenge:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE code_challenge was not provided during authorization"}, status_code=400)
        if not _verify_pkce(code_verifier, challenge, method):
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

        access_token = f"mcp_at_{secrets.token_urlsafe(32)}"
        refresh_token = f"mcp_rt_{secrets.token_urlsafe(32)}"
        expires_in = 2592000  # 30 days
        try:
            _save_oauth_token(access_token, refresh_token, effective_client_id, time.time() + expires_in)
        except Exception as ex:
            return JSONResponse(
                {"error": "server_error", "error_description": f"Failed to encrypt credentials securely: {ex}"},
                status_code=500
            )

        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "refresh_token": refresh_token,
                "scope": "mcp"
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )

    elif grant_type == "refresh_token":
        refresh_token = body.get("refresh_token", "")
        new_tokens = _refresh_oauth_token(refresh_token)
        if not new_tokens:
            return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}, status_code=400)
        return JSONResponse(new_tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    return JSONResponse({"error": "unsupported_grant_type", "error_description": f"Grant type '{grant_type}' not supported"}, status_code=400)


DEFAULT_ALLOWED_ORIGINS = [
    "https://mammouth.ai",
    "https://app.mammouth.ai",
    "https://chatgpt.com",
    "https://www.chatgpt.com",
    "https://chat.openai.com",
    "https://platform.openai.com",
    "https://openai.com",
    "https://claude.ai",
    "https://code.claude.ai",
    "https://app.claude.ai",
    "https://claude.com",
    "https://www.claude.ai",
    "https://www.claude.com",
    "https://console.anthropic.com",
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000",
    "http://localhost:8742"
]
DEFAULT_ALLOW_ORIGIN_REGEX = r"^https://([a-zA-Z0-9.-]+\.)?(mammouth\.ai|chatgpt\.com|openai\.com|oaiusercontent\.com|claude\.ai|anthropic\.com|claude\.com)$|^http://(localhost|127\.0\.0\.1)(:\d+)?$"


def is_allowed_origin(
    origin: str,
    allowed_origins: list[str] | None = None,
    allow_origin_regex: str | None = None
) -> bool:
    """Check if an Origin header is permitted under allowed_origins or allow_origin_regex."""
    if not origin or not isinstance(origin, str):
        return False
    clean_origin = origin.strip()
    if not clean_origin or clean_origin == "*":
        return False
    if allowed_origins is None:
        try:
            cfg = load_config()
            allowed_origins = cfg.get("server", {}).get("allowed_origins", DEFAULT_ALLOWED_ORIGINS)
        except Exception:
            allowed_origins = DEFAULT_ALLOWED_ORIGINS
    if clean_origin in allowed_origins:
        return True
    pattern = allow_origin_regex or DEFAULT_ALLOW_ORIGIN_REGEX
    try:
        if re.match(pattern, clean_origin, re.IGNORECASE):
            return True
    except re.error:
        logger.warning("Invalid allow_origin_regex; origin rejected", exc_info=True)
    return False


class SecurityAndAuthMiddleware:
    """Handles constant-time Bearer token authentication, progressive IP backoff, fail-closed enforcement, OPTIONS preflight, security headers, and safe logging."""
    def __init__(
        self,
        app: ASGIApp,
        token: str = "",
        enforce_auth: bool = True,
        allow_query_token: bool = False,
        allowed_origins: list[str] | None = None,
        allow_origin_regex: str | None = None
    ):
        self.app = app
        self.enforce_auth = enforce_auth
        self.token = str(token).strip()
        self.allow_query_token = allow_query_token
        self.allowed_origins = allowed_origins
        self.allow_origin_regex = allow_origin_regex
        # H-1 Fix: Fail closed — if enforce_auth is True, ensure a non-empty token is present
        if self.enforce_auth and not self.token:
            import secrets
            self.token = f"mc_{secrets.token_urlsafe(32)}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            raw_headers = list(scope.get("headers", []))
            header_map = {k.decode("latin1").lower(): v.decode("latin1") for k, v in raw_headers}
            client_ip = _resolve_client_ip((scope.get("client") or ("unknown", 0))[0], header_map)
            method = scope.get("method", "GET")
            path = scope.get("path", "/")
            clean_path = "/" + path.lstrip("/")

            # Wrapped send to inject standard security response headers (L-05)
            async def send_with_security_headers(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    existing_keys = {k.lower() for k, _ in headers}
                    if b"x-content-type-options" not in existing_keys:
                        headers.append((b"x-content-type-options", b"nosniff"))
                    # Anti-clickjacking: DENY by default; for OAuth consent endpoints, restrict framing to mammouth.ai, claude.ai, anthropic.com and self
                    is_oauth_consent = (
                        clean_path.startswith("/oauth/")
                        or clean_path.startswith("/.well-known/")
                        or "/.well-known/" in clean_path
                        or clean_path in (
                            "/authorize", "/token", "/register",
                            "/mcp/authorize", "/mcp/token", "/mcp/register",
                            "/mcp/oauth/authorize", "/mcp/oauth/token", "/mcp/oauth/register",
                        )
                    )
                    if is_oauth_consent:
                        if b"content-security-policy" not in existing_keys:
                            headers.append((b"content-security-policy", b"frame-ancestors 'self' https://mammouth.ai https://*.mammouth.ai https://chatgpt.com https://*.chatgpt.com https://openai.com https://*.openai.com https://claude.ai https://*.claude.ai https://anthropic.com https://*.anthropic.com https://claude.com https://*.claude.com"))
                    else:
                        if b"x-frame-options" not in existing_keys:
                            headers.append((b"x-frame-options", b"DENY"))
                    if b"referrer-policy" not in existing_keys:
                        headers.append((b"referrer-policy", b"no-referrer"))
                    if b"x-xss-protection" not in existing_keys:
                        headers.append((b"x-xss-protection", b"1; mode=block"))
                    if b"cache-control" not in existing_keys:
                        headers.append((b"cache-control", b"no-store, no-cache, must-revalidate, private"))
                    if b"pragma" not in existing_keys:
                        headers.append((b"pragma", b"no-cache"))
                    # Support Chromium Private Network Access (PNA) for in-app browser & local network
                    if b"access-control-allow-private-network" not in existing_keys:
                        headers.append((b"access-control-allow-private-network", b"true"))
                    if message.get("status") == 401 and b"www-authenticate" not in existing_keys:
                        base_meta_url = _resolve_base_url(header_map)
                        meta_subpath = f"/.well-known/oauth-protected-resource{clean_path}" if clean_path in ("/mcp", "/sse") else "/.well-known/oauth-protected-resource"
                        headers.append((b"www-authenticate", f'Bearer realm="MammouthDefroster9000", resource_metadata="{base_meta_url}{meta_subpath}", scope="mcp"'.encode("latin1")))
                    message["headers"] = headers
                await send(message)

            # L-03: CORS Preflight OPTIONS requests must bypass auth unconditionally and return 200 with CORS headers
            if method == "OPTIONS":
                req_origin = header_map.get("origin", "").strip()
                cors_headers = {
                    "access-control-allow-methods": "GET, POST, DELETE, OPTIONS, HEAD",
                    "access-control-allow-headers": "*",
                    "access-control-allow-private-network": "true",
                    "access-control-max-age": "86400",
                }
                if req_origin and is_allowed_origin(req_origin, self.allowed_origins, self.allow_origin_regex):
                    cors_headers["access-control-allow-origin"] = req_origin
                    cors_headers["access-control-allow-credentials"] = "true"

                cors_resp = Response(
                    content="",
                    status_code=200,
                    headers=cors_headers
                )
                await cors_resp(scope, receive, send_with_security_headers)
                return

            if method == "HEAD" and clean_path in ("/", "/sse", "/mcp"):
                head_resp = Response(content="", status_code=200)
                await head_resp(scope, receive, send_with_security_headers)
                return

            if clean_path == "/favicon.ico":
                fav_resp = Response(content="", status_code=204)
                await fav_resp(scope, receive, send_with_security_headers)
                return

            # OAuth 2.0 Discovery & Endpoints bypass pre-authentication
            is_oauth_public = (
                clean_path in {
                    "/oauth/register", "/register", "/mcp/oauth/register", "/mcp/register",
                    "/oauth/authorize", "/authorize", "/mcp/oauth/authorize", "/mcp/authorize",
                    "/oauth/token", "/token", "/mcp/oauth/token", "/mcp/token",
                }
                or clean_path.startswith("/.well-known/")
                or "/.well-known/" in clean_path
                or clean_path.startswith("/oauth/")
                or "/oauth/" in clean_path
            )
            if is_oauth_public:
                await self.app(scope, receive, send_with_security_headers)
                return

            # Fail-closed authentication check
            if self.enforce_auth:
                now = time.time()
                auth_header = header_map.get("authorization", "").strip()
                provided_token = ""
                if auth_header.lower().startswith("bearer "):
                    provided_token = auth_header[7:].strip()
                elif auth_header and not auth_header.lower().startswith("basic "):
                    provided_token = auth_header

                # Also support x-api-key header
                if not provided_token:
                    provided_token = header_map.get("x-api-key", "").strip()

                # Also support URL query parameters (?token=... or ?api_key=... or ?access_token=...) if explicitly permitted
                query_string = scope.get("query_string", b"").decode("latin1")
                params = urllib.parse.parse_qs(query_string)
                if not provided_token and self.allow_query_token:
                    provided_token = (
                        params.get("token", [""])[0]
                        or params.get("api_key", [""])[0]
                        or params.get("access_token", [""])[0]
                    ).strip()

                is_valid = False
                if provided_token:
                    if self.token and secrets.compare_digest(provided_token, self.token) or _is_valid_oauth_token(provided_token):
                        is_valid = True

                # Check active authenticated SSE session for POST /messages from verified SSE clients
                if not is_valid:
                    sid = params.get("session_id", [""])[0]
                    if sid and is_sse_session_authenticated(sid):
                        is_valid = True

                if not is_valid:
                    # The lockout only applies to bad tokens: every tunnelled client shares one IP
                    # bucket, so one stale MCP entry retrying an expired token must not block the
                    # valid connections (tokens are random 256-bit values, brute force is moot anyway).
                    is_locked, remaining_delay = _is_ip_locked_out(client_ip, now)
                    if is_locked:
                        response = JSONResponse(
                            {"error": "TooManyRequests", "message": f"Too many failed authentication attempts. Progressive cooldown active ({int(remaining_delay) + 1}s remaining)."},
                            status_code=429
                        )
                        await response(scope, receive, send_with_security_headers)
                        return
                    if provided_token:
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


def build_app(token: str | None = None):
    # GUI restarts rebuild the ASGI app without re-importing this module.
    register_active_tools()
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
                effective_token = f"mc_{secrets.token_hex(16)}"
                server_cfg["api_token"] = effective_token
                try:
                    from config import save_config
                    save_config(cfg)
                except Exception:
                    logger.warning("Could not persist generated API token; it will change on next start", exc_info=True)
        else:
            effective_token = ""
    elif enforce_auth and not effective_token:
        import secrets
        effective_token = f"mc_{secrets.token_urlsafe(32)}"

    streamable_http_app = StreamableHTTPASGIApp(None)

    sse_transport = SseServerTransport(
        "/messages",
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    class _SSERouteHandler:
        def __init__(self, transport: SseServerTransport, fallback_app: ASGIApp):
            self.transport = transport
            self.fallback_app = fallback_app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                method = scope.get("method", "GET")
                qs = scope.get("query_string", b"").decode("latin1")
                if method == "GET":
                    async with self.transport.connect_sse(scope, receive, send) as streams:
                        for sid_uuid in list(self.transport._read_stream_writers.keys()):
                            record_authenticated_sse_session(sid_uuid.hex)
                            record_authenticated_sse_session(str(sid_uuid))
                        await mcp._mcp_server.run(
                            streams[0],
                            streams[1],
                            mcp._mcp_server.create_initialization_options(),
                        )
                    return
                elif method == "POST" and "session_id=" in qs:
                    await self.transport.handle_post_message(scope, receive, send)
                    return
            await self.fallback_app(scope, receive, send)

    class _MessagesRouteHandler:
        def __init__(self, transport: SseServerTransport, fallback_app: ASGIApp):
            self.transport = transport
            self.fallback_app = fallback_app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and scope["method"] == "POST":
                qs = scope.get("query_string", b"").decode("latin1")
                if "session_id=" in qs:
                    await self.transport.handle_post_message(scope, receive, send)
                    return
            await self.fallback_app(scope, receive, send)

    unified_handler = _SSERouteHandler(sse_transport, streamable_http_app)
    messages_handler = _MessagesRouteHandler(sse_transport, streamable_http_app)

    routes = [
        Route("/", endpoint=unified_handler, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"]),
        Route("/mcp", endpoint=unified_handler, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"]),
        Route("/sse", endpoint=unified_handler, methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"]),
        Route("/messages", endpoint=messages_handler, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/mcp/messages", endpoint=messages_handler, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/sse/messages", endpoint=messages_handler, methods=["GET", "POST", "DELETE", "OPTIONS"]),

        # RFC 9728 Protected Resource Metadata (root and subpaths)
        Route("/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/.well-known/oauth-protected-resource/{subpath:path}", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/oauth-protected-resource/{subpath:path}", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/sse/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),
        Route("/sse/.well-known/oauth-protected-resource/{subpath:path}", endpoint=oauth_protected_resource, methods=["GET", "OPTIONS"]),

        # RFC 8414 Authorization Server Metadata (root and subpaths)
        Route("/.well-known/oauth-authorization-server", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/.well-known/oauth-authorization-server/{subpath:path}", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/oauth-authorization-server", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/oauth-authorization-server/{subpath:path}", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/sse/.well-known/oauth-authorization-server", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),
        Route("/sse/.well-known/oauth-authorization-server/{subpath:path}", endpoint=oauth_authorization_server, methods=["GET", "OPTIONS"]),

        # OpenID Connect Discovery compatibility
        Route("/.well-known/openid-configuration", endpoint=openid_configuration, methods=["GET", "OPTIONS"]),
        Route("/.well-known/openid-configuration/{subpath:path}", endpoint=openid_configuration, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/openid-configuration", endpoint=openid_configuration, methods=["GET", "OPTIONS"]),
        Route("/mcp/.well-known/openid-configuration/{subpath:path}", endpoint=openid_configuration, methods=["GET", "OPTIONS"]),

        # OAuth 2.0 Endpoints and subpath aliases
        Route("/oauth/register", endpoint=oauth_register, methods=["POST", "OPTIONS"]),
        Route("/register", endpoint=oauth_register, methods=["POST", "OPTIONS"]),
        Route("/mcp/oauth/register", endpoint=oauth_register, methods=["POST", "OPTIONS"]),
        Route("/mcp/register", endpoint=oauth_register, methods=["POST", "OPTIONS"]),

        Route("/oauth/authorize", endpoint=oauth_authorize, methods=["GET", "POST", "OPTIONS"]),
        Route("/authorize", endpoint=oauth_authorize, methods=["GET", "POST", "OPTIONS"]),
        Route("/mcp/oauth/authorize", endpoint=oauth_authorize, methods=["GET", "POST", "OPTIONS"]),
        Route("/mcp/authorize", endpoint=oauth_authorize, methods=["GET", "POST", "OPTIONS"]),

        Route("/oauth/token", endpoint=oauth_token, methods=["POST", "OPTIONS"]),
        Route("/token", endpoint=oauth_token, methods=["POST", "OPTIONS"]),
        Route("/mcp/oauth/token", endpoint=oauth_token, methods=["POST", "OPTIONS"]),
        Route("/mcp/token", endpoint=oauth_token, methods=["POST", "OPTIONS"]),
    ]

    @asynccontextmanager
    async def lifespan(app) -> AsyncGenerator[None, None]:
        streamable_http_app.session_manager = FastMCPStreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=True,
            stateless=True,
        )
        cfg = load_config()
        if cfg.get("modules", {}).get("browser_agent", {}).get("enabled", True):
            try:
                init_browser_agent(cfg.get("browser_agent", {}))
            except Exception as e:
                print(f"[BROWSER AGENT] Initialization notice: {e}")
        global _SERVER_EVENT_LOOP
        _SERVER_EVENT_LOOP = asyncio.get_running_loop()
        started_sched_loop = False
        try:
            if cfg.get("modules", {}).get("task_scheduler", {}).get("enabled", True):
                from modules.task_scheduler import TaskSchedulerEngine, register_default_handlers
                sched_eng = TaskSchedulerEngine.get_instance()
                register_default_handlers(sched_eng, overwrite=False)
                if not sched_eng._running:
                    sched_eng.start_background_loop(poll_interval=1.0)
                    started_sched_loop = True
        except Exception as e:
            logger.debug("Task scheduler lifespan init notice: %s", e)
        try:
            async with mcp._lifespan_manager(), streamable_http_app.session_manager.run():
                yield
        finally:
            if started_sched_loop:
                try:
                    from modules.task_scheduler import TaskSchedulerEngine
                    TaskSchedulerEngine.get_instance().stop_background_loop()
                except Exception:
                    pass
            _SERVER_EVENT_LOOP = None
            try:
                browser_close()
            except Exception:
                pass

    # CORS settings: Allow Mammouth AI, Claude Code / Anthropic, and localhost origins
    configured_origins = server_cfg.get("allowed_origins", DEFAULT_ALLOWED_ORIGINS)
    allow_origin_regex = server_cfg.get("allow_origin_regex", DEFAULT_ALLOW_ORIGIN_REGEX)
    allow_query_token = bool(server_cfg.get("allow_query_token", False))

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=configured_origins,
            allow_origin_regex=allow_origin_regex,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
            allow_headers=["*"],
            expose_headers=["*"],
            allow_credentials=True,
            allow_private_network=True,
        ),

        Middleware(
            SecurityAndAuthMiddleware,
            token=effective_token or "",
            enforce_auth=enforce_auth,
            allow_query_token=allow_query_token,
            allowed_origins=configured_origins,
            allow_origin_regex=allow_origin_regex,
        ),
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
    port = int(os.environ.get("PORT", server_cfg.get("port", 8742)))
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
