import os
import json
import shutil
import base64
import ctypes
from ctypes import wintypes
import subprocess
import winreg
from pathlib import Path
from typing import Dict, Any, Optional, List

from config import get_app_dir

HOSTS_FILE = get_app_dir() / "hosts.json"

# ==========================================
# WINDOWS DPAPI PASSWORD ENCRYPTION
# ==========================================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char))
    ]

def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt password using current Windows user's DPAPI credentials."""
    if not plaintext or plaintext.startswith("dpapi:"):
        return plaintext
    if os.name != 'nt':
        return plaintext
    try:
        data = plaintext.encode('utf-8')
        blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "MammouthHostPassword",
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out)
        ):
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return "dpapi:" + base64.b64encode(encrypted).decode('ascii')
    except Exception:
        pass
    return plaintext

def _dpapi_decrypt(ciphertext: str) -> str:
    """Decrypt DPAPI-encrypted password for execution."""
    if not ciphertext or not ciphertext.startswith("dpapi:"):
        return ciphertext
    if os.name != 'nt':
        return ciphertext
    try:
        raw_b64 = ciphertext[len("dpapi:"):]
        data = base64.b64decode(raw_b64)
        blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out)
        ):
            decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return decrypted.decode('utf-8', errors='replace')
    except Exception:
        pass
    return ""

def _load_hosts() -> Dict[str, Any]:
    if HOSTS_FILE.exists():
        try:
            return json.loads(HOSTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_hosts(data: Dict[str, Any]):
    HOSTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def ssh_list_saved_hosts() -> List[Dict[str, Any]]:
    """List all configured SSH hosts/aliases from the local secure hosts.json file (passwords masked)."""
    hosts_data = _load_hosts()
    result = []
    for alias, cfg in hosts_data.items():
        result.append({
            "alias": alias,
            "host": cfg.get("host", ""),
            "username": cfg.get("username", ""),
            "port": cfg.get("port", 22),
            "has_password": bool(cfg.get("password")),
            "private_key_path": cfg.get("private_key_path", ""),
            "description": cfg.get("description", "")
        })
    return result

def ssh_save_host(
    alias: str,
    host: str,
    username: str = "root",
    password: Optional[str] = "",
    private_key_path: Optional[str] = "",
    port: int = 22,
    description: str = ""
) -> str:
    """Save or update an SSH host login alias in the local hosts.json file with DPAPI encryption."""
    hosts = _load_hosts()
    encrypted_pw = _dpapi_encrypt(password or "") if password else ""
    hosts[alias] = {
        "host": host,
        "username": username,
        "port": port,
        "password": encrypted_pw,
        "private_key_path": private_key_path or "",
        "description": description
    }
    _save_hosts(hosts)
    return f"Successfully saved host alias '{alias}' ({username}@{host}:{port}) to local hosts.json (Password DPAPI encrypted)"

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
    hosts_data = _load_hosts()
    target_host = host
    target_user = username
    target_pw = password
    target_key = private_key_path
    target_port = port or 22
    
    if host in hosts_data:
        cfg = hosts_data[host]
        target_host = cfg.get("host", host)
        if not target_user:
            target_user = cfg.get("username")
        if not target_pw:
            target_pw = _dpapi_decrypt(cfg.get("password", ""))
        if not target_key:
            target_key = cfg.get("private_key_path")
        if not port:
            target_port = cfg.get("port", 22)
    elif target_pw:
        target_pw = _dpapi_decrypt(target_pw)

    plink_bin = shutil.which("plink") or r"C:\Program Files\PuTTY\plink.exe"
    if not os.path.exists(plink_bin) and not shutil.which("plink"):
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": "PuTTY plink.exe not found on system."
        }

    cmd = [plink_bin, "-batch"]
    
    if session_name:
        cmd.extend(["-load", session_name])
    if target_port and target_port != 22:
        cmd.extend(["-P", str(target_port)])
    if target_user:
        cmd.extend(["-l", target_user])
    if target_pw:
        cmd.extend(["-pw", target_pw])
    if target_key:
        cmd.extend(["-i", target_key])
        
    if not session_name:
        target = f"{target_user}@{target_host}" if target_user and "@" not in target_host else target_host
        cmd.append(target)
        
    cmd.append(command)
    
    try:
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
            "stderr": proc.stderr,
            "host": target_host,
            "command": command
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"PuTTY SSH command timed out after {timeout_seconds} seconds.",
            "host": target_host,
            "command": command
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"SSH error: {str(e)}",
            "host": target_host,
            "command": command
        }

