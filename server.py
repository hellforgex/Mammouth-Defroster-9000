import os
import sys
import json
import secrets
import functools
import re
import time
import hashlib
from pathlib import Path
from typing import Optional, AsyncGenerator, Any, Dict, List

import uvicorn
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

# Fix sys.path for standalone bundled environment
ROOT_DIR = Path(__file__).parent.resolve()
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
    screen_list_monitors
)
from modules.web_tools import (
    web_fetch_url,
    web_check_status
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

# Initialize FastMCP Server with Mammouth Defroster 9000 & Unreal Engine capabilities
mcp = FastMCP(
    name="Mammouth-Defroster-9000",
    instructions="""
    Mammouth Defroster 9000 (v0.2.0): Sovereign Windows 11 Desktop Cockpit, Vision & Unreal Engine 5 Automation Platform.
    Provides sandboxed long-term memory, tasks, file operations, hardware diagnostics, desktop vision, and Unreal Engine automation exclusively for Mammouth.ai.
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
            return fn(*args, **kwargs)
        return wrapper
    return decorator


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


register_active_tools()

# ==========================================
# AUTHENTICATION & SECURITY MIDDLEWARE
# ==========================================

# Persistent log path for server operations
log_path = Path(__file__).parent / "server.log"

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


class SecurityAndAuthMiddleware:
    """Handles constant-time Bearer token authentication, progressive IP backoff, fail-closed enforcement, OPTIONS preflight, security headers, and safe logging."""
    def __init__(self, app: ASGIApp, token: str = "", enforce_auth: bool = True):
        self.app = app
        self.token = str(token).strip()
        self.enforce_auth = enforce_auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            raw_headers = list(scope.get("headers", []))
            header_map = {k.decode("latin1").lower(): v.decode("latin1") for k, v in raw_headers}
            client_ip = scope.get("client", ("unknown", 0))[0]
            method = scope.get("method", "GET")
            path = scope.get("path", "/")

            # Wrapped send to inject standard security response headers (L-05)
            async def send_with_security_headers(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-content-type-options", b"nosniff"))
                    headers.append((b"x-frame-options", b"DENY"))
                    headers.append((b"referrer-policy", b"no-referrer"))
                    headers.append((b"x-xss-protection", b"1; mode=block"))
                    headers.append((b"cache-control", b"no-store, no-cache, must-revalidate, private"))
                    headers.append((b"pragma", b"no-cache"))
                    message["headers"] = headers
                await send(message)

            # L-03: CORS Preflight OPTIONS requests must bypass auth unconditionally
            if method == "OPTIONS":
                await self.app(scope, receive, send_with_security_headers)
                return

            # Fail-closed authentication check
            if self.enforce_auth:
                if not self.token:
                    response = JSONResponse(
                        {"error": "Unauthorized", "message": "Authentication is enforced on the server, but no valid API token is configured. Please configure an API token in settings."},
                        status_code=401
                    )
                    await response(scope, receive, send_with_security_headers)
                    return

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

                is_valid = secrets.compare_digest(provided_token, self.token) if provided_token else False

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

            # Safe access logging (Method + Path only - NO body dumping to prevent credential/data leaks)
            print(f"[MCP ACCESS] {method} {path}")

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
        else:
            effective_token = ""

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
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Accept",
                "X-Request-ID",
                "Origin",
                "User-Agent",
            ],
            allow_credentials=True,
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

    if enable_tls and (not cert_file or not os.path.exists(str(cert_file))):
        default_cert = str(Path(__file__).parent / "cert.pem")
        default_key = str(Path(__file__).parent / "key.pem")
        if not os.path.exists(default_cert):
            print("🔒 Generating self-signed TLS certificate for local network security...")
            generate_self_signed_cert(default_cert, default_key, host)
        cert_file = default_cert
        key_file = default_key

    proto = "https" if enable_tls else "http"
    print(f"Starting Mammouth Defroster 9000 on {proto}://{host}:{port}...")

    if not enable_tls and host not in ("127.0.0.1", "localhost"):
        print("\n=======================================================")
        print("⚠️  SECURITY NOTICE: Server is bound to external interface")
        print(f"   without TLS encryption ({host}:{port}).")
        print("   All traffic within your LAN will be transmitted in plaintext.")
        print("   Enable 'server.enable_tls: true' in config for HTTPS.")
        print("=======================================================\n")

    if server_cfg.get("enforce_auth", True):
        print("🔐 Token Authentication: ACTIVE (Secure by Default)")
    else:
        print("\n⚠️  WARNING: Authentication is DISABLED. Server is open to all clients on your network!")
        if host == "0.0.0.0":
            print("🔴 CRITICAL WARNING: Binding to 0.0.0.0 without authentication is dangerous and exposes your machine!\n")

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
