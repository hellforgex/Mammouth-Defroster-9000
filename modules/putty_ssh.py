import os
import sys
import json
import base64
import shutil
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

HOSTS_FILE = Path(__file__).parent.parent / "hosts.json"

BLOCKED_REMOTE_COMMANDS = [
    r'\brm\s+-[^\s]*[rfRF]',
    r'\brm\s+.*--no-preserve-root',
    r'\b(mkfs|wipefs|fdisk|parted)\b',
    r'\bdd\s+.*if=',
    r':\(\)\s*\{\s*:\|\:&\s*\}\s*;\s*:',
    r'\b(shutdown|reboot|poweroff|halt)\b',
    r'\binit\s+[06]\b',
    r'\bsystemctl\s+(poweroff|reboot|halt)\b',
    r'\b(curl|wget)\b.*\|\s*(ba)?sh\b',
    r'>\s*/dev/sd[a-z]',
]


def _validate_remote_command(command: str) -> str:
    """Validate remote command against destructive Linux commands."""
    clean = str(command).strip()
    if not clean:
        raise ValueError("Remote command cannot be empty.")
    for pat in BLOCKED_REMOTE_COMMANDS:
        if re.search(pat, clean, re.IGNORECASE):
            raise PermissionError(f"Security Shield: Destructive remote command pattern blocked: '{pat}'")
    return clean


def _sanitize_param(val: Optional[str], name: str) -> str:
    """Sanitize input parameters to prevent command injection."""
    if not val:
        return ""
    clean = str(val).strip()
    if any(c in clean for c in [";", "&", "|", "`", "$", "\n", "\r", "\"", "'", "<", ">"]):
        raise ValueError(f"Invalid characters detected in '{name}'. Parameter must not contain shell control characters.")
    return clean


def _encrypt_dpapi(plaintext: str) -> str:
    """Encrypt password using Windows DPAPI (Hardware/TPM backed)."""
    if not plaintext:
        return ""
    if plaintext.startswith("dpapi:"):
        return plaintext
    try:
        import win32crypt
        encrypted_blob = win32crypt.CryptProtectData(
            plaintext.encode("utf-8"),
            "MammouthSSHSecret",
            None,
            None,
            None,
            0
        )
        return "dpapi:" + base64.b64encode(encrypted_blob).decode("utf-8")
    except ImportError:
        raise RuntimeError("Windows DPAPI (pywin32) is required for password encryption. Plaintext password storage is prohibited.")
    except Exception as ex:
        raise RuntimeError(f"DPAPI Encryption Error: {ex}. Plaintext password fallback is prohibited.")


def _decrypt_dpapi(ciphertext: str) -> str:
    """Decrypt password using Windows DPAPI."""
    if not ciphertext or not ciphertext.startswith("dpapi:"):
        return ciphertext
    try:
        import win32crypt
        raw_b64 = ciphertext[len("dpapi:"):]
        encrypted_blob = base64.b64decode(raw_b64)
        _, decrypted_blob = win32crypt.CryptUnprotectData(
            encrypted_blob,
            None,
            None,
            None,
            0
        )
        return decrypted_blob.decode("utf-8")
    except Exception as ex:
        return ""


