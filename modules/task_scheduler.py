"""
Mammouth Defroster 9000 - Automated Task Scheduler & Triggers Module
Provides persistent scheduling, recurring intervals, and automated trigger
capabilities for Mammouth AI Web chat, Mammouth Code CLI, and desktop commands.
"""

import os
import sys
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger("task_scheduler")

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DB_PATH = BASE_DIR / "tasks.db"

MAX_NAME_LENGTH = 256
MAX_PROMPT_LENGTH = 65536
VALID_STATUSES = {"active", "paused", "completed", "stopped"}
VALID_TARGETS = {"mammouth_web", "mammouth_code", "powershell", "notification"}

# Built-in high-value presets
PRESET_TEMPLATES = [
    {
        "id": "football_live",
        "name": "⚽ Live Match Report: Football",
        "prompt": "Provide a detailed live report on the current football match: search the web for the latest score, goals, cards, substitutions, and match events over the last 5 minutes.",
        "interval_seconds": 300,  # 5 min
        "repeat_count": 20,       # 20 runs = ~100 min
        "target": "mammouth_web",
        "description": "Generates a live ticker for the ongoing match with goals & highlights every 5 minutes."
    },
    {
        "id": "crypto_ticker",
        "name": "📈 Crypto & Finance Ticker",
        "prompt": "Check the current prices of Bitcoin (BTC), Ethereum (ETH), and Solana (SOL) as well as the S&P 500 / NASDAQ. Summarize the key market movements from the last 15 minutes concisely.",
        "interval_seconds": 900,  # 15 min
        "repeat_count": 0,        # continuous
        "target": "mammouth_web",
        "description": "Summarize current market and cryptocurrency prices in chat every 15 minutes."
    },
    {
        "id": "system_health",
        "name": "🖥️ System & Hardware Health Check",
        "prompt": "Use system_get_specs and system_get_processes to inspect current CPU, RAM, and process utilization, and report any anomalies.",
        "interval_seconds": 600,  # 10 min
        "repeat_count": 0,
        "target": "mammouth_web",
        "description": "Periodic system diagnostics and load spike detection every 10 minutes."
    },
    {
        "id": "mammouth_code_scan",
        "name": "💻 Mammouth Code Workspace Review",
        "prompt": "Examine the current project for bugs and incomplete features, and compile a to-do list of upcoming improvements.",
        "interval_seconds": 1800, # 30 min
        "repeat_count": 4,
        "target": "mammouth_code",
        "description": "Headless Coding Agent executes an automated code review every 30 minutes."
    },
    {
        "id": "news_flash",
        "name": "📰 Breaking News & Headlines",
        "prompt": "Search for the top breaking news and headlines from the past hour across world, tech, and business, and summarize the top 3.",
        "interval_seconds": 3600, # 60 min
        "repeat_count": 0,
        "target": "mammouth_web",
        "description": "Hourly summary of top headlines and breaking news."
    }
]


_schema_ready_paths = set()  # DB files whose schema was created in this process
_schema_lock = threading.Lock()


def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    db_key = str(DB_PATH)
    if db_key not in _schema_ready_paths:
        # Schema DDL + commit only once per DB file and process instead of on every call / scheduler tick
        with _schema_lock:
            if db_key not in _schema_ready_paths:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS scheduled_tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            prompt TEXT NOT NULL,
                            interval_seconds INTEGER NOT NULL DEFAULT 300,
                            repeat_count INTEGER NOT NULL DEFAULT 0,
                            runs_done INTEGER NOT NULL DEFAULT 0,
                            target TEXT NOT NULL DEFAULT 'mammouth_web',
                            status TEXT NOT NULL DEFAULT 'active',
                            auto_submit INTEGER NOT NULL DEFAULT 1,
                            switch_tab INTEGER NOT NULL DEFAULT 1,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            last_run TEXT DEFAULT '',
                            next_run TEXT DEFAULT '',
                            last_result TEXT DEFAULT ''
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled_tasks(status)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_sched_next_run ON scheduled_tasks(next_run)")
                _schema_ready_paths.add(db_key)
    return conn


def _shell_module_enabled() -> bool:
    try:
        from config import load_config
        return bool(load_config().get("modules", {}).get("shell_processes", {}).get("enabled", False))
    except Exception:
        return False


