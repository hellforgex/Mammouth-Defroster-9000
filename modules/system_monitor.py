import os
import json
import platform
import psutil
import subprocess
from typing import Dict, Any, List

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

def system_get_processes(limit: int = 20, sort_by: str = "memory") -> List[Dict[str, Any]]:
    """List top running processes sorted by memory or CPU.
    
    Args:
        limit: Number of top processes to return (default 20, max 100).
        sort_by: 'memory' or 'cpu'.
    """
    clean_limit = max(1, min(int(limit), 100))
    clean_sort = "cpu" if str(sort_by).lower() == "cpu" else "memory"

    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
        try:
            info = p.info
            mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1) if info.get('memory_info') else 0
            procs.append({
                "pid": info['pid'],
                "name": info['name'],
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

def system_get_event_logs(log_name: str = "System", entry_type: str = "Error", count: int = 10) -> List[Dict[str, Any]]:
    """Query recent Windows Event Logs for diagnostics with strict parameter validation.
    
    Args:
        log_name: 'System', 'Application', or 'Security'.
        entry_type: 'Error', 'Warning', or 'Information'.
        count: Max records to return (default 10, max 100).
    """
    valid_logs = {"System", "Application", "Security"}
    valid_types = {"Error", "Warning", "Information"}

    clean_log = str(log_name).strip()
    if clean_log not in valid_logs:
        return [{"error": f"Invalid log_name '{log_name}'. Allowed values: {sorted(list(valid_logs))}"}]

    clean_type = str(entry_type).strip()
    if clean_type not in valid_types:
        return [{"error": f"Invalid entry_type '{entry_type}'. Allowed values: {sorted(list(valid_types))}"}]

    try:
        clean_count = max(1, min(int(str(count).strip()), 100))
        ps_cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "param($log, $type, $num) Get-EventLog -LogName $log -EntryType $type -Newest $num | Select-Object TimeGenerated, Source, EventID, Message | ConvertTo-Json",
            clean_log, clean_type, str(clean_count)
        ]
        proc = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            return data if isinstance(data, list) else [data]
        return [{"message": "No event logs found matching criteria."}]
    except Exception as e:
        return [{"error": str(e)}]
