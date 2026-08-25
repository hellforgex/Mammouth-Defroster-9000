# /// script
# dependencies = [
#     "fastmcp>=3.4.0",
#     "httpx>=0.28.0",
#     "psutil>=7.0.0",
#     "uvicorn>=0.30.0",
#     "starlette>=0.38.0",
# ]
# ///
import os
import sys
import time
import secrets
import argparse
import threading
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator, Dict, Set
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.http import (
    StreamableHTTPASGIApp,
    FastMCPStreamableHTTPSessionManager,
    create_base_app,
)
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send
import uvicorn

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, is_module_enabled

# Build dynamic instructions based on active modules
cfg = load_config()
cfg_server = cfg.get("server", {})
active_capabilities = []

# Initialize FastMCP Server
mcp = FastMCP(
    name="Mammouth-Defroster-9000",
    instructions="Mammouth Defroster 9000: Advanced Windows 11, Automation & DevOps MCP Server for Mammouth.ai. (noskillz edition)"
)

# 1. Memory Module
if is_module_enabled("memory"):
    from modules.memory import memory_save, memory_recall, memory_get, memory_delete, memory_list
    mcp.tool()(memory_save)
    mcp.tool()(memory_recall)
    mcp.tool()(memory_get)
    mcp.tool()(memory_delete)
    mcp.tool()(memory_list)
    active_capabilities.append("1. Persistent Long-Term Memory (memory_save, memory_recall, memory_list, memory_get, memory_delete)")

# 2. Kanban / Tasks Module
if is_module_enabled("tasks_kanban"):
    from modules.tasks_kanban import task_create, task_update, task_list, task_delete
    mcp.tool()(task_create)
    mcp.tool()(task_update)
    mcp.tool()(task_list)
    mcp.tool()(task_delete)
    active_capabilities.append("2. Task & Kanban Board (task_create, task_update, task_list, task_delete)")

# 3. File Operations Module (Sandboxed)
if is_module_enabled("file_ops"):
    from modules.file_ops import file_read, file_write, file_replace_chunk, file_search_text, directory_list, directory_tree
    mcp.tool()(file_read)
    mcp.tool()(file_write)
    mcp.tool()(file_replace_chunk)
    mcp.tool()(file_search_text)
    mcp.tool()(directory_list)
    mcp.tool()(directory_tree)
    active_capabilities.append("3. File & Code Operations (Sandboxed: file_read, file_write, file_replace_chunk, file_search_text, directory_tree)")

# 4. Shell & Background Processes Module (High Privilege)
if is_module_enabled("shell_processes"):
    from modules.shell_processes import command_run, process_start_background, process_list_background, process_get_output, process_kill_background
    mcp.tool()(command_run)
    mcp.tool()(process_start_background)
    mcp.tool()(process_list_background)
    mcp.tool()(process_get_output)
    mcp.tool()(process_kill_background)
    active_capabilities.append("4. PowerShell & Background Processes (command_run, process_start_background, process_get_output, process_kill_background)")

# 5. PuTTY & SSH Remote Module (Encrypted)
if is_module_enabled("putty_ssh"):
    from modules.putty_ssh import ssh_exec_command, ssh_open_putty_window, ssh_transfer_file, ssh_list_saved_hosts, ssh_save_host, ssh_list_putty_registry_sessions
    mcp.tool()(ssh_exec_command)
    mcp.tool()(ssh_open_putty_window)
    mcp.tool()(ssh_transfer_file)
    mcp.tool()(ssh_list_saved_hosts)
    mcp.tool()(ssh_save_host)
    mcp.tool()(ssh_list_putty_registry_sessions)
    active_capabilities.append("5. PuTTY / SSH Remote Shell & SCP File Sync (DPAPI Encrypted: ssh_exec_command, ssh_open_putty_window, ssh_transfer_file, hosts.json)")

