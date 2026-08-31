import json
import copy
import socket
import secrets
from pathlib import Path
from typing import Dict, Any, Optional, List

CONFIG_FILE = Path(__file__).parent / "config.json"
CONFIG_EXAMPLE_FILE = Path(__file__).parent / "config.example.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "tunnel_mode": "Tailscale Funnel",  # Options: "Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"
        "endpoint_path": "/sse",           # Options: "/sse", "/mcp", "/messages", "/"
        "auto_tunnel": False,              # Safe by Default: Opt-in for public exposure
        "api_token": "",                   # Generated securely on initial run
        "enforce_auth": True,              # Secure by Default: Require Bearer token
        "allowed_origins": [
            "https://mammouth.ai",
            "https://app.mammouth.ai",
            "http://localhost",
            "http://127.0.0.1"
        ],
        "workspace_root": "./workspace",
        "enforce_workspace_sandbox": True, # Secure by Default: Sandboxed to workspace
        "tailscale_path": "",
        "cloudflared_path": "cloudflared",
        "ngrok_path": "ngrok",
        "custom_public_url": "",
        "cloudflare_custom_url": "",
        "ngrok_custom_url": "",
        "appearance_mode": "System",       # Options: "System", "Dark", "Light"
        "allow_admin_shell": False,        # Secure by Default: Read-Only shell commands only
        "enable_tls": False,               # Opt-in for LAN HTTPS
        "ssl_certfile": "",
        "ssl_keyfile": ""
    },
    "modules": {
        "memory": {
            "enabled": True,
            "name": "Persistent Long-Term Memory",
            "description": "SQLite cross-session memory storage (save, recall, list, get, delete)."
        },
        "tasks_kanban": {
            "enabled": True,
            "name": "Task & Kanban Board",
            "description": "Persistent task tracking and project management (todo, in_progress, done)."
        },
        "file_ops": {
            "enabled": True,
            "name": "File & Code Operations (Sandboxed)",
            "description": "Read, write, search files within workspace, replace code chunks, and directory trees."
        },
        "shell_processes": {
            "enabled": False,  # Disabled by default for security
            "name": "PowerShell & Background Daemons",
            "description": "Execute synchronous commands and manage long-running background tasks. (High Privilege)"
        },
        "putty_ssh": {
            "enabled": True,
            "name": "PuTTY & SSH Host Manager (DPAPI Encrypted)",
            "description": "Remote shell execution, PuTTY GUI launch, SCP file transfers, and host manager."
        },
        "system_monitor": {
            "enabled": True,
            "name": "System & Hardware Diagnostics",
            "description": "Hardware specs (CPU, RAM, Disks), GPU info, process listing, and Windows Event Logs."
        },
        "web_tools": {
            "enabled": False,  # Disabled by default for security (SSRF prevention)
            "name": "Web Scraper & URL Tools",
            "description": "Fetch and extract clean markdown/text from webpages, and check endpoint status."
        },
        "screen_capture": {
            "enabled": True,
            "name": "Desktop Vision & Screen Capture",
            "require_consent": True,
            "description": "Multi-monitor screenshot capture, downscaling for multimodal LLMs, and workspace saving."
        },
        "unreal_engine": {
            "enabled": True,
            "name": "Unreal Engine 5/4 Live Automation",
            "description": "Python remote execution, scene inspection, actor spawning, and viewport screenshot automation in Unreal Engine Editor."
        }
    }
}

import base64

try:
    import win32crypt
    HAS_DPAPI = True
except ImportError:
    HAS_DPAPI = False


def _encrypt_dpapi(data_str: str) -> str:
    """Encrypt a string using Windows DPAPI and return a 'dpapi:' prefixed base64 string."""
    if not data_str:
        return ""
    if not HAS_DPAPI:
        return data_str
    try:
        data_bytes = data_str.encode('utf-8')
        encrypted = win32crypt.CryptProtectData(data_bytes, "Mammouth_Token", None, None, None, 0)
        return "dpapi:" + base64.b64encode(encrypted).decode('ascii')
    except Exception:
        return data_str


def _decrypt_dpapi(encrypted_str: str) -> str:
    """Decrypt a 'dpapi:' prefixed string using Windows DPAPI."""
    if not encrypted_str:
        return ""
    if not encrypted_str.startswith("dpapi:"):
        return encrypted_str
    if not HAS_DPAPI:
        return encrypted_str
    try:
        raw_b64 = encrypted_str[6:]
        raw_bytes = base64.b64decode(raw_b64.encode('ascii'))
        decrypted = win32crypt.CryptUnprotectData(raw_bytes, None, None, None, 0)[1]
        return decrypted.decode('utf-8')
    except Exception:
        return encrypted_str


def generate_secure_token() -> str:
    """Generate a cryptographically secure 32-character URL-safe authentication token."""
    return secrets.token_urlsafe(24)


def get_lan_ip() -> str:
    """Detect local network LAN IP (e.g. 192.168.x.x or 10.x.x.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json, merging with defaults if keys are missing."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    token_was_present = False
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                if "server" in user_cfg:
                    cfg["server"].update(user_cfg["server"])
                    raw_token = cfg["server"].get("api_token", "")
                    if raw_token:
                        token_was_present = True
                        if not raw_token.startswith("dpapi:"):
                            # Proactive migration: encrypt plaintext token on disk immediately
                            cfg["server"]["api_token"] = raw_token
                            save_config(cfg)
                        else:
                            cfg["server"]["api_token"] = _decrypt_dpapi(raw_token)
                if "modules" in user_cfg:
                    for mod_key, mod_val in user_cfg["modules"].items():
                        if mod_key in cfg["modules"]:
                            cfg["modules"][mod_key].update(mod_val)
                        else:
                            cfg["modules"][mod_key] = mod_val
        except Exception:
            pass

    # Only generate a token if explicitly empty / missing on disk
    if not cfg["server"].get("api_token") and not token_was_present:
        cfg["server"]["api_token"] = generate_secure_token()
        save_config(cfg)

    return cfg


def save_config(config_data: Dict[str, Any]) -> bool:
    """Save configuration to config.json with formatted indentation and DPAPI encrypted token."""
    try:
        disk_cfg = copy.deepcopy(config_data)
        raw_tok = disk_cfg.get("server", {}).get("api_token", "")
        if raw_tok and not raw_tok.startswith("dpapi:"):
            disk_cfg["server"]["api_token"] = _encrypt_dpapi(raw_tok)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(disk_cfg, f, indent=2)
        return True
    except Exception as e:
        import logging
        logging.getLogger("config").error(f"Failed to save configuration to {CONFIG_FILE}: {e}")
        return False
