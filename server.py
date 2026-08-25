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
import argparse
from pathlib import Path
from typing import AsyncGenerator
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
from starlette.types import ASGIApp, Scope, Receive, Send
import uvicorn

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, is_module_enabled

# Build dynamic instructions based on active modules
cfg = load_config()
active_capabilities = []

# Initialize FastMCP Server
mcp = FastMCP(
    name="Mammouth-Powerhouse-MCP",
    instructions="Advanced Windows 11, Automation & DevOps MCP Server for Mammouth.ai."
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

# 3. File Operations Module
if is_module_enabled("file_ops"):
    from modules.file_ops import file_read, file_write, file_replace_chunk, file_search_text, directory_list, directory_tree
    mcp.tool()(file_read)
    mcp.tool()(file_write)
    mcp.tool()(file_replace_chunk)
    mcp.tool()(file_search_text)
    mcp.tool()(directory_list)
    mcp.tool()(directory_tree)
    active_capabilities.append("3. File & Code Operations (file_read, file_write, file_replace_chunk, file_search_text, directory_tree)")

# 4. Shell & Background Processes Module
if is_module_enabled("shell_processes"):
    from modules.shell_processes import command_run, process_start_background, process_list_background, process_get_output, process_kill_background
    mcp.tool()(command_run)
    mcp.tool()(process_start_background)
    mcp.tool()(process_list_background)
    mcp.tool()(process_get_output)
    mcp.tool()(process_kill_background)
    active_capabilities.append("4. PowerShell & Background Processes (command_run, process_start_background, process_get_output, process_kill_background)")

# 5. PuTTY & SSH Remote Module
if is_module_enabled("putty_ssh"):
    from modules.putty_ssh import ssh_exec_command, ssh_open_putty_window, ssh_transfer_file, ssh_list_saved_hosts, ssh_save_host, ssh_list_putty_registry_sessions
    mcp.tool()(ssh_exec_command)
    mcp.tool()(ssh_open_putty_window)
    mcp.tool()(ssh_transfer_file)
    mcp.tool()(ssh_list_saved_hosts)
    mcp.tool()(ssh_save_host)
    mcp.tool()(ssh_list_putty_registry_sessions)
    active_capabilities.append("5. PuTTY / SSH Remote Shell & SCP File Sync (ssh_exec_command, ssh_open_putty_window, ssh_transfer_file, hosts.json)")

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
# ASGI APP & LIFESPAN CONFIGURATION
# ==========================================

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

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        ),
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
    
    print(f"Starting Mammouth-Powerhouse MCP Server on http://{host}:{port}...")
    print(f"Active modules ({len(active_capabilities)}): {[k for k, v in cfg.get('modules', {}).items() if v.get('enabled')]}")
    uvicorn.run(app, host=host, port=port, log_level="info")
