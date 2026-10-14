import os
import json
import platform
import psutil
import subprocess
import re
from typing import Dict, Any, List, Optional

def system_get_specs() -> Dict[str, Any]:
    """Get comprehensive system specs (OS, CPU, RAM, Disk partitions)."""
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
    }

def system_get_processes(
    limit: int = 20,
    sort_by: str = "memory",
    filter_name: Optional[str] = None
) -> List[Dict[str, Any]]:
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

def system_get_gpu_info() -> Dict[str, Any]:
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

ENTRY_TYPE_TO_LEVEL: Dict[str, int] = {
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
    entry_type: Optional[str] = None,
    count: int = 10,
    event_id: Optional[int] = None,
    provider_name: Optional[str] = None,
    channel: Optional[str] = None,
    level: Optional[str] = None,
    id: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
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
    level_int: Optional[int] = None
    if clean_type and clean_type.lower() not in {"all", "*", "any"}:
        level_int = ENTRY_TYPE_TO_LEVEL.get(clean_type.lower())
        if level_int is None:
            return [{
                "error": f"Invalid entry_type '{target_type}'. Allowed values: 'Critical', 'Error', "
                         f"'Warning', 'Information', 'Verbose', 'All', or None."
            }]

    clean_id: Optional[int] = None
    if target_id is not None:
        try:
            clean_id = int(str(target_id).strip())
            if clean_id < 0 or clean_id > 65535:
                return [{"error": f"Invalid event_id '{target_id}'. Event ID must be between 0 and 65535."}]
        except (ValueError, TypeError):
            return [{"error": f"Invalid event_id '{target_id}'. Event ID must be an integer."}]

    clean_provider: Optional[str] = None
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

    payload: Dict[str, Any] = {
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


def system_list_event_channels(pattern: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
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

