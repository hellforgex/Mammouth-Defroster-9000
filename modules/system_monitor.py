import os
import json
import platform
import psutil
import subprocess
import re
from typing import Any, Literal

_KNOWN_FOLDER_GUIDS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


def _known_folders() -> dict[str, str]:
    """Resolve the user's shell folders (Desktop, Documents, Downloads, ...), honouring OneDrive/redirected folders."""
    home = os.path.expanduser("~")
    folders: dict[str, str] = {"home": home}
    if os.name == "nt":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            def _to_guid(text: str) -> "_GUID":
                u = uuid.UUID(text)
                g = _GUID()
                g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
                for i, b in enumerate(u.bytes[8:]):
                    g.Data4[i] = b
                return g

            shell32 = ctypes.windll.shell32
            ole32 = ctypes.windll.ole32
            shell32.SHGetKnownFolderPath.argtypes = [
                ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)
            ]
            shell32.SHGetKnownFolderPath.restype = ctypes.c_long
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            for key, guid in _KNOWN_FOLDER_GUIDS.items():
                out = ctypes.c_wchar_p()
                hr = shell32.SHGetKnownFolderPath(ctypes.byref(_to_guid(guid)), 0, None, ctypes.byref(out))
                try:
                    if hr == 0 and out.value:
                        folders[key] = out.value
                finally:
                    ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))
        except Exception:
            pass
    for key in _KNOWN_FOLDER_GUIDS:
        folders.setdefault(key, os.path.join(home, key.capitalize()))
    return folders


def system_get_specs() -> dict[str, Any]:
    """Get comprehensive system specs (OS, CPU, RAM, Disk partitions) plus the user's known folders."""
    total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
    avail_ram_gb = round(psutil.virtual_memory().available / (1024**3), 2)
    
    disks = {}
    for part in psutil.disk_partitions():
        if os.name == 'nt' and ('cdrom' in part.opts or not part.fstype):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks[part.device] = {
                "mountpoint": part.mountpoint,
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent_used": usage.percent
            }
        except Exception:
            pass

    return {
        "os": f"{platform.system()} {platform.release()} (Build {platform.version()})",
        "hostname": platform.node(),
        "cpu": platform.processor(),
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "cpu_current_percent": psutil.cpu_percent(interval=0.1),
        "ram_total_gb": total_ram_gb,
        "ram_available_gb": avail_ram_gb,
        "ram_used_percent": psutil.virtual_memory().percent,
        "disks": disks,
        "known_folders": _known_folders(),
    }

