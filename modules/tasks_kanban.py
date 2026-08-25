import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import get_app_dir

DB_PATH = get_app_dir() / "tasks.db"

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    return conn

def task_create(title: str, description: str = "", priority: str = "medium") -> Dict[str, Any]:
    """Create a new task in the persistent todo/Kanban board.
    
    Args:
        title: Short actionable title of the task.
        description: Detailed instructions or subtasks.
        priority: 'low', 'medium', 'high', 'urgent'.
    """
    now = datetime.now().isoformat()
    conn = _get_db()
    with conn:
        cursor = conn.execute("""
            INSERT INTO tasks (title, description, status, priority, created_at, updated_at)
            VALUES (?, ?, 'todo', ?, ?, ?)
        """, (title.strip(), description.strip(), priority.lower(), now, now))
        task_id = cursor.lastrowid
    conn.close()
    return {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "todo",
        "priority": priority,
        "created_at": now
    }

def task_update(
    task_id: int,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """Update task status ('todo', 'in_progress', 'done', 'blocked') or details.
    
    Args:
        task_id: The ID of the task to update.
        status: New status ('todo', 'in_progress', 'done', 'blocked').
        title: New title (optional).
        description: New description (optional).
        priority: New priority (optional).
    """
    now = datetime.now().isoformat()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"error": f"Task with ID {task_id} not found."}
        
    current = dict(row)
    new_title = title.strip() if title is not None else current["title"]
    new_desc = description.strip() if description is not None else current["description"]
    new_status = status.lower().strip() if status is not None else current["status"]
    new_prio = priority.lower().strip() if priority is not None else current["priority"]
    
    with conn:
        conn.execute("""
            UPDATE tasks
            SET title = ?, description = ?, status = ?, priority = ?, updated_at = ?
            WHERE id = ?
        """, (new_title, new_desc, new_status, new_prio, now, task_id))
    conn.close()
    
    return {
        "id": task_id,
        "title": new_title,
        "description": new_desc,
        "status": new_status,
        "priority": new_prio,
        "updated_at": now
    }

def task_list(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List tasks from the board, optionally filtered by status ('todo', 'in_progress', 'done', 'blocked').
    
    Args:
        status: Optional filter ('todo', 'in_progress', 'done', 'blocked', 'all').
    """
    conn = _get_db()
    cursor = conn.cursor()
    if status and status.lower() != 'all':
        cursor.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id ASC", (status.lower().strip(),))
    else:
        cursor.execute("SELECT * FROM tasks ORDER BY CASE status WHEN 'in_progress' THEN 1 WHEN 'todo' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END, id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def task_delete(task_id: int) -> str:
    """Delete a task by ID.
    
    Args:
        task_id: ID of the task to delete.
    """
    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Task {task_id} deleted." if deleted else f"Task {task_id} not found."
