"""
Mammouth Defroster 9000 - Smart Clipboard AI & Quick-Actions Module
Provides Unicode clipboard reading and writing via native Win32 API,
deterministic text/data formatters, and AI quick actions
(explain, fix_bug, translate, format_data, git_commit, summarize).
Zero external API dependencies, reliable on Windows 11.
"""

import sys
import json
import csv
import io
import re
import time
import ctypes
import ctypes.wintypes
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("smart_clipboard")

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
GHND = GMEM_MOVEABLE | GMEM_ZEROINIT

# Configure 64-bit pointer return types and arguments for Win32 API
if sys.platform == "win32":
    try:
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32

        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.restype = ctypes.c_int
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        k32.GlobalFree.restype = ctypes.c_void_p
        k32.GlobalFree.argtypes = [ctypes.c_void_p]

        u32.OpenClipboard.restype = ctypes.c_int
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        u32.CloseClipboard.restype = ctypes.c_int
        u32.CloseClipboard.argtypes = []
        u32.EmptyClipboard.restype = ctypes.c_int
        u32.EmptyClipboard.argtypes = []
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.GetClipboardData.argtypes = [ctypes.c_uint]
        u32.SetClipboardData.restype = ctypes.c_void_p
        u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    except Exception as _setup_err:
        logger.debug(f"Win32 clipboard ctypes setup notice: {_setup_err}")


def get_clipboard_text(max_retries: int = 5, retry_delay: float = 0.05) -> str:
    """Read unicode text from Windows clipboard using native Win32 API with retry logic."""
    if sys.platform != "win32":
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    opened = False
    for _ in range(max_retries):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(retry_delay)

    if not opened:
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return ""
        ptr = kernel32.GlobalLock(h_data)
        if not ptr:
            return ""
        try:
            val = ctypes.c_wchar_p(ptr).value
            return val or ""
        finally:
            kernel32.GlobalUnlock(h_data)
    except Exception as e:
        logger.debug(f"Error reading clipboard data: {e}")
        return ""
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str, max_retries: int = 5, retry_delay: float = 0.05) -> bool:
    """Write unicode text to Windows clipboard using native Win32 API with retry logic."""
    text = str(text or "")
    if sys.platform != "win32":
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    text_encoded = text.encode("utf-16le") + b"\x00\x00"
    size = len(text_encoded)

    opened = False
    for _ in range(max_retries):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(retry_delay)

    if not opened:
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    try:
        user32.EmptyClipboard()
        h_mem = kernel32.GlobalAlloc(GHND, size)
        if not h_mem:
            return False
        ptr = kernel32.GlobalLock(h_mem)
        if not ptr:
            kernel32.GlobalFree(h_mem)
            return False
        try:
            ctypes.memmove(ptr, text_encoded, size)
        finally:
            kernel32.GlobalUnlock(h_mem)

        res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        if not res:
            kernel32.GlobalFree(h_mem)
            return False
        return True
    except Exception as e:
        logger.debug(f"Error setting clipboard data: {e}")
        return False
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Deterministic Formatters & Transformers
# ---------------------------------------------------------------------------

def _try_format_json(text: str) -> Optional[str]:
    """Attempt parsing and pretty-printing JSON text."""
    stripped = text.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return None


