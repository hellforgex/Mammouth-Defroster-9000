import json
import copy
import os
import socket
import threading
import time
import secrets
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("config")

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

CONFIG_FILE = BASE_DIR / "config.json"
CONFIG_EXAMPLE_FILE = BASE_DIR / "config.example.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "tunnel_mode": "Tailscale Funnel",  # Options: "Tailscale Funnel", "Cloudflare Tunnel", "ngrok", "Direct / LAN IP", "Custom Domain"
        "endpoint_path": "/sse",           # Options: "/sse", "/mcp", "/messages", "/"
        "auto_tunnel": False,              # Safe by Default: Opt-in for public exposure
        "auto_start_server": True,         # Default in v0.4.0: Native MCP server active on launch
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
        "registration_token": "",          # Optional: If set, only clients with this token in Authorization header can register OAuth clients
        "ssl_certfile": "",
        "ssl_keyfile": "",
        "auto_check_updates": True,        # Automatically check for updates on startup
        "start_in_web_tab": False,         # Chat-First Mode: Auto switch to Mammouth AI tab on startup
        "global_hotkey_enabled": True,     # Global hotkey (Ctrl+Shift+M) to summon/toggle Mammouth Defroster
        "global_hotkey": "Ctrl+Shift+M"
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
        "task_scheduler": {
            "enabled": True,
            "name": "Automated Task Scheduler & Triggers",
            "description": "Scheduled & recurring prompt automation in Mammouth Web, Code CLI, and system."
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
        "mammouth_code": {
            "enabled": True,
            "name": "Mammouth Code CLI Agent",
            "description": "Terminal coding agent integration: 1-click install, interactive launcher, headless task execution, and dual-bridge MCP sync."
        },
        "desktop_input": {
            "enabled": True,
            "name": "Desktop Mouse & Keyboard Automation",
            "description": "Mouse clicks, movement, drag, scroll, keyboard typing, and hotkeys for browser and desktop automation."
        },
        "google_drive": {
            "enabled": True,
            "name": "Google Drive Cloud Storage",
            "description": "Browse, search, read, download, and upload files to Google Drive with OAuth2/Service Account auth."
        },
        "browser_agent": {
            "enabled": True,
            "name": "Playwright Browser Automation Agent",
            "description": "Full automated browser control via Playwright (Edge/Chrome): navigate, click, fill, snapshots, tabs, and JS execution."
        },
    },
    "browser_agent": {
        "channel": "msedge",
        "headless": False,
        "viewport_width": 1280,
        "viewport_height": 800,
        "timeout_seconds": 30,
        "user_data_dir": "./data/agent_browser_profile"
    },
    "mammouth_code": {
        "binary_path": "",
        "api_key": "",
        "auto_sync_mcp": True,
        "default_terminal": "wt",          # "wt" (Windows Terminal) or "powershell"
        "headless_timeout_seconds": 180
    },
    "embedded_browser": {
        "enabled": True,
        "start_page": "https://mammouth.ai",
        "auto_open_on_server_start": True,
        "user_data_dir": "./data/browser_profile",
        "quota_sidebar_enabled": True,
        "quota_refresh_interval_seconds": 300,
        "zen_mode": False
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
    if data_str.startswith("dpapi:"):
        return data_str
    if not HAS_DPAPI:
        raise RuntimeError("DPAPI is unavailable. Plaintext fallback is strictly prohibited.")
    try:
        data_bytes = data_str.encode('utf-8')
        encrypted = win32crypt.CryptProtectData(data_bytes, "Mammouth_Token", None, None, None, 0)
        return "dpapi:" + base64.b64encode(encrypted).decode('ascii')
    except Exception as ex:
        raise RuntimeError(f"DPAPI encryption failed: {ex}")


def _decrypt_dpapi(encrypted_str: str) -> str:
    """Decrypt a 'dpapi:' prefixed string using Windows DPAPI."""
    if not encrypted_str:
        return ""
    if not encrypted_str.startswith("dpapi:"):
        return encrypted_str
    if not HAS_DPAPI:
        raise RuntimeError("DPAPI is unavailable. Plaintext fallback is strictly prohibited.")
    try:
        raw_b64 = encrypted_str[6:]
        raw_bytes = base64.b64decode(raw_b64.encode('ascii'))
        decrypted = win32crypt.CryptUnprotectData(raw_bytes, None, None, None, 0)[1]
        return decrypted.decode('utf-8')
    except Exception as ex:
        raise RuntimeError(f"DPAPI decryption failed: {ex}")


def generate_secure_token() -> str:
    """Generate a cryptographically secure 32-character hex authentication token."""
    return "mc_" + secrets.token_hex(16)


def get_lan_ip() -> str:
    """Detect local network LAN IP (e.g. 192.168.x.x or 10.x.x.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as ex:
        logger.debug(f"Local LAN IP auto-detection fallback to 127.0.0.1: {ex}")
        return "127.0.0.1"


# In-memory cache: load_config() is called on every MCP tool call, so re-reading the file and
# DPAPI-decrypting secrets each time is wasteful. The cache is invalidated by the file's mtime/size.
_config_lock = threading.RLock()
_config_cache: Optional[Dict[str, Any]] = None
_config_cache_stamp: Optional[tuple] = None

# Top-level sections that are merged key-by-key from config.json over DEFAULT_CONFIG.
_MERGED_SECTIONS = ("server", "browser_agent", "mammouth_code", "embedded_browser")


def _config_file_stamp() -> Optional[tuple]:
    try:
        st = CONFIG_FILE.stat()
        return (str(CONFIG_FILE), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_config_from_disk() -> Dict[str, Any]:
    """Build the effective configuration from defaults + config.json. Raises on unreadable JSON."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    token_was_present = False
    needs_save = False
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        for section in _MERGED_SECTIONS:
            if isinstance(user_cfg.get(section), dict):
                cfg[section].update(user_cfg[section])
        # Keep unknown top-level sections (e.g. written by newer/older versions) instead of dropping them
        for key, val in user_cfg.items():
            if key not in cfg:
                cfg[key] = val

        raw_token = cfg["server"].get("api_token", "")
        if raw_token:
            token_was_present = True
            if raw_token.startswith("dpapi:"):
                try:
                    cfg["server"]["api_token"] = _decrypt_dpapi(raw_token)
                except Exception as ex:
                    logger.error(f"Failed to decrypt token, generating a new one: {ex}")
                    cfg["server"]["api_token"] = generate_secure_token()
                    needs_save = True
            else:
                # Manually set plaintext token: keep it but persist encrypted
                needs_save = True

        if isinstance(user_cfg.get("modules"), dict):
            for mod_key, mod_val in user_cfg["modules"].items():
                if mod_key == "unreal_engine":
                    continue  # Retired in v0.5.0
                if mod_key in cfg["modules"] and isinstance(mod_val, dict):
                    cfg["modules"][mod_key].update(mod_val)
                else:
                    cfg["modules"][mod_key] = mod_val

        raw_mc_key = cfg["mammouth_code"].get("api_key", "")
        if raw_mc_key:
            if raw_mc_key.startswith("dpapi:"):
                try:
                    cfg["mammouth_code"]["api_key"] = _decrypt_dpapi(raw_mc_key)
                except Exception as ex:
                    logger.error(f"Failed to decrypt mammouth_code api_key: {ex}")
                    cfg["mammouth_code"]["api_key"] = ""
            else:
                needs_save = True

    # Ensure retired modules are clean
    cfg["modules"].pop("unreal_engine", None)

    # Only generate a token if explicitly empty / missing on disk
    if not cfg["server"].get("api_token") and not token_was_present:
        cfg["server"]["api_token"] = generate_secure_token()
        needs_save = True

    if needs_save:
        save_config(cfg)
    return cfg


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json, merging with defaults if keys are missing.

    Returns a private deep copy (callers may mutate it). A config.json that cannot be parsed —
    e.g. read while another thread/process is mid-write — never triggers a save: the last good
    configuration is returned instead, so a transient read error can no longer reset the user's
    config (and API token) to defaults.
    """
    global _config_cache, _config_cache_stamp
    with _config_lock:
        stamp = _config_file_stamp()
        if _config_cache is not None and stamp == _config_cache_stamp:
            return copy.deepcopy(_config_cache)
        try:
            cfg = _read_config_from_disk()
        except Exception as ex:
            logger.error(f"Failed to read/parse configuration from {CONFIG_FILE}: {ex}")
            if _config_cache is not None:
                return copy.deepcopy(_config_cache)
            # First load and the file is unreadable: run on defaults in memory, but do NOT overwrite it
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg["server"]["api_token"] = generate_secure_token()
            return cfg
        _config_cache = cfg
        _config_cache_stamp = _config_file_stamp()
        return copy.deepcopy(cfg)


def save_config(config_data: Dict[str, Any]) -> bool:
    """Save configuration to config.json atomically (temp file + os.replace), secrets DPAPI-encrypted."""
    global _config_cache, _config_cache_stamp
    try:
        disk_cfg = copy.deepcopy(config_data)
        # Never write retired unreal_engine module to disk
        if "modules" in disk_cfg and "unreal_engine" in disk_cfg["modules"]:
            disk_cfg["modules"].pop("unreal_engine", None)

        raw_tok = disk_cfg.get("server", {}).get("api_token", "")
        if raw_tok and not raw_tok.startswith("dpapi:"):
            encrypted = _encrypt_dpapi(raw_tok)
            if not encrypted.startswith("dpapi:"):
                raise RuntimeError("DPAPI encryption unavailable or failed. Plaintext fallback is strictly prohibited.")
            disk_cfg["server"]["api_token"] = encrypted

        raw_mc_key = disk_cfg.get("mammouth_code", {}).get("api_key", "")
        if raw_mc_key and not raw_mc_key.startswith("dpapi:"):
            encrypted_mc = _encrypt_dpapi(raw_mc_key)
            if not encrypted_mc.startswith("dpapi:"):
                raise RuntimeError("DPAPI encryption unavailable or failed. Plaintext fallback is strictly prohibited.")
            disk_cfg["mammouth_code"]["api_key"] = encrypted_mc

        with _config_lock:
            tmp_path = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(disk_cfg, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # os.replace is atomic on NTFS: readers see either the old or the new file, never a partial one
            for attempt in range(5):
                try:
                    os.replace(tmp_path, CONFIG_FILE)
                    break
                except PermissionError:
                    # Windows: target briefly locked by a concurrent reader / AV scanner
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            _config_cache = None
            _config_cache_stamp = None
        return True
    except Exception as e:
        logger.error(f"Failed to save configuration to {CONFIG_FILE}: {e}")
        try:
            if "tmp_path" in locals() and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False