def scheduler_get_presets() -> List[Dict[str, Any]]:
    """Return available pre-configured templates."""
    return [dict(p) for p in PRESET_TEMPLATES]


def scheduler_create_task(
    name: str,
    prompt: str,
    interval_seconds: int = 300,
    repeat_count: int = 0,
    target: str = "mammouth_web",
    auto_submit: bool = True,
    switch_tab: bool = True,
    start_immediately: bool = False
) -> Dict[str, Any]:
    """Create a new scheduled automated task.
    
    Args:
        name: Human-readable task name (e.g. '⚽ Livebericht: FC Bayern vs. Dortmund')
        prompt: Action prompt to trigger in Mammouth chat or headless runner
        interval_seconds: Interval in seconds between triggers (minimum 10s)
        repeat_count: 0 for unlimited / continuous, or positive int for max executions
        target: 'mammouth_web', 'mammouth_code', 'powershell', or 'notification'
        auto_submit: Whether to automatically send the prompt in chat
        switch_tab: Whether to focus the Mammouth tab upon trigger
        start_immediately: If True, first trigger occurs in 2 seconds; otherwise after interval
    """
    clean_name = str(name).strip()[:MAX_NAME_LENGTH]
    if not clean_name:
        return {"error": "Task name cannot be empty."}

    clean_prompt = str(prompt).strip()[:MAX_PROMPT_LENGTH]
    if not clean_prompt:
        return {"error": "Task prompt cannot be empty."}

    clean_interval = max(10, int(interval_seconds))
    clean_repeats = max(0, int(repeat_count))
    clean_target = str(target).lower().strip()
    if clean_target not in VALID_TARGETS:
        clean_target = "mammouth_web"
    if clean_target == "powershell" and not _shell_module_enabled():
        return {"error": "Target 'powershell' requires the 'shell_processes' module to be enabled in the Defroster cockpit."}

    now_dt = datetime.now()
    now_str = now_dt.isoformat()

    if start_immediately:
        next_run_dt = now_dt - timedelta(seconds=1)
    else:
        next_run_dt = now_dt + timedelta(seconds=clean_interval)

    next_run_str = next_run_dt.isoformat()

    conn = _get_db()
    with conn:
        cursor = conn.execute("""
            INSERT INTO scheduled_tasks (
                name, prompt, interval_seconds, repeat_count, runs_done,
                target, status, auto_submit, switch_tab,
                created_at, updated_at, last_run, next_run, last_result
            ) VALUES (?, ?, ?, ?, 0, ?, 'active', ?, ?, ?, ?, '', ?, 'Scheduled')
        """, (
            clean_name,
            clean_prompt,
            clean_interval,
            clean_repeats,
            clean_target,
            1 if auto_submit else 0,
            1 if switch_tab else 0,
            now_str,
            now_str,
            next_run_str
        ))
        task_id = cursor.lastrowid
    conn.close()

    task_obj = scheduler_get_task(task_id)
    TaskSchedulerEngine.get_instance().notify_changed()
    return task_obj


