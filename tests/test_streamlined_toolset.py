"""Regression & parity tests for the streamlined 42-tool MCP architecture."""

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import config
import server
from modules import (
    browser_agent,
    claude_code,
    desktop_input,
    file_ops,
    google_drive,
    mammouth_code,
    memory,
    putty_ssh,
    screen_capture,
    shell_processes,
    smart_clipboard,
    system_monitor,
    task_scheduler,
    tasks_kanban,
    web_tools,
    workspace_indexer,
)


def _all_enabled_config(profile: str = "all") -> dict:
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    for mod_data in cfg.get("modules", {}).values():
        mod_data["enabled"] = True
    cfg.setdefault("server", {})["tool_profile"] = profile
    return cfg


class TestStreamlinedToolset(unittest.TestCase):
    """Verify 42 canonical MCP tools, token reductions, legacy aliases, and security gates."""

    def test_exact_42_canonical_tools_and_title_stripping(self):
        """All 16 modules enabled yields exactly 42 tools with zero schema title bloat."""
        cfg = _all_enabled_config("all")
        with patch("server.load_config", return_value=cfg):
            server.register_active_tools()

        counts_by_mod, total = server.get_streamlined_tool_counts()
        self.assertEqual(len(counts_by_mod), 16)
        self.assertEqual(total, 42)
        self.assertEqual(len(server._registered_tool_names), 42)

        async def _check():
            with patch("server.load_config", return_value=cfg):
                tools = await server.mcp.list_tools()
                wire = []
                for t in tools:
                    m = t.to_mcp_tool()
                    server._sanitize_mcp_tool_schema(m)
                    d = m.model_dump(by_alias=True, exclude_none=True)
                    schema = d.get("inputSchema", {})
                    self.assertNotIn("title", schema)
                    for prop in schema.get("properties", {}).values():
                        self.assertNotIn("title", prop)
                    wire.append(d)
                self.assertEqual(len(wire), 42)
                wire_tokens = len(json.dumps(wire, ensure_ascii=False)) // 4
                # Verify substantial reduction from pre-streamlining ~16,189 tokens
                self.assertLess(wire_tokens, 9200)

        asyncio.run(_check())

    def test_catalog_overview_and_three_tier_metrics(self):
        """Catalog overview remains compact and accounts for all 16 module categories (39 module tools)."""
        cfg = _all_enabled_config("mammouth_safe")
        with patch("server.load_config", return_value=cfg):
            overview = server.defroster_catalog()
            self.assertEqual(overview["status"], "success")
            self.assertEqual(len(overview["categories"]), 16)
            self.assertEqual(overview["tool_inventory_metrics"]["total_catalog_suite"], 39)
            self.assertLess(len(json.dumps(overview)), 5500)

    def test_legacy_aliases_respect_profile_and_module_gates(self):
        """defroster_execute_tool resolves legacy names while enforcing profile allowlist and module switches."""
        async def _check():
            safe_cfg = _all_enabled_config("mammouth_safe")
            with patch("server.load_config", return_value=safe_cfg):
                # task_create -> task_board is excluded in mammouth_safe
                res_task = await server.defroster_execute_tool("task_create", {"title": "Denied"})
                self.assertEqual(res_task["status"], "error")
                self.assertEqual(res_task["tool"], "task_create")
                self.assertEqual(res_task["error"], "tool not in active profile")

                # mouse_get_position remains explicitly rejected in mammouth_safe
                res_pos = await server.defroster_execute_tool("mouse_get_position", {})
                self.assertEqual(res_pos["status"], "error")
                self.assertEqual(res_pos["tool"], "mouse_get_position")
                self.assertEqual(res_pos["error"], "tool not in active profile")

                # clipboard_get_text routes to clipboard_manage when allowed in mammouth_safe
                with patch("modules.smart_clipboard.clipboard_get_text", return_value={"status": "success", "text": "hello"}):
                    res_clip = await server.defroster_execute_tool("clipboard_get_text", {})
                    self.assertEqual(res_clip["status"], "success")
                    self.assertEqual(res_clip["tool"], "clipboard_get_text")
                    self.assertEqual(res_clip["result"]["text"], "hello")

            # Disabled module blocks alias even under 'all' profile
            disabled_cfg = _all_enabled_config("all")
            disabled_cfg["modules"]["tasks_kanban"]["enabled"] = False
            with patch("server.load_config", return_value=disabled_cfg):
                res_dis = await server.defroster_execute_tool("task_create", {"title": "Blocked"})
                self.assertEqual(res_dis["status"], "error")
                self.assertEqual(res_dis["tool"], "task_create")
                self.assertIn("disabled in Defroster settings", res_dis["error"])

        asyncio.run(_check())

    def test_file_ops_clean_and_directory_tree_parity(self):
        """Streamlined file_ops tools preserve CRUD, search, recursive tree, and sandbox boundaries."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp).resolve()
            (ws / "sub").mkdir()
            with patch("modules.file_ops._get_sandbox_config", return_value=(True, ws)):
                w = file_ops.file_write_clean("sub/demo.txt", "alpha\nbeta\ngamma")
                self.assertIn("Successfully", w)
                self.assertEqual(file_ops.file_read_clean("sub/demo.txt", start_line=2, end_line=2), "beta")
                file_ops.file_replace_chunk_clean("sub/demo.txt", "beta", "DELTA")
                matches = file_ops.file_search_text_clean(".", "DELTA")
                self.assertEqual(len(matches), 1)

                tree = file_ops.directory_list_clean(".", recursive=True, max_depth=3)
                self.assertIsInstance(tree, dict)
                flat = file_ops.directory_list_clean(".", recursive=False)
                self.assertIsInstance(flat, list)

                outside = file_ops.file_read_clean("C:/Windows/System32/drivers/etc/hosts")
                self.assertIn("Sandbox Violation", outside)

    def test_shell_and_process_manage_dispatchers(self):
        """powershell_exec_clean supports powershell/cmd shells with workspace cwd & shield checks."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp).resolve()
            with patch("modules.shell_processes.resolve_workspace_root", return_value=str(ws)):
                with patch("config.load_config", return_value={"server": {"allow_admin_shell": False, "read_only_shell": False}}):
                    res = shell_processes.powershell_exec_clean("echo hello_cmd", shell="cmd")
                    self.assertEqual(res["exit_code"], 0)
                    self.assertIn("hello_cmd", res["stdout"])

                    blocked = shell_processes.powershell_exec_clean("Remove-Item -Recurse C:\\Windows")
                    self.assertEqual(blocked["status"], "permission_denied")
                    self.assertEqual(blocked["error_code"], "ERR_SECURITY_SHIELD")

                self.assertIsInstance(shell_processes.process_manage(action="list"), list)

    def test_desktop_input_dispatchers(self):
        """desktop_mouse and desktop_keyboard route actions cleanly to underlying primitives."""
        with patch("modules.desktop_input.mouse_click", return_value={"status": "ok", "clicked": True}) as mc:
            r1 = desktop_input.desktop_mouse(action="click", x=10, y=20)
            self.assertTrue(r1["clicked"])
            mc.assert_called_once()
        with patch("modules.desktop_input.keyboard_hotkey", return_value={"status": "ok"}) as kh:
            r2 = desktop_input.desktop_keyboard(action="hotkey", key="ctrl+s")
            self.assertEqual(r2["status"], "ok")
            kh.assert_called_once_with(keys="ctrl+s")

    def test_screen_capture_consent_and_windows_dispatch(self):
        """screen_capture_dispatch preserves consent enforcement; screen_windows lists monitors."""
        screen_capture.screen_revoke_consent()
        try:
            with patch("config.load_config", return_value={"modules": {"screen_capture": {"consent_granted": False}}}):
                denied = screen_capture.screen_capture_dispatch(target="active_window")
                self.assertEqual(denied["status"], "consent_required")
        finally:
            screen_capture.screen_revoke_consent()
        mons = screen_capture.screen_windows(action="monitors")
        self.assertIsInstance(mons, list)

    def test_browser_agent_consolidated_dispatchers(self):
        """browser_inspect, browser_interact, browser_session dispatch cleanly to worker/helpers."""
        with patch("modules.browser_agent.browser_snapshot", return_value={"ok": True}) as bs:
            self.assertEqual(browser_agent.browser_inspect(mode="snapshot"), {"ok": True})
            bs.assert_called_once()
        with patch("modules.browser_agent.browser_click", return_value={"clicked": True}) as bc:
            self.assertEqual(browser_agent.browser_interact(action="click", target="#ok"), {"clicked": True})
            bc.assert_called_once()
        with patch("modules.browser_agent.browser_status", return_value={"running": False}) as st:
            self.assertEqual(browser_agent.browser_session(action="status"), {"running": False})
            st.assert_called_once()

    def test_gdrive_dispatchers_safe_status(self):
        """gdrive_manage(status) and argument dispatchers operate safely."""
        with patch("modules.google_drive.gdrive_status", return_value={"authenticated": False}):
            self.assertFalse(google_drive.gdrive_manage(action="status")["authenticated"])

    def test_memory_and_task_board_and_scheduler_clean(self):
        """memory_*_clean, task_board, and task_schedule_manage perform full SQLite operations."""
        with tempfile.TemporaryDirectory() as tmp:
            mem_db = Path(tmp) / "mem.db"
            task_db = Path(tmp) / "task.db"
            sched_db = Path(tmp) / "sched.db"
            with patch("modules.memory.DB_PATH", mem_db):
                self.assertIn("saved", memory.memory_save_clean("k1", "value_one").lower())
                got = memory.memory_recall_clean(key="k1")
                self.assertEqual(got["content"], "value_one")
                self.assertIsInstance(memory.memory_recall_clean(), list)
                self.assertIn("deleted", memory.memory_delete_clean("k1").lower())

            with patch("modules.tasks_kanban.DB_PATH", task_db):
                created = tasks_kanban.task_board(action="create", title="Clean Toolset")
                tid = created["id"]
                self.assertEqual(created["title"], "Clean Toolset")
                listed = tasks_kanban.task_board(action="list")
                self.assertEqual(len(listed), 1)
                upd = tasks_kanban.task_board(action="update", task_id=tid, status="done")
                self.assertEqual(upd["status"], "done")
                self.assertIn("deleted", tasks_kanban.task_board(action="delete", task_id=tid).lower())

            with patch("modules.task_scheduler.DB_PATH", sched_db):
                presets = task_scheduler.task_schedule_manage(action="presets")
                self.assertIsInstance(presets, list)
                self.assertIsInstance(task_scheduler.task_schedule_manage(action="list"), list)

    def test_system_workspace_clipboard_ssh_coding_web_dispatchers(self):
        """Remaining unified dispatchers enforce security and preserve expected contracts."""
        specs = system_monitor.system_specs_dispatch(include_gpu=False)
        self.assertIn("cpu", specs)

        with patch("modules.workspace_indexer.workspace_get_stats", return_value={"indexed_files": 5}):
            self.assertEqual(workspace_indexer.workspace_code_search(action="stats")["indexed_files"], 5)

        fmt = smart_clipboard.clipboard_manage(action="format", text='{"b": 2, "a": 1}')
        self.assertEqual(fmt["status"], "success")
        self.assertIn('"a": 1', fmt["deterministic_result"])

        with patch("modules.putty_ssh.ssh_list_saved_hosts", return_value={"hosts": []}):
            self.assertEqual(putty_ssh.ssh_hosts(action="list"), {"hosts": []})

        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            with self.assertRaises(PermissionError):
                mammouth_code.mammouth_code_dispatch(action="launch_terminal")
            with self.assertRaises(PermissionError):
                claude_code.claude_code_dispatch(action="launch_terminal")

        # SSRF shield remains active in web_fetch
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            res_ssrf = web_tools.web_fetch("http://localhost.local/admin", mode="status")
            self.assertIn("error", res_ssrf)


if __name__ == "__main__":
    unittest.main()
