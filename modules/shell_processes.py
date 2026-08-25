import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from config import get_app_dir

LOGS_DIR = get_app_dir() / "process_logs"
LOGS_DIR.mkdir(exist_ok=True)

# In-memory registry of background processes
BACKGROUND_PROCESSES: Dict[str, Dict[str, Any]] = {}

def command_run(command: str, cwd: Optional[str] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Execute a local PowerShell command synchronously and return stdout and stderr.
    
    Args:
        command: PowerShell command to run.
        cwd: Working directory (optional).
        timeout_seconds: Timeout in seconds (default 60).
    """
    work_dir = cwd if cwd and os.path.exists(cwd) else os.getcwd()
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=work_dir,
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
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds} seconds."
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

MAX_CONCURRENT_TASKS = 20

def process_start_background(command: str, cwd: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """Start a long-running process in the background (e.g. dev server, script).
    
    Args:
        command: The command line to execute.
        cwd: Working directory (optional).
        name: Short descriptive name for this background task.
    """
    # Count active running processes
    running_count = sum(1 for p in BACKGROUND_PROCESSES.values() if p["proc"].poll() is None)
    if running_count >= MAX_CONCURRENT_TASKS:
        return {"error": f"Process limit reached ({running_count}/{MAX_CONCURRENT_TASKS} active tasks). Terminate finished or running tasks first."}

    task_id = str(uuid.uuid4())[:8]
    task_name = name or f"task-{task_id}"
    log_file = LOGS_DIR / f"{task_id}.log"
    work_dir = cwd if cwd and os.path.exists(cwd) else os.getcwd()
    
    try:
        log_handle = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", command],
            cwd=work_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        BACKGROUND_PROCESSES[task_id] = {
            "id": task_id,
            "name": task_name,
            "command": command,
            "pid": proc.pid,
            "proc": proc,
            "log_file": str(log_file),
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return {
            "task_id": task_id,
            "name": task_name,
            "pid": proc.pid,
            "status": "running",
            "log_file": str(log_file)
        }
    except Exception as e:
        return {"error": f"Failed to start background process: {e}"}

def process_list_background() -> List[Dict[str, Any]]:
    """List all running and finished background processes managed by the MCP server."""
    result = []
    for tid, info in list(BACKGROUND_PROCESSES.items()):
        proc = info["proc"]
        poll = proc.poll()
        status = "running" if poll is None else f"exited (code {poll})"
        result.append({
            "task_id": tid,
            "name": info["name"],
            "command": info["command"],
            "pid": info["pid"],
            "status": status,
            "start_time": info["start_time"]
        })
    return result

def process_get_output(task_id: str, max_lines: int = 50) -> Dict[str, Any]:
    """Get the latest log output from a background process.
    
    Args:
        task_id: The ID of the background task.
        max_lines: Number of trailing log lines to return (default 50).
    """
    if task_id not in BACKGROUND_PROCESSES:
        return {"error": f"Task ID '{task_id}' not found."}
        
    info = BACKGROUND_PROCESSES[task_id]
    log_file = Path(info["log_file"])
    if not log_file.exists():
        return {"output": "", "status": "no log file"}
        
    try:
        content = log_file.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        tail = "\n".join(lines[-max_lines:])
        poll = info["proc"].poll()
        status = "running" if poll is None else f"exited (code {poll})"
        return {
            "task_id": task_id,
            "status": status,
            "output": tail,
            "total_lines": len(lines)
        }
    except Exception as e:
        return {"error": str(e)}

def process_kill_background(task_id: str) -> Dict[str, Any]:
    """Terminate a running background process.
    
    Args:
        task_id: The ID of the background task to kill.
    """
    if task_id not in BACKGROUND_PROCESSES:
        return {"error": f"Task ID '{task_id}' not found."}
        
    info = BACKGROUND_PROCESSES[task_id]
    proc = info["proc"]
    try:
        if proc.poll() is None:
            if os.name == 'nt':
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.terminate()
            return {"status": "terminated", "task_id": task_id, "pid": info["pid"]}
        else:
            return {"status": "already exited", "task_id": task_id}
    except Exception as e:
        return {"error": f"Failed to kill process: {e}"}