def scheduler_get_task(task_id: int) -> Dict[str, Any]:
    """Retrieve details of a single scheduled task by ID."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (int(task_id),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"error": f"Task {task_id} not found."}
    return dict(row)


def scheduler_list_tasks(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all scheduled tasks optionally filtered by status."""
    conn = _get_db()
    cursor = conn.cursor()
    if status and str(status).lower().strip() in VALID_STATUSES:
        cursor.execute("SELECT * FROM scheduled_tasks WHERE status = ? ORDER BY id DESC", (str(status).lower().strip(),))
    else:
        cursor.execute("SELECT * FROM scheduled_tasks ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def scheduler_update_task(
    task_id: int,
    name: Optional[str] = None,
    prompt: Optional[str] = None,
    interval_seconds: Optional[int] = None,
    repeat_count: Optional[int] = None,
    target: Optional[str] = None,
    auto_submit: Optional[bool] = None,
    switch_tab: Optional[bool] = None,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """Update properties of an existing scheduled task."""
    updates = []
    params = []

    if name is not None:
        clean_name = str(name).strip()[:MAX_NAME_LENGTH]
        if clean_name:
            updates.append("name = ?")
            params.append(clean_name)

    if prompt is not None:
        clean_prompt = str(prompt).strip()[:MAX_PROMPT_LENGTH]
        if clean_prompt:
            updates.append("prompt = ?")
            params.append(clean_prompt)

    if interval_seconds is not None:
        clean_interval = max(10, int(interval_seconds))
        updates.append("interval_seconds = ?")
        params.append(clean_interval)

    if repeat_count is not None:
        updates.append("repeat_count = ?")
        params.append(max(0, int(repeat_count)))

    if target is not None:
        clean_target = str(target).lower().strip()
        if clean_target == "powershell" and not _shell_module_enabled():
            return {"error": "Target 'powershell' requires the 'shell_processes' module to be enabled in the Defroster cockpit."}
        if clean_target in VALID_TARGETS:
            updates.append("target = ?")
            params.append(clean_target)

    if auto_submit is not None:
        updates.append("auto_submit = ?")
        params.append(1 if auto_submit else 0)

    if switch_tab is not None:
        updates.append("switch_tab = ?")
        params.append(1 if switch_tab else 0)

    if status is not None:
        clean_st = str(status).lower().strip()
        if clean_st in VALID_STATUSES:
            updates.append("status = ?")
            params.append(clean_st)

    if not updates:
        return {"error": "No valid fields to update."}

    now_str = datetime.now().isoformat()
    updates.append("updated_at = ?")
    params.append(now_str)
    params.append(int(task_id))

    conn = _get_db()
    try:
        with conn:
            cursor = conn.execute(f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE id = ?", params)
            updated = cursor.rowcount
    finally:
        conn.close()
    if updated == 0:
        return {"error": f"Task {task_id} not found."}

    TaskSchedulerEngine.get_instance().notify_changed()
    return scheduler_get_task(task_id)


def scheduler_delete_task(task_id: int) -> str:
    """Delete a scheduled task permanently."""
    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (int(task_id),))
        deleted = cursor.rowcount > 0
    conn.close()
    if deleted:
        TaskSchedulerEngine.get_instance().notify_changed()
        return f"Successfully deleted scheduled task {task_id}."
    return f"Scheduled task {task_id} not found."


def scheduler_pause_task(task_id: int) -> Dict[str, Any]:
    """Pause execution of a scheduled task."""
    return scheduler_update_task(task_id, status="paused")


def scheduler_resume_task(task_id: int) -> Dict[str, Any]:
    """Resume a paused or stopped task."""
    current = scheduler_get_task(task_id)
    if "error" in current:
        return current

    # Re-calculate next run to now + interval
    interval = current.get("interval_seconds", 300)
    next_run = (datetime.now() + timedelta(seconds=interval)).isoformat()

    conn = _get_db()
    with conn:
        conn.execute("""
            UPDATE scheduled_tasks
            SET status = 'active', next_run = ?, updated_at = ?
            WHERE id = ?
        """, (next_run, datetime.now().isoformat(), int(task_id)))
    conn.close()

    TaskSchedulerEngine.get_instance().notify_changed()
    return scheduler_get_task(task_id)


def scheduler_trigger_task_now(task_id: int) -> Dict[str, Any]:
    """Immediately trigger a scheduled task without waiting for the interval."""
    current = scheduler_get_task(task_id)
    if "error" in current:
        return current

    # Set next_run to now so the engine executes it immediately
    now_str = (datetime.now() - timedelta(seconds=1)).isoformat()
    conn = _get_db()
    with conn:
        conn.execute("""
            UPDATE scheduled_tasks
            SET status = 'active', next_run = ?, updated_at = ?
            WHERE id = ?
        """, (now_str, datetime.now().isoformat(), int(task_id)))
    conn.close()

    # Do not dispatch from this (MCP worker) thread: handlers belong to the scheduler tick.
    # The task is due now and will be picked up within ~1 second.
    TaskSchedulerEngine.get_instance().notify_changed()
    return {
        "status": "triggered",
        "task_id": task_id,
        "message": "Task is due now and will run on the next scheduler tick (within ~1s)."
    }


class TaskSchedulerEngine:
    """Background engine coordinating task timing and dispatching execution callbacks."""
    _instance: Optional["TaskSchedulerEngine"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TaskSchedulerEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = TaskSchedulerEngine()
            return cls._instance

    def __init__(self):
        self._run_lock = threading.Lock()
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._listeners: List[Callable[[], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register_handler(self, target: str, handler: Callable[[Dict[str, Any]], Any]):
        """Register a handler function for a specific target ('mammouth_web', 'mammouth_code', etc.)."""
        self._handlers[target] = handler

    def register_listener(self, callback: Callable[[], None]):
        """Register a callback notified on task additions, updates, or triggers."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[], None]):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def notify_changed(self):
        """Invoke all change listeners safely."""
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as e:
                logger.debug(f"Error in scheduler change listener: {e}")

    def start_background_loop(self, poll_interval: float = 1.0):
        """Start background daemon thread polling for due tasks."""
        if self._running:
            return
        self._running = True

        def _loop():
            import time
            while self._running:
                try:
                    self.check_and_run_due_tasks()
                except Exception as ex:
                    logger.debug(f"Scheduler tick error: {ex}")
                time.sleep(poll_interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="TaskSchedulerThread")
        self._thread.start()

    def stop_background_loop(self):
        self._running = False

    def check_and_run_due_tasks(self) -> List[Dict[str, Any]]:
        """Check all active tasks and execute any that are due.

        Serialized by a lock, and every due row is claimed atomically (compare-and-set on next_run)
        before its handler runs, so concurrent callers can never execute the same run twice.
        """
        if not self._run_lock.acquire(blocking=False):
            return []  # another tick is already dispatching
        try:
            return self._check_and_run_due_tasks_locked()
        finally:
            self._run_lock.release()

    def _check_and_run_due_tasks_locked(self) -> List[Dict[str, Any]]:
        now_dt = datetime.now()
        now_str = now_dt.isoformat()

        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM scheduled_tasks
            WHERE status = 'active' AND next_run != '' AND next_run <= ?
        """, (now_str,))
        due_rows = cursor.fetchall()
        conn.close()

        if not due_rows:
            return []

        executed_reports = []

        for row in due_rows:
            task = dict(row)
            task_id = task["id"]
            target = task.get("target", "mammouth_web")
            runs_done = task.get("runs_done", 0) + 1
            repeat_count = task.get("repeat_count", 0)
            interval_seconds = task.get("interval_seconds", 300)

            # Determine whether task is completed
            is_completed = (repeat_count > 0 and runs_done >= repeat_count)
            new_status = "completed" if is_completed else "active"
            next_run_str = "" if is_completed else (now_dt + timedelta(seconds=interval_seconds)).isoformat()

            # Claim this run before dispatching: only proceeds if nobody advanced next_run meanwhile
            claim_conn = _get_db()
            try:
                with claim_conn:
                    claimed = claim_conn.execute("""
                        UPDATE scheduled_tasks
                        SET runs_done = ?, status = ?, last_run = ?, next_run = ?, updated_at = ?
                        WHERE id = ? AND status = 'active' AND next_run = ?
                    """, (runs_done, new_status, now_str, next_run_str, now_str, task_id, task.get("next_run", ""))).rowcount
            finally:
                claim_conn.close()
            if not claimed:
                continue

            # Execute via registered handler or default fallback
            res_str = "Dispatched"
            try:
                if target in self._handlers:
                    handler_res = self._handlers[target](task)
                    res_str = str(handler_res) if handler_res is not None else "Success"
                else:
                    res_str = f"Default trigger ({target})"
            except Exception as e:
                res_str = f"Error: {e}"
                logger.error(f"Failed to execute task {task_id} ({task.get('name')}): {e}")

            # Store the run result (schedule fields were already advanced by the claim)
            update_conn = _get_db()
            try:
                with update_conn:
                    update_conn.execute(
                        "UPDATE scheduled_tasks SET last_result = ? WHERE id = ?",
                        (res_str[:512], task_id)
                    )
            finally:
                update_conn.close()

            executed_reports.append({
                "id": task_id,
                "name": task.get("name"),
                "runs_done": runs_done,
                "status": new_status,
                "result": res_str
            })

        self.notify_changed()
        return executed_reports
