"""Unit and integration tests for Defrostr (v0.9.0) Google Gemini WebApp Integration,
Rebrand, Security Tab Consolidation & Provider Visibility Controls:
- Isolated English (en-US) WebView2 profile & DevMode landing URL (?hl=en)
- Parallel ✨ Gemini Web tab, toolbar DevMode shortcut, URL copy guidance, and Settings persistence
- Exact-host Google OAuth 2.1 callback validation (oauth-redirect*.googleusercontent.com, vertexaisearch.cloud.google.com, gemini.google.com)
- Strict rejection of arbitrary *.googleusercontent.com subdomains & spoofed origins
- End-to-end Gemini DCR + PKCE S256 + MCP initialize/tools/list flow
- Quill editor DOM injection and task scheduler 'gemini_web' resolution
- Defrostr rebrand + tagline, consolidated 🛡️ Security tab, and selectable provider tabs
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

import config  # noqa: E402
import gui  # noqa: E402
import server  # noqa: E402
from modules.embedded_browser import (  # noqa: E402
    MammouthBrowserFrame,
    _create_edge_chrome,
    _is_trusted_browser_origin,
)
from modules.task_scheduler import (  # noqa: E402
    VALID_TARGETS,
    TaskSchedulerEngine,
    scheduler_create_task,
    scheduler_delete_task,
)


class TestGeminiWebAppIntegrationV090(unittest.TestCase):
    """Comprehensive tests for v0.9.0 Gemini WebApp embedding, English profile, and OAuth connector support."""

    def test_version_alignment_v090(self):
        """Verify version strings across gui, server, pyproject, build.bat, CHANGELOG, and README match v0.9.0."""
        self.assertEqual(gui.APP_VERSION, "v0.9.0")
        self.assertIn("v0.9.0", server.mcp.instructions or "")

        pyproject = (SRC_DIR / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.9.0"', pyproject)

        build_bat = (SRC_DIR / "build.bat").read_text(encoding="utf-8")
        self.assertIn("MammouthDefroster9000-v0.9.0-windows-x64.zip", build_bat)
        self.assertIn("MammouthDefroster9000-v0.9.0", build_bat)

        changelog = (SRC_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertLess(changelog.index("## [0.9.0]"), changelog.index("## [0.8.2]"))

    def test_config_defaults_include_gemini_english_profile(self):
        """Verify config.py and config.example.json define gemini_browser with en-US profile and DevMode ?hl=en URL."""
        gm = config.DEFAULT_CONFIG["gemini_browser"]
        self.assertTrue(gm["enabled"])
        self.assertEqual(gm["start_page"], "https://gemini.google.com/devmode?hl=en")
        self.assertEqual(gm["language"], "en-US")
        self.assertEqual(gm["user_data_dir"], "./data/gemini_browser_profile")
        self.assertIn("gemini_browser", config._MERGED_SECTIONS)

        origins = config.DEFAULT_CONFIG["server"]["allowed_origins"]
        for expected in (
            "https://gemini.google.com",
            "https://oauth-redirect.googleusercontent.com",
            "https://oauth-redirect-sandbox.googleusercontent.com",
            "https://oauth-redirect-test.googleusercontent.com",
            "https://vertexaisearch.cloud.google.com",
        ):
            self.assertIn(expected, origins)

        ex_data = json.loads((SRC_DIR / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("gemini_browser", ex_data)
        self.assertEqual(ex_data["gemini_browser"]["start_page"], "https://gemini.google.com/devmode?hl=en")
        self.assertEqual(ex_data["gemini_browser"]["language"], "en-US")

    def test_trusted_oauth_redirect_and_cors_for_gemini_reject_wildcards(self):
        """Verify exact Google Gemini OAuth callbacks are trusted while arbitrary googleusercontent.com hosts fail closed."""
        valid_uris = (
            "https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-123",
            "https://oauth-redirect-sandbox.googleusercontent.com/r/abc",
            "https://oauth-redirect-test.googleusercontent.com/r/xyz",
            "https://vertexaisearch.cloud.google.com/oauth-redirect",
            "https://gemini.google.com/callback",
        )
        for uri in valid_uris:
            with self.subTest(valid_uri=uri):
                self.assertTrue(server._is_trusted_oauth_redirect_uri(uri))

        invalid_uris = (
            "http://oauth-redirect.googleusercontent.com/r/123",
            "https://evil.googleusercontent.com/r/123",
            "https://colab.googleusercontent.com/callback",
            "https://oauth-redirect.googleusercontent.com.attacker.example/r/123",
            "https://gemini.google.com.attacker.example/callback",
        )
        for uri in invalid_uris:
            with self.subTest(invalid_uri=uri):
                self.assertFalse(server._is_trusted_oauth_redirect_uri(uri))

        self.assertTrue(server.is_allowed_origin("https://gemini.google.com"))
        self.assertTrue(server.is_allowed_origin("https://oauth-redirect.googleusercontent.com"))
        self.assertFalse(server.is_allowed_origin("https://evil.googleusercontent.com"))
        self.assertFalse(server.is_allowed_origin("https://evil.gemini.google.com"))

    def test_gemini_oauth_dcr_pkce_csp_and_mcp_e2e(self):
        """End-to-end Gemini Developer Mode DCR + PKCE S256 + CSP + MCP initialize/tools/list check."""
        real_cfg = server.load_config()
        all_cfg = copy.deepcopy(config.DEFAULT_CONFIG)
        for mod_data in all_cfg.get("modules", {}).values():
            mod_data["enabled"] = True
        all_cfg.setdefault("server", {})["tool_profile"] = "all"
        all_cfg["server"]["api_token"] = real_cfg.get("server", {}).get("api_token") or "mc_test_gm90_token_abcdef"

        with patch("server.load_config", return_value=all_cfg):
            server.register_active_tools()

        redir_uri = "https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-test"
        with patch("server.load_config", return_value=all_cfg), \
             TestClient(server.app) as client:
            r_reg = client.post(
                "/oauth/register",
                json={
                    "redirect_uris": [redir_uri],
                    "token_endpoint_auth_method": "none",
                },
            )
            self.assertEqual(r_reg.status_code, 201)
            reg_data = r_reg.json()
            self.assertEqual(reg_data["client_name"], "Gemini")
            cid = reg_data["client_id"]

            verifier = "gemini_v090_pkce_verifier_secret_string_123456"
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).decode("ascii").rstrip("=")

            redir_q = urllib.parse.quote(redir_uri, safe="")
            r_get = client.get(
                f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri={redir_q}"
                f"&state=gm90&code_challenge={challenge}&code_challenge_method=S256"
            )
            self.assertEqual(r_get.status_code, 200)
            self.assertIn("Google Gemini wants to connect", r_get.text)
            csp = r_get.headers.get("content-security-policy", "")
            self.assertIn("https://gemini.google.com", csp)
            self.assertIn("https://oauth-redirect.googleusercontent.com", csp)
            self.assertIn("https://vertexaisearch.cloud.google.com", csp)

            m = re.search(r'name="csrf_token" value="([^"]+)"', r_get.text)
            self.assertIsNotNone(m)

            tok = all_cfg["server"]["api_token"]
            r_post = client.post(
                "/oauth/authorize",
                data={"action": "allow", "csrf_token": m.group(1), "owner_token": tok},
                follow_redirects=False,
            )
            self.assertEqual(r_post.status_code, 302)
            loc = r_post.headers["location"]
            self.assertTrue(loc.startswith(redir_uri))
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            code = qs["code"][0]

            r_tok = client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redir_uri,
                    "client_id": cid,
                    "code_verifier": verifier,
                },
            )
            self.assertEqual(r_tok.status_code, 200)
            at = r_tok.json()["access_token"]

            r_list = client.post(
                "/mcp",
                headers={"Authorization": f"Bearer {at}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            self.assertEqual(r_list.status_code, 200)
            self.assertGreater(len(r_list.json().get("result", {}).get("tools", [])), 0)

    def test_embedded_browser_gemini_language_origins_and_dom_injection(self):
        """Verify Gemini origins, brand detection, WebView2 en-US Language hook, and Quill prompt injection."""
        self.assertTrue(_is_trusted_browser_origin("https://gemini.google.com/devmode?hl=en"))
        self.assertTrue(_is_trusted_browser_origin("https://accounts.google.com/o/oauth2/v2/auth"))
        self.assertTrue(_is_trusted_browser_origin("https://oauth-redirect.googleusercontent.com/r/abc"))
        self.assertFalse(_is_trusted_browser_origin("https://evil.googleusercontent.com/r/abc"))
        self.assertFalse(_is_trusted_browser_origin("https://gemini.google.com.evil.example"))

        import customtkinter as ctk
        with patch.object(ctk.CTkFrame, "__init__", lambda self, *a, **kw: None), \
             patch.object(MammouthBrowserFrame, "_build_ui", lambda self: None), \
             patch.object(MammouthBrowserFrame, "_schedule_ui_queue_poll", lambda self: None):
            dummy_frame = MammouthBrowserFrame(
                master=MagicMock(),
                start_url="https://gemini.google.com/devmode?hl=en",
            )
            self.assertEqual(dummy_frame.brand_name, "Gemini")
            self.assertEqual(dummy_frame.browser_language, "en-US")

        # Verify _create_edge_chrome applies props.Language = 'en-US' and restores CoreWebView2CreationProperties
        import webview.platforms.edgechromium as ec_mod
        orig_cls = ec_mod.CoreWebView2CreationProperties
        created_props = []

        class FakeProps:
            def __init__(self):
                self.Language = None
                created_props.append(self)

        def fake_edge_chrome(ctrl, win, prof_dir):
            ec_mod.CoreWebView2CreationProperties()
            return "EDGE_OK"

        with patch.object(ec_mod, "CoreWebView2CreationProperties", FakeProps), \
             patch("modules.embedded_browser.EdgeChrome", side_effect=fake_edge_chrome):
            res = _create_edge_chrome(MagicMock(), MagicMock(), "C:/tmp/gemini_prof", language="en-US")
            self.assertEqual(res, "EDGE_OK")
            self.assertEqual(len(created_props), 1)
            self.assertEqual(created_props[0].Language, "en-US")
            self.assertIs(ec_mod.CoreWebView2CreationProperties, FakeProps)
        self.assertIs(ec_mod.CoreWebView2CreationProperties, orig_cls)

        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.hwnd = 12345
        frame.is_embedded = True
        frame.brand_name = "Gemini"
        frame.start_url = "https://gemini.google.com/devmode?hl=en"
        frame.winfo_toplevel = MagicMock()
        frame.winfo_toplevel.return_value.winfo_id.return_value = 999
        frame.edge = MagicMock()
        frame.edge.webview.CoreWebView2 = MagicMock()

        scheduled = []
        frame.after = lambda ms, fn: scheduled.append((ms, fn)) or "aid"

        with patch("modules.embedded_browser.HAS_WEBVIEW2", True), \
             patch("modules.embedded_browser.user32"):
            ok = frame.send_chat_prompt("Hello Gemini!", auto_submit=True, delay_ms=100)
            self.assertTrue(ok)
            scheduled[0][1]()
            js_code = frame.edge.webview.CoreWebView2.ExecuteScriptAsync.call_args[0][0]
            self.assertIn("rich-textarea div.ql-editor", js_code)
            self.assertIn("button.send-button", js_code)

    def test_task_scheduler_supports_gemini_web_and_auto_resolution(self):
        """Verify scheduler VALID_TARGETS and task_schedule_create(target='auto') support gemini_web."""
        self.assertIn("gemini_web", VALID_TARGETS)
        import modules.task_scheduler as ts

        tmp_db = SRC_DIR / "tests" / "_tmp_gemini_tasks.db"
        with patch.object(ts, "DB_PATH", tmp_db):
            try:
                cfg_gm = {"embedded_browser": {"default_chat_tab": "gemini"}, "modules": {}}
                with patch("server.load_config", return_value=cfg_gm):
                    t = server.task_schedule_create(
                        name="Gemini Auto Check",
                        prompt="Summarize git status",
                        interval_minutes=5,
                    )
                    self.assertEqual(t["target"], "gemini_web")
                    scheduler_delete_task(t["id"])

                t_direct = scheduler_create_task(
                    name="Gemini Direct",
                    prompt="Ping",
                    interval_seconds=300,
                    repeat_count=1,
                    target="gemini_web",
                )
                self.assertEqual(t_direct["target"], "gemini_web")
                scheduler_delete_task(t_direct["id"])
            finally:
                if tmp_db.exists():
                    tmp_db.unlink()

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    @patch.object(MammouthBrowserFrame, "ensure_initialized", lambda self: None)
    def test_gui_parallel_gemini_tab_switching_trigger_and_settings(self):
        """Verify Cockpit initializes Gemini Web tab (en-US), switching, scheduler trigger, URL copy, and settings save."""
        app = gui.MammouthControlCenter()
        try:
            self.assertTrue(hasattr(app, "tab_gemini"))
            self.assertTrue(hasattr(app, "gemini_browser"))
            self.assertTrue(hasattr(app, "btn_open_gemini"))
            self.assertEqual(app.gemini_browser.start_url, "https://gemini.google.com/devmode?hl=en")
            self.assertEqual(app.gemini_browser.brand_name, "Gemini")
            self.assertEqual(app.gemini_browser.browser_language, "en-US")
            self.assertTrue(hasattr(app.gemini_browser, "gemini_hint_bar"))
            self.assertFalse(hasattr(app.chatgpt_browser, "gemini_hint_bar"))

            # Verify sticky ?hl=en rewriting & post-login redirect detection for Gemini English UI
            app.gemini_browser._gemini_saw_auth = False
            self.assertEqual(
                app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/app"),
                "https://gemini.google.com/app?hl=en",
            )
            self.assertEqual(
                app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/app/abc123?hl=de&authuser=1"),
                "https://gemini.google.com/app/abc123?authuser=1&hl=en",
            )
            self.assertIsNone(app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/app?hl=en"))
            self.assertIsNone(app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/devmode?hl=en"))
            self.assertIsNone(app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/_/BardChatUi/data/batchexecute"))
            self.assertTrue(app.gemini_browser._maybe_mark_gemini_auth("https://accounts.google.com/v3/signin/identifier"))
            self.assertEqual(
                app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/app"),
                "https://gemini.google.com/devmode?hl=en",
            )
            self.assertEqual(
                app.gemini_browser._resolve_gemini_english_url("https://gemini.google.com/app"),
                "https://gemini.google.com/app?hl=en",
            )

            engine = TaskSchedulerEngine.get_instance()
            self.assertIn("gemini_web", engine._handlers)

            app._switch_to_gemini_tab()
            self.assertEqual(app._get_active_chat_tab_key(), "✨ Gemini Web")
            self.assertIs(app._get_active_chat_browser(), app.gemini_browser)

            res = app._on_trigger_gemini_web_task({
                "name": "Gemini Scheduled Ping",
                "prompt": "Hello from scheduler",
                "runs_done": 0,
                "switch_tab": True,
                "auto_submit": True,
            })
            self.assertEqual(res, "Dispatched to Gemini Web")

            # Verify Settings exposes Gemini Web default option, URL, and Locale
            app.opt_default_chat_tab.set("Gemini Web")
            app.entry_gemini_start_url.delete(0, "end")
            app.entry_gemini_start_url.insert(0, "https://gemini.google.com/app?hl=en")
            app.entry_gemini_language.delete(0, "end")
            app.entry_gemini_language.insert(0, "en-GB")
            with patch("gui.save_config"), patch("tkinter.messagebox.showinfo"):
                app._save_settings()
            self.assertEqual(app.config_data["embedded_browser"]["default_chat_tab"], "gemini")
            self.assertEqual(app.active_chat_tab_key, "✨ Gemini Web")
            self.assertEqual(app.config_data["gemini_browser"]["start_page"], "https://gemini.google.com/app?hl=en")
            self.assertEqual(app.config_data["gemini_browser"]["language"], "en-GB")

            # Verify _copy_gemini_connector_url uses live dynamic tunnel URL and includes EU ?hl=en instructions
            app.dynamic_tunnel_url = "https://gemini-live.trycloudflare.com/sse"
            with patch("tkinter.messagebox.showinfo") as mock_info:
                app._copy_gemini_connector_url()
                clip = app.clipboard_get()
                self.assertEqual(clip, "https://gemini-live.trycloudflare.com/mcp")
                mock_info.assert_called_once()
                msg_body = mock_info.call_args[0][1]
                self.assertIn("devmode?hl=en", msg_body)
                self.assertIn("+ Create new", msg_body)
                self.assertIn("Open in Browser", msg_body)
                self.assertIn("🧪 DevMode", msg_body)
                self.assertIn("Bearer API Key", msg_body)
        finally:
            app.destroy()

    def test_defrostr_rebrand_and_tagline_across_server_and_tray(self):
        """Verify Defrostr rebrand across FastMCP metadata, OAuth consent UI, and Tray Manager."""
        self.assertEqual(server.mcp.name, "Defrostr")
        self.assertIn("Defrostr (v0.9.0)", server.mcp.instructions or "")

        client = TestClient(server.app)
        reg = client.post(
            "/oauth/register",
            json={
                "client_name": "Gemini",
                "redirect_uris": ["https://oauth-redirect.googleusercontent.com/r/rebrand_check"],
            },
        )
        self.assertEqual(reg.status_code, 201)
        cid = reg.json()["client_id"]
        verifier = "defrostr_rebrand_verifier_43_chars_long_123456"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        auth = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": cid,
                "redirect_uri": "https://oauth-redirect.googleusercontent.com/r/rebrand_check",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(auth.status_code, 200)
        self.assertIn("<h2>Defrostr</h2>", auth.text)
        self.assertIn("Defrostr — Authorization", auth.text)

        tray_src = (SRC_DIR / "tray_manager.py").read_text(encoding="utf-8")
        self.assertIn('item("❄️ Defrostr", None, enabled=False)', tray_src)
        self.assertIn('pystray.Icon("Defrostr", image, "Defrostr (Online)", menu)', tray_src)

        gui_src = (SRC_DIR / "gui.py").read_text(encoding="utf-8")
        self.assertIn('Every AI. One Local Bridge. Zero Lock-In.', gui_src)

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    @patch.object(MammouthBrowserFrame, "ensure_initialized", lambda self: None)
    def test_gui_defrostr_title_security_tab_and_provider_visibility_toggles(self):
        """Verify Defrostr title, dedicated 🛡️ Security tab, and Settings provider tab visibility filtering."""
        import tkinter as tk

        app = gui.MammouthControlCenter()
        try:
            self.assertEqual(app.title(), "Defrostr ❄️🔥 (v0.9.0)")
            self.assertTrue(hasattr(app, "tab_security"))
            self.assertIn("🛡️ Security", app._nav_buttons)
            self.assertIn("⚙️ Settings", app._nav_buttons)
            self.assertNotIn("⚙️ Security & Settings", app._nav_buttons)

            # All Security controls live in the dedicated Security tab & save cleanly
            for attr in (
                "var_enforce_auth",
                "entry_token",
                "var_allow_query_token",
                "var_sandbox",
                "var_protect_secret_files",
                "entry_workspace",
                "var_admin_shell",
                "var_shell_downloads",
                "var_screen_req_consent",
                "var_enable_tls",
                "var_expose_tool_annotations",
            ):
                self.assertTrue(hasattr(app, attr), f"Missing Security control: {attr}")

            app.var_protect_secret_files.set(False)
            app.var_allow_query_token.set(True)
            app.var_expose_tool_annotations.set(True)
            app.var_admin_shell.set(True)
            app.var_shell_downloads.set(False)
            app.var_screen_req_consent.set(False)
            with patch("gui.save_config"), patch("tkinter.messagebox.showinfo"):
                app._save_security()

            srv = app.config_data["server"]
            self.assertFalse(srv["protect_secret_files"])
            self.assertTrue(srv["allow_query_token"])
            self.assertTrue(srv["expose_tool_annotations"])
            self.assertTrue(srv["allow_admin_shell"])
            self.assertFalse(srv["allow_shell_downloads"])
            self.assertFalse(app.config_data["modules"]["screen_capture"]["require_consent"])

            # Selectable provider tabs: hide Mammouth AI and ChatGPT, keep Claude + Gemini
            app.active_chat_tab_key = "🤖 ChatGPT Web"
            app.var_show_chatgpt_tab.set(False)
            app.var_show_mammouth_tab.set(False)
            app.var_show_claude_tab.set(True)
            app.var_show_gemini_tab.set(True)
            with patch("gui.save_config"), patch("tkinter.messagebox.showinfo"):
                app._save_settings()

            self.assertFalse(app.config_data["chatgpt_browser"]["enabled"])
            self.assertFalse(app.config_data["embedded_browser"]["mammouth_enabled"])
            self.assertTrue(app.config_data["claude_browser"]["enabled"])
            self.assertTrue(app.config_data["gemini_browser"]["enabled"])

            # Fallback active chat tab must move off disabled ChatGPT onto an enabled tab
            self.assertIn(app.active_chat_tab_key, ("🟠 Claude Web", "✨ Gemini Web"))
            self.assertEqual(app.opt_default_chat_tab.cget("values"), ["Claude Web", "Gemini Web"])

            # Hidden nav/header/URL buttons must be unpack-ed while enabled ones remain packed
            self.assertTrue(app._nav_buttons["🟠 Claude Web"].winfo_manager())
            self.assertTrue(app._nav_buttons["✨ Gemini Web"].winfo_manager())
            self.assertEqual(app._nav_buttons["🤖 ChatGPT Web"].winfo_manager(), "")
            self.assertEqual(app._nav_buttons["💬 Mammouth AI Web"].winfo_manager(), "")
            self.assertEqual(app.btn_open_chatgpt.winfo_manager(), "")
            self.assertEqual(app.btn_open_mammouth.winfo_manager(), "")
            self.assertTrue(app.btn_open_claude.winfo_manager())
            self.assertTrue(app.btn_open_gemini.winfo_manager())
            self.assertEqual(app.btn_copy_chatgpt_url.winfo_manager(), "")
            self.assertTrue(app.btn_copy_gemini_url.winfo_manager())
            with self.assertRaises(tk.TclError):
                app.btn_open_chatgpt.pack_info()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