# 6. System & Hardware Diagnostics Module
if is_module_enabled("system_monitor"):
    from modules.system_monitor import system_get_specs, system_get_processes, system_get_gpu_info, system_get_event_logs
    mcp.tool()(system_get_specs)
    mcp.tool()(system_get_processes)
    mcp.tool()(system_get_gpu_info)
    mcp.tool()(system_get_event_logs)
    active_capabilities.append("6. System Hardware & Windows Diagnostics (system_get_specs, system_get_processes, system_get_gpu_info, system_get_event_logs)")

# 7. Web Tools Module
if is_module_enabled("web_tools"):
    from modules.web_tools import web_fetch_url, web_check_status
    mcp.tool()(web_fetch_url)
    mcp.tool()(web_check_status)
    active_capabilities.append("7. Web Scraping & URL Tools (web_fetch_url, web_check_status)")

# Set updated instructions
if active_capabilities:
    mcp.instructions = "Advanced Windows 11 & DevOps Agent MCP Server.\nActive capabilities:\n" + "\n".join(active_capabilities)

# ==========================================
# SECURITY & AUTHENTICATION
# ==========================================

# Active authenticated session cache (session_id -> expiration timestamp)
AUTHENTICATED_SESSIONS: Dict[str, float] = {}
SESSION_LOCK = threading.Lock()

def record_authenticated_session(session_id: str, ttl_seconds: float = 86400.0):
    if not session_id:
        return
    with SESSION_LOCK:
        now = time.time()
        # Clean expired
        expired = [sid for sid, exp in AUTHENTICATED_SESSIONS.items() if exp < now]
        for sid in expired:
            del AUTHENTICATED_SESSIONS[sid]
        AUTHENTICATED_SESSIONS[session_id] = now + ttl_seconds

def is_session_authenticated(session_id: str) -> bool:
    if not session_id:
        return False
    with SESSION_LOCK:
        exp = AUTHENTICATED_SESSIONS.get(session_id)
        if exp is not None:
            if time.time() < exp:
                return True
            else:
                del AUTHENTICATED_SESSIONS[session_id]
        return False


