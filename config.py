import sys
import json
import copy
import socket
import secrets
from pathlib import Path
from typing import Dict, Any, Optional, List

def get_app_dir() -> Path:
    """Return root directory where config, DBs, and runtime files reside (handles PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

APP_DIR = get_app_dir()
CONFIG_FILE = APP_DIR / "config.json"
CONFIG_EXAMPLE_FILE = APP_DIR / "config.example.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "tunnel_mode": "Tailscale Funnel",  # Options: "Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"
        "endpoint_path": "/mcp",           # Options: "/mcp", "/sse", "/messages", "/"
        "auto_tunnel": True,
        "api_token": "",                   # Generated on initial run
        "enforce_auth": True,              # Require Bearer token or ?token= in URL
        "allowed_origins": [
            "https://mammouth.ai",
            "https://app.mammouth.ai",
            "http://localhost",
            "http://127.0.0.1"
        ],
        "workspace_root": str(APP_DIR / "workspace"),
        "enforce_workspace_sandbox": True,  # Prevent path traversal outside workspace
        "tailscale_path": r"C:\Program Files\Tailscale\tailscale.exe",
        "cloudflared_path": "cloudflared",
        "ngrok_path": "ngrok",
        "custom_public_url": "",
        "cloudflare_custom_url": "",
        "ngrok_custom_url": ""
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
            "enabled": True,
            "name": "Web Scraper & URL Tools",
            "description": "Fetch and extract clean markdown/text from webpages, and check endpoint status."
        }
    }
}

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
    """Load configuration from config.json with fallback to default values."""
    if not CONFIG_FILE.exists():
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["server"]["api_token"] = generate_secure_token()
        save_config(cfg)
        return cfg
        
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        merged = copy.deepcopy(DEFAULT_CONFIG)
        if "server" in data:
            merged["server"].update(data["server"])
        if "modules" in data:
            for k, v in data["modules"].items():
                if k in merged["modules"]:
                    merged["modules"][k].update(v)
                else:
                    merged["modules"][k] = v
                    
        # Ensure an API token exists
        if not merged["server"].get("api_token"):
            merged["server"]["api_token"] = generate_secure_token()
            save_config(merged)
            
        return merged
    except Exception:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["server"]["api_token"] = generate_secure_token()
        return cfg

def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to config.json."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

def is_module_enabled(module_key: str) -> bool:
    """Check if a specific module/skill is enabled."""
    cfg = load_config()
    mod = cfg.get("modules", {}).get(module_key, {})
    return mod.get("enabled", True)