def system_get_processes(
    limit: int = 20,
    sort_by: str = "memory",
    filter_name: str | None = None
) -> list[dict[str, Any]]:
    """List top running processes sorted by memory or CPU, with Windows Session IDs.
    
    Args:
        limit: Number of top processes to return (default 20, max 100).
        sort_by: 'memory' or 'cpu'.
        filter_name: Optional case-insensitive substring to filter process names (e.g. 'firefox', 'python', 'Mammouth').
    """
    clean_limit = max(1, min(int(limit), 100))
    clean_sort = "cpu" if str(sort_by).lower() == "cpu" else "memory"
    filter_pattern = str(filter_name).strip().lower() if filter_name else None

    kernel32 = None
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32

    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
        try:
            info = p.info
            p_name = info.get('name') or ""
            if filter_pattern and filter_pattern not in p_name.lower():
                continue

            session_id = -1
            if kernel32:
                sid = ctypes.c_uint()
                if kernel32.ProcessIdToSessionId(info['pid'], ctypes.byref(sid)):
                    session_id = sid.value

            mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1) if info.get('memory_info') else 0
            procs.append({
                "pid": info['pid'],
                "name": p_name,
                "session_id": session_id,
                "memory_mb": mem_mb,
                "memory_percent": round(info['memory_percent'] or 0, 1),
                "cpu_percent": round(info['cpu_percent'] or 0, 1)
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
    if clean_sort == "cpu":
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    else:
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        
    return procs[:clean_limit]

def system_get_gpu_info() -> dict[str, Any]:
    """Get graphics controller / GPU details."""
    try:
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", 
               "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, VideoProcessor, AdapterRAM | ConvertTo-Json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            return {"gpu_devices": json.loads(proc.stdout)}
    except Exception as e:
        return {"error": str(e)}
    return {"gpu": "Unknown / Not detected"}


_EVENT_LOG_POWERSHELL_QUERY = """
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput) {
        Write-Output "[]"
        exit 0
    }
    $inputJson = $rawInput | ConvertFrom-Json
    $filter = @{ LogName = [string]$inputJson.LogName }
    if ($inputJson.Id) {
        $filter["Id"] = [int]$inputJson.Id
    }
    if ($inputJson.Level) {
        $filter["Level"] = [int]$inputJson.Level
    }
    if ($inputJson.ProviderName) {
        $filter["ProviderName"] = [string]$inputJson.ProviderName
    }
    $max = if ($inputJson.MaxEvents) { [int]$inputJson.MaxEvents } else { 10 }
    
    $events = Get-WinEvent -FilterHashtable $filter -MaxEvents $max -ErrorAction Stop
    $result = @($events | ForEach-Object {
        [PSCustomObject]@{
            TimeCreated = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            TimeGenerated = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            EventID = $_.Id
            Level = if ($_.LevelDisplayName) { $_.LevelDisplayName } else { [string]$_.Level }
            ProviderName = if ($_.ProviderName) { $_.ProviderName } else { "" }
            Source = if ($_.ProviderName) { $_.ProviderName } else { "" }
            LogName = if ($_.LogName) { $_.LogName } else { [string]$inputJson.LogName }
            Message = if ($_.Message) { $_.Message.Trim() } else { "" }
        }
    })
    $json = $result | ConvertTo-Json -Depth 3
    [Console]::Out.WriteLine($json)
} catch {
    $msg = $_.Exception.Message
    if ($msg -match "No events were found|Keine Ereignisse|0x80070103|259") {
        Write-Output "[]"
    } else {
        Write-Output ("ERROR:" + $msg)
    }
}
"""

_EVENT_CHANNELS_POWERSHELL_QUERY = """
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
try {
    $rawInput = [Console]::In.ReadToEnd()
    $inputJson = if ($rawInput) { $rawInput | ConvertFrom-Json } else { $null }
    $pattern = if ($inputJson -and $inputJson.Pattern) { [string]$inputJson.Pattern } else { "*" }
    $max = if ($inputJson -and $inputJson.Limit) { [int]$inputJson.Limit } else { 50 }
    
    $logs = Get-WinEvent -ListLog $pattern -ErrorAction SilentlyContinue | Select-Object -First $max
    $result = @($logs | ForEach-Object {
        [PSCustomObject]@{
            LogName = $_.LogName
            RecordCount = if ($_.RecordCount -ne $null) { $_.RecordCount } else { 0 }
            IsEnabled = $_.IsEnabled
            LogMode = [string]$_.LogMode
            FileSize = if ($_.FileSize -ne $null) { $_.FileSize } else { 0 }
        }
    })
    $json = $result | ConvertTo-Json -Depth 2
    [Console]::Out.WriteLine($json)
} catch {
    $msg = $_.Exception.Message
    Write-Output ("ERROR:" + $msg)
}
"""

ENTRY_TYPE_TO_LEVEL: dict[str, int] = {
    "critical": 1,
    "crit": 1,
    "1": 1,
    "error": 2,
    "err": 2,
    "2": 2,
    "warning": 3,
    "warn": 3,
    "3": 3,
    "information": 4,
    "info": 4,
    "informational": 4,
    "4": 4,
    "verbose": 5,
    "verb": 5,
    "5": 5,
}


def system_get_event_logs(
    log_name: str = "System",
    entry_type: str | None = None,
    count: int = 10,
    event_id: int | None = None,
    provider_name: str | None = None,
    channel: str | None = None,
    level: str | None = None,
    id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query recent Windows Event Logs for diagnostics with Get-WinEvent, supporting all standard
    and Application/Services channels (e.g. 'Microsoft-Windows-Kernel-PnP/Device Management'),
    Event IDs (e.g. 1010 for surprise removal/disconnects), and level filters.

    Args:
        log_name: Name of the event log or channel (e.g. 'System', 'Application', 'Security',
                  or any channel under Applications and Services Logs like
                  'Microsoft-Windows-Kernel-PnP/Device Management'). Defaults to 'System'.
        entry_type: Optional filter by event level/type: 'Error', 'Warning', 'Information',
                    'Critical', 'Verbose', or 'All'/None to retrieve events regardless of level.
        count: Max records to return (default 10, max 200).
        event_id: Optional filter for a specific Event ID (e.g. 1010).
        provider_name: Optional filter for event provider name (e.g. 'Microsoft-Windows-Kernel-PnP').
        channel: Parameter alias for log_name.
        level: Parameter alias for entry_type.
        id: Parameter alias for event_id.
        limit: Parameter alias for count.
    """
    # Resolve aliases
    target_log = channel if channel is not None else log_name
    target_type = level if level is not None else entry_type
    target_id = id if id is not None else event_id
    target_count = limit if limit is not None else count

    clean_log = str(target_log).strip() if target_log else "System"
    if not clean_log:
        clean_log = "System"
    if len(clean_log) > 256:
        return [{"error": "Invalid log_name: channel name exceeds maximum length of 256 characters."}]
    if not re.match(r'^[a-zA-Z0-9_\-\./\\ @]+$', clean_log):
        return [{
            "error": f"Invalid characters in log_name '{target_log}'. Channel names may only contain "
                     f"alphanumeric characters, spaces, dots, hyphens, underscores, slashes, and '@'."
        }]

    clean_type = str(target_type).strip() if target_type is not None else ""
    level_int: int | None = None
    if clean_type and clean_type.lower() not in {"all", "*", "any"}:
        level_int = ENTRY_TYPE_TO_LEVEL.get(clean_type.lower())
        if level_int is None:
            return [{
                "error": f"Invalid entry_type '{target_type}'. Allowed values: 'Critical', 'Error', "
                         f"'Warning', 'Information', 'Verbose', 'All', or None."
            }]

    clean_id: int | None = None
    if target_id is not None:
        try:
            clean_id = int(str(target_id).strip())
            if clean_id < 0 or clean_id > 65535:
                return [{"error": f"Invalid event_id '{target_id}'. Event ID must be between 0 and 65535."}]
        except (ValueError, TypeError):
            return [{"error": f"Invalid event_id '{target_id}'. Event ID must be an integer."}]

    clean_provider: str | None = None
    if provider_name is not None and str(provider_name).strip():
        clean_provider = str(provider_name).strip()
        if len(clean_provider) > 256:
            return [{"error": "Invalid provider_name: exceeds maximum length of 256 characters."}]
        if not re.match(r'^[a-zA-Z0-9_\-\./\\ @]+$', clean_provider):
            return [{"error": f"Invalid characters in provider_name '{provider_name}'."}]

    try:
        clean_count = max(1, min(int(str(target_count).strip()), 200))
    except (ValueError, TypeError):
        clean_count = 10

    payload: dict[str, Any] = {
        "LogName": clean_log,
        "MaxEvents": clean_count,
    }
    if level_int is not None:
        payload["Level"] = level_int
    if clean_id is not None:
        payload["Id"] = clean_id
    if clean_provider is not None:
        payload["ProviderName"] = clean_provider

    try:
        ps_cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            _EVENT_LOG_POWERSHELL_QUERY
        ]
        proc = subprocess.run(
            ps_cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20
        )
        out_text = proc.stdout.strip() if proc.stdout else ""
        if out_text.startswith("ERROR:"):
            err_msg = out_text[6:].strip()
            return [{"error": f"Failed to retrieve event logs for '{clean_log}': {err_msg}"}]
        if proc.returncode == 0 and out_text:
            data = json.loads(out_text)
            if isinstance(data, list):
                if not data:
                    return [{"message": f"No event logs found matching criteria in '{clean_log}'."}]
                return data
            return [data]
        return [{"message": f"No event logs found matching criteria in '{clean_log}'."}]
    except subprocess.TimeoutExpired:
        return [{"error": f"Timeout querying Windows event logs for '{clean_log}'."}]
    except Exception as e:
        return [{"error": str(e)}]


def system_list_event_channels(pattern: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List or search available Windows Event Log channels/logs (e.g. 'Kernel-PnP', 'USB', 'System').

    Args:
        pattern: Optional wildcard or substring filter (e.g. 'Kernel-PnP', '*USB*', '*Power*').
        limit: Max channels to return (default 50, max 200).
    """
    clean_limit = 50
    try:
        if limit is not None:
            clean_limit = max(1, min(int(str(limit).strip()), 200))
    except (ValueError, TypeError):
        clean_limit = 50

    clean_pattern = "*"
    if pattern is not None and str(pattern).strip():
        p_str = str(pattern).strip()
        if not re.match(r'^[a-zA-Z0-9_\-\./\\ @*?]+$', p_str):
            return [{"error": f"Invalid characters in pattern '{pattern}'."}]
        if "*" not in p_str and "?" not in p_str:
            clean_pattern = f"*{p_str}*"
        else:
            clean_pattern = p_str

    payload = {
        "Pattern": clean_pattern,
        "Limit": clean_limit
    }

    try:
        ps_cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            _EVENT_CHANNELS_POWERSHELL_QUERY
        ]
        proc = subprocess.run(
            ps_cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20
        )
        out_text = proc.stdout.strip() if proc.stdout else ""
        if out_text.startswith("ERROR:"):
            return [{"error": f"Failed to list event channels: {out_text[6:].strip()}"}]
        if proc.returncode == 0 and out_text:
            data = json.loads(out_text)
            if isinstance(data, list):
                return data
            return [data]
        return []
    except subprocess.TimeoutExpired:
        return [{"error": "Timeout listing Windows event channels."}]
    except Exception as e:
        return [{"error": str(e)}]


def system_specs_dispatch(include_gpu: bool = True) -> dict[str, Any]:
    """Get OS, CPU, RAM, disk specifications and optionally GPU details."""
    specs = system_get_specs()
    if include_gpu:
        specs["gpu"] = system_get_gpu_info()
    return specs


def system_event_logs(
    action: Literal["query", "list_channels"] = "query",
    log_name: str = "System",
    entry_type: str | None = None,
    count: int = 10,
    event_id: int | None = None,
    provider_name: str | None = None,
    pattern: str | None = None
) -> list[dict[str, Any]]:
    """Query Windows Event Logs or discover available event log channels.

    Args:
        action: 'query' (read events) or 'list_channels' (list log channels).
        log_name: Event log/channel name (e.g. 'System', 'Application').
        entry_type: Optional level ('Critical', 'Error', 'Warning', 'Information', 'Verbose').
        count: Max events to return (default 10, max 200).
        event_id: Optional Event ID filter.
        provider_name: Optional provider filter.
        pattern: Optional channel wildcard filter for action='list_channels'.
    """
    if str(action or "query").strip().lower() == "list_channels":
        return system_list_event_channels(pattern=pattern, limit=count or 50)
    return system_get_event_logs(
        log_name=log_name,
        entry_type=entry_type,
        count=count,
        event_id=event_id,
        provider_name=provider_name,
    )