def ssh_open_putty_window(
    host: str,
    username: Optional[str] = None,
    port: Optional[int] = None,
    session_name: Optional[str] = None
) -> Dict[str, Any]:
    """Launch an interactive PuTTY GUI window on the Windows desktop for the user."""
    hosts_data = _load_hosts()
    target_host = host
    target_user = username
    target_port = port or 22
    
    if host in hosts_data:
        cfg = hosts_data[host]
        target_host = cfg.get("host", host)
        if not target_user:
            target_user = cfg.get("username")
        if not port:
            target_port = cfg.get("port", 22)

    putty_bin = shutil.which("putty") or r"C:\Program Files\PuTTY\putty.exe"
    if not os.path.exists(putty_bin) and not shutil.which("putty"):
        return {"error": "PuTTY GUI (putty.exe) not found."}
        
    cmd = [putty_bin]
    if session_name:
        cmd.extend(["-load", session_name])
    else:
        cmd.extend(["-ssh"])
        if target_port and target_port != 22:
            cmd.extend(["-P", str(target_port)])
        if target_user:
            cmd.extend(["-l", target_user])
        cmd.append(target_host)
        
    try:
        subprocess.Popen(cmd)
        return {
            "status": "success",
            "message": f"Launched PuTTY window connecting to {target_user or ''}@{target_host}" if not session_name else f"Launched PuTTY session '{session_name}'"
        }
    except Exception as e:
        return {"error": f"Failed to launch PuTTY: {e}"}

def ssh_transfer_file(
    mode: str,
    local_path: str,
    remote_path: str,
    host: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    private_key_path: Optional[str] = None,
    port: Optional[int] = None,
    recursive: bool = False
) -> Dict[str, Any]:
    """Transfer files between the local PC and a remote SSH server using PuTTY pscp (Sandboxed)."""
    # Validate local path against workspace sandbox policy
    from modules.file_ops import _validate_path_safety
    is_write = mode.lower() == "download"
    path_err = _validate_path_safety(local_path, is_write=is_write)
    if path_err:
        return {"error": path_err}

    # Reject options injection in remote path
    if remote_path.strip().startswith("-"):
        return {"error": "Invalid remote path. Options injection detected."}

    hosts_data = _load_hosts()
    target_host = host
    target_user = username
    target_pw = password
    target_key = private_key_path
    target_port = port or 22
    
    if host in hosts_data:
        cfg = hosts_data[host]
        target_host = cfg.get("host", host)
        if not target_user:
            target_user = cfg.get("username")
        if not target_pw:
            target_pw = _dpapi_decrypt(cfg.get("password", ""))
        if not target_key:
            target_key = cfg.get("private_key_path")
        if not port:
            target_port = cfg.get("port", 22)
    elif target_pw:
        target_pw = _dpapi_decrypt(target_pw)

    pscp_bin = shutil.which("pscp") or r"C:\Program Files\PuTTY\pscp.exe"
    if not os.path.exists(pscp_bin) and not shutil.which("pscp"):
        return {"error": "PuTTY pscp.exe not found on system."}
        
    cmd = [pscp_bin, "-batch"]
    if recursive:
        cmd.append("-r")
    if target_port and target_port != 22:
        cmd.extend(["-P", str(target_port)])
    if target_user:
        cmd.extend(["-l", target_user])
    if target_pw:
        cmd.extend(["-pw", target_pw])
    if target_key:
        cmd.extend(["-i", target_key])
        
    target_remote = f"{target_user}@{target_host}:{remote_path}" if target_user and "@" not in target_host else f"{target_host}:{remote_path}"
    
    if mode.lower() == "upload":
        cmd.extend([local_path, target_remote])
    elif mode.lower() == "download":
        cmd.extend([target_remote, local_path])
    else:
        return {"error": "Invalid mode. Use 'upload' or 'download'."}
        
    try:
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
            "mode": mode,
            "success": proc.returncode == 0
        }
    except Exception as e:
        return {"error": f"PSCP error: {str(e)}"}

def ssh_list_putty_registry_sessions() -> List[Dict[str, Any]]:
    """List all saved PuTTY sessions from the Windows Registry."""
    sessions = []
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SimonTatham\PuTTY\Sessions")
        i = 0
        while True:
            try:
                session_name = winreg.EnumKey(key, i)
                sub_key = winreg.OpenKey(key, session_name)
                host = ""
                user = ""
                port = 22
                
                num_vals = winreg.QueryInfoKey(sub_key)[1]
                for j in range(num_vals):
                    val_name, val_data, _ = winreg.EnumValue(sub_key, j)
                    if val_name == "HostName":
                        host = str(val_data)
                    elif val_name == "UserName":
                        user = str(val_data)
                    elif val_name == "PortNumber":
                        port = int(val_data)
                        
                sessions.append({
                    "session_name": session_name,
                    "host": host,
                    "username": user,
                    "port": port
                })
                winreg.CloseKey(sub_key)
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except Exception as e:
        return [{"error": f"Could not read PuTTY registry: {e}"}]
        
    return sessions
