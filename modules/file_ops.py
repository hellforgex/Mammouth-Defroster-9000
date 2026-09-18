import os
import re
import json
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional

import sys

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

CONFIG_FILE = BASE_DIR / "config.json"

CRITICAL_BLOCKED_WRITE_ROOTS = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
] if os.name == 'nt' else [
    "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/etc", "/root"
]

PROTECTED_SENSITIVE_DIRS = [
    ".ssh", ".aws", ".azure", ".kube", ".gnupg", "startup"
]


def _get_sandbox_config():
    """Load workspace sandbox settings from config.json."""
    default_ws = (BASE_DIR / "workspace").resolve()
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            server_cfg = cfg.get("server", {})
            enforce_sandbox = server_cfg.get("enforce_workspace_sandbox", True)
            ws_root_str = server_cfg.get("workspace_root", "./workspace")
            ws_root = (BASE_DIR / ws_root_str).resolve() if not Path(ws_root_str).is_absolute() else Path(ws_root_str).resolve()
            return enforce_sandbox, ws_root
        except Exception:
            pass
    return True, default_ws


def _is_binary_file(file_path: Path) -> bool:
    """Check if file contains null bytes (binary file)."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return True


def _normalize_and_resolve_path(raw_path_str: str) -> str:
    """Normalize UNC, DOS 8.3, symlinks, junctions, and relative segments into a canonical path."""
    if "\0" in raw_path_str:
        raise ValueError("Invalid path: null byte detected.")

    clean_str = str(raw_path_str).strip()

    # Strip UNC device namespace prefixes (\\?\UNC\server\share -> \\server\share, \\?\C:\ -> C:\, \\.\C:\ -> C:\)
    if clean_str.startswith("\\\\?\\UNC\\") or clean_str.startswith("\\\\?\\unc\\"):
        clean_str = "\\\\" + clean_str[8:]
    elif clean_str.startswith("\\\\?\\") or clean_str.startswith("\\\\.\\"):
        clean_str = clean_str[4:]
    elif clean_str.startswith("//?/"):
        clean_str = clean_str[4:]

    # Resolve 8.3 short names and symlinks on Windows
    if os.name == 'nt':
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            res = ctypes.windll.kernel32.GetLongPathNameW(clean_str, buf, 32768)
            if res > 0:
                clean_str = buf.value
            else:
                parent = os.path.dirname(clean_str)
                fname = os.path.basename(clean_str)
                if parent and ctypes.windll.kernel32.GetLongPathNameW(parent, buf, 32768) > 0:
                    clean_str = os.path.join(buf.value, fname)
        except Exception:
            pass

    resolved = os.path.abspath(os.path.realpath(clean_str))
    return resolved


def _validate_path(target_path_str: str, for_write: bool = False) -> Path:
    """Validate and sandbox path against path traversal attacks, UNC bypasses, and unauthorized system writes."""
    if "\0" in target_path_str:
        raise ValueError("Invalid path: null byte detected.")

    enforce_sandbox, ws_root = _get_sandbox_config()
    raw_path = Path(target_path_str)

    if not raw_path.is_absolute():
        target_path_str = str(ws_root / raw_path)

    canonical_path = _normalize_and_resolve_path(target_path_str)
    canonical_cf = canonical_path.casefold()

    if enforce_sandbox:
        ws_canonical = _normalize_and_resolve_path(str(ws_root))
        ws_cf = ws_canonical.casefold()
        sep = os.sep.casefold()

        is_inside = (canonical_cf == ws_cf) or canonical_cf.startswith(ws_cf + sep) or canonical_cf.startswith(ws_cf + "/")
        if not is_inside:
            raise PermissionError(f"Sandbox Violation: Path '{target_path_str}' is outside allowed workspace '{ws_canonical}'.")

    # Hard write guards (evaluated regardless of sandbox settings)
    if for_write:
        # Check system write roots with casefolded comparison
        for root in CRITICAL_BLOCKED_WRITE_ROOTS:
            root_canonical = _normalize_and_resolve_path(root)
            root_cf = root_canonical.casefold()
            sep = os.sep.casefold()
            if canonical_cf == root_cf or canonical_cf.startswith(root_cf + sep) or canonical_cf.startswith(root_cf + "/"):
                raise PermissionError(f"Security Shield: Direct write access to system directory '{root}' is strictly prohibited.")

        # Check sensitive user/credential directories (.ssh, .aws, .azure, .kube, .gnupg, startup)
        path_parts = [p.casefold() for p in Path(canonical_path).parts]
        for sensitive in PROTECTED_SENSITIVE_DIRS:
            if sensitive in path_parts:
                raise PermissionError(f"Security Shield: Write access to sensitive security credential directory '{sensitive}' is strictly prohibited.")

    return Path(canonical_path)


def file_read(
    file_path: Optional[str] = None,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_chars: int = 50000,
    path: Optional[str] = None
) -> str:
    """Read a text file with optional line slicing within allowed workspace boundaries.
    
    Args:
        file_path: Relative or absolute path to the target text file.
        start_line: Optional 1-based start line number to begin reading from.
        end_line: Optional 1-based end line number to stop reading at.
        max_chars: Maximum characters to return before truncation (default 50000).
        path: Alias for file_path.
    """
    target = file_path if file_path is not None else (path if path is not None else "")
    if not target:
        return "Error: file_path (or path) parameter is required."

    try:
        validated_path = _validate_path(target, for_write=False)
    except Exception as e:
        return f"Security/Validation Error: {e}"

    if not validated_path.exists():
        return f"Error: File not found: {target}"
    if not validated_path.is_file():
        return f"Error: Path is not a file: {target}"
        
    try:
        content = validated_path.read_text(encoding="utf-8", errors="replace")
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


def file_write(
    file_path: Optional[str] = None,
    content: str = "",
    overwrite: bool = True,
    path: Optional[str] = None
) -> str:
    """Write or overwrite a file on disk within allowed workspace boundaries.
    
    Args:
        file_path: Target path of the file to create or overwrite.
        content: Text content to write.
        overwrite: Allow overwriting existing files (default True).
        path: Alias for file_path.
    """
    target = file_path if file_path is not None else (path if path is not None else "")
    if not target:
        return "Error: file_path (or path) parameter is required."

    try:
        validated_path = _validate_path(target, for_write=True)
    except Exception as e:
        return f"Security/Validation Error: {e}"

    if validated_path.exists() and not overwrite:
        return f"Error: File already exists: {target}"
        
    try:
        validated_path.parent.mkdir(parents=True, exist_ok=True)
        validated_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {validated_path.name}"
    except Exception as e:
        return f"Error writing file: {e}"


def file_replace_chunk(
    file_path: Optional[str] = None,
    target_chunk: str = "",
    replacement_chunk: str = "",
    path: Optional[str] = None
) -> str:
    """Replace an exact block of text/code in a file.
    
    Args:
        file_path: Path to the target file.
        target_chunk: Exact string block to find and replace.
        replacement_chunk: New replacement string block.
        path: Alias for file_path.
    """
    target = file_path if file_path is not None else (path if path is not None else "")
    if not target:
        return "Error: file_path (or path) parameter is required."

    try:
        validated_path = _validate_path(target, for_write=True)
    except Exception as e:
        return f"Security/Validation Error: {e}"

    if not validated_path.exists() or not validated_path.is_file():
        return f"Error: File not found: {target}"
        
    try:
        content = validated_path.read_text(encoding="utf-8", errors="replace")
        if target_chunk not in content:
            return f"Error: target_chunk was not found in {target}."
        if content.count(target_chunk) > 1:
            return f"Error: target_chunk appears {content.count(target_chunk)} times. Specify a larger unique block."
            
        new_content = content.replace(target_chunk, replacement_chunk, 1)
        validated_path.write_text(new_content, encoding="utf-8")
        return f"Successfully replaced chunk in {target}"
    except Exception as e:
        return f"Error modifying file: {e}"


def file_search_text(
    directory_path: Optional[str] = None,
    search_query: Optional[str] = None,
    file_pattern: str = "*",
    is_regex: bool = False,
    max_matches: int = 50,
    path: Optional[str] = None,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search for text inside files in a directory (like grep/ripgrep).
    
    Args:
        directory_path: Directory path to search within.
        search_query: Search string or regex pattern to match within file lines.
        file_pattern: Filename glob pattern to restrict search (e.g. '*.py', '*.json').
        is_regex: Treat search_query as regular expression if True.
        max_matches: Maximum total matching lines to return (default 50).
        path: Alias for directory_path.
        query: Alias for search_query.
    """
    raw_dir = directory_path if directory_path is not None else (path if path is not None else ".")
    raw_query = search_query if search_query is not None else (query if query is not None else "")
    if not raw_query:
        return [{"error": "search_query (or query) parameter is required."}]
    try:
        validated_dir = _validate_path(raw_dir, for_write=False)
    except Exception as e:
        return [{"error": f"Security/Validation Error: {e}"}]

    if not validated_dir.exists() or not validated_dir.is_dir():
        return [{"error": f"Invalid directory: {raw_dir}"}]
        
    results = []
    compiled_re = None
    if is_regex:
        try:
            compiled_re = re.compile(raw_query, re.IGNORECASE)
        except re.error as e:
            return [{"error": f"Invalid regex: {e}"}]
            
    try:
        for root, _, files in os.walk(str(validated_dir)):
            for f in files:
                if not fnmatch.fnmatch(f, file_pattern):
                    continue
                fp = Path(root) / f
                if _is_binary_file(fp):
                    continue
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as file_handle:
                        for line_num, line in enumerate(file_handle, 1):
                            matched = False
                            if is_regex and compiled_re:
                                if compiled_re.search(line):
                                    matched = True
                            elif search_query.lower() in line.lower():
                                matched = True
                                
                            if matched:
                                results.append({
                                    "file": str(fp),
                                    "line": line_num,
                                    "content": line.strip()[:200]
                                })
                                if len(results) >= max_matches:
                                    return results
                except Exception:
                    continue
    except Exception as e:
        return [{"error": str(e)}]
        
    return results