def _load_hosts() -> Dict[str, Any]:
    if not HOSTS_FILE.exists():
        return {}
    try:
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_hosts(data: Dict[str, Any]):
    with open(HOSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def ssh_save_host(
    alias: str,
    host: str,
    username: str = "root",
    password: Optional[str] = None,
    private_key_path: Optional[str] = None,
    port: int = 22,
    description: Optional[str] = None
) -> str:
    """Save an SSH server login profile encrypted with Windows DPAPI."""
    clean_alias = _sanitize_param(alias, "alias")
    clean_host = _sanitize_param(host, "host")
    clean_user = _sanitize_param(username, "username")
    
    if not clean_alias or not clean_host:
        return "Error: alias and host are required."

    encrypted_pw = _encrypt_dpapi(password) if password else ""
    hosts = _load_hosts()
    hosts[clean_alias] = {
        "host": clean_host,
        "username": clean_user or "root",
        "port": int(port) if port else 22,
        "password": encrypted_pw,
        "private_key_path": private_key_path or "",
        "description": description or ""
    }
    _save_hosts(hosts)
    return f"Successfully saved host alias '{clean_alias}' ({clean_user}@{clean_host}:{port}) with DPAPI hardware encryption."


def ssh_list_saved_hosts() -> Dict[str, Any]:
    """List all saved SSH hosts."""
    hosts = _load_hosts()
    sanitized = {}
    for alias, info in hosts.items():
        sanitized[alias] = {
            "host": info.get("host"),
            "username": info.get("username"),
            "port": info.get("port", 22),
            "has_password": bool(info.get("password")),
            "private_key_path": info.get("private_key_path"),
            "description": info.get("description", "")
        }
    return sanitized


def _secure_temp_pwfile(temp_pw_path: str) -> None:
    """Apply strict Owner-only ACLs on Windows for temporary password files."""
    if os.name == 'nt':
        import getpass
        current_user = os.environ.get('USERNAME') or getpass.getuser()
        if not current_user:
            raise PermissionError("Cannot determine current user account for secure tempfile ACLs.")
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        proc = subprocess.run(
            ["icacls", temp_pw_path, "/inheritance:r", "/grant:r", f"{current_user}:(R,W)"],
            capture_output=True,
            text=True,
            creationflags=flags
        )
        if proc.returncode != 0:
            raise PermissionError(f"Failed to set secure owner ACL on password file: {proc.stderr.strip()}")


def ssh_exec_command(
    host: str,
    command: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    private_key_path: Optional[str] = None,
    port: Optional[int] = None,
    session_name: Optional[str] = None,
    timeout_seconds: int = 60
) -> Dict[str, Any]:
    """Execute a remote shell command on any SSH server via PuTTY plink."""
    try:
        clean_command = _validate_remote_command(command)
        target_host = _sanitize_param(host, "host")
        target_user = _sanitize_param(username, "username") if username else None
        clean_session = _sanitize_param(session_name, "session_name") if session_name else None
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"Security Validation Error: {e}"}

    hosts_data = _load_hosts()
    target_pw = password
    target_key = private_key_path
    target_port = port or 22
    
    if host in hosts_data:
        cfg = hosts_data[host]
        target_host = cfg.get("host", host)
        if not target_user:
            target_user = cfg.get("username")
        if not target_pw:
            target_pw = _decrypt_dpapi(cfg.get("password", ""))
        if not target_key:
            target_key = cfg.get("private_key_path")
        if not port:
            target_port = cfg.get("port", 22)
    elif target_pw and target_pw.startswith("dpapi:"):
        target_pw = _decrypt_dpapi(target_pw)

    plink_bin = shutil.which("plink") or r"C:\Program Files\PuTTY\plink.exe"
    if not os.path.exists(plink_bin) and not shutil.which("plink"):
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": "PuTTY plink.exe not found on system. Ensure PuTTY is installed."
        }

    cmd = [plink_bin, "-batch"]
    
    if clean_session:
        cmd.extend(["-load", clean_session])
    if target_port and target_port != 22:
        cmd.extend(["-P", str(int(target_port))])
    if target_user:
        cmd.extend(["-l", target_user])
    if target_key:
        cmd.extend(["-i", target_key])
        
    temp_pw_path = None
    try:
        if target_pw:
            fd, temp_pw_path = tempfile.mkstemp(prefix="md_ssh_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(target_pw + "\n")
            _secure_temp_pwfile(temp_pw_path)
            cmd.extend(["-pwfile", temp_pw_path])

        if not clean_session:
            target = f"{target_user}@{target_host}" if target_user and "@" not in target_host else target_host
            cmd.append(target)

        cmd.append(clean_command)

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"SSH Command timed out after {timeout_seconds}s."}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}
    finally:
        if temp_pw_path and os.path.exists(temp_pw_path):
            try:
                os.remove(temp_pw_path)
            except Exception:
                pass


