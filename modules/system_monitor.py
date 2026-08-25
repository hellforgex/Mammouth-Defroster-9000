import os
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
        limit: Number of top processes to return (default 20).
        sort_by: 'memory' or 'cpu'.
    """
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
            
    if sort_by.lower() == "cpu":
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    else:
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        
    return procs[:limit]

def system_get_gpu_info() -> Dict[str, Any]:
    """Get graphics controller / GPU details."""
    try:
        cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, VideoProcessor, AdapterRAM | ConvertTo-Json"
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            import json
            return {"gpu_devices": json.loads(proc.stdout)}
    except Exception as e:
        return {"error": str(e)}
    return {"gpu": "Unknown / Not detected"}

def system_get_event_logs(log_name: str = "System", entry_type: str = "Error", count: int = 10) -> List[Dict[str, Any]]:
    """Query recent Windows Event Logs for diagnostics.
    
    Args:
        log_name: 'System', 'Application', or 'Security'.
        entry_type: 'Error', 'Warning', or 'Information'.
        count: Max records to return (default 10).
    """
    try:
        ps_cmd = f"Get-EventLog -LogName '{log_name}' -EntryType '{entry_type}' -Newest {count} | Select-Object TimeGenerated, Source, EventID, Message | ConvertTo-Json"
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            import json
            data = json.loads(proc.stdout)
            return data if isinstance(data, list) else [data]
        return [{"message": "No event logs found matching criteria."}]
    except Exception as e:
        return [{"error": str(e)}]
