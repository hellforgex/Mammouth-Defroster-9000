"""
Mammouth Defroster 9000 - Sovereign Workspace Memory & Semantic Code Search (Local RAG)
Provides high-performance, offline SQLite FTS5 code search, AST/regex symbol extraction,
and incremental workspace indexing with mtime tracking.
Zero external API dependencies, fully sandboxed, fast on Windows 11.
"""

import os
import sys
import ast
import re
import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("workspace_indexer")

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

DEFAULT_DB_PATH = BASE_DIR / "workspace_index.db"
_active_db_path: Path = DEFAULT_DB_PATH

# Directory ignore list (skip massive dependency & build artifacts)
IGNORE_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "bower_components",
    ".venv", "venv", "env", ".env",
    "dist", "build", "target", "out",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".idea", ".vscode",
    ".tox", "wheels", ".cache", "obj", "bin"
}

# Recognized text and code file extensions
TEXT_EXTENSIONS = {
    ".py", ".pyw",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".json", ".json5", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".md", ".markdown", ".rst", ".txt",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".rs", ".go", ".java", ".kt", ".kts", ".cs", ".php",
    ".rb", ".sh", ".bash", ".ps1", ".bat", ".cmd",
    ".sql", ".graphql", ".proto", ".lua", ".swift",
    ".dockerfile", "dockerfile"
}

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB limit per file


def set_index_db_path(db_path: Path) -> None:
    """Override database location (useful for isolated unit testing)."""
    global _active_db_path
    _active_db_path = Path(db_path)


def get_index_db_path() -> Path:
    """Return active database path."""
    return _active_db_path


def _get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and schema initialization."""
    target_path = Path(db_path or _active_db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Initialize database tables for files, symbols, and FTS5 code search."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                file_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                file_size INTEGER NOT NULL,
                language TEXT NOT NULL,
                indexed_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                symbol_type TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                signature TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_symbols_file ON file_symbols(file_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_symbols_name ON file_symbols(symbol_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_symbols_type ON file_symbols(symbol_type)")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_code USING fts5(
                file_path UNINDEXED,
                chunk_index UNINDEXED,
                start_line UNINDEXED,
                end_line UNINDEXED,
                content,
                tokenize='unicode61'
            )
        """)


def _detect_language(filepath: Path) -> str:
    """Infer programming/markup language from file extension."""
    ext = filepath.suffix.lower()
    mapping = {
        ".py": "python",
        ".pyw": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".html": "html",
        ".css": "css",
        ".md": "markdown",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".cs": "csharp",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c_header",
        ".hpp": "cpp_header",
        ".ps1": "powershell",
        ".bat": "batch",
        ".sh": "bash",
        ".sql": "sql"
    }
    return mapping.get(ext, ext.lstrip(".") or "text")


