import json
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
        "auto_tunnel": True,
        "api_token": "",                   # Generated on initial run
        "enforce_auth": False,             # Optional: Require Bearer token or ?token= (Disabled by default for Mammouth compatibility)
        "allowed_origins": [
            "https://mammouth.ai",
            "https://app.mammouth.ai",
            "http://localhost",
            "http://127.0.0.1"
        ],
        "workspace_root": str(Path(__file__).parent / "workspace"),
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
        cfg = DEFAULT_CONFIG.copy()
        cfg["server"]["api_token"] = generate_secure_token()
        save_config(cfg)
        return cfg
        
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        merged = DEFAULT_CONFIG.copy()
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
        cfg = DEFAULT_CONFIG.copy()
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
