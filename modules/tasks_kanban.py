import threading
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import sys

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DB_PATH = BASE_DIR / "tasks.db"

MAX_TITLE_LENGTH = 256
MAX_DESC_LENGTH = 65536  # 64 KB
VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}

_schema_ready_paths = set()  # DB files whose schema was created in this process
_schema_lock = threading.Lock()


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    db_key = str(DB_PATH)
    if db_key not in _schema_ready_paths:
        # Schema DDL + commit only once per DB file and process instead of on every call / scheduler tick
        with _schema_lock:
            if db_key not in _schema_ready_paths:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            description TEXT DEFAULT '',
                            status TEXT DEFAULT 'todo',
                            priority TEXT DEFAULT 'medium',
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
                _schema_ready_paths.add(db_key)
    return conn

def task_create(title: str, description: str = "", priority: str = "medium") -> dict[str, Any]:
    """Create a new task in the persistent todo/Kanban board.
    
    Args:
        title: Short actionable title of the task (max 256 chars).
        description: Detailed instructions or subtasks (max 64 KB).
        priority: 'low', 'medium', 'high', 'urgent'.
    """
    clean_title = str(title).strip()[:MAX_TITLE_LENGTH]
    if not clean_title:
        return {"error": "Task title cannot be empty."}

    clean_desc = str(description).strip()[:MAX_DESC_LENGTH]
    clean_prio = str(priority).lower().strip()
    if clean_prio not in VALID_PRIORITIES:
        clean_prio = "medium"

    now = datetime.now().isoformat()
    conn = _get_db()
    with conn:
        cursor = conn.execute("""
            INSERT INTO tasks (title, description, status, priority, created_at, updated_at)
            VALUES (?, ?, 'todo', ?, ?, ?)
        """, (clean_title, clean_desc, clean_prio, now, now))
        task_id = cursor.lastrowid
    conn.close()
    return {
        "id": task_id,
        "title": clean_title,
        "description": clean_desc,
        "status": "todo",
        "priority": clean_prio,
        "created_at": now
    }

def task_update(
    task_id: int | None = None,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    id: int | None = None
) -> dict[str, Any]:
    """Update task status ('todo', 'in_progress', 'done', 'blocked') or details."""
    updates = []
    params = []
    
    if status is not None:
        clean_st = str(status).lower().strip()
        if clean_st in VALID_STATUSES:
            updates.append("status = ?")
            params.append(clean_st)
            
    if title is not None:
        clean_title = str(title).strip()[:MAX_TITLE_LENGTH]
        if clean_title:
            updates.append("title = ?")
            params.append(clean_title)
            
    if description is not None:
        updates.append("description = ?")
        params.append(str(description).strip()[:MAX_DESC_LENGTH])
        
    if priority is not None:
        clean_prio = str(priority).lower().strip()
        if clean_prio in VALID_PRIORITIES:
            updates.append("priority = ?")
            params.append(clean_prio)
            
    effective_id = task_id if task_id is not None else id
    if effective_id is None:
        return {"error": "task_id (or id) parameter is required."}

    if not updates:
        return {"error": "No valid fields to update."}
        
    now = datetime.now().isoformat()
    updates.append("updated_at = ?")
    params.append(now)
    params.append(int(effective_id))
    
    conn = _get_db()
    try:
        with conn:
            cursor = conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            updated = cursor.rowcount
        if updated == 0:
            return {"error": f"Task with ID {effective_id} not found."}
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(effective_id),)).fetchone()
        return dict(row)
    finally:
        conn.close()

def task_list(status: str | None = None, priority: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List persistent tasks filtered by status or priority."""
    conn = _get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM tasks"
    conditions = []
    params = []
    
    if status and str(status).lower().strip() in VALID_STATUSES:
        conditions.append("status = ?")
        params.append(str(status).lower().strip())
        
    if priority and str(priority).lower().strip() in VALID_PRIORITIES:
        conditions.append("priority = ?")
        params.append(str(priority).lower().strip())
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    clean_limit = max(1, min(int(limit), 100))
    query += " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, updated_at DESC LIMIT ?"
    params.append(clean_limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def task_delete(task_id: int | None = None, id: int | None = None) -> str:
    """Delete a task from the persistent database."""
    effective_id = task_id if task_id is not None else id
    if effective_id is None:
        return "Error: task_id (or id) parameter is required."

    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (int(effective_id),))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Successfully deleted task {effective_id}." if deleted else f"Task {effective_id} not found."


def task_board(
    action: Literal["list", "create", "update", "delete"] = "list",
    task_id: int | None = None,
    title: str = "",
    description: str = "",
    status: str = "",
    priority: str = "",
    limit: int = 50
) -> dict[str, Any] | list[dict[str, Any]] | str:
    """Manage persistent Kanban tasks (list, create, update, delete).

    Args:
        action: 'list', 'create', 'update', or 'delete'.
        task_id: Task ID for 'update' or 'delete'.
        title: Task title for 'create' or 'update'.
        description: Task description for 'create' or 'update'.
        status: 'todo', 'in_progress', 'done', or 'blocked'.
        priority: 'low', 'medium', 'high', or 'urgent'.
        limit: Max tasks returned for 'list' (default 50).
    """
    act = str(action or "list").strip().lower()
    if act == "list":
        return task_list(status=status or None, priority=priority or None, limit=limit)
    if act == "create":
        return task_create(title=title, description=description, priority=priority or "medium")
    if act == "update":
        return task_update(
            task_id=task_id,
            status=status or None,
            title=title or None,
            description=description if description else None,
            priority=priority or None,
        )
    if act == "delete":
        return task_delete(task_id=task_id)
    return {"error": f"Unknown task_board action '{action}'. Valid: 'list', 'create', 'update', 'delete'."}