def ssh_open_putty_window(
    host_or_alias: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    private_key_path: Optional[str] = None,
    port: Optional[int] = None
) -> Dict[str, Any]:
    """Launch an interactive GUI PuTTY terminal window for a saved alias or host."""
    putty_bin = shutil.which("putty") or r"C:\Program Files\PuTTY\putty.exe"
    if not os.path.exists(putty_bin) and not shutil.which("putty"):
        return {"error": "PuTTY GUI executable (putty.exe) not found on system."}

    hosts_data = _load_hosts()
    target_host = host_or_alias
    target_user = username
    target_pw = password
    target_key = private_key_path
    target_port = port or 22
    is_saved_session = False

    if host_or_alias in hosts_data:
        cfg = hosts_data[host_or_alias]
        target_host = cfg.get("host", host_or_alias)
        target_user = target_user or cfg.get("username")
        target_pw = target_pw or _decrypt_dpapi(cfg.get("password", ""))
        target_key = target_key or cfg.get("private_key_path")
        target_port = target_port or cfg.get("port", 22)
    elif host_or_alias in _get_putty_registry_sessions_list():
        is_saved_session = True

    cmd = [putty_bin]
    if is_saved_session:
        cmd.extend(["-load", host_or_alias])
    else:
        if target_port and target_port != 22:
            cmd.extend(["-P", str(int(target_port))])
        if target_user:
            cmd.extend(["-l", target_user])
        if target_key:
            cmd.extend(["-i", target_key])
        target = f"{target_user}@{target_host}" if target_user and "@" not in target_host else target_host
        cmd.append(target)

    try:
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        return {"status": "success", "message": f"Launched PuTTY window for '{host_or_alias}'."}
    except Exception as e:
        return {"error": f"Failed to launch PuTTY: {e}"}


def ssh_transfer_file(
    host: str,
    local_path: str,
    remote_path: str,
    direction: str = "upload",
    username: Optional[str] = None,
    password: Optional[str] = None,
    private_key_path: Optional[str] = None,
    port: Optional[int] = None
) -> Dict[str, Any]:
    """Securely upload or download files via pscp."""
    pscp_bin = shutil.which("pscp") or r"C:\Program Files\PuTTY\pscp.exe"
    if not os.path.exists(pscp_bin) and not shutil.which("pscp"):
        return {"error": "PuTTY pscp.exe not found on system."}

    hosts_data = _load_hosts()
    target_host = host
    target_user = username
    target_pw = password
    target_key = private_key_path
    target_port = port or 22

    if host in hosts_data:
        cfg = hosts_data[host]
        target_host = cfg.get("host", host)
        target_user = target_user or cfg.get("username")
        target_pw = target_pw or _decrypt_dpapi(cfg.get("password", ""))
        target_key = target_key or cfg.get("private_key_path")
        target_port = target_port or cfg.get("port", 22)

    cmd = [pscp_bin, "-batch"]
    if target_port and target_port != 22:
        cmd.extend(["-P", str(int(target_port))])
    if target_user:
        cmd.extend(["-l", target_user])
    if target_key:
        cmd.extend(["-i", target_key])
    temp_pw_path = None
    try:
        if target_pw:
            fd, temp_pw_path = tempfile.mkstemp(prefix="md_pscp_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(target_pw + "\n")
            _secure_temp_pwfile(temp_pw_path)
            cmd.extend(["-pwfile", temp_pw_path])

        user_host = f"{target_user}@{target_host}" if target_user else target_host
        remote_spec = f"{user_host}:{remote_path}"

        if direction == "upload":
            cmd.extend([local_path, remote_spec])
        else:
            cmd.extend([remote_spec, local_path])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "status": "success" if proc.returncode == 0 else "failed"
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if temp_pw_path and os.path.exists(temp_pw_path):
            try:
                os.remove(temp_pw_path)
            except Exception:
                pass


def _get_putty_registry_sessions_list() -> List[str]:
    """Helper to read PuTTY saved sessions from Windows Registry."""
    if os.name != 'nt':
        return []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SimonTatham\PuTTY\Sessions")
        sessions = []
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
                sessions.append(name)
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
        return sessions
    except Exception:
        return []


def ssh_list_putty_registry_sessions() -> Dict[str, Any]:
    """List all saved sessions configured directly in PuTTY's Windows Registry."""
    sessions = _get_putty_registry_sessions_list()
    return {"sessions": sessions, "count": len(sessions)}
