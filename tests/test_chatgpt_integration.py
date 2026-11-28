"""Unit and integration tests for Mammouth Defroster 9000 v0.8.0 ChatGPT Integration:
- Parallel ChatGPT Web & Mammouth AI Web tabs in Cockpit GUI
- ChatGPT OAuth 2.1, DCR, PKCE S256, CORS, and anti-clickjacking CSP
- Embedded browser origin validation, brand detection, and ProseMirror prompt injection
- Automated task scheduler 'chatgpt_web' target
- Version alignment to v0.8.0
"""

import asyncio
import base64
import hashlib
import json
import re
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.requests import Request
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


class TestChatGPTIntegrationV080(unittest.TestCase):
    """Comprehensive tests for v0.8.0 ChatGPT integration and parallel chat tabs."""

    def test_version_alignment_v080(self):
        """Verify version strings are aligned across project files."""
        self.assertEqual(gui.APP_VERSION, "v0.9.0")
        self.assertIn("v0.9.0", server.mcp.instructions or "")

        pyproject = (SRC_DIR / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.9.0"', pyproject)

        build_bat = (SRC_DIR / "build.bat").read_text(encoding="utf-8")
        self.assertIn("MammouthDefroster9000-v0.9.0-windows-x64.zip", build_bat)

    def test_config_defaults_include_chatgpt(self):
        """Verify DEFAULT_CONFIG defines chatgpt_browser, default_chat_tab, and ChatGPT CORS origins."""
        eb = config.DEFAULT_CONFIG["embedded_browser"]
        self.assertEqual(eb["start_page"], "https://mammouth.ai")
        self.assertEqual(eb["default_chat_tab"], "chatgpt")

        cg = config.DEFAULT_CONFIG["chatgpt_browser"]
        self.assertTrue(cg["enabled"])
        self.assertEqual(cg["start_page"], "https://chatgpt.com")
        self.assertEqual(cg["user_data_dir"], "./data/chatgpt_browser_profile")

        origins = config.DEFAULT_CONFIG["server"]["allowed_origins"]
        self.assertIn("https://chatgpt.com", origins)
        self.assertIn("https://chat.openai.com", origins)
        self.assertIn("https://platform.openai.com", origins)
        self.assertIn("https://openai.com", origins)

    def test_trusted_oauth_redirect_uris_for_chatgpt(self):
        """Verify ChatGPT / OpenAI OAuth redirect URIs are trusted and spoofed domains rejected."""
        self.assertTrue(server._is_trusted_oauth_redirect_uri("https://chatgpt.com/connector_platform_oauth_redirect"))
        self.assertTrue(server._is_trusted_oauth_redirect_uri("https://chat.openai.com/oauth/callback"))
        self.assertTrue(server._is_trusted_oauth_redirect_uri("https://platform.openai.com/apps/callback"))
        self.assertTrue(server._is_trusted_oauth_redirect_uri("https://auth.openai.com/callback"))

        # Insecure HTTP or spoofed hosts must fail closed
        self.assertFalse(server._is_trusted_oauth_redirect_uri("http://chatgpt.com/connector_platform_oauth_redirect"))
        self.assertFalse(server._is_trusted_oauth_redirect_uri("https://notchatgpt.com/connector_platform_oauth_redirect"))
        self.assertFalse(server._is_trusted_oauth_redirect_uri("https://chatgpt.com.evil.com/callback"))

    def test_cors_and_csp_headers_for_chatgpt(self):
        """Verify OPTIONS preflight, 401 CORS reflection, and OAuth CSP frame-ancestors for ChatGPT."""
        with TestClient(server.app) as client:
            for origin in ("https://chatgpt.com", "https://chat.openai.com", "https://platform.openai.com"):
                opt = client.options("/mcp", headers={"Origin": origin})
                self.assertEqual(opt.status_code, 200)
                self.assertEqual(opt.headers.get("access-control-allow-origin"), origin)
                self.assertEqual(opt.headers.get("access-control-allow-credentials"), "true")

                # Unauthenticated POST /mcp must still return CORS + WWW-Authenticate on 401
                unauth = client.post("/mcp", headers={"Origin": origin})
                self.assertEqual(unauth.status_code, 401)
                self.assertEqual(unauth.headers.get("access-control-allow-origin"), origin)
                self.assertIn("www-authenticate", unauth.headers)

            # Spoofed ChatGPT origin must NOT be reflected
            bad_opt = client.options("/mcp", headers={"Origin": "https://chatgpt.com.attacker.example"})
            self.assertEqual(bad_opt.status_code, 200)
            self.assertNotIn("access-control-allow-origin", bad_opt.headers)

            # OAuth consent page CSP allows ChatGPT framing
            auth_resp = client.get(
                "/oauth/authorize?response_type=code&client_id=chatgpt_test"
                "&redirect_uri=https://chatgpt.com/connector_platform_oauth_redirect"
                "&state=st1&code_challenge=abc123&code_challenge_method=S256"
            )
            self.assertEqual(auth_resp.status_code, 200)
            csp = auth_resp.headers.get("content-security-policy", "")
            self.assertIn("https://chatgpt.com", csp)
            self.assertIn("https://openai.com", csp)
            self.assertIn("OpenAI ChatGPT wants to connect", auth_resp.text)

    def test_full_chatgpt_oauth_and_mcp_e2e_flow(self):
        """End-to-end OAuth 2.1 + PKCE S256 + MCP initialize/tools/list flow for ChatGPT."""
        with TestClient(server.app) as client:
            # 0. Verify RFC 8414 / RFC 9728 metadata fields required by ChatGPT
            r_meta = client.get("/.well-known/oauth-authorization-server")
            self.assertEqual(r_meta.status_code, 200)
            meta = r_meta.json()
            self.assertTrue(meta.get("authorization_response_iss_parameter_supported"))
            self.assertTrue(meta.get("client_id_metadata_document_supported"))
            self.assertIn("openid", meta.get("scopes_supported", []))
            self.assertIn("offline_access", meta.get("scopes_supported", []))

            # 1. Dynamic Client Registration
            r = client.post(
                "/oauth/register",
                json={
                    "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
                    "token_endpoint_auth_method": "none",
                },
            )
            self.assertEqual(r.status_code, 201)
            reg = r.json()
            self.assertEqual(reg["client_name"], "ChatGPT")
            cid = reg["client_id"]

            # 2. Authorize GET (consent page)
            verifier = "chatgpt_pkce_verifier_string_0123456789_xyz"
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
            redir = urllib.parse.quote("https://chatgpt.com/connector_platform_oauth_redirect", safe="")
            r = client.get(
                f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri={redir}"
                f"&state=cg_state_99&code_challenge={challenge}&code_challenge_method=S256"
            )
            self.assertEqual(r.status_code, 200)
            m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
            self.assertIsNotNone(m)
            csrf_token = m.group(1)

            # 3. Authorize POST
            tok = server.load_config()["server"]["api_token"]
            r = client.post(
                "/oauth/authorize",
                data={"action": "allow", "csrf_token": csrf_token, "owner_token": tok},
                follow_redirects=False,
            )
            self.assertEqual(r.status_code, 302)
            loc = r.headers["location"]
            self.assertTrue(loc.startswith("https://chatgpt.com/connector_platform_oauth_redirect"))
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            self.assertEqual(qs["state"][0], "cg_state_99")
            self.assertEqual(qs["iss"][0], meta["issuer"])
            code = qs["code"][0]

            # 4. Token Exchange
            r = client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://chatgpt.com/connector_platform_oauth_redirect",
                    "client_id": cid,
                    "code_verifier": verifier,
                },
            )
            self.assertEqual(r.status_code, 200)
            at = r.json()["access_token"]

            # 5. MCP Initialize & Tools List
            r = client.post(
                "/mcp",
                headers={"Authorization": f"Bearer {at}"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ChatGPT", "version": "1.0"},
                    },
                },
            )
            self.assertEqual(r.status_code, 200)

            r = client.post(
                "/mcp",
                headers={"Authorization": f"Bearer {at}"},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            self.assertEqual(r.status_code, 200)
            tools = r.json().get("result", {}).get("tools", [])
            self.assertGreater(len(tools), 0)

    def test_embedded_browser_chatgpt_origins_and_dom_injection(self):
        """Verify embedded browser trusts ChatGPT origins and injects into ProseMirror #prompt-textarea."""
        self.assertTrue(_is_trusted_browser_origin("https://chatgpt.com/c/123"))
        self.assertTrue(_is_trusted_browser_origin("https://chat.openai.com"))
        self.assertTrue(_is_trusted_browser_origin("https://files.oaiusercontent.com/file.png"))
        self.assertFalse(_is_trusted_browser_origin("https://chatgpt.com.evil.com"))

        self.assertTrue(_is_trusted_web_origin("https://chatgpt.com/c/abc", "https://chatgpt.com"))
        self.assertFalse(_is_trusted_web_origin("https://evil.com", "https://chatgpt.com"))

        # Verify send_chat_prompt schedules JS containing ChatGPT selectors
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.hwnd = 12345
        frame.is_embedded = True
        frame.brand_name = "ChatGPT"
        frame.start_url = "https://chatgpt.com"
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
            ok = frame.send_chat_prompt("Hello ChatGPT!", auto_submit=True, delay_ms=100)
            self.assertTrue(ok)
            self.assertEqual(len(scheduled), 1)
            # Execute the scheduled UI callback
            scheduled[0][1]()
            frame.edge.webview.CoreWebView2.ExecuteScriptAsync.assert_called_once()
            js_code = frame.edge.webview.CoreWebView2.ExecuteScriptAsync.call_args[0][0]
            self.assertIn("#prompt-textarea", js_code)
            self.assertIn('button[data-testid="send-button"]', js_code)

    def test_task_scheduler_supports_chatgpt_web_target(self):
        """Verify task scheduler accepts and persists target='chatgpt_web'."""
        self.assertIn("chatgpt_web", VALID_TARGETS)
        import modules.task_scheduler as ts

        with patch.object(ts, "DB_PATH", SRC_DIR / "tests" / "_tmp_chatgpt_tasks.db"):
            try:
                t = scheduler_create_task(
                    name="ChatGPT Daily Check",
                    prompt="Check workspace status",
                    interval_seconds=300,
                    repeat_count=1,
                    target="chatgpt_web",
                )
                self.assertEqual(t["target"], "chatgpt_web")
                scheduler_delete_task(t["id"])
            finally:
                db_p = SRC_DIR / "tests" / "_tmp_chatgpt_tasks.db"
                if db_p.exists():
                    db_p.unlink()

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    @patch.object(MammouthBrowserFrame, "ensure_initialized", lambda self: None)
    def test_gui_parallel_chatgpt_and_mammouth_tabs(self):
        """Verify Cockpit initializes both ChatGPT Web and Mammouth AI Web tabs and supports all triggers."""
        app = gui.MammouthControlCenter()
        try:
            self.assertTrue(hasattr(app, "tab_chatgpt"))
            self.assertTrue(hasattr(app, "tab_mammouth"))
            self.assertTrue(hasattr(app, "chatgpt_browser"))
            self.assertTrue(hasattr(app, "mammouth_browser"))
            self.assertEqual(app.chatgpt_browser.start_url, "https://chatgpt.com")
            self.assertEqual(app.chatgpt_browser.brand_name, "ChatGPT")
            self.assertEqual(app.mammouth_browser.start_url, "https://mammouth.ai")
            self.assertEqual(app.mammouth_browser.brand_name, "Mammouth.ai")

            # Verify scheduler handler registration for chatgpt_web
            engine = TaskSchedulerEngine.get_instance()
            self.assertIn("chatgpt_web", engine._handlers)
            self.assertIn("mammouth_web", engine._handlers)

            # Verify tab switching updates active_chat_tab_key
            app._switch_to_mammouth_tab()
            self.assertEqual(app._get_active_chat_tab_key(), "💬 Mammouth AI Web")
            self.assertIs(app._get_active_chat_browser(), app.mammouth_browser)

            app._switch_to_chatgpt_tab()
            self.assertEqual(app._get_active_chat_tab_key(), "🤖 ChatGPT Web")
            self.assertIs(app._get_active_chat_browser(), app.chatgpt_browser)

            # Verify _on_trigger_chatgpt_web_task dispatches cleanly
            res = app._on_trigger_chatgpt_web_task({
                "name": "Test ChatGPT Task",
                "prompt": "Ping",
                "runs_done": 0,
                "switch_tab": True,
                "auto_submit": True,
            })
            self.assertEqual(res, "Dispatched to ChatGPT Web")

            # Verify _copy_chatgpt_connector_url copies /mcp URL
            with patch("tkinter.messagebox.showinfo") as mock_info, \
                 patch("modules.claude_code.resolve_public_tunnel_url", return_value="https://demo.ts.net/mcp"):
                app._copy_chatgpt_connector_url()
                clip = app.clipboard_get()
                self.assertEqual(clip, "https://demo.ts.net/mcp")
                mock_info.assert_called_once()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