class AuthenticationMiddleware:
    """Enforces Bearer token, URL query token, or active SSE session validation."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            # Always allow CORS preflight
            if scope.get("method") == "OPTIONS":
                await self.app(scope, receive, send)
                return

            current_cfg = load_config().get("server", {})
            enforce_auth = current_cfg.get("enforce_auth", True)
            expected_token = current_cfg.get("api_token", "").strip()

            if enforce_auth and expected_token:
                path = scope.get("path", "")
                query_string = scope.get("query_string", b"").decode("latin1")
                params = urllib.parse.parse_qs(query_string)
                session_id = params.get("session_id", [""])[0]

                # Check 1: Authorization Header
                raw_headers = dict(scope.get("headers", []))
                auth_header = raw_headers.get(b"authorization", b"").decode("latin1").strip()
                token_valid = False

                if auth_header.startswith("Bearer "):
                    provided = auth_header[len("Bearer "):].strip()
                    if secrets.compare_digest(provided, expected_token):
                        token_valid = True

                # Check 2: Query token (?token=... or ?api_key=...)
                if not token_valid:
                    query_token = params.get("token", [""])[0] or params.get("api_key", [""])[0]
                    if query_token and secrets.compare_digest(query_token, expected_token):
                        token_valid = True

                # Check 3: Active authenticated SSE session (for POST /messages from verified SSE client)
                if not token_valid and session_id:
                    if is_session_authenticated(session_id):
                        token_valid = True

                # If token was valid and a session_id exists, remember this session
                if token_valid and session_id:
                    record_authenticated_session(session_id)

                if not token_valid:
                    print(f"[AUTH BLOCKED] Unauthorized request to {scope.get('method')} {path} (Query: {query_string})")
                    response = JSONResponse(
                        {
                            "error": "Unauthorized",
                            "message": "Invalid or missing API authentication token. Include '?token=<token>' in your URL or 'Authorization: Bearer <token>' in headers."
                        },
                        status_code=401
                    )
                    await response(scope, receive, send)
                    return

            # Intercept outgoing response for /sse to extract and register session_id
            if scope.get("path") == "/sse":
                async def custom_send(message):
                    if message.get("type") == "http.response.body":
                        body = message.get("body", b"").decode("utf-8", errors="ignore")
                        if "session_id=" in body:
                            match = urllib.parse.parse_qs(urllib.parse.urlparse(body.split("data: ")[-1].strip()).query)
                            sid = match.get("session_id", [""])[0]
                            if sid:
                                record_authenticated_session(sid)
                    await send(message)

                await self.app(scope, receive, custom_send)
                return

        await self.app(scope, receive, send)


class LoggingAndNormalizationMiddleware:
    """Logs requests and normalizes Accept headers for seamless MCP cloud compatibility."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            raw_headers = list(scope.get("headers", []))
            header_map = {k.decode("latin1").lower(): v.decode("latin1") for k, v in raw_headers}
            
            accept = header_map.get("accept", "")
            if not accept or accept == "*/*" or "application/json" not in accept:
                new_headers = [(k, v) for k, v in raw_headers if k.lower() != b"accept"]
                new_headers.append((b"accept", b"application/json, text/event-stream, */*"))
                scope["headers"] = new_headers

            body_chunks = []
            async def receive_with_logging():
                msg = await receive()
                if msg.get("type") == "http.request":
                    body_chunks.append(msg.get("body", b""))
                    if not msg.get("more_body", False):
                        full_body = b"".join(body_chunks).decode("utf-8", errors="replace")
                        if full_body.strip():
                            print(f"[MCP INCOMING] {scope.get('method')} {scope.get('path')} Body: {full_body[:300]}")
                return msg

            async def send_with_logging(msg):
                if msg.get("type") == "http.response.body":
                    chunk = msg.get("body", b"").decode("utf-8", errors="replace")
                    if chunk.strip():
                        print(f"[MCP OUTGOING] Body: {chunk[:300]}")
                await send(msg)

            await self.app(scope, receive_with_logging, send_with_logging)
        else:
            await self.app(scope, receive, send)

def build_app():
    streamable_http_app = StreamableHTTPASGIApp(None)
    
    routes = [
        Route("/", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/mcp", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/sse", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Route("/messages", endpoint=streamable_http_app, methods=["GET", "POST", "DELETE", "OPTIONS"]),
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

    # Hardened CORS: only allow Mammouth.ai domains and local development
    allowed_origins = cfg_server.get("allowed_origins", [
        "https://mammouth.ai",
        "https://app.mammouth.ai",
        "http://localhost",
        "http://127.0.0.1",
    ])

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_origin_regex=r"https://[a-zA-Z0-9-]+\.mammouth\.ai$",
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials=True,
        ),
        Middleware(AuthenticationMiddleware),
        Middleware(LoggingAndNormalizationMiddleware),
    ]

    return create_base_app(routes=routes, middleware=middleware, lifespan=lifespan)

app = build_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mammouth MCP Server")
    parser.add_argument("--host", default=None, help="Bind host")
    parser.add_argument("--port", type=int, default=None, help="Bind port")
    args = parser.parse_args()

    cfg_server = cfg.get("server", {})
    host = args.host or os.environ.get("HOST") or cfg_server.get("host", "127.0.0.1")
    port = args.port or int(os.environ.get("PORT") or cfg_server.get("port", 8000))
    
    auth_status = "ENABLED (Token Protected)" if cfg_server.get("enforce_auth", True) else "DISABLED (Open)"
    print(f"Starting Mammouth Defroster 9000 on http://{host}:{port}...")
    print(f"Security: Authentication={auth_status}, Workspace Sandbox={cfg_server.get('enforce_workspace_sandbox', True)}")
    print(f"Active modules ({len(active_capabilities)}): {[k for k, v in cfg.get('modules', {}).items() if v.get('enabled')]}")
    uvicorn.run(app, host=host, port=port, log_level="info")
