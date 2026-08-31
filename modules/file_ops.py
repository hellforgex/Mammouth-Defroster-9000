import os
import re
import json
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional

CONFIG_FILE = Path(__file__).parent.parent / "config.json"

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
    default_ws = (Path(__file__).parent.parent / "workspace").resolve()
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            server_cfg = cfg.get("server", {})
            enforce_sandbox = server_cfg.get("enforce_workspace_sandbox", True)
            ws_root_str = server_cfg.get("workspace_root", "./workspace")
            ws_root = (Path(__file__).parent.parent / ws_root_str).resolve() if not Path(ws_root_str).is_absolute() else Path(ws_root_str).resolve()
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


def file_read(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None, max_chars: int = 50000) -> str:
    """Read a text file with optional line slicing within allowed workspace boundaries."""
    try:
        path = _validate_path(file_path, for_write=False)
    except Exception as e:
        return f"Security/Validation Error: {e}"

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


def file_write(file_path: str, content: str, overwrite: bool = True) -> str:
    """Write or overwrite a file on disk within allowed workspace boundaries."""
    try:
        path = _validate_path(file_path, for_write=True)
    except Exception as e:
        return f"Security/Validation Error: {e}"

    if path.exists() and not overwrite:
        return f"Error: File already exists: {file_path}"
        
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {path.name}"
    except Exception as e:
        return f"Error writing file: {e}"


def file_replace_chunk(file_path: str, target_chunk: str, replacement_chunk: str) -> str:
    """Replace an exact block of text/code in a file."""
    try:
        path = _validate_path(file_path, for_write=True)
    except Exception as e:
        return f"Security/Validation Error: {e}"

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
    """Search for text inside files in a directory (like grep/ripgrep)."""
    try:
        path = _validate_path(directory_path, for_write=False)
    except Exception as e:
        return [{"error": f"Security/Validation Error: {e}"}]

    if not path.exists() or not path.is_dir():
        return [{"error": f"Invalid directory: {directory_path}"}]
        
    results = []
    compiled_re = None
    if is_regex:
        try:
            compiled_re = re.compile(search_query, re.IGNORECASE)
        except re.error as e:
            return [{"error": f"Invalid regex: {e}"}]
            
    try:
        for root, _, files in os.walk(str(path)):
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


def directory_list(directory_path: str = ".") -> List[Dict[str, Any]]:
    """List all files and folders inside a directory."""
    try:
        path = _validate_path(directory_path, for_write=False)
    except Exception as e:
        return [{"error": f"Security/Validation Error: {e}"}]

    if not path.exists() or not path.is_dir():
        return [{"error": f"Directory not found: {directory_path}"}]
        
    entries = []
    try:
        for item in sorted(path.iterdir()):
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size_bytes": item.stat().st_size if item.is_file() else None,
                "path": str(item)
            })
    except Exception as e:
        return [{"error": str(e)}]
    return entries


def directory_tree(directory_path: str = ".", max_depth: int = 3) -> Dict[str, Any]:
    """Generate a nested directory hierarchy tree up to max_depth."""
    try:
        path = _validate_path(directory_path, for_write=False)
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

    return build_tree(path, 1)
