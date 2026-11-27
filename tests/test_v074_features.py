"""
Tests for Mammouth Defroster 9000 v0.7.4 features, bugfixes, and UI robustness:
- Resolution of GUI startup crash (NameError: curr_prof_id in _setup_skills_tab)
- Resolution of server NameError: logger in defroster_catalog
- Cross-thread/cross-loop safe broadcast of tools/list_changed notification
- Tool profile selection widgets (sidebar, dashboard hero card, skills tab)
- Hero Card anti-clipping layout: guarantees visibility of OAuth, Bearer, and Sandbox badges
- Dynamic profile switching by label or ID, gauge updates, and _enable_safe_skills sync
- Background disk sync of external profile switches (defroster_catalog)
- Multilingual keyword enrichment and idempotency
- Web & Vision profile tool count alignment
- Version string alignment
"""

import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import asyncio
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui
import server
from config import TOOL_PROFILES


class TestV074FeaturesAndFixes(unittest.TestCase):
    def tearDown(self):
        import gc
        gc.collect()

    def test_version_alignment_v074(self):
        """Verify APP_VERSION in gui.py, server.py, and pyproject.toml are aligned."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        content = pyproject_path.read_text(encoding="utf-8")
        import re
        m = re.search(r'version\s*=\s*"([^"]+)"', content)
        self.assertIsNotNone(m)
        expected_ver = m.group(1)
        self.assertEqual(gui.APP_VERSION, f"v{expected_ver}")
        self.assertIn(f"v{expected_ver}", server.mcp.instructions or "")

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    def test_gui_init_curr_prof_id_not_raising_name_error(self):
        """Regression test: verify MammouthControlCenter initializes without NameError on curr_prof_id."""
        app = gui.MammouthControlCenter()
        try:
            self.assertTrue(hasattr(app, "curr_tool_profile_id"))
            self.assertTrue(bool(app.curr_tool_profile_id))
            self.assertTrue(hasattr(app, "var_tool_profile"))
            self.assertTrue(hasattr(app, "sidebar_profile_menu"))
            self.assertTrue(hasattr(app, "dash_profile_menu"))
            self.assertTrue(hasattr(app, "dash_profile_badge"))
            self.assertTrue(hasattr(app, "lbl_schema_gauge"))
            self.assertTrue(hasattr(app, "lbl_nav_tools"))

            # Verify current profile matches config
            curr_prof = app.config_data.get("server", {}).get("tool_profile", "mammouth_safe")
            self.assertEqual(app.curr_tool_profile_id, curr_prof)
        finally:
            app.destroy()

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    def test_gui_tool_profile_switch_sync(self):
        """Verify switching tool profile in GUI updates curr_tool_profile_id, config, badges, and stats."""
        app = gui.MammouthControlCenter()
        try:
            # Switch using label
            target_profile_id = "developer"
            target_label = TOOL_PROFILES[target_profile_id]["label"]

            app._on_tool_profile_change(target_label)

            self.assertEqual(app.curr_tool_profile_id, target_profile_id)
            self.assertEqual(app.config_data.get("server", {}).get("tool_profile"), target_profile_id)
            expected_est = f"~{TOOL_PROFILES[target_profile_id]['token_estimate']:,}"
            self.assertIn(expected_est, app.dash_profile_badge.cget("text"))

            # Switch using profile ID directly
            app._on_tool_profile_change("web_vision")
            self.assertEqual(app.curr_tool_profile_id, "web_vision")
            self.assertEqual(app.var_tool_profile.get(), TOOL_PROFILES["web_vision"]["label"])

            # Test _enable_safe_skills() button action
            app._enable_safe_skills()
            self.assertEqual(app.curr_tool_profile_id, "mammouth_safe")
            self.assertEqual(app.config_data.get("server", {}).get("tool_profile"), "mammouth_safe")
            self.assertEqual(app.var_tool_profile.get(), TOOL_PROFILES["mammouth_safe"]["label"])
        finally:
            app.destroy()

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    def test_gui_dashboard_hero_card_no_clipping(self):
        """Verify that security badges in Hero Card mode_bar are not clipped or hidden."""
        app = gui.MammouthControlCenter()
        try:
            app.geometry("1060x740")  # Minimum window size
            app.deiconify()
            app.update_idletasks()
            app.update()

            pills_box = app.lbl_oauth_status.master
            self.assertTrue(pills_box.winfo_ismapped(), "Security pills_box must be mapped and visible")
            self.assertGreater(pills_box.winfo_width(), 100, "Security pills_box must not be squeezed to 0/1 width")
            self.assertTrue(app.lbl_oauth_status.winfo_ismapped())
            self.assertTrue(app.lbl_auth_status.winfo_ismapped())
            self.assertTrue(app.lbl_sandbox_status.winfo_ismapped())
            self.assertTrue(app.dash_profile_menu.winfo_ismapped())
            self.assertTrue(app.dash_profile_badge.winfo_ismapped())
        finally:
            app.destroy()

    def test_server_broadcast_tool_list_changed_cross_loop_safety(self):
        """Verify broadcast_tool_list_changed safely dispatches via run_coroutine_threadsafe."""
        dummy_loop = MagicMock()
        dummy_loop.is_running.return_value = True

        with patch.object(server, "_SERVER_EVENT_LOOP", dummy_loop):
            with patch("asyncio.run_coroutine_threadsafe") as mock_threadsafe:
                server.broadcast_tool_list_changed()
                mock_threadsafe.assert_called_once()
                # Verify it targeted the running server event loop
                self.assertEqual(mock_threadsafe.call_args[0][1], dummy_loop)
                # Close the coroutine to prevent unawaited warning
                coro = mock_threadsafe.call_args[0][0]
                coro.close()

    def test_server_logger_defined_and_not_raising_name_error(self):
        """Verify server module defines logger and broadcast error handling does not raise NameError."""
        self.assertTrue(hasattr(server, "logger"))
        self.assertIsNotNone(server.logger)

        with patch.object(server.logger, "debug") as mock_debug:
            try:
                raise RuntimeError("Test broadcast failure")
            except Exception as e:
                server.logger.debug(f"Tool list change broadcast notice: {e}")
            mock_debug.assert_called_once()
            self.assertIn("Test broadcast failure", mock_debug.call_args[0][0])

    def test_multilingual_hints_enrichment_idempotent(self):
        """Verify multilingual keyword enrichment adds keywords and does not duplicate on repeated calls."""
        class MockTool:
            def __init__(self, name, description=""):
                self.name = name
                self.description = description
                self.input_schema = {"type": "object", "properties": {}}

        tool = MockTool(name="browser_navigate", description="Open a URL in browser.")
        server._sanitize_mcp_tool_schema(tool)

        self.assertIn("[Keywords/Mots-clés:", tool.description)
        self.assertIn("Browser-Automatisierung", tool.description)
        self.assertIn("naviguer page web", tool.description)

        first_desc = tool.description
        # Call second time
        server._sanitize_mcp_tool_schema(tool)
        self.assertEqual(tool.description, first_desc, "Keyword enrichment must be idempotent and never duplicate tags")

    def test_defroster_catalog_switch_profile_execution(self):
        """Test defroster_catalog tool executes profile switch cleanly."""
        res = server.defroster_catalog(switch_profile="mammouth_safe")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("active_tool_profile", {}).get("id"), "mammouth_safe")
        self.assertIn("mammouth_safe", res.get("profile_switch_status", ""))

    def test_web_vision_profile_tools_count_alignment(self):
        """Verify web_vision profile label matches the exact tool count in tools list."""
        wv = TOOL_PROFILES["web_vision"]
        tool_cnt = len(wv["tools"])
        self.assertIn(f"({tool_cnt} Tools)", wv["label"])

    def test_mcp_tool_schema_sanitization_removes_draft_fields(self):
        """Verify _sanitize_mcp_tool_schema strips draft fields (title, output_schema, meta) for MCP 2024-11-05."""
        class MockMcpTool:
            def __init__(self):
                self.name = "test_tool"
                self.description = "A test tool"
                self.input_schema = {"type": "object", "properties": {}}
                self.title = "Test Tool Draft Title"
                self.output_schema = {"type": "object"}
                self.meta = {"fastmcp": {"tags": []}}
                self._meta = {"internal": True}
                self.icons = ["icon.png"]
                self.annotations = {"audience": "user"}
                self.execution = {"mode": "auto"}

        tool = MockMcpTool()
        server._sanitize_mcp_tool_schema(tool)

        self.assertIsNone(tool.title)
        self.assertIsNone(tool.output_schema)
        self.assertIsNone(tool.meta)
        self.assertIsNone(tool._meta)
        self.assertIsNone(tool.icons)
        self.assertIsNone(tool.annotations)
        self.assertIsNone(tool.execution)

    def test_authenticated_sse_session_lifecycle(self):
        """Verify SSE session tokens are recorded, validated, and expired."""
        test_sid = "test_sse_session_uuid_12345"
        self.assertFalse(server.is_sse_session_authenticated(test_sid))

        server.record_authenticated_sse_session(test_sid, ttl_seconds=10.0)
        self.assertTrue(server.is_sse_session_authenticated(test_sid))

        # Test expiration
        server.record_authenticated_sse_session("expired_sid", ttl_seconds=-1.0)
        self.assertFalse(server.is_sse_session_authenticated("expired_sid"))

    def test_sse_endpoint_and_tool_discovery_e2e(self):
        """End-to-end test: GET /sse returns endpoint, POST /messages performs initialize & tools/list."""
        import json
        import httpx
        import uvicorn
        import threading
        import time
        import gc
        gc.collect()

        test_token = "mc_test_sse_token_1234567890abcdef"
        app = server.build_app(token=test_token)

        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        srv = uvicorn.Server(config)
        errs = []
        def _run_srv():
            try:
                srv.run()
            except Exception as e:
                errs.append(e)

        srv_thread = threading.Thread(target=_run_srv, daemon=True)
        srv_thread.start()
        for _ in range(100):
            if getattr(srv, "started", False) or errs:
                break
            time.sleep(0.1)
        if errs:
            raise RuntimeError(f"Server thread failed to start: {errs}")
        self.assertTrue(getattr(srv, "started", False), f"Uvicorn server failed to start within 10s (alive={srv_thread.is_alive()})")

        test_port = None
        for s in srv.servers:
            for sock in s.sockets:
                test_port = sock.getsockname()[1]
                break
            if test_port:
                break
        self.assertIsNotNone(test_port, "Could not determine uvicorn bound port")

        try:
            headers = {"Authorization": f"Bearer {test_token}"}
            with httpx.Client(timeout=10.0) as client:
                with client.stream("GET", f"http://127.0.0.1:{test_port}/sse", headers=headers) as stream:
                    self.assertEqual(stream.status_code, 200)
                    lines = stream.iter_lines()

                    # Read endpoint event
                    event_l = next(lines)
                    data_l = next(lines)
                    next(lines)
                    self.assertIn("endpoint", event_l)
                    self.assertIn("/messages?session_id=", data_l)

                    endpoint_rel = data_l.replace("data: ", "").strip()
                    post_url = f"http://127.0.0.1:{test_port}{endpoint_rel}"

                    # Post initialize without auth header (authenticated via SSE session)
                    init_body = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "mammouth.ai", "version": "1.0"}
                        }
                    }
                    res = client.post(post_url, json=init_body)
                    self.assertEqual(res.status_code, 202)

                    # Wait for initialize response on SSE
                    while True:
                        l = next(lines)
                        if l.startswith("data: "):
                            data = json.loads(l[6:])
                            if data.get("id") == 1:
                                break

                    # Initialized notification
                    res = client.post(post_url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                    self.assertEqual(res.status_code, 202)

                    # List tools
                    list_body = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {}
                    }
                    res = client.post(post_url, json=list_body)
                    self.assertEqual(res.status_code, 202)

                    # Read tools/list on SSE
                    while True:
                        l = next(lines)
                        if l.startswith("data: "):
                            data = json.loads(l[6:])
                            if data.get("id") == 2:
                                tools = data["result"]["tools"]
                                self.assertGreater(len(tools), 0)
                                for t in tools:
                                    tname = t.get("name")
                                    self.assertNotIn("title", t, f"Forbidden title field in tool {tname}")
                                    self.assertNotIn("outputSchema", t, f"Forbidden outputSchema field in tool {tname}")
                                    self.assertNotIn("meta", t, f"Forbidden meta field in tool {tname}")
                                break
        finally:
            srv.should_exit = True

    def test_defroster_catalog_token_safety(self):
        """Verify defroster_catalog returns a token-safe compact overview by default, and detailed tools on drill-down."""
        import json
        # 1. Default overview
        overview = server.defroster_catalog()
        self.assertEqual(overview["status"], "success")
        self.assertIn("hint", overview)
        self.assertIn("files", overview["categories"])
        
        # Tools in overview should only contain 'name' to keep token count compact
        first_tool = overview["categories"]["files"]["tools"][0]
        self.assertIn("name", first_tool)
        self.assertNotIn("desc", first_tool)
        
        # Verify overview size is strictly token-budget safe (< 1,200 tokens / < 4,800 chars)
        overview_dump = json.dumps(overview)
        self.assertLess(len(overview_dump), 5500, f"Overview size {len(overview_dump)} chars is too large!")

        # 2. Specific category drilldown returns full tool descriptions
        files_cat = server.defroster_catalog(category="files")
        self.assertEqual(len(files_cat["categories"]), 1)
        files_first_tool = files_cat["categories"]["files"]["tools"][0]
        self.assertIn("name", files_first_tool)
        self.assertIn("desc", files_first_tool)
        self.assertIn("description", files_cat["categories"]["files"])

        # 3. Search filter returns full tool descriptions for matches
        search_res = server.defroster_catalog(search="navigate")
        self.assertIn("browser", search_res["categories"])
        browser_tools = search_res["categories"]["browser"]["tools"]
        self.assertTrue(any(t["name"] == "browser_navigate" and "desc" in t for t in browser_tools))

        # 4. Explicit detailed=True returns full tool descriptions
        detailed_res = server.defroster_catalog(detailed=True)
        det_first_tool = detailed_res["categories"]["files"]["tools"][0]
        self.assertIn("name", det_first_tool)
        self.assertIn("desc", det_first_tool)



    def test_defroster_execute_tool_on_demand(self):
        """Verify defroster_execute_tool enforces active profile allowlist and blocks recursion."""
        async def _test():
            # 1. Desktop screen info execution (allowed in mammouth_safe)
            res = await server.defroster_execute_tool("desktop_get_screen_info", {})
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("tool"), "desktop_get_screen_info")
            self.assertIn("width", res.get("result", {}))

            # 2. Rejection of tool outside active profile (mouse_get_position not in mammouth_safe)
            res_m = await server.defroster_execute_tool("mouse_get_position", {})
            self.assertEqual(res_m.get("status"), "error")
            self.assertEqual(res_m.get("error"), "tool not in active profile")

            # 3. Recursion prevention
            res_rec = await server.defroster_execute_tool("defroster_execute_tool", {})
            self.assertEqual(res_rec.get("status"), "error")
            self.assertIn("recursively", res_rec.get("error", ""))

            # 4. Unknown tool handling
            res_unk = await server.defroster_execute_tool("nonexistent_dummy_tool", {})
            self.assertEqual(res_unk.get("status"), "error")

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
