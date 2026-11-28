"""Unit and integration tests for Mammouth Defroster 9000 v0.8.1 Claude WebApp Integration & Environment Parity:
- Parallel Claude Web, ChatGPT Web & Mammouth AI Web tabs in Cockpit GUI
- Embedded browser origins, brand detection, and TipTap/ProseMirror prompt injection for claude.ai
- Task scheduler 'claude_web' target & default_chat_tab='claude' auto-resolution
- Claude OAuth 2.1 DCR (none & client_secret_post), PKCE S256, and live streamlined 42-tool discovery
- Version alignment to v0.8.1 & frozen v0.8.0 archive preservation
"""

import base64
import copy
import hashlib
import json
import re
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import config
import gui
import server
from modules.embedded_browser import (
    MammouthBrowserFrame,
    _is_trusted_browser_origin,
    _is_trusted_web_origin,
)
from modules.task_scheduler import (
    VALID_TARGETS,
    TaskSchedulerEngine,
    scheduler_create_task,
    scheduler_delete_task,
)


class TestClaudeWebAppIntegrationV081(unittest.TestCase):
    """Comprehensive tests for v0.8.1 Claude WebApp embedding and OAuth connector onboarding."""

    def test_version_alignment_v081(self):
        """Verify version strings across gui, server, pyproject, build script, and README match current version."""
        self.assertEqual(gui.APP_VERSION, "v0.9.0")
        self.assertIn("v0.9.0", server.mcp.instructions or "")

        pyproject = (SRC_DIR / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.9.0"', pyproject)

        build_bat = (SRC_DIR / "build.bat").read_text(encoding="utf-8")
        self.assertIn("MammouthDefroster9000-v0.9.0-windows-x64.zip", build_bat)
        self.assertIn("MammouthDefroster9000-v0.9.0", build_bat)
        self.assertNotIn("MammouthDefroster9000-v0.8.0", build_bat)

    def test_config_defaults_include_claude_browser(self):
        """Verify config.py and config.example.json include claude_browser defaults and origins."""
        cl = config.DEFAULT_CONFIG["claude_browser"]
        self.assertTrue(cl["enabled"])
        self.assertEqual(cl["start_page"], "https://claude.ai")
        self.assertEqual(cl["user_data_dir"], "./data/claude_browser_profile")
        self.assertIn("claude_browser", config._MERGED_SECTIONS)

        origins = config.DEFAULT_CONFIG["server"]["allowed_origins"]
        for expected in ("https://claude.ai", "https://claude.com", "https://www.claude.com"):
            self.assertIn(expected, origins)

        ex_data = json.loads((SRC_DIR / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("claude_browser", ex_data)
        self.assertEqual(ex_data["claude_browser"]["start_page"], "https://claude.ai")

    def test_embedded_browser_claude_origins_brand_and_dom_injection(self):
        """Verify embedded browser trusts claude origins, detects brand, and injects TipTap ProseMirror selectors."""
        self.assertTrue(_is_trusted_browser_origin("https://claude.ai/new"))
        self.assertTrue(_is_trusted_browser_origin("https://claude.com/login"))
        self.assertTrue(_is_trusted_browser_origin("https://console.anthropic.com"))
        self.assertFalse(_is_trusted_browser_origin("https://claude.ai.attacker.example"))

        self.assertTrue(_is_trusted_web_origin("https://claude.ai/chat/123", "https://claude.ai"))
        self.assertFalse(_is_trusted_web_origin("https://evil.com", "https://claude.ai"))

        # Verify brand auto-detection via constructor without live Tk / WebView2 runtime
        import customtkinter as ctk
        with patch.object(ctk.CTkFrame, "__init__", lambda self, *a, **kw: None), \
             patch.object(MammouthBrowserFrame, "_build_ui", lambda self: None), \
             patch.object(MammouthBrowserFrame, "_schedule_ui_queue_poll", lambda self: None):
            dummy_frame = MammouthBrowserFrame(master=MagicMock(), start_url="https://claude.ai")
            self.assertEqual(dummy_frame.brand_name, "Claude")

        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.hwnd = 12345
        frame.is_embedded = True
        frame.brand_name = "Claude"
        frame.start_url = "https://claude.ai"
        frame.winfo_toplevel = MagicMock()
        frame.winfo_toplevel.return_value.winfo_id.return_value = 999
        frame.edge = MagicMock()
        frame.edge.webview.CoreWebView2 = MagicMock()

        scheduled = []

        def fake_after(ms, fn):
            scheduled.append((ms, fn))
            return "aid"

        frame.after = fake_after

        with patch("modules.embedded_browser.HAS_WEBVIEW2", True), \
             patch("modules.embedded_browser.user32"):
            ok = frame.send_chat_prompt("Hello Claude!", auto_submit=True, delay_ms=100)
            self.assertTrue(ok)
            self.assertEqual(len(scheduled), 1)
            scheduled[0][1]()
            frame.edge.webview.CoreWebView2.ExecuteScriptAsync.assert_called_once()
            js_code = frame.edge.webview.CoreWebView2.ExecuteScriptAsync.call_args[0][0]
            self.assertIn('[data-testid="chat-input"]', js_code)
            self.assertIn('button[aria-label="Send message"]', js_code)

    def test_task_scheduler_supports_claude_web_and_auto_resolution(self):
        """Verify scheduler VALID_TARGETS and task_schedule_create(target='auto') support claude_web."""
        self.assertIn("claude_web", VALID_TARGETS)
        import modules.task_scheduler as ts

        tmp_db = SRC_DIR / "tests" / "_tmp_claude_tasks.db"
        with patch.object(ts, "DB_PATH", tmp_db):
            try:
                cfg_cl = {"embedded_browser": {"default_chat_tab": "claude"}, "modules": {}}
                with patch("server.load_config", return_value=cfg_cl):
                    t = server.task_schedule_create(
                        name="Claude Auto Check",
                        prompt="Summarize git status",
                        interval_minutes=5,
                    )
                    self.assertEqual(t["target"], "claude_web")
                    scheduler_delete_task(t["id"])

                t_direct = scheduler_create_task(
                    name="Claude Direct",
                    prompt="Ping",
                    interval_seconds=300,
                    repeat_count=1,
                    target="claude_web",
                )
                self.assertEqual(t_direct["target"], "claude_web")
                scheduler_delete_task(t_direct["id"])
            finally:
                if tmp_db.exists():
                    tmp_db.unlink()

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    @patch.object(MammouthBrowserFrame, "ensure_initialized", lambda self: None)
    def test_gui_parallel_claude_tab_switching_trigger_and_settings(self):
        """Verify Cockpit initializes Claude Web tab, switching, scheduler trigger, URL copy, and settings save."""
        app = gui.MammouthControlCenter()
        try:
            self.assertTrue(hasattr(app, "tab_claude"))
            self.assertTrue(hasattr(app, "claude_browser"))
            self.assertTrue(hasattr(app, "btn_open_claude"))
            self.assertEqual(app.claude_browser.start_url, "https://claude.ai")
            self.assertEqual(app.claude_browser.brand_name, "Claude")

            engine = TaskSchedulerEngine.get_instance()
            self.assertIn("claude_web", engine._handlers)

            app._switch_to_claude_tab()
            self.assertEqual(app._get_active_chat_tab_key(), "🟠 Claude Web")
            self.assertIs(app._get_active_chat_browser(), app.claude_browser)

            res = app._on_trigger_claude_web_task({
                "name": "Claude Scheduled Ping",
                "prompt": "Hello from scheduler",
                "runs_done": 0,
                "switch_tab": True,
                "auto_submit": True,
            })
            self.assertEqual(res, "Dispatched to Claude Web")

            # Verify Settings exposes Claude Web default option & custom URL
            app.opt_default_chat_tab.set("Claude Web")
            app.entry_claude_start_url.delete(0, "end")
            app.entry_claude_start_url.insert(0, "https://claude.ai/projects")
            with patch("gui.save_config"), patch("tkinter.messagebox.showinfo"):
                app._save_settings()
            self.assertEqual(app.config_data["embedded_browser"]["default_chat_tab"], "claude")
            self.assertEqual(app.active_chat_tab_key, "🟠 Claude Web")
            self.assertEqual(app.config_data["claude_browser"]["start_page"], "https://claude.ai/projects")

            # Verify _copy_claude_connector_url uses live dynamic tunnel URL
            app.dynamic_tunnel_url = "https://claude-live.trycloudflare.com/sse"
            with patch("tkinter.messagebox.showinfo") as mock_info:
                app._copy_claude_connector_url()
                clip = app.clipboard_get()
                self.assertEqual(clip, "https://claude-live.trycloudflare.com/mcp")
                mock_info.assert_called_once()
                msg_body = mock_info.call_args[0][1]
                self.assertIn("Connectors", msg_body)
                self.assertIn("Bearer API Key", msg_body)
        finally:
            app.destroy()

    def test_claude_oauth_with_dynamic_tunnel_streamlined_tools_e2e(self):
        """End-to-end Claude.ai DCR + PKCE S256 OAuth + streamlined 42-tool discovery check."""
        real_cfg = server.load_config()
        all_cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        for mod_data in all_cfg.get("modules", {}).values():
            mod_data["enabled"] = True
        all_cfg.setdefault("server", {})["tool_profile"] = "all"
        all_cfg["server"]["api_token"] = real_cfg.get("server", {}).get("api_token") or "mc_test_cl81_token_abcdef"

        with patch("server.load_config", return_value=all_cfg):
            server.register_active_tools()

        with patch("server.load_config", return_value=all_cfg), \
             TestClient(server.app) as client:
            r_reg = client.post(
                "/oauth/register",
                json={
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    "token_endpoint_auth_method": "none",
                },
            )
            self.assertEqual(r_reg.status_code, 201)
            reg_data = r_reg.json()
            self.assertEqual(reg_data["client_name"], "Claude")
            cid = reg_data["client_id"]

            verifier = "claude_v081_pkce_verifier_secret_string_123456"
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).decode("ascii").rstrip("=")

            redir = urllib.parse.quote("https://claude.ai/api/mcp/auth_callback", safe="")
            r_get = client.get(
                f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri={redir}"
                f"&state=cl81&code_challenge={challenge}&code_challenge_method=S256"
            )
            self.assertEqual(r_get.status_code, 200)
            self.assertIn("Anthropic Claude wants to connect", r_get.text)
            m = re.search(r'name="csrf_token" value="([^"]+)"', r_get.text)
            self.assertIsNotNone(m)

            tok = all_cfg["server"]["api_token"] or server.load_config()["server"]["api_token"]
            r_post = client.post(
                "/oauth/authorize",
                data={"action": "allow", "csrf_token": m.group(1), "owner_token": tok},
                follow_redirects=False,
            )
            self.assertEqual(r_post.status_code, 302)
            loc = r_post.headers["location"]
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            code = qs["code"][0]

            r_tok = client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                    "client_id": cid,
                    "code_verifier": verifier,
                },
            )
            self.assertEqual(r_tok.status_code, 200)
            at = r_tok.json()["access_token"]

            r_tools = client.post(
                "/mcp",
                headers={"Authorization": f"Bearer {at}"},
                json={"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}},
            )
            self.assertEqual(r_tools.status_code, 200)
            tool_names = [t["name"] for t in r_tools.json()["result"]["tools"]]
            self.assertEqual(len(tool_names), 42)
            self.assertIn("claude_code", tool_names)


if __name__ == "__main__":
    unittest.main()
