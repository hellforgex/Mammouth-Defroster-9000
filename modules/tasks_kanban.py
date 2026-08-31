import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).parent.parent / "tasks.db"

MAX_TITLE_LENGTH = 256
MAX_DESC_LENGTH = 65536  # 64 KB
VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}

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
    task_id: int,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None
) -> Dict[str, Any]:
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
            
    if not updates:
        return {"error": "No valid fields to update."}
        
    now = datetime.now().isoformat()
    updates.append("updated_at = ?")
    params.append(now)
    params.append(int(task_id))
    
    conn = _get_db()
    with conn:
        cursor = conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
        if cursor.rowcount == 0:
            conn.close()
            return {"error": f"Task with ID {task_id} not found."}
            
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
    row = cursor.fetchone()
    conn.close()
    return dict(row)

def task_list(status: Optional[str] = None, priority: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
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

def task_delete(task_id: int) -> str:
    """Delete a task from the persistent database."""
    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Successfully deleted task {task_id}." if deleted else f"Task {task_id} not found."