def directory_list(
    directory_path: Optional[str] = None,
    path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List all files and folders inside a directory.
    
    Args:
        directory_path: Path to the directory (defaults to "." for workspace root).
        path: Alias for directory_path.
    """
    raw_path = directory_path if directory_path is not None else (path if path is not None else ".")
    try:
        validated_dir = _validate_path(raw_path, for_write=False)
    except Exception as e:
        return [{"error": f"Security/Validation Error: {e}"}]

    if not validated_dir.exists() or not validated_dir.is_dir():
        return [{"error": f"Directory not found: {raw_path}"}]
        
    entries = []
    try:
        for item in sorted(validated_dir.iterdir()):
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size_bytes": item.stat().st_size if item.is_file() else None,
                "path": str(item)
            })
    except Exception as e:
        return [{"error": str(e)}]
    return entries


def directory_tree(
    directory_path: Optional[str] = None,
    max_depth: int = 3,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a nested directory hierarchy tree up to max_depth.
    
    Args:
        directory_path: Path to root directory to inspect (defaults to ".").
        max_depth: Maximum recursion depth for tree traversal (default 3).
        path: Alias for directory_path.
    """
    raw_path = directory_path if directory_path is not None else (path if path is not None else ".")
    try:
        validated_dir = _validate_path(raw_path, for_write=False)
    except Exception as e:
        return {"error": f"Security/Validation Error: {e}"}

    def build_tree(current_path: Path, depth: int) -> Dict[str, Any]:
        if depth > max_depth:
            return {"name": current_path.name, "type": "directory", "children": "[Depth Limit Reached]"}
            
        tree = {"name": current_path.name, "type": "directory", "children": []}
        try:
            for item in sorted(current_path.iterdir()):
                if item.name in [".git", "__pycache__", "node_modules", ".venv"]:
                    continue
                if item.is_dir():
                    tree["children"].append(build_tree(item, depth + 1))
                else:
                    tree["children"].append({"name": item.name, "type": "file", "size_bytes": item.stat().st_size})
        except Exception:
            pass
        return tree

    return build_tree(validated_dir, 1)