def _try_format_csv_to_markdown(text: str) -> Optional[str]:
    """Attempt converting CSV/TSV data into a clean Markdown table."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    delimiter = ","
    if "\t" in lines[0] and lines[0].count("\t") >= lines[0].count(","):
        delimiter = "\t"
    elif ";" in lines[0] and lines[0].count(";") >= lines[0].count(","):
        delimiter = ";"

    try:
        reader = csv.reader(lines, delimiter=delimiter)
        rows = list(reader)
        if not rows or len(rows) < 2:
            return None

        col_count = len(rows[0])
        if col_count < 2:
            return None

        # Build Markdown table (escaping pipe characters in cell content)
        header = [h.strip().replace("|", "\\|") for h in rows[0]]
        separator = ["---"] * col_count
        md_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |"
        ]
        for row in rows[1:]:
            padded = row + [""] * (col_count - len(row))
            cleaned_row = [c.strip().replace("|", "\\|") for c in padded[:col_count]]
            md_lines.append("| " + " | ".join(cleaned_row) + " |")

        return "\n".join(md_lines)
    except Exception:
        return None


def _generate_conventional_commit_heuristic(diff_or_text: str) -> str:
    """Generate a conventional commit message proposal based on diff or change description."""
    lines = diff_or_text.strip().splitlines()
    first_line = lines[0] if lines else "update code"

    # Check for git diff markers
    has_test = any("test" in l.lower() for l in lines)
    has_doc = any("readme" in l.lower() or "doc" in l.lower() for l in lines)
    has_fix = any("fix" in l.lower() or "bug" in l.lower() or "error" in l.lower() for l in lines)
    has_refactor = any("refactor" in l.lower() for l in lines)

    if has_fix:
        prefix = "fix"
    elif has_test:
        prefix = "test"
    elif has_doc:
        prefix = "docs"
    elif has_refactor:
        prefix = "refactor"
    else:
        prefix = "feat"

    # Extract meaningful summary
    summary_candidate = first_line.lstrip("+-#* ").strip()
    if summary_candidate.startswith("diff --git"):
        # Extract filename
        parts = summary_candidate.split()
        if len(parts) >= 3:
            fname = parts[2].lstrip("a/").lstrip("b/")
            summary_candidate = f"update {fname}"
    if len(summary_candidate) > 50:
        summary_candidate = summary_candidate[:47] + "..."

    return f"{prefix}: {summary_candidate.lower()}"


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

def clipboard_get_text() -> Dict[str, Any]:
    """Retrieve the current unicode text content from the Windows clipboard.
    
    Returns:
        dict: status, text, char_count, line_count
    """
    text = get_clipboard_text()
    return {
        "status": "success",
        "text": text,
        "char_count": len(text),
        "line_count": len(text.splitlines()) if text else 0
    }


def clipboard_set_text(text: str) -> Dict[str, Any]:
    """Write unicode text directly to the Windows clipboard.

    Args:
        text: The unicode string to copy into the clipboard.
    """
    success = set_clipboard_text(text)
    if success:
        return {
            "status": "success",
            "message": "Text successfully copied to Windows clipboard.",
            "char_count": len(text)
        }
    return {
        "status": "error",
        "message": "Failed to set clipboard text."
    }


def clipboard_transform(
    action: str,
    text: Optional[str] = None,
    target_lang: str = "English",
    custom_prompt: Optional[str] = None,
    update_clipboard: bool = False
) -> Dict[str, Any]:
    """Perform smart AI transformations or deterministic formatting on clipboard text.

    Args:
        action: Transformation action:
                'explain' - Analyzes and explains code, error messages, or concepts.
                'fix_bug' - Identifies bugs, runtime errors, and provides corrected code.
                'translate' - Translates text or code comments into target_lang.
                'format_data' - Deterministically formats JSON or CSV/TSV into Markdown tables.
                'git_commit' - Generates conventional commit proposals (feat, fix, docs).
                'summarize' - Generates concise executive summary with action items.
                'custom' - Applies custom_prompt to the text.
        text: Text to transform. If omitted or empty, reads the current Windows clipboard.
        target_lang: Target language for translation (default 'English').
        custom_prompt: Prompt instruction when action is 'custom'.
        update_clipboard: If True and deterministic formatting succeeds, updates the Windows clipboard.
    """
    action_clean = str(action or "explain").strip().lower()
    input_text = text if (text is not None and text.strip()) else get_clipboard_text()

    if not input_text or not input_text.strip():
        return {
            "status": "empty_input",
            "message": "Clipboard is empty and no text was provided.",
            "action": action_clean
        }

    # Safety guard: limit maximum text size to prevent token/memory overflow
    MAX_CLIPBOARD_CHARS = 500_000
    if len(input_text) > MAX_CLIPBOARD_CHARS:
        input_text = input_text[:MAX_CLIPBOARD_CHARS] + "\n... [truncated due to size limit]"

    deterministic_result: Optional[str] = None
    prepared_prompt: str = ""

    if action_clean == "explain":
        prepared_prompt = (
            "Analyze and explain the following code snippet, error message, or text clearly and concisely. "
            "Highlight key architecture, mechanics, edge cases, and potential pitfalls:\n\n"
            f"```\n{input_text}\n```"
        )

    elif action_clean == "fix_bug":
        prepared_prompt = (
            "Identify the bugs, logic errors, syntax mistakes, or runtime exceptions in the following snippet. "
            "Provide:\n1. Root Cause Analysis\n2. Corrected Code\n3. Explanation of Fix\n\n"
            f"```\n{input_text}\n```"
        )

    elif action_clean == "translate":
        prepared_prompt = (
            f"Translate the following text or code comments accurately and naturally into {target_lang}. "
            "Preserve code formatting, Markdown tags, identifiers, and placeholders:\n\n"
            f"{input_text}"
        )

    elif action_clean == "format_data":
        json_res = _try_format_json(input_text)
        if json_res:
            deterministic_result = json_res
        else:
            table_res = _try_format_csv_to_markdown(input_text)
            if table_res:
                deterministic_result = table_res

        prepared_prompt = (
            "Parse and format the following unstructured or raw data into a clean, well-structured format "
            "(JSON or Markdown Table):\n\n"
            f"{input_text}"
        )

    elif action_clean == "git_commit":
        deterministic_result = _generate_conventional_commit_heuristic(input_text)
        prepared_prompt = (
            "Generate a conventional git commit message (e.g. feat, fix, docs, refactor, test) "
            "following the schema:\n"
            "<type>(<scope>): <short imperative description>\n\n"
            "[Optional detailed bullet points explaining why and what changed]\n\n"
            f"Changes / Diff:\n```\n{input_text}\n```"
        )

    elif action_clean == "summarize":
        prepared_prompt = (
            "Provide a concise executive summary of the following content:\n"
            "- 1-sentence Executive Overview\n"
            "- Key Takeaways (bullet points)\n"
            "- Action Items / Next Steps\n\n"
            f"{input_text}"
        )

    elif action_clean == "custom":
        user_inst = custom_prompt.strip() if custom_prompt else "Process the following text:"
        prepared_prompt = f"{user_inst}\n\n{input_text}"

    else:
        prepared_prompt = f"Process the following text using action '{action_clean}':\n\n{input_text}"

    # Optionally update clipboard if deterministic transformation succeeded
    clipboard_updated = False
    if update_clipboard and deterministic_result:
        clipboard_updated = set_clipboard_text(deterministic_result)

    return {
        "status": "success",
        "action": action_clean,
        "original_char_count": len(input_text),
        "prepared_prompt": prepared_prompt,
        "deterministic_result": deterministic_result,
        "clipboard_updated": clipboard_updated
    }
