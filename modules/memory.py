import threading
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import sys

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DB_PATH = BASE_DIR / "memory.db"

MAX_KEY_LENGTH = 256
MAX_CATEGORY_LENGTH = 128
MAX_CONTENT_LENGTH = 262144  # 256 KB max per memory entry

_schema_ready_paths = set()  # DB files whose schema was created in this process
_schema_lock = threading.Lock()


def _auto_migrate_legacy_db():
    """If DB_PATH does not exist, check parent or previous release folders for existing memory.db and migrate."""
    if DB_PATH.exists():
        return
    try:
        parent_dir = BASE_DIR.parent
        if not parent_dir.exists():
            return
        candidates = []
        for sibling in sorted(parent_dir.glob("MammouthDefroster9000-v*"), reverse=True):
            cand = sibling / "memory.db"
            if cand.exists() and cand != DB_PATH and cand.stat().st_size > 0:
                candidates.append(cand)
        src_cand = parent_dir / "src" / "memory.db"
        if src_cand.exists() and src_cand != DB_PATH and src_cand.stat().st_size > 0:
            candidates.append(src_cand)

        for cand in candidates:
            try:
                conn_cand = sqlite3.connect(cand)
                cursor = conn_cand.cursor()
                cursor.execute("SELECT count(*) FROM memories")
                count = cursor.fetchone()[0]
                conn_cand.close()
                if count > 0:
                    shutil.copy2(cand, DB_PATH)
                    break
            except Exception:
                continue
    except Exception:
        pass


def _get_db():
    if not DB_PATH.exists():
        _auto_migrate_legacy_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    db_key = str(DB_PATH)
    if db_key not in _schema_ready_paths:
        # Schema DDL + commit only once per DB file and process instead of on every call / scheduler tick
        with _schema_lock:
            if db_key not in _schema_ready_paths:
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
                _schema_ready_paths.add(db_key)
    return conn

def memory_save(
    key: str = "",
    content: Optional[str] = None,
    category: str = "general",
    value: Optional[str] = None,
    text: Optional[str] = None,
    note: Optional[str] = None,
    data: Optional[str] = None,
    name: Optional[str] = None
) -> str:
    """Save or update persistent long-term memory/knowledge that persists across chats.
    
    Args:
        key: Unique identifier for the memory (max 256 chars).
        content: The information/note to remember (max 256 KB). Also accepts aliases: value, text, note, data.
        category: Optional category (max 128 chars). Default: 'general'.
        value: Alias for content.
        text: Alias for content.
        note: Alias for content.
        data: Alias for content.
        name: Alias for key.
    """
    clean_key = str(key or name or "").strip()[:MAX_KEY_LENGTH]
    if not clean_key:
        return "Error: Memory key cannot be empty."

    raw_content = content if content is not None else (
        value if value is not None else (
            text if text is not None else (
                note if note is not None else (
                    data if data is not None else ""
                )
            )
        )
    )
    clean_content = str(raw_content).strip()
    if not clean_content:
        return f"Error: Memory content for key '{clean_key}' cannot be empty."

    clean_category = str(category).strip()[:MAX_CATEGORY_LENGTH] or "general"
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

def memory_recall(
    query: Optional[str] = None,
    search_query: Optional[str] = None,
    q: Optional[str] = None,
    search: Optional[str] = None,
    keyword: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search persistent long-term memory by key or content keyword.
    
    Args:
        query: Search term to find in keys or content.
        search_query: Alias for query.
        q: Alias for query.
        search: Alias for query.
        keyword: Alias for query.
    """
    effective_q = ""
    for candidate in (query, search_query, q, search, keyword):
        if candidate is not None:
            effective_q = candidate
            break

    conn = _get_db()
    cursor = conn.cursor()
    clean_q = str(effective_q).strip()[:128]
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
    if category and str(category).strip() and str(category).strip().lower() != "all":
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

def memory_get(key: str = "", name: Optional[str] = None, id: Optional[Any] = None) -> Dict[str, Any]:
    """Retrieve full content of a specific memory entry by exact key."""
    actual_key = str(key or name or (str(id) if id is not None else "")).strip()
    if not actual_key:
        return {"error": "Memory key cannot be empty."}

    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, content, category, created_at, updated_at FROM memories WHERE key = ?", (actual_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"error": f"Memory key '{actual_key}' not found."}

def memory_delete(key: str = "", name: Optional[str] = None) -> str:
    """Delete a memory entry from persistent long-term storage."""
    actual_key = str(key or name or "").strip()
    if not actual_key:
        return "Error: Memory key cannot be empty."

    conn = _get_db()
    with conn:
        cursor = conn.execute("DELETE FROM memories WHERE key = ?", (actual_key,))
        deleted = cursor.rowcount > 0
    conn.close()
    return f"Successfully deleted memory '{actual_key}'." if deleted else f"Memory key '{actual_key}' was not found."

def memory_get_all(category: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """Retrieve full content of memories for GUI cockpit management."""
    conn = _get_db()
    cursor = conn.cursor()
    clean_limit = max(1, min(int(limit), 1000))
    if category and str(category).strip() and str(category).strip().lower() != "all":
        cursor.execute("""
            SELECT id, key, content, category, created_at, updated_at, length(content) as content_chars
            FROM memories
            WHERE category = ?
            ORDER BY updated_at DESC
            LIMIT ?
        """, (str(category).strip(), clean_limit))
    else:
        cursor.execute("""
            SELECT id, key, content, category, created_at, updated_at, length(content) as content_chars
            FROM memories
            ORDER BY updated_at DESC
            LIMIT ?
        """, (clean_limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def memory_get_categories() -> List[str]:
    """Retrieve list of distinct category names present in memories table."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM memories WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
    rows = cursor.fetchall()
    conn.close()
    return [r["category"] for r in rows if r["category"]]

def memory_get_stats() -> Dict[str, Any]:
    """Retrieve summary telemetry: total memories, categories count, and storage bytes."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*), count(DISTINCT category), coalesce(sum(length(content)), 0) FROM memories")
    row = cursor.fetchone()
    conn.close()
    return {
        "total": row[0] if row else 0,
        "categories": row[1] if row else 0,
        "total_chars": row[2] if row else 0
    }

