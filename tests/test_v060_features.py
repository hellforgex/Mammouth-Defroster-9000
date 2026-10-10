"""
Unit tests for Mammouth Defroster 9000 v0.6.0 features:
Feature 1: Multimodal Screen & Window Copilot (Global Hotkey, Active Window Capture)
Feature 2: Sovereign Workspace Memory & Semantic Code Search (FTS5 RAG, Symbols, mtime tracking)
Feature 3: Smart Clipboard AI & Quick-Actions (Unicode Win32 clipboard, formatters, actions)
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image as RealPILImage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.global_hotkey import (
    GlobalHotkeyManager,
    register_global_hotkey,
    unregister_global_hotkey,
    is_global_hotkey_registered,
    list_registered_hotkeys
)
from modules.screen_capture import (
    get_foreground_window_info,
    screen_capture_active_window,
    screen_capture_active_window_local,
    screen_grant_consent,
    screen_revoke_consent
)
from modules.workspace_indexer import (
    workspace_index_directory,
    workspace_search,
    workspace_find_symbols,
    workspace_get_stats,
    set_index_db_path,
    _extract_python_symbols,
    _extract_regex_symbols,
    _chunk_file_content,
    _sanitize_fts5_query
)
from modules.smart_clipboard import (
    get_clipboard_text,
    set_clipboard_text,
    clipboard_get_text,
    clipboard_set_text,
    clipboard_transform,
    _try_format_json,
    _try_format_csv_to_markdown,
    _generate_conventional_commit_heuristic
)
from server import require_module


class TestV060GlobalHotkey(unittest.TestCase):
    def tearDown(self):
        unregister_global_hotkey()

    def test_hotkey_manager_multi_register(self):
        """Test registering and unregistering multiple global hotkeys with distinct IDs."""
        mgr = GlobalHotkeyManager()
        called_1 = []
        called_2 = []

        # Register hotkey 1
        ok1 = mgr.register(lambda: called_1.append(1), key="SPACE", modifiers="Ctrl+Shift", hotkey_id=3001)
        # In test environment, Windows RegisterHotKey might succeed or fail depending on desktop session,
        # but manager state and unregister logic must be consistent.
        if ok1:
            self.assertTrue(mgr.is_hotkey_registered(3001))
            self.assertTrue(mgr.is_registered)

            # Register hotkey 2
            ok2 = mgr.register(lambda: called_2.append(2), key="K", modifiers="Ctrl+Shift", hotkey_id=3002)
            if ok2:
                self.assertTrue(mgr.is_hotkey_registered(3002))
                hotkeys = mgr.list_hotkeys()
                self.assertGreaterEqual(len(hotkeys), 2)

                # Unregister single hotkey
                mgr.unregister(hotkey_id=3001)
                self.assertFalse(mgr.is_hotkey_registered(3001))
                self.assertTrue(mgr.is_hotkey_registered(3002))

            # Unregister all
            mgr.unregister()
            self.assertFalse(mgr.is_registered)
            self.assertFalse(mgr.is_hotkey_registered(3002))

    def test_composite_key_parsing(self):
        """Test composite key spec parsing like 'Ctrl+Shift+Space'."""
        mgr = GlobalHotkeyManager()
        # Non-Windows simulation
        with patch("modules.global_hotkey.sys.platform", "linux"):
            res = mgr.register(lambda: None, key="Ctrl+Shift+Space", hotkey_id=3003)
            self.assertFalse(res)


class TestV060ScreenCopilot(unittest.TestCase):
    def setUp(self):
        screen_revoke_consent()

    def tearDown(self):
        screen_revoke_consent()

    def test_foreground_window_info_structure(self):
        """Test structure of get_foreground_window_info."""
        info = get_foreground_window_info()
        self.assertIsInstance(info, dict)
        self.assertIn("hwnd", info)
        self.assertIn("title", info)
        self.assertIn("process_id", info)
        self.assertIn("process_name", info)
        self.assertIn("rect", info)
        rect = info["rect"]
        self.assertIn("width", rect)
        self.assertIn("height", rect)

    def test_screen_capture_active_window_consent_gate(self):
        """Test that MCP client screen_capture_active_window requires consent."""
        res = screen_capture_active_window(save_to_workspace=False)
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("status"), "consent_required")

    def test_screen_capture_active_window_local_bypasses_gate(self):
        """Test that GUI-initiated active window capture bypasses consent gate."""
        mock_img = RealPILImage.new("RGB", (640, 480), color=(80, 120, 160))
        with patch("modules.screen_capture.ImageGrab") as mock_grab, \
             patch("modules.screen_capture.mss", None):
            mock_grab.grab.return_value = mock_img
            res = screen_capture_active_window_local(save_to_workspace=False, include_metadata=True)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("status"), "success")
            self.assertIn("window_title", res)
            self.assertIn("window_rect", res)
            self.assertIn("current_resolution", res)

    def test_screen_capture_active_window_with_consent(self):
        """Test screen_capture_active_window succeeds when consent is granted."""
        screen_grant_consent("once")
        mock_img = RealPILImage.new("RGB", (800, 600), color=(50, 50, 50))
        with patch("modules.screen_capture.ImageGrab") as mock_grab, \
             patch("modules.screen_capture.mss", None):
            mock_grab.grab.return_value = mock_img
            res = screen_capture_active_window(save_to_workspace=False, include_metadata=True)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("current_resolution"), "800x600")

    def test_screen_capture_minimized_window_fallback(self):
        """Test screen_capture_active_window gracefully falls back when foreground window is minimized."""
        screen_grant_consent("once")
        minimized_info = {
            "hwnd": 12345,
            "title": "Minimized App",
            "process_id": 999,
            "process_name": "app.exe",
            "is_minimized": True,
            "rect": {"left": -32000, "top": -32000, "right": -31840, "bottom": -31972, "width": 0, "height": 0}
        }
        mock_full_img = RealPILImage.new("RGB", (1920, 1080), color=(10, 10, 10))
        with patch("modules.screen_capture.get_foreground_window_info", return_value=minimized_info), \
             patch("modules.screen_capture.ImageGrab") as mock_grab, \
             patch("modules.screen_capture.mss", None):
            mock_grab.grab.return_value = mock_full_img
            res = screen_capture_active_window(save_to_workspace=False, include_metadata=True)
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("current_resolution"), "1920x1080")


class TestV060WorkspaceIndexer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="defroster_test_ws_")
        self.db_dir = tempfile.mkdtemp(prefix="defroster_test_db_")
        self.db_file = Path(self.db_dir) / "test_index.db"
        set_index_db_path(self.db_file)

        # Create sample files
        py_content = '''"""Sample module."""

class DataProcessor:
    def process_records(self, items):
        return [i * 2 for i in items]

def compute_total(a, b):
    """Compute total sum."""
    return a + b
'''
        Path(self.test_dir, "processor.py").write_text(py_content, encoding="utf-8")

        js_content = '''
class ApiClient {
    constructor() {}
}

function fetchUser(id) {
    return { id: id };
}
'''
        Path(self.test_dir, "client.js").write_text(js_content, encoding="utf-8")

        # Create ignored folder (.git)
        git_dir = Path(self.test_dir, ".git")
        git_dir.mkdir()
        Path(git_dir, "config.txt").write_text("should be ignored", encoding="utf-8")

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
            shutil.rmtree(self.db_dir, ignore_errors=True)
        except Exception:
            pass

    def test_extract_python_symbols_ast(self):
        """Test extracting classes and methods from Python source."""
        code = "class Calculator:\n    def add(self, x, y):\n        return x + y\n\ndef helper():\n    pass\n"
        symbols = _extract_python_symbols(code, "calc.py")
        names = [s["symbol_name"] for s in symbols]
        self.assertIn("Calculator", names)
        self.assertIn("Calculator.add", names)
        self.assertIn("helper", names)

    def test_extract_regex_symbols(self):
        """Test extracting functions and classes via regex for non-Python files."""
        code = "class AppState {}\nfunction initialize(cfg) {}\nconst render = (el) => {}"
        symbols = _extract_regex_symbols(code, "app.js")
        names = [s["symbol_name"] for s in symbols]
        self.assertIn("AppState", names)
        self.assertIn("initialize", names)
        self.assertIn("render", names)

    def test_chunking_file_content(self):
        """Test line-based overlapping chunking."""
        lines = [f"line {i}" for i in range(100)]
        content = "\n".join(lines)
        chunks = _chunk_file_content(content, chunk_size=30, overlap=10)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["start_line"], 1)
        self.assertEqual(chunks[0]["end_line"], 30)

    def test_sanitize_fts5_query(self):
        """Test FTS5 query sanitizer removes hazardous syntax symbols."""
        raw = 'def process_records(self, items): -> "test" *'
        cleaned = _sanitize_fts5_query(raw)
        self.assertNotIn("(", cleaned)
        self.assertNotIn(":", cleaned)
        self.assertIn('"process_records"*', cleaned)

    def test_index_and_search_workflow(self):
        """Test complete workspace indexing, searching, and stats retrieval."""
        # 1. First index run
        res = workspace_index_directory(self.test_dir)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["indexed_files"], 2)
        self.assertEqual(res["skipped_files"], 0)

        # 2. Second index run: mtime tracking should skip unchanged files
        res2 = workspace_index_directory(self.test_dir)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["indexed_files"], 0)
        self.assertEqual(res2["skipped_files"], 2)

        # 3. FTS5 Search
        search_res = workspace_search("compute_total", limit=5)
        self.assertEqual(search_res["status"], "success")
        self.assertGreaterEqual(search_res["total_matches"], 1)
        self.assertIn("processor.py", search_res["matches"][0]["file_path"])

        # 4. Symbol Search
        sym_res = workspace_find_symbols(symbol_name="DataProcessor", symbol_type="class")
        self.assertEqual(sym_res["status"], "success")
        self.assertEqual(sym_res["total_symbols"], 1)
        self.assertEqual(sym_res["symbols"][0]["symbol_type"], "class")
        self.assertEqual(sym_res["symbols"][0]["symbol_name"], "DataProcessor")

        # 5. Telemetry Stats
        stats = workspace_get_stats()
        self.assertEqual(stats["status"], "success")
        self.assertEqual(stats["indexed_files"], 2)
        self.assertGreaterEqual(stats["total_symbols"], 3)
        self.assertIn("python", stats["languages"])

        # 6. File modification & deletion pruning
        os.remove(Path(self.test_dir, "client.js"))
        res3 = workspace_index_directory(self.test_dir)
        self.assertEqual(res3["deleted_pruned"], 1)
        stats2 = workspace_get_stats()
        self.assertEqual(stats2["indexed_files"], 1)

    def test_prefix_collision_underscores(self):
        """Test that directories with underscores do not prune or overwrite sibling folders."""
        base_dir = tempfile.mkdtemp(prefix="test_prefix_base_")
        try:
            dir_dash = Path(base_dir) / "proj-a"
            dir_under = Path(base_dir) / "proj_a"
            dir_dash.mkdir()
            dir_under.mkdir()

            (dir_dash / "test.py").write_text("def func_dash(): pass", encoding="utf-8")
            (dir_under / "test.py").write_text("def func_under(): pass", encoding="utf-8")

            res1 = workspace_index_directory(str(dir_dash))
            self.assertEqual(res1["indexed_files"], 1)
            self.assertEqual(res1["deleted_pruned"], 0)

            # Indexing proj_a must not prune files from proj-a
            res2 = workspace_index_directory(str(dir_under))
            self.assertEqual(res2["indexed_files"], 1)
            self.assertEqual(res2["deleted_pruned"], 0)

            stats = workspace_get_stats()
            self.assertEqual(stats["indexed_files"], 2)
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    def test_empty_file_cleanup_from_fts(self):
        """Test that truncating a file to 0 bytes removes its symbols and FTS chunks."""
        test_file = Path(self.test_dir, "disappearing.py")
        test_file.write_text("def unique_vanish_symbol(): pass", encoding="utf-8")

        res = workspace_index_directory(self.test_dir)
        self.assertGreaterEqual(res["indexed_files"], 1)

        search1 = workspace_search("unique_vanish_symbol")
        self.assertEqual(search1["total_matches"], 1)

        # Truncate to 0 bytes and re-index
        test_file.write_text("", encoding="utf-8")
        res2 = workspace_index_directory(self.test_dir)
        self.assertEqual(res2["status"], "success")

        # Must no longer match
        search2 = workspace_search("unique_vanish_symbol")
        self.assertEqual(search2["total_matches"], 0)

    def test_complex_class_bases_ast(self):
        """Test extracting class bases with module prefixes via ast.unparse."""
        code = "class CustomWidget(ctk.CTkFrame, base.Base):\n    def init_ui(self): pass\n"
        syms = _extract_python_symbols(code, "widget.py")
        self.assertEqual(len(syms), 2)
        cls_sym = [s for s in syms if s["symbol_type"] == "class"][0]
        self.assertEqual(cls_sym["symbol_name"], "CustomWidget")
        self.assertIn("ctk.CTkFrame", cls_sym["signature"])


class TestV060SmartClipboard(unittest.TestCase):
    def test_unicode_read_write(self):
        """Test writing and reading Unicode text to/from clipboard."""
        test_text = "Mammouth Defroster 9000 🦣❄️🔥 Unicode Test — äöüß €"
        ok = set_clipboard_text(test_text)
        if ok:
            read_back = get_clipboard_text()
            self.assertEqual(read_back, test_text)

    def test_clipboard_tools_basic(self):
        """Test clipboard_set_text and clipboard_get_text tools."""
        set_res = clipboard_set_text("Hello FastMCP Clipboard")
        self.assertEqual(set_res["status"], "success")
        get_res = clipboard_get_text()
        self.assertEqual(get_res["status"], "success")
        self.assertIn("Hello FastMCP", get_res["text"])

    def test_format_json_deterministic(self):
        """Test JSON pretty-printing formatter."""
        raw_json = '{"name":"mammouth","version":"0.6.0","active":true}'
        formatted = _try_format_json(raw_json)
        self.assertIsNotNone(formatted)
        self.assertIn('  "name": "mammouth"', formatted)

    def test_format_csv_to_markdown_table(self):
        """Test CSV to Markdown table formatter."""
        raw_csv = "id,name,role\n1,Mammouth,DevOps\n2,Defroster,Cockpit"
        md = _try_format_csv_to_markdown(raw_csv)
        self.assertIsNotNone(md)
        self.assertIn("| id | name | role |", md)
        self.assertIn("| 1 | Mammouth | DevOps |", md)

    def test_conventional_commit_heuristic(self):
        """Test conventional commit proposal generation."""
        diff = "diff --git a/src/server.py b/src/server.py\n+ def fix_bug(): pass"
        msg = _generate_conventional_commit_heuristic(diff)
        self.assertTrue(msg.startswith("fix:"))

    def test_clipboard_transform_actions(self):
        """Test clipboard_transform across supported actions."""
        # Explain
        res_exp = clipboard_transform(action="explain", text="def add(a, b): return a + b")
        self.assertEqual(res_exp["status"], "success")
        self.assertIn("Analyze and explain", res_exp["prepared_prompt"])

        # Fix bug
        res_fix = clipboard_transform(action="fix_bug", text="throw new Error('missing')")
        self.assertEqual(res_fix["status"], "success")
        self.assertIn("Identify the bugs", res_fix["prepared_prompt"])

        # Translate
        res_tr = clipboard_transform(action="translate", text="Guten Morgen", target_lang="English")
        self.assertEqual(res_tr["status"], "success")
        self.assertIn("English", res_tr["prepared_prompt"])

        # Format data with deterministic JSON
        res_fmt = clipboard_transform(action="format_data", text='{"test": 123}', update_clipboard=False)
        self.assertEqual(res_fmt["status"], "success")
        self.assertIsNotNone(res_fmt["deterministic_result"])

        # Git commit
        res_gc = clipboard_transform(action="git_commit", text="Add workspace indexer and smart clipboard features")
        self.assertEqual(res_gc["status"], "success")
        self.assertIn("conventional git commit", res_gc["prepared_prompt"])

        # Summarize
        res_sum = clipboard_transform(action="summarize", text="Long log contents...")
        self.assertEqual(res_sum["status"], "success")
        self.assertIn("executive summary", res_sum["prepared_prompt"].lower())

    def test_format_csv_with_pipe_escaping(self):
        """Test that pipe characters within CSV cells are properly escaped in Markdown output."""
        raw_csv = "id,rule\n1,Alpha | Beta\n2,Gamma | Delta"
        md = _try_format_csv_to_markdown(raw_csv)
        self.assertIsNotNone(md)
        # Should escape pipe so column count remains 2
        self.assertIn(r"Alpha \| Beta", md)
        for line in md.splitlines():
            # Check exactly 2 columns (3 pipes per line: leading, separator, trailing)
            self.assertEqual(line.count("|") - line.count(r"\|"), 3)

    def test_clipboard_transform_custom_prompt(self):
        """Test clipboard_transform with action='custom' and custom_prompt."""
        res = clipboard_transform(action="custom", text="print('hi')", custom_prompt="Rewrite in Rust:")
        self.assertEqual(res["status"], "success")
        self.assertIn("Rewrite in Rust:", res["prepared_prompt"])

    def test_clipboard_transform_size_limit(self):
        """Test that very large clipboard content is truncated safely."""
        giant_text = "A" * 600_000
        res = clipboard_transform(action="explain", text=giant_text)
        self.assertEqual(res["status"], "success")
        self.assertIn("[truncated due to size limit]", res["prepared_prompt"])


class TestV060ServerGateIntegration(unittest.TestCase):
    def test_workspace_memory_require_module_gate(self):
        """Test that require_module('workspace_memory') enforces config toggle."""
        @require_module("workspace_memory")
        def dummy_rag():
            return {"rag": True}

        with patch("server.load_config", return_value={"modules": {"workspace_memory": {"enabled": False}}}):
            with self.assertRaises(PermissionError):
                dummy_rag()

        with patch("server.load_config", return_value={"modules": {"workspace_memory": {"enabled": True}}}):
            res = dummy_rag()
            self.assertEqual(res, {"rag": True})

    def test_smart_clipboard_require_module_gate(self):
        """Test that require_module('smart_clipboard') enforces config toggle."""
        @require_module("smart_clipboard")
        def dummy_clip():
            return {"clip": True}

        with patch("server.load_config", return_value={"modules": {"smart_clipboard": {"enabled": False}}}):
            with self.assertRaises(PermissionError):
                dummy_clip()

        with patch("server.load_config", return_value={"modules": {"smart_clipboard": {"enabled": True}}}):
            res = dummy_clip()
            self.assertEqual(res, {"clip": True})


if __name__ == "__main__":
    unittest.main()
