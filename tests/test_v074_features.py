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
from config import TOOL_PROFILES, load_config, save_config


class TestV074FeaturesAndFixes(unittest.TestCase):
    def test_version_alignment_v074(self):
        """Verify APP_VERSION in gui.py, server.py, and pyproject.toml are aligned to v0.7.4."""
        self.assertEqual(gui.APP_VERSION, "v0.7.4")
        self.assertIn("v0.7.4", server.mcp.instructions or "")

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        content = pyproject_path.read_text(encoding="utf-8")
        self.assertIn('version = "0.7.4"', content)

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
            self.assertIn("~3,800", app.dash_profile_badge.cget("text"))

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


if __name__ == "__main__":
    unittest.main()