def _extract_python_symbols(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract classes, functions, and methods from Python code using AST."""
    symbols = []
    try:
        tree = ast.parse(content, filename=rel_path)
    except Exception:
        return _extract_regex_symbols(content, rel_path)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                sig = f"({ast.unparse(node.args)})"
            except Exception:
                args = [a.arg for a in node.args.args]
                sig = f"({', '.join(args)})"
            symbols.append({
                "symbol_name": node.name,
                "symbol_type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "line_number": getattr(node, "lineno", 1),
                "signature": sig
            })
        elif isinstance(node, ast.ClassDef):
            try:
                bases = [ast.unparse(b) for b in node.bases]
            except Exception:
                bases = [getattr(b, "id", "") for b in node.bases if hasattr(b, "id")]
            base_str = f"({', '.join(bases)})" if bases else ""
            symbols.append({
                "symbol_name": node.name,
                "symbol_type": "class",
                "line_number": getattr(node, "lineno", 1),
                "signature": base_str
            })
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    try:
                        m_sig = f"({ast.unparse(item.args)})"
                    except Exception:
                        m_args = [a.arg for a in item.args.args]
                        m_sig = f"({', '.join(m_args)})"
                    symbols.append({
                        "symbol_name": f"{node.name}.{item.name}",
                        "symbol_type": "method",
                        "line_number": getattr(item, "lineno", 1),
                        "signature": m_sig
                    })
    return symbols


def _extract_regex_symbols(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """Extract declarations from source code using regex patterns."""
    symbols = []
    lines = content.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        # class Foo
        m = re.match(r"^(?:export\s+)?class\s+([A-Za-z0-9_]+)", stripped)
        if m:
            symbols.append({"symbol_name": m.group(1), "symbol_type": "class", "line_number": idx, "signature": ""})
            continue
        # function bar(...)
        m = re.match(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*(\([^\)]*\))", stripped)
        if m:
            symbols.append({"symbol_name": m.group(1), "symbol_type": "function", "line_number": idx, "signature": m.group(2)})
            continue
        # const bar = (...) =>
        m = re.match(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_]+)\s*=>", stripped)
        if m:
            symbols.append({"symbol_name": m.group(1), "symbol_type": "function", "line_number": idx, "signature": "arrow_func"})
            continue
        # def bar(...)
        m = re.match(r"^(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*(\([^\)]*\))", stripped)
        if m:
            symbols.append({"symbol_name": m.group(1), "symbol_type": "function", "line_number": idx, "signature": m.group(2)})
            continue
        # fn bar or func bar
        m = re.match(r"^(?:pub\s+)?(?:fn|func)\s+([A-Za-z0-9_]+)\s*(\([^\)]*\))", stripped)
        if m:
            symbols.append({"symbol_name": m.group(1), "symbol_type": "function", "line_number": idx, "signature": m.group(2)})
            continue
    return symbols


def _chunk_file_content(content: str, chunk_size: int = 60, overlap: int = 15) -> List[Dict[str, Any]]:
    """Split file content into overlapping chunks with line numbers for FTS5 indexing."""
    lines = content.splitlines()
    if not lines:
        return []
    total_lines = len(lines)
    if total_lines <= chunk_size:
        return [{
            "chunk_index": 0,
            "start_line": 1,
            "end_line": total_lines,
            "content": content
        }]

    chunks = []
    chunk_idx = 0
    start = 0
    step = max(1, chunk_size - overlap)
    while start < total_lines:
        end = min(start + chunk_size, total_lines)
        chunk_lines = lines[start:end]
        chunks.append({
            "chunk_index": chunk_idx,
            "start_line": start + 1,
            "end_line": end,
            "content": "\n".join(chunk_lines)
        })
        chunk_idx += 1
        if end >= total_lines:
            break
        start += step
    return chunks


def _sanitize_fts5_query(raw_query: str) -> str:
    """Sanitize arbitrary user / LLM text into a safe, valid FTS5 match query."""
    clean = re.sub(r'["\':*^()\[\]{}~+?-]', ' ', raw_query).strip()
    tokens = [t for t in clean.split() if t and t.upper() not in ("AND", "OR", "NOT", "NEAR")]
    if not tokens:
        return ""
    # Prefix match on alphanumeric tokens
    return " ".join(f'"{t}"*' for t in tokens)


def resolve_index_target(target_dir: str = "") -> Path:
    """Resolve target directory to index, respecting workspace configuration."""
    from modules.shell_processes import resolve_workspace_root
    workspace_root = Path(resolve_workspace_root()).resolve()

    if not target_dir or not target_dir.strip():
        return workspace_root

    p = Path(target_dir.strip())
    if not p.is_absolute():
        p = (workspace_root / p).resolve()
    else:
        p = p.resolve()
    return p


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

def workspace_index_directory(
    directory_path: str = "",
    force_reindex: bool = False,
    max_files: int = 5000
) -> Dict[str, Any]:
    """Index or incrementally refresh files in a workspace directory for FTS5 code search and symbol lookups.
    
    Skips ignored folders (.git, node_modules, .venv, dist, build, etc.) and tracks mtime
    so only modified or newly created files are reprocessed.

    Args:
        directory_path: Relative or absolute path to target directory (defaults to configured workspace).
        force_reindex: If True, reindexes all files regardless of mtime.
        max_files: Maximum number of candidate files to process (default 5000).
    """
    start_time = time.time()
    target_dir = resolve_index_target(directory_path)

    if not target_dir.exists() or not target_dir.is_dir():
        return {
            "status": "error",
            "message": f"Target directory does not exist or is not a directory: {target_dir}"
        }

    conn = _get_connection()
    try:
        # Load existing mtime records for this directory using exact path prefix (not SQL LIKE wildcards)
        cur = conn.cursor()
        target_norm = str(target_dir).replace("\\", "/")
        target_slash = target_norm.rstrip("/") + "/"
        cur.execute(
            "SELECT file_path, mtime FROM indexed_files WHERE substr(file_path, 1, ?) = ? OR file_path = ?",
            (len(target_slash), target_slash, target_norm)
        )
        existing_records = {row["file_path"]: row["mtime"] for row in cur.fetchall()}

        indexed_count = 0
        skipped_count = 0
        pruned_count = 0
        total_chunks = 0
        total_symbols = 0
        seen_files = set()
        reached_limit = False

        # Walk target directory
        for root, dirs, files in os.walk(target_dir):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]

            for fname in files:
                if (indexed_count + skipped_count) >= max_files:
                    reached_limit = True
                    break

                fpath = Path(root) / fname
                ext = fpath.suffix.lower()
                if ext not in TEXT_EXTENSIONS and fname.lower() not in TEXT_EXTENSIONS:
                    continue

                norm_path = str(fpath.resolve()).replace("\\", "/")
                seen_files.add(norm_path)

                try:
                    stat = fpath.stat()
                except OSError:
                    continue

                # If file size is 0 or exceeds max size, clean up old index entries if previously indexed
                if stat.st_size == 0 or stat.st_size > MAX_FILE_SIZE:
                    if norm_path in existing_records:
                        with conn:
                            conn.execute("DELETE FROM file_symbols WHERE file_path = ?", (norm_path,))
                            conn.execute("DELETE FROM fts_code WHERE file_path = ?", (norm_path,))
                            conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (norm_path,))
                    continue

                # Check mtime cache
                last_mtime = existing_records.get(norm_path)
                if not force_reindex and last_mtime is not None and abs(last_mtime - stat.st_mtime) < 0.001:
                    skipped_count += 1
                    continue

                # Read content
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception as read_err:
                    logger.debug(f"Could not read {fpath}: {read_err}")
                    continue

                # Quick binary check - purge if previously indexed
                if "\x00" in content:
                    if norm_path in existing_records:
                        with conn:
                            conn.execute("DELETE FROM file_symbols WHERE file_path = ?", (norm_path,))
                            conn.execute("DELETE FROM fts_code WHERE file_path = ?", (norm_path,))
                            conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (norm_path,))
                    continue

                lang = _detect_language(fpath)

                # Extract symbols
                if lang == "python":
                    symbols = _extract_python_symbols(content, norm_path)
                else:
                    symbols = _extract_regex_symbols(content, norm_path)

                # Extract chunks
                chunks = _chunk_file_content(content)

                # Database transaction for this file
                with conn:
                    # Remove old entries
                    conn.execute("DELETE FROM file_symbols WHERE file_path = ?", (norm_path,))
                    conn.execute("DELETE FROM fts_code WHERE file_path = ?", (norm_path,))

                    # Insert symbols
                    for s in symbols:
                        conn.execute(
                            "INSERT INTO file_symbols (file_path, symbol_name, symbol_type, line_number, signature) VALUES (?, ?, ?, ?, ?)",
                            (norm_path, s["symbol_name"], s["symbol_type"], s["line_number"], s.get("signature", ""))
                        )
                    total_symbols += len(symbols)

                    # Insert FTS chunks
                    for c in chunks:
                        conn.execute(
                            "INSERT INTO fts_code (file_path, chunk_index, start_line, end_line, content) VALUES (?, ?, ?, ?, ?)",
                            (norm_path, c["chunk_index"], c["start_line"], c["end_line"], c["content"])
                        )
                    total_chunks += len(chunks)

                    # Update indexed_files record
                    conn.execute(
                        "INSERT OR REPLACE INTO indexed_files (file_path, mtime, file_size, language, indexed_at) VALUES (?, ?, ?, ?, ?)",
                        (norm_path, stat.st_mtime, stat.st_size, lang, time.time())
                    )

                indexed_count += 1

            if reached_limit:
                break

        # Prune deleted files that were previously indexed strictly within this directory
        with conn:
            for old_path in existing_records.keys():
                if old_path not in seen_files:
                    conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (old_path,))
                    conn.execute("DELETE FROM file_symbols WHERE file_path = ?", (old_path,))
                    conn.execute("DELETE FROM fts_code WHERE file_path = ?", (old_path,))
                    pruned_count += 1

        elapsed = time.time() - start_time
        res: Dict[str, Any] = {
            "status": "success",
            "directory": str(target_dir),
            "indexed_files": indexed_count,
            "skipped_files": skipped_count,
            "deleted_pruned": pruned_count,
            "total_chunks_indexed": total_chunks,
            "symbols_extracted": total_symbols,
            "elapsed_seconds": round(elapsed, 3)
        }
        if reached_limit:
            res["limit_reached"] = True
            res["message"] = f"Reached maximum file limit of {max_files}."
        return res
    finally:
        conn.close()


def workspace_search(
    query: str,
    limit: int = 10,
    file_pattern: str = ""
) -> Dict[str, Any]:
    """Execute high-speed full-text code search across indexed workspace files using SQLite FTS5.

    Args:
        query: Search term or phrase to find.
        limit: Maximum number of relevant code chunks to return (default 10).
        file_pattern: Optional substring filter on file paths (e.g. '.py', 'server', 'modules/').
    """
    if not query or not query.strip():
        return {"status": "empty_query", "matches": [], "total_matches": 0}

    limit = max(1, min(int(limit or 10), 100))
    sanitized = _sanitize_fts5_query(query)
    if not sanitized:
        return {"status": "empty_query", "matches": [], "total_matches": 0}

    conn = _get_connection()
    try:
        cur = conn.cursor()
        sql = """
            SELECT file_path, chunk_index, start_line, end_line,
                   snippet(fts_code, 4, '>>>', '<<<', '...', 32) AS snippet,
                   rank
            FROM fts_code
            WHERE fts_code MATCH ?
        """
        params: List[Any] = [sanitized]

        if file_pattern and file_pattern.strip():
            sql += " AND file_path LIKE ?"
            params.append(f"%{file_pattern.strip()}%")

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except sqlite3.Error as search_err:
            logger.warning(f"FTS5 query failed for '{sanitized}': {search_err}")
            return {
                "status": "error",
                "message": f"Search failed: {search_err}",
                "matches": [],
                "total_matches": 0
            }

        matches = []
        for r in rows:
            matches.append({
                "file_path": r["file_path"],
                "chunk_index": r["chunk_index"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "snippet": r["snippet"],
                "relevance_score": round(float(r["rank"]), 4)
            })

        return {
            "status": "success",
            "query": query,
            "total_matches": len(matches),
            "matches": matches
        }
    finally:
        conn.close()


def workspace_find_symbols(
    symbol_name: str = "",
    symbol_type: str = "",
    file_pattern: str = "",
    limit: int = 50
) -> Dict[str, Any]:
    """Search for declared symbols (functions, classes, methods, arrow functions) across the indexed codebase.

    Args:
        symbol_name: Name or substring of the symbol (e.g. 'load_config', 'GlobalHotkey').
        symbol_type: Optional type filter: 'function', 'class', 'method', 'async_function'.
        file_pattern: Optional path substring filter (e.g. 'gui.py', 'modules/').
        limit: Maximum symbols to return (default 50).
    """
    limit = max(1, min(int(limit or 50), 200))
    conn = _get_connection()
    try:
        cur = conn.cursor()
        sql = "SELECT file_path, symbol_name, symbol_type, line_number, signature FROM file_symbols WHERE 1=1"
        params: List[Any] = []

        if symbol_name and symbol_name.strip():
            sql += " AND symbol_name LIKE ?"
            params.append(f"%{symbol_name.strip()}%")

        if symbol_type and symbol_type.strip():
            sql += " AND symbol_type = ?"
            params.append(symbol_type.strip().lower())

        if file_pattern and file_pattern.strip():
            sql += " AND file_path LIKE ?"
            params.append(f"%{file_pattern.strip()}%")

        sql += " ORDER BY symbol_name ASC LIMIT ?"
        params.append(limit)

        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except sqlite3.Error as sym_err:
            logger.warning(f"Symbol lookup failed: {sym_err}")
            return {
                "status": "error",
                "message": f"Symbol lookup failed: {sym_err}",
                "symbols": [],
                "total_symbols": 0
            }

        symbols = [
            {
                "file_path": r["file_path"],
                "symbol_name": r["symbol_name"],
                "symbol_type": r["symbol_type"],
                "line_number": r["line_number"],
                "signature": r["signature"]
            }
            for r in rows
        ]

        return {
            "status": "success",
            "total_symbols": len(symbols),
            "symbols": symbols
        }
    finally:
        conn.close()


def workspace_get_stats() -> Dict[str, Any]:
    """Retrieve statistical telemetry about the sovereign code index (file counts, symbol counts, DB size)."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS total_files, COALESCE(SUM(file_size), 0) AS total_bytes FROM indexed_files")
        row_files = cur.fetchone()

        cur.execute("SELECT COUNT(*) AS total_chunks FROM fts_code")
        row_chunks = cur.fetchone()

        cur.execute("SELECT COUNT(*) AS total_symbols FROM file_symbols")
        row_symbols = cur.fetchone()

        cur.execute("SELECT language, COUNT(*) as count FROM indexed_files GROUP BY language ORDER BY count DESC LIMIT 10")
        lang_rows = cur.fetchall()
        languages = {r["language"]: r["count"] for r in lang_rows}

        db_path = get_index_db_path()
        db_size_kb = round(db_path.stat().st_size / 1024, 2) if db_path.exists() else 0.0

        return {
            "status": "success",
            "indexed_files": row_files["total_files"] if row_files else 0,
            "total_file_bytes": row_files["total_bytes"] if row_files else 0,
            "total_chunks": row_chunks["total_chunks"] if row_chunks else 0,
            "total_symbols": row_symbols["total_symbols"] if row_symbols else 0,
            "languages": languages,
            "db_size_kb": db_size_kb,
            "db_path": str(db_path)
        }
    finally:
        conn.close()
