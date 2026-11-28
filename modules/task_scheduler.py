"""
Mammouth Defroster 9000 - Automated Task Scheduler & Triggers Module
Provides persistent scheduling, recurring intervals, and automated trigger
capabilities for Mammouth AI Web chat, Mammouth Code CLI, and desktop commands.
"""

import time
import sys
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional
from collections.abc import Callable

logger = logging.getLogger("task_scheduler")

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DB_PATH = BASE_DIR / "tasks.db"

MAX_NAME_LENGTH = 256
MAX_PROMPT_LENGTH = 65536
VALID_STATUSES = {"active", "paused", "completed", "stopped"}
VALID_TARGETS = {"mammouth_web", "chatgpt_web", "claude_web", "gemini_web", "mammouth_code", "powershell", "notification"}

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


def _parse_local_naive_dt(iso_str: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into local naive datetime for reliable comparison."""
    if not iso_str:
        return None
    try:
        s = str(iso_str).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _get_db():
    db_file = Path(DB_PATH)
    db_key = str(db_file)
    needs_schema = (
        db_key not in _schema_ready_paths
        or not db_file.exists()
        or db_file.stat().st_size == 0
    )
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    if needs_schema:
        # Schema DDL + commit only once per DB file and process instead of on every call / scheduler tick
        with _schema_lock:
            needs_schema_locked = (
                db_key not in _schema_ready_paths
                or not db_file.exists()
                or db_file.stat().st_size == 0
            )
            if needs_schema_locked:
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
                    conn.execute('''
                        CREATE TABLE IF NOT EXISTS task_runs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            task_id INTEGER NOT NULL,
                            run_number INTEGER NOT NULL,
                            started_at TEXT NOT NULL,
                            finished_at TEXT NOT NULL,
                            duration_ms INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            exit_code INTEGER DEFAULT 0,
                            output_summary TEXT DEFAULT '',
                            FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE
                        )
                    ''')
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id)")
                _schema_ready_paths.add(db_key)
    return conn


def _shell_module_enabled() -> bool:
    try:
        from config import load_config
        return bool(load_config().get("modules", {}).get("shell_processes", {}).get("enabled", False))
    except Exception:
        return False


def scheduler_get_presets() -> list[dict[str, Any]]:
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
) -> dict[str, Any]:
    """Create a new scheduled automated task.
    
    Args:
        name: Human-readable task name (e.g. '⚽ Live Match Report: Arsenal vs. Chelsea')
        prompt: Action prompt to trigger in Mammouth chat or headless runner
        interval_seconds: Interval in seconds between triggers (minimum 10s)
        repeat_count: 0 for unlimited / continuous, or positive int for max executions
        target: 'mammouth_web', 'chatgpt_web', 'claude_web', 'gemini_web', 'mammouth_code', 'powershell', or 'notification'
        auto_submit: Whether to automatically send the prompt in chat
        switch_tab: Whether to focus the target chat tab upon trigger
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


def scheduler_get_task(task_id: int) -> dict[str, Any]:
    """Retrieve details of a single scheduled task by ID."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (int(task_id),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"error": f"Task {task_id} not found."}
    return dict(row)


def scheduler_list_tasks(status: str | None = None) -> list[dict[str, Any]]:
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
    name: str | None = None,
    prompt: str | None = None,
    interval_seconds: int | None = None,
    repeat_count: int | None = None,
    target: str | None = None,
    auto_submit: bool | None = None,
    switch_tab: bool | None = None,
    status: str | None = None
) -> dict[str, Any]:
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
            if clean_st == "active":
                existing = scheduler_get_task(task_id)
                if "error" not in existing and not existing.get("next_run"):
                    eff_interval = clean_interval if interval_seconds is not None else existing.get("interval_seconds", 300)
                    updates.append("next_run = ?")
                    params.append((datetime.now() + timedelta(seconds=eff_interval)).isoformat())

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


def scheduler_pause_task(task_id: int) -> dict[str, Any]:
    """Pause execution of a scheduled task."""
    return scheduler_update_task(task_id, status="paused")


def scheduler_resume_task(task_id: int) -> dict[str, Any]:
    """Resume a paused, stopped, or completed task."""
    current = scheduler_get_task(task_id)
    if "error" in current:
        return current

    # Re-calculate next run to now + interval
    interval = current.get("interval_seconds", 300)
    next_run = (datetime.now() + timedelta(seconds=interval)).isoformat()

    # If a completed task reached its repeat_count limit, reset runs_done so resuming executes again
    reset_runs = (
        current.get("status") == "completed"
        and current.get("repeat_count", 0) > 0
        and current.get("runs_done", 0) >= current.get("repeat_count", 0)
    )

    conn = _get_db()
    with conn:
        if reset_runs:
            conn.execute("""
                UPDATE scheduled_tasks
                SET status = 'active', runs_done = 0, next_run = ?, updated_at = ?
                WHERE id = ?
            """, (next_run, datetime.now().isoformat(), int(task_id)))
        else:
            conn.execute("""
                UPDATE scheduled_tasks
                SET status = 'active', next_run = ?, updated_at = ?
                WHERE id = ?
            """, (next_run, datetime.now().isoformat(), int(task_id)))
    conn.close()

    TaskSchedulerEngine.get_instance().notify_changed()
    return scheduler_get_task(task_id)


def scheduler_trigger_task_now(task_id: int) -> dict[str, Any]:
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
    """Background engine coordinating task timing and dispatching execution callbacks.

    The engine uses a daemon thread to poll the SQLite database for due tasks
    every *poll_interval* seconds.  Handlers registered via ``register_handler``
    are called **on this background thread**, so GUI-bound handlers must
    marshal work onto the UI thread themselves (e.g. ``tkinter.after``).

    Call ``start_background_loop()`` once after all handlers are registered.
    The GUI helper ``_on_scheduler_tick()`` in ``gui.py`` no longer drives
    execution directly; it only refreshes countdown labels.
    """
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
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._running = False
        self._thread: threading.Thread | None = None

    def register_handler(self, target: str, handler: Callable[[dict[str, Any]], Any]):
        """Register a handler function for a specific target ('mammouth_web', 'mammouth_code', etc.)."""
        self._handlers[target] = handler
        logger.info("Registered handler for target '%s'", target)

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
        """Start background daemon thread polling for due tasks.

        Safe to call multiple times; subsequent calls are no-ops while the
        loop is already running.
        """
        if self._running:
            return
        self._running = True

        def _loop():
            logger.info("TaskSchedulerEngine background loop started (poll=%.1fs)", poll_interval)
            while self._running:
                try:
                    executed = self.check_and_run_due_tasks()
                    if executed:
                        logger.info("Scheduler dispatched %d task(s): %s", len(executed),
                                    ", ".join(f"#{r['id']}({r.get('name','')})" for r in executed))
                except Exception as ex:
                    logger.warning("Scheduler tick error: %s", ex, exc_info=True)
                time.sleep(poll_interval)
            logger.info("TaskSchedulerEngine background loop stopped")

        self._thread = threading.Thread(target=_loop, daemon=True, name="TaskSchedulerThread")
        self._thread.start()

    def stop_background_loop(self):
        self._running = False

    def check_and_run_due_tasks(self) -> list[dict[str, Any]]:
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

    def _check_and_run_due_tasks_locked(self) -> list[dict[str, Any]]:
        now_dt = datetime.now()
        now_str = now_dt.isoformat()

        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM scheduled_tasks
            WHERE status = 'active' AND next_run != ''
        """)
        active_rows = cursor.fetchall()
        conn.close()

        due_rows = []
        for row in active_rows:
            nr_str = row["next_run"]
            nr_dt = _parse_local_naive_dt(nr_str)
            if nr_dt is not None:
                if nr_dt <= now_dt:
                    due_rows.append(row)
            elif nr_str <= now_str:
                due_rows.append(row)

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
            t0 = time.perf_counter()
            started_at = datetime.now().isoformat()
            res_str = "Dispatched"
            try:
                if target in self._handlers:
                    logger.info("Dispatching task #%d '%s' to handler '%s'", task_id, task.get("name"), target)
                    handler_res = self._handlers[target](task)
                    res_str = str(handler_res) if handler_res is not None else "Success"
                    logger.info("Handler '%s' returned: %s", target, res_str[:200])
                else:
                    res_str = f"Error: No handler registered for target '{target}'"
                    logger.warning("Task #%d '%s': no handler registered for target '%s' "
                                   "(registered: %s)", task_id, task.get("name"), target,
                                   list(self._handlers.keys()))
            except Exception as e:
                res_str = f"Error: {e}"
                logger.error("Failed to execute task %d (%s): %s", task_id, task.get("name"), e, exc_info=True)

            duration_ms = round((time.perf_counter() - t0) * 1000)
            finished_at = datetime.now().isoformat()
            run_status = "error" if res_str.startswith("Error") else "success"

            # Store the run result (schedule fields were already advanced by the claim)
            update_conn = _get_db()
            try:
                with update_conn:
                    update_conn.execute(
                        "UPDATE scheduled_tasks SET last_result = ? WHERE id = ?",
                        (res_str[:512], task_id)
                    )
                    update_conn.execute(
                        """
                        INSERT INTO task_runs (task_id, run_number, started_at, finished_at, duration_ms, status, exit_code, output_summary)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (task_id, runs_done, started_at, finished_at, duration_ms, run_status, 0 if run_status == "success" else -1, res_str[:2048])
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


def scheduler_get_history(task_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve execution history logs for a scheduled task."""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM task_runs
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (int(task_id), max(1, min(int(limit), 100))))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def scheduler_test_run(task_id: int, dry_run: bool = False) -> dict[str, Any]:
    """Test run or preview a scheduled task without modifying its recurring schedule.
    
    Args:
        task_id: Task ID to test or preview.
        dry_run: If True, returns a simulation preview without executing any actions.
    """
    task = scheduler_get_task(task_id)
    if "error" in task:
        return task

    if dry_run:
        return {
            "status": "preview",
            "dry_run": True,
            "task_id": task["id"],
            "name": task["name"],
            "target": task["target"],
            "prompt": task["prompt"],
            "interval_seconds": task["interval_seconds"],
            "repeat_count": task["repeat_count"],
            "runs_done": task["runs_done"],
            "next_run": task["next_run"],
            "simulated_action": f"Would dispatch prompt ({len(task['prompt'])} chars) to target '{task['target']}' with auto_submit={bool(task.get('auto_submit', 1))}."
        }

    # Execute single test run immediately
    import time
    engine = TaskSchedulerEngine.get_instance()
    target = task.get("target", "mammouth_web")
    t0 = time.perf_counter()
    started_at = datetime.now().isoformat()
    try:
        if target in engine._handlers:
            handler_res = engine._handlers[target](task)
            res_str = str(handler_res) if handler_res is not None else "Success"
        else:
            res_str = f"Default trigger ({target})"
    except Exception as e:
        res_str = f"Error: {e}"

    duration_ms = round((time.perf_counter() - t0) * 1000)
    finished_at = datetime.now().isoformat()
    run_status = "error" if res_str.startswith("Error") else "success"

    # Record into task_runs table
    conn = _get_db()
    try:
        with conn:
            conn.execute("""
                INSERT INTO task_runs (task_id, run_number, started_at, finished_at, duration_ms, status, exit_code, output_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task["id"], 0, started_at, finished_at, duration_ms, f"test_{run_status}", 0 if run_status == "success" else -1, res_str[:2048]))
    finally:
        conn.close()

    return {
        "status": "success" if run_status == "success" else "error",
        "dry_run": False,
        "task_id": task["id"],
        "duration_ms": duration_ms,
        "result": res_str
    }


def scheduler_update_run_result(
    task_id: int,
    run_number: int,
    status: str,
    exit_code: int,
    output_summary: str,
    duration_ms: int | None = None
) -> None:
    """Update last_result and the corresponding task_runs entry when an async handler finishes."""
    try:
        conn = _get_db()
        with conn:
            conn.execute(
                "UPDATE scheduled_tasks SET last_result = ?, updated_at = ? WHERE id = ?",
                (str(output_summary)[:512], datetime.now().isoformat(), int(task_id))
            )
            if duration_ms is not None:
                conn.execute(
                    """
                    UPDATE task_runs
                    SET status = ?, exit_code = ?, output_summary = ?, finished_at = ?, duration_ms = ?
                    WHERE id = (
                        SELECT id FROM task_runs
                        WHERE task_id = ? AND run_number = ?
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (
                        status,
                        int(exit_code),
                        str(output_summary)[:2048],
                        datetime.now().isoformat(),
                        int(duration_ms),
                        int(task_id),
                        int(run_number),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE task_runs
                    SET status = ?, exit_code = ?, output_summary = ?, finished_at = ?
                    WHERE id = (
                        SELECT id FROM task_runs
                        WHERE task_id = ? AND run_number = ?
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (
                        status,
                        int(exit_code),
                        str(output_summary)[:2048],
                        datetime.now().isoformat(),
                        int(task_id),
                        int(run_number),
                    ),
                )
        conn.close()
        TaskSchedulerEngine.get_instance().notify_changed()
    except Exception as ex:
        logger.debug("scheduler_update_run_result error: %s", ex)


def register_default_handlers(engine: TaskSchedulerEngine | None = None, overwrite: bool = False) -> None:
    """Register built-in headless execution handlers for non-GUI targets (powershell, mammouth_code, notification).

    Called by server lifespan in headless mode so scheduled CLI/PowerShell/alert tasks execute even
    without the Desktop Cockpit GUI running.
    """
    eng = engine or TaskSchedulerEngine.get_instance()

    def _run_powershell(task: dict[str, Any]) -> str:
        prompt = task.get("prompt", "")
        if not _shell_module_enabled():
            return "Error: Target 'powershell' requires module 'shell_processes' to be enabled."
        from modules.shell_processes import powershell_exec
        res = powershell_exec(command=prompt)
        exit_code = res.get("exit_code", -1)
        status = res.get("status", "error")
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or res.get("error") or "").strip()
        if status == "permission_denied":
            return f"Error: {err or 'Permission denied'}"
        if exit_code != 0:
            return f"Error (exit {exit_code}): {err or out}"
        return f"Exit 0: {out[:200]}" if out else "Exit 0 (OK)"

    def _run_mammouth_code(task: dict[str, Any]) -> str:
        prompt = task.get("prompt", "")
        from modules.mammouth_code import run_mammouth_task
        res = run_mammouth_task(task_prompt=prompt, stream_output=False, timeout_seconds=180)
        if res.get("success"):
            return f"Success: {str(res.get('output', '')).strip()[:200]}"
        return f"Error: {res.get('error', 'unknown')}"

    def _run_notification(task: dict[str, Any]) -> str:
        name = task.get("name", "Task")
        prompt = task.get("prompt", "")
        logger.info("[TASK ALERT] %s: %s", name, prompt[:120])
        if sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        return "Notification displayed"

    for tgt, fn in (
        ("powershell", _run_powershell),
        ("mammouth_code", _run_mammouth_code),
        ("notification", _run_notification),
    ):
        if overwrite or tgt not in eng._handlers:
            eng.register_handler(tgt, fn)


def task_schedule_manage(
    action: Literal["list", "presets", "pause", "resume", "trigger", "stop", "test_run", "dry_run", "history", "delete"] = "list",
    task_id: int | None = None,
    status: str | None = None,
    limit: int = 20
) -> dict[str, Any] | list[dict[str, Any]] | str:
    """List, inspect presets/history, control, test, or delete scheduled tasks.

    Args:
        action: 'list', 'presets', 'pause', 'resume', 'trigger', 'stop', 'test_run', 'dry_run', 'history', or 'delete'.
        task_id: Scheduled task ID (required for all actions except 'list' and 'presets').
        status: Optional status filter for 'list' ('active', 'paused', 'completed', 'stopped').
        limit: Max history entries when action='history' (default 20).
    """
    act = str(action or "list").strip().lower()
    if act == "list":
        return scheduler_list_tasks(status=status)
    if act == "presets":
        return scheduler_get_presets()
    if task_id is None:
        return {"error": f"Parameter 'task_id' is required for action='{action}'."}
    tid = int(task_id)
    if act == "pause":
        return scheduler_pause_task(tid)
    if act == "resume":
        return scheduler_resume_task(tid)
    if act in ("trigger", "trigger_now"):
        return scheduler_trigger_task_now(tid)
    if act in ("stop", "abort"):
        return scheduler_update_task(tid, status="stopped")
    if act == "test_run":
        return scheduler_test_run(tid, dry_run=False)
    if act in ("dry_run", "preview"):
        return scheduler_test_run(tid, dry_run=True)
    if act == "history":
        return {"status": "success", "task_id": tid, "history": scheduler_get_history(tid, limit=limit)}
    if act == "delete":
        return scheduler_delete_task(tid)
    return {"error": f"Unknown task_schedule_manage action '{action}'."}

