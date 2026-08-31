import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).parent.parent / "memory.db"

MAX_KEY_LENGTH = 256
MAX_CATEGORY_LENGTH = 128
MAX_CONTENT_LENGTH = 262144  # 256 KB max per memory entry

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
        key: Unique identifier for the memory (max 256 chars).
        content: The information/note to remember (max 256 KB).
        category: Optional category (max 128 chars).
    """
    clean_key = str(key).strip()[:MAX_KEY_LENGTH]
    if not clean_key:
        return "Error: Memory key cannot be empty."

    clean_category = str(category).strip()[:MAX_CATEGORY_LENGTH] or "general"
    clean_content = str(content).strip()
    if len(clean_content) > MAX_CONTENT_LENGTH:
        clean_content = clean_content[:MAX_CONTENT_LENGTH] + "\n[... Content truncated to 256 KB limit ...]"

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
        """, (clean_key, clean_content, clean_category, now, now))
    conn.close()
    return f"Successfully saved memory '{clean_key}' in category '{clean_category}'."

def memory_recall(query: str) -> List[Dict[str, Any]]:
    """Search persistent long-term memory by key or content keyword.
    
    Args:
        query: Search term to find in keys or content.
    """
    conn = _get_db()
    cursor = conn.cursor()
    clean_q = str(query).strip()[:128]
    like_q = f"%{clean_q}%"
    cursor.execute("""
        SELECT key, content, category, updated_at
        FROM memories
        WHERE key LIKE ? OR content LIKE ? OR category LIKE ?
        ORDER BY updated_at DESC
        LIMIT 50
    """, (like_q, like_q, like_q))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def memory_list(category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List saved memory keys, their categories, and timestamps (without full text content)."""
    conn = _get_db()
    cursor = conn.cursor()
    clean_limit = max(1, min(int(limit), 100))
    if category:
        cursor.execute("""
            SELECT id, key, category, updated_at, length(content) as content_chars
            FROM memories
            WHERE category = ?
            ORDER BY updated_at DESC
            LIMIT ?
        """, (str(category).strip(), clean_limit))
    else:
        cursor.execute("""
            SELECT id, key, category, updated_at, length(content) as content_chars
            FROM memories
            ORDER BY updated_at DESC
            LIMIT ?
        """, (clean_limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def memory_get(key: str) -> Dict[str, Any]:
    """Retrieve full content of a specific memory entry by exact key."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, content, category, created_at, updated_at FROM memories WHERE key = ?", (str(key).strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"error": f"Memory key '{key}' not found."}

def memory_delete(key: str) -> str:
    """Delete a memory entry from persistent long-term storage."""
    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM memories WHERE key = ?", (str(key).strip(),))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Successfully deleted memory '{key}'." if deleted else f"Memory key '{key}' was not found."
