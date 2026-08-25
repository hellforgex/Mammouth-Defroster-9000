import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import get_app_dir

DB_PATH = get_app_dir() / "memory.db"

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
    return conn

def memory_save(key: str, content: str, category: str = "general") -> str:
    """Save or update persistent long-term memory/knowledge that persists across chats.
    
    Args:
        key: Unique identifier for the memory (e.g. 'preferred_editor', 'project_db_structure', 'vps_info').
        content: The information/note to remember.
        category: Optional category (e.g. 'project', 'preference', 'infrastructure', 'note').
    """
    now = datetime.now().isoformat()
    conn = _get_db()
    with conn:
        conn.execute("""
            INSERT INTO memories (key, content, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                updated_at = excluded.updated_at
        """, (key.strip(), content.strip(), category.strip(), now, now))
    conn.close()
    return f"Successfully saved memory '{key}' in category '{category}'."

def memory_recall(query: str) -> List[Dict[str, Any]]:
    """Search persistent long-term memory by key or content keyword.
    
    Args:
        query: Search term to find in keys or content.
    """
    conn = _get_db()
    cursor = conn.cursor()
    like_q = f"%{query}%"
    cursor.execute("""
        SELECT key, content, category, updated_at
        FROM memories
        WHERE key LIKE ? OR content LIKE ? OR category LIKE ?
        ORDER BY updated_at DESC
        LIMIT 20
    """, (like_q, like_q, like_q))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def memory_get(key: str) -> Optional[Dict[str, Any]]:
    """Retrieve an exact memory item by key.
    
    Args:
        key: The key identifier.
    """
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, content, category, updated_at FROM memories WHERE key = ?", (key.strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def memory_delete(key: str) -> str:
    """Delete a memory item by key.
    
    Args:
        key: The key identifier to remove.
    """
    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key.strip(),))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Memory '{key}' deleted." if deleted else f"Memory '{key}' not found."

def memory_list(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all saved memories, optionally filtered by category.
    
    Args:
        category: Optional category filter.
    """
    conn = _get_db()
    cursor = conn.cursor()
    if category:
        cursor.execute("SELECT key, content, category, updated_at FROM memories WHERE category = ? ORDER BY updated_at DESC", (category.strip(),))
    else:
        cursor.execute("SELECT key, content, category, updated_at FROM memories ORDER BY updated_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
