import os
import re
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import load_config

FORBIDDEN_WINDOWS_PATHS = [
    os.environ.get("SystemRoot", r"C:\Windows").lower(),
    os.environ.get("ProgramFiles", r"C:\Program Files").lower(),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower(),
    r"\microsoft\windows\start menu\programs\startup",
]

def _validate_path_safety(target_path: str, is_write: bool = False) -> Optional[str]:
    """Validate path against directory traversal and workspace sandbox policy."""
    try:
        path = Path(target_path).resolve()
    except Exception as e:
        return f"Error: Invalid path format: {e}"

    str_path = str(path).lower()

    # Block sensitive system folders
    for forbidden in FORBIDDEN_WINDOWS_PATHS:
        if forbidden in str_path:
            return f"Security Error: Access to system protected location '{path}' is blocked."

    # Enforce workspace sandbox if configured
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    if server_cfg.get("enforce_workspace_sandbox", True):
        ws_root = server_cfg.get("workspace_root", "")
        if ws_root:
            ws_path = Path(ws_root).resolve()
            ws_path.mkdir(parents=True, exist_ok=True)
            try:
                if not path.is_relative_to(ws_path):
                    return f"Security Error: Path '{path}' is outside the authorized workspace directory '{ws_path}'. Modify workspace_root in Settings to expand scope."
            except AttributeError:
                # Python < 3.9 compatibility
                if not str(path).startswith(str(ws_path)):
                    return f"Security Error: Path '{path}' is outside the authorized workspace directory '{ws_path}'."

    return None

def file_read(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None, max_chars: int = 50000) -> str:
    """Read a text file with optional line slicing within authorized workspace.
    
    Args:
        file_path: Absolute path to the file.
        start_line: Optional 1-indexed start line.
        end_line: Optional 1-indexed end line.
        max_chars: Character limit (default 50,000).
    """
    safety_err = _validate_path_safety(file_path, is_write=False)
    if safety_err:
        return safety_err

    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"
    if not path.is_file():
        return f"Error: Path is not a file: {file_path}"
        
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        
        if start_line is not None or end_line is not None:
            s = max(0, (start_line - 1) if start_line else 0)
            e = end_line if end_line else len(lines)
            selected_lines = lines[s:e]
            content = "\n".join(selected_lines)
            
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... Truncated, total length is {len(content)} characters ...]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"

DANGEROUS_WRITE_EXTENSIONS = {".exe", ".dll", ".scr", ".sys", ".drv", ".msi", ".com"}

def file_write(file_path: str, content: str, overwrite: bool = True) -> str:
    """Write or overwrite a file on disk securely within the workspace sandbox.
    
    Args:
        file_path: Target path.
        content: Text content.
        overwrite: Overwrite if file exists.
    """
    safety_err = _validate_path_safety(file_path, is_write=True)
    if safety_err:
        return safety_err

    path = Path(file_path)
    if path.suffix.lower() in DANGEROUS_WRITE_EXTENSIONS:
        return f"Security Error: Writing executable binary file type '{path.suffix}' is blocked by workspace security policy."

    if path.exists() and not overwrite:
        return f"Error: File already exists: {file_path}"
        
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"

def file_replace_chunk(file_path: str, target_chunk: str, replacement_chunk: str) -> str:
    """Replace an exact block of text/code in a file securely within the workspace sandbox.
    
    Args:
        file_path: Path of the file to modify.
        target_chunk: Exact string to find and replace.
        replacement_chunk: Exact string to replace it with.
    """
    safety_err = _validate_path_safety(file_path, is_write=True)
    if safety_err:
        return safety_err

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return f"Error: File not found: {file_path}"
        
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if target_chunk not in content:
            return f"Error: target_chunk was not found in {file_path}."
        if content.count(target_chunk) > 1:
            return f"Error: target_chunk appears {content.count(target_chunk)} times. Specify a larger unique block."
            
        new_content = content.replace(target_chunk, replacement_chunk, 1)
        path.write_text(new_content, encoding="utf-8")
        return f"Successfully replaced chunk in {file_path}"
    except Exception as e:
        return f"Error modifying file: {e}"

def file_search_text(
    directory_path: str,
    search_query: str,
    file_pattern: str = "*",
    is_regex: bool = False,
    max_matches: int = 50
) -> List[Dict[str, Any]]:
    """Search for text inside files in a directory (like grep/ripgrep).
    
    Args:
        directory_path: Base directory to search.
        search_query: Search term or regex pattern.
        file_pattern: File glob pattern (e.g. '*.py', '*.ts', '*.json').
        is_regex: Whether search_query is a regex.
        max_matches: Maximum matching lines to return.
    """
    safety_err = _validate_path_safety(directory_path, is_write=False)
    if safety_err:
        return [{"error": safety_err}]

    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        return [{"error": f"Invalid directory: {directory_path}"}]
        
    results = []
    compiled_re = None
    if is_regex:
        if len(search_query) > 200:
            return [{"error": "Regex pattern exceeds maximum allowed length of 200 characters (ReDoS protection)."}]
        try:
            compiled_re = re.compile(search_query, re.IGNORECASE)
        except re.error as e:
            return [{"error": f"Invalid regex: {e}"}]
            
    try:
        for root, _, files in os.walk(directory_path, followlinks=False):
            if any(part in root.split(os.sep) for part in ['.git', 'node_modules', '__pycache__', '.venv', 'venv']):
                continue
                
            for file in files:
                if fnmatch.fnmatch(file.lower(), file_pattern.lower()):
                    fp = Path(root) / file
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                            for idx, line in enumerate(f, 1):
                                match = False
                                if is_regex and compiled_re:
                                    match = bool(compiled_re.search(line))
                                elif search_query.lower() in line.lower():
                                    match = True
                                    
                                if match:
                                    results.append({
                                        "file": str(fp),
                                        "line_number": idx,
                                        "line_content": line.strip()
                                    })
                                    if len(results) >= max_matches:
                                        return results
                    except Exception:
                        pass
    except Exception as e:
        results.append({"error": str(e)})
        
    return results

def directory_list(directory_path: str, max_depth: int = 1) -> List[Dict[str, Any]]:
    """List files and subfolders in a directory."""
    safety_err = _validate_path_safety(directory_path, is_write=False)
    if safety_err:
        return [{"error": safety_err}]

    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        return [{"error": f"Invalid directory: {directory_path}"}]
        
    results = []
    try:
        for item in sorted(path.iterdir()):
            results.append({
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
                "size_bytes": item.stat().st_size if item.is_file() else None
            })
    except Exception as e:
        return [{"error": str(e)}]
    return results[:100]

def directory_tree(directory_path: str, max_depth: int = 2) -> str:
    """Generate an ASCII visual tree structure of a directory."""
    safety_err = _validate_path_safety(directory_path, is_write=False)
    if safety_err:
        return safety_err

    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        return f"Invalid directory: {directory_path}"
        
    lines = [f"{path.name}/"]
    
    def _build_tree(curr_path: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(list(curr_path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        except Exception:
            return
            
        entries = [e for e in entries if e.name not in ['.git', 'node_modules', '__pycache__', '.venv']]
        total = len(entries)
        for i, entry in enumerate(entries):
            is_last = (i == total - 1)
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                _build_tree(entry, prefix + child_prefix, depth + 1)
            else:
                lines.append(f"{prefix}{connector}{entry.name}")
                
    _build_tree(path, "", 1)
    return "\n".join(lines[:200])
