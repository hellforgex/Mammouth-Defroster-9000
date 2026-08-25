import json
from pathlib import Path
from typing import Dict, Any

CONFIG_FILE = Path(__file__).parent / "config.json"
CONFIG_EXAMPLE_FILE = Path(__file__).parent / "config.example.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "auto_tailscale": True,
        "tailscale_path": r"C:\Program Files\Tailscale\tailscale.exe",
        "custom_public_url": ""
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
            "name": "File & Code Operations",
            "description": "Read, write, search files (grep-like), replace code chunks, and directory trees."
        },
        "shell_processes": {
            "enabled": True,
            "name": "PowerShell & Background Daemons",
            "description": "Execute synchronous commands and manage long-running background tasks."
        },
        "putty_ssh": {
            "enabled": True,
            "name": "PuTTY & SSH Host Manager",
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

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json with fallback to default values."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
        
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
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to config.json."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

def is_module_enabled(module_key: str) -> bool:
    """Check if a specific module/skill is enabled."""
    cfg = load_config()
    mod = cfg.get("modules", {}).get(module_key, {})
    return mod.get("enabled", True)
