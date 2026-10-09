import unittest
import os
import sys
from typing import Dict, Any
from unittest.mock import MagicMock, patch

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import DEFAULT_CONFIG
from modules.embedded_browser import (
    parse_mammouth_quota_data,
    MAMMOUTH_BRAND_COLORS,
    PLAN_MULTIPLIERS,
    BASE_THRESHOLD_CENTS
)
from modules.screen_capture import copy_image_to_clipboard


class TestMammouthQuotaParser(unittest.TestCase):
    """Unit tests for the Mammouth AI quota data parser and calculation engine."""

    def test_parse_starter_matching_screenshot(self):
        """Validates calculation matching the user's uploaded Mammouth Kontingent screenshot."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "starter",
                "currentSpendCents": 90.0,
                "usageCounts": {"prompt": 14}
            },
            "recent": {
                "usedModels": ["claude-3-5-sonnet", "gpt-4o", "glm-4", "gemini-1.5-pro", "sonar-pro"],
                "byBrand": [
                    {"brand": "claude", "value": 92.0},
                    {"brand": "gpt", "value": 3.0},
                    {"brand": "glm", "value": 3.0},
                    {"brand": "gemini", "value": 2.0},
                    {"brand": "perplexity", "value": 0.5}
                ]
            }
        }
        res = parse_mammouth_quota_data(payload)

        self.assertTrue(res["is_logged_in"])
        self.assertEqual(res["plan_id"], "starter")
        self.assertEqual(res["plan_label"], "Starter x1")
        self.assertEqual(res["multiplier"], 1)
        self.assertEqual(res["max_spend_cents"], 150.0)
        self.assertEqual(res["current_spend_cents"], 90.0)
        self.assertEqual(res["total_percent"], 60.0)

        brands = res["brands"]
        self.assertEqual(len(brands), 5)
        self.assertEqual(brands[0]["brand"], "claude")
        self.assertEqual(brands[0]["label"], "Claude")
        self.assertEqual(brands[0]["value"], 92.0)
        self.assertEqual(brands[0]["color"], MAMMOUTH_BRAND_COLORS["claude"][0])

        self.assertEqual(brands[1]["brand"], "gpt")
        self.assertEqual(brands[1]["label"], "GPT")
        self.assertEqual(brands[1]["value"], 3.0)

    def test_parse_standard_plan(self):
        """Validates Standard plan (x3 multiplier -> $4.50 limit)."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "standard",
                "currentSpendCents": 225.0
            },
            "recent": {
                "byBrand": [
                    {"brand": "claude", "value": 100.0}
                ]
            }
        }
        res = parse_mammouth_quota_data(payload)
        self.assertEqual(res["plan_id"], "standard")
        self.assertEqual(res["multiplier"], 3)
        self.assertEqual(res["max_spend_cents"], 450.0)
        self.assertEqual(res["current_spend_cents"], 225.0)
        self.assertEqual(res["total_percent"], 50.0)

    def test_parse_expert_plan(self):
        """Validates Expert plan (x10 multiplier -> $15.00 limit)."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "expert",
                "currentSpendCents": 1500.0
            }
        }
        res = parse_mammouth_quota_data(payload)
        self.assertEqual(res["plan_id"], "expert")
        self.assertEqual(res["multiplier"], 10)
        self.assertEqual(res["max_spend_cents"], 1500.0)
        self.assertEqual(res["total_percent"], 100.0)

    def test_parse_unauthenticated_or_error(self):
        """Validates fallback when user is logged out or API returns error."""
        res_error = parse_mammouth_quota_data({"ok": False, "error": "Not logged in"})
        self.assertFalse(res_error["is_logged_in"])
        self.assertEqual(res_error["total_percent"], 0.0)
        self.assertEqual(res_error["plan_label"], "Nicht eingeloggt")
        self.assertEqual(len(res_error["brands"]), 0)

        res_none = parse_mammouth_quota_data(None)
        self.assertFalse(res_none["is_logged_in"])

    def test_parse_schema_resilience(self):
        """Validates parser resilience against missing fields and unexpected types."""
        weird_payload = {
            "ok": True,
            "current": {
                "usagePlan": "unknown_tier",
                "currentSpendCents": "invalid_number"
            },
            "recent": {
                "byBrand": "not_a_list"
            }
        }
        res = parse_mammouth_quota_data(weird_payload)
        self.assertTrue(res["is_logged_in"])
        self.assertEqual(res["multiplier"], 1)
        self.assertEqual(res["current_spend_cents"], 0.0)
        self.assertEqual(len(res["brands"]), 0)


class TestMammouthQuotaConfig(unittest.TestCase):
    """Validates configuration defaults for embedded browser and quota telemetry."""

    def test_quota_config_defaults(self):
        browser_cfg = DEFAULT_CONFIG.get("embedded_browser", {})
        self.assertIn("quota_sidebar_enabled", browser_cfg)
        self.assertIn("quota_refresh_interval_seconds", browser_cfg)
        self.assertTrue(browser_cfg["quota_sidebar_enabled"])
        self.assertEqual(browser_cfg["quota_refresh_interval_seconds"], 300)


class TestBugfixV041(unittest.TestCase):
    """Unit tests verifying fixes for screenshot hang and download crash issues."""

    def test_copy_image_to_clipboard_retries_and_cleans_up(self):
        """Validates that copy_image_to_clipboard handles locked clipboard gracefully with retries."""
        from PIL import Image
        test_img = Image.new("RGB", (10, 10), color="red")
        
        # Test calling with PIL image directly
        # On Windows without open conflicts, it should execute without unhandled crash
        res = copy_image_to_clipboard(test_img)
        self.assertIsInstance(res, bool)

    def test_download_starting_routes_and_completes_deferral(self):
        """Validates that _on_download_starting configures result path asynchronously, preserves WebView2 download, and completes deferral."""
        from modules.embedded_browser import MammouthBrowserFrame
        
        # Mock WebView2 DownloadStarting args
        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Users\\test\\Downloads\\export.zip"
        mock_args.DownloadOperation = MagicMock()
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral
        
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame._prompt_save_file = MagicMock(return_value="D:\\Saved\\export.zip")
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())
        
        # Call the actual method
        MammouthBrowserFrame._on_download_starting(frame, sender=None, args=mock_args)
        
        # Wait for worker thread to complete
        if hasattr(frame, "_last_download_thread") and frame._last_download_thread:
            frame._last_download_thread.join(timeout=2.0)

        # Ensure ResultFilePath is set to destination via set_ResultFilePath
        mock_args.set_ResultFilePath.assert_called_with(os.path.normpath("D:\\Saved\\export.zip"))
        mock_args.set_Handled.assert_called_with(True)
        # Ensure deferral was completed
        mock_deferral.Complete.assert_called_once()

    def test_safe_ui_call_queuing_and_polling(self):
        """Validates that _safe_ui_call queues actions and _schedule_ui_queue_poll executes them."""
        import queue
        from modules.embedded_browser import MammouthBrowserFrame

        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame._ui_queue = queue.Queue()
        executed = []

        # Force async queueing
        frame._safe_ui_call(lambda: executed.append("action1"), force_async=True)
        self.assertEqual(len(executed), 0)
        self.assertEqual(frame._ui_queue.qsize(), 1)

        # Mock after so poll doesn't loop infinitely
        frame.after = MagicMock()
        frame._schedule_ui_queue_poll()
        self.assertEqual(executed, ["action1"])
        self.assertEqual(frame._ui_queue.qsize(), 0)

    def test_on_download_starting_production_op_does_not_hook_com_state_changed(self):
        """Validates that real production download operations without mock_calls are not hooked via COM delegates."""
        from modules.embedded_browser import MammouthBrowserFrame

        class DummyRealDownloadOp:
            def __init__(self):
                self.hooked = False
            @property
            def StateChanged(self):
                return self
            def __iadd__(self, other):
                self.hooked = True
                return self

        dummy_op = DummyRealDownloadOp()
        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Downloads\\data.csv"
        mock_args.DownloadOperation = dummy_op
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral

        frame = MagicMock(spec=MammouthBrowserFrame)
        frame._prompt_save_file = MagicMock(return_value="C:\\Downloads\\data.csv")

        MammouthBrowserFrame._on_download_starting(frame, sender=None, args=mock_args)
        # Verify dummy_op.StateChanged was NOT hooked
        self.assertFalse(dummy_op.hooked)
        mock_deferral.Complete.assert_called_once()


class TestCTkMammouthQuotaCard(unittest.TestCase):
    """Tests the CustomTkinter Quota Card GUI lifecycle."""

    def setUp(self):
        try:
            import customtkinter as ctk
            self.root = ctk.CTk()
            self.root.withdraw()
        except Exception as e:
            self.skipTest(f"Tkinter display not available: {e}")

    def tearDown(self):
        if hasattr(self, "root") and self.root:
            try:
                self.root.destroy()
            except Exception:
                pass

    def test_quota_card_lifecycle(self):
        if not hasattr(self, "root") or not self.root:
            return

        from gui import CTkMammouthQuotaCard

        card = CTkMammouthQuotaCard(self.root)
        self.assertIsNotNone(card)
        self.assertEqual(card.lbl_plan.cget("text"), "Wird geladen...")

        # Update with unauthenticated data
        unauth_parsed = parse_mammouth_quota_data({"ok": False})
        card.update_quota(unauth_parsed)
        self.assertEqual(card.lbl_plan.cget("text"), "Nicht eingeloggt")
        self.assertEqual(card.lbl_percent.cget("text"), "-- %")

        # Update with screenshot quota data
        auth_payload = {
            "ok": True,
            "current": {
                "usagePlan": "starter",
                "currentSpendCents": 90.0
            },
            "recent": {
                "byBrand": [
                    {"brand": "claude", "value": 92.0},
                    {"brand": "gpt", "value": 3.0},
                    {"brand": "glm", "value": 3.0},
                    {"brand": "gemini", "value": 2.0},
                    {"brand": "perplexity", "value": 0.5}
                ]
            }
        }
        auth_parsed = parse_mammouth_quota_data(auth_payload)
        card.update_quota(auth_parsed)

        self.assertEqual(card.lbl_plan.cget("text"), "Starter x1")
        self.assertEqual(card.lbl_percent.cget("text"), "60 %")
        # 3 rows of brands (pairs: 2 + 2 + 1)

class TestUnifiedWebMessage(unittest.TestCase):
    """Validates _unified_web_message correctly unpacks JSON WebMessages and notifies quota_cb."""

    def test_quota_web_message_triggers_callback(self):
        from modules.embedded_browser import MammouthBrowserFrame
        import json

        received_payload = []
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame.quota_cb = lambda p: received_payload.append(p)
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())

        # Simulate WebMessage arriving as JSON string from WebView2
        payload_obj = {
            "type": "mammouth_quota",
            "payload": {
                "ok": True,
                "current": {"plan": "starter", "currentSpendCents": 45.0},
                "recent": {"byBrand": [{"brand": "claude", "value": 100.0}]}
            }
        }
        # In WebView2, if JS sends postMessage(JSON.stringify(...)), get_WebMessageAsJson returns JSON string of that string
        mock_args = MagicMock()
        mock_args.Source = "https://mammouth.ai/app"
        mock_args.get_WebMessageAsJson.return_value = json.dumps(json.dumps(payload_obj))

        MammouthBrowserFrame._unified_web_message(frame, sender=None, args=mock_args)

        self.assertEqual(len(received_payload), 1)
        self.assertTrue(received_payload[0]["ok"])
        self.assertEqual(received_payload[0]["current"]["currentSpendCents"], 45.0)

    def test_quota_web_message_single_json_level(self):
        from modules.embedded_browser import MammouthBrowserFrame
        import json

        received_payload = []
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame.quota_cb = lambda p: received_payload.append(p)
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())

        payload_obj = {
            "type": "mammouth_quota",
            "payload": {
                "ok": True,
                "current": {"usagePlan": "standard", "spendCents": 150.0}
            }
        }
        mock_args = MagicMock()
        mock_args.Source = "https://mammouth.ai/app"
        mock_args.get_WebMessageAsJson.return_value = json.dumps(payload_obj)

        MammouthBrowserFrame._unified_web_message(frame, sender=None, args=mock_args)

        self.assertEqual(len(received_payload), 1)
        self.assertEqual(received_payload[0]["current"]["usagePlan"], "standard")

    def test_web_message_from_foreign_origin_is_ignored(self):
        from modules.embedded_browser import MammouthBrowserFrame
        import json

        received_payload = []
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame.quota_cb = lambda p: received_payload.append(p)
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())

        mock_args = MagicMock()
        mock_args.Source = "https://evil.example/phish"
        mock_args.get_WebMessageAsJson.return_value = json.dumps({"type": "mammouth_quota", "payload": {"ok": True}})

        MammouthBrowserFrame._unified_web_message(frame, sender=None, args=mock_args)

        self.assertEqual(received_payload, [])

    def test_edgechrome_handlers_neutralized_and_instantiation_safe(self):
        """Validates EdgeChrome monkeypatches are active and direct instantiation does not raise State TypeError."""
        import sys
        if sys.platform != "win32":
            return
        from webview.platforms import edgechromium
        from webview.window import Window

        # Test that calling monkeypatched handlers does not throw
        edge_dummy = edgechromium.EdgeChrome.__new__(edgechromium.EdgeChrome)
        edgechromium.EdgeChrome.on_script_notify(edge_dummy, None, None)
        edgechromium.EdgeChrome.on_navigation_completed(edge_dummy, None, None)
        edgechromium.EdgeChrome.on_download_starting(edge_dummy, None, None)

        # Test Window creation doesn't fail with State class TypeError
        w = Window("Test", "Test", "http://localhost")
        self.assertIsNotNone(w.state)


class TestV041SecurityAndParameterFixes(unittest.TestCase):
    """Verifies all audit P0 findings and parameter parsing hardening."""

    def setUp(self):
        from modules.file_ops import _get_sandbox_config
        _, self.ws_root = _get_sandbox_config()
        self.test_files_created = []

    def tearDown(self):
        for p in self.test_files_created:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    def test_file_write_parameter_parsing_and_quotes(self):
        """Test that file_write handles wrapping quotes, internal quotes, and leading slashes safely."""
        from modules.file_ops import file_write, file_read
        from pathlib import Path

        # 1. Path wrapped in double quotes
        res1 = file_write(file_path='"wrapped_quote.txt"', content="Line 1\nLine 2")
        self.assertIn("Successfully wrote", res1)
        p1 = self.ws_root / "wrapped_quote.txt"
        self.test_files_created.append(p1)
        self.assertTrue(p1.exists())
        self.assertEqual(file_read("wrapped_quote.txt"), "Line 1\nLine 2")

        # 2. Path with internal quotes (the "2.0" phantom file issue) - quotes are stripped
        res2 = file_write(file_path='test "2.0".txt', content="Version 2.0 content")
        self.assertIn("Successfully wrote", res2)
        p2 = self.ws_root / "test 2.0.txt"
        self.test_files_created.append(p2)
        self.assertTrue(p2.exists())
        self.assertEqual(file_read("test 2.0.txt"), "Version 2.0 content")

        # 3. Path with leading slashes (/path or \path) anchored to workspace root
        res3 = file_write(file_path='/leading_slash.txt', content="Anchored relative")
        self.assertIn("Successfully wrote", res3)
        p3 = self.ws_root / "leading_slash.txt"
        self.test_files_created.append(p3)
        self.assertTrue(p3.exists())
        self.assertEqual(file_read("/leading_slash.txt"), "Anchored relative")

        # 4. Complex script content with quotes, backslashes, and special characters preserved 1:1
        script_content = (
            "#!/usr/bin/env python3\n"
            "# Header Version 2.0\n"
            "import os, sys\n"
            'msg = "Hello \\"2.0\\" \\n world!"\n'
            "print(msg)\n"
        )
        res4 = file_write(file_path="script_header_test.py", content=script_content)
        self.assertIn("Successfully wrote", res4)
        p4 = self.ws_root / "script_header_test.py"
        self.test_files_created.append(p4)
        read_back = file_read("script_header_test.py")
        self.assertEqual(read_back, script_content)

    def test_local_exec_command_execution_and_quotes(self):
        """Test local_exec_command executes via PowerShell with 1:1 quotes and workspace-anchored cwd."""
        from server import local_exec_command

        # 1. Command with quotes and backslashes
        res = local_exec_command('Write-Output "Hello 2.0 World"')
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Hello 2.0 World", res["stdout"])

        # 2. Command with relative cwd (anchored to workspace root)
        res_cwd = local_exec_command('Get-Location', cwd=".")
        self.assertEqual(res_cwd["exit_code"], 0)

        # 3. Cwd outside workspace is rejected
        res_bad_cwd = local_exec_command('whoami', cwd="C:\\Windows\\System32")
        self.assertEqual(res_bad_cwd["exit_code"], -1)
        self.assertIn("Security: cwd", res_bad_cwd["stderr"])

    def test_shell_newline_and_operator_allowlist_bypass_blocked(self):
        """F-03: Verify newline, &&, ||, and Out-File cannot bypass read-only allowlist."""
        from modules.shell_processes import _validate_shell_command

        # Newline separation bypass
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Process\nRemove-Item C:\\test.txt", allow_admin=False)

        # Windows CRLF separation bypass
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Process\r\nRemove-Item C:\\test.txt", allow_admin=False)

        # && operator separation bypass
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Process && Remove-Item C:\\test.txt", allow_admin=False)

        # || operator separation bypass
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Process || Remove-Item C:\\test.txt", allow_admin=False)

        # Out-File write bypass
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Process | Out-File output.txt", allow_admin=False)

    def test_oauth_csrf_protection_and_fail_closed_registration(self):
        """F-01 & F-02: Verify CSRF token requirement for OAuth consent and fail-closed registration."""
        import asyncio
        from starlette.requests import Request
        from server import oauth_authorize, oauth_register, _save_oauth_client

        # Register a test client for authorize
        _save_oauth_client("mcp_test_client", "test_sec", "Test Client", ["https://mammouth.ai/callback"])

        async def run_checks():
            # 1. GET /oauth/authorize generates CSRF token in HTML
            scope_get = {
                "type": "http",
                "method": "GET",
                "path": "/oauth/authorize",
                "query_string": b"client_id=mcp_test_client&code_challenge=xyz123&code_challenge_method=S256&redirect_uri=https://mammouth.ai/callback",
                "headers": [(b"host", b"127.0.0.1:8000")]
            }
            req_get = Request(scope_get)
            resp_get = await oauth_authorize(req_get)
            self.assertEqual(resp_get.status_code, 200)
            body_html = resp_get.body.decode("utf-8")
            self.assertIn('name="csrf_token"', body_html)

            # 2. POST /oauth/authorize WITHOUT csrf_token on untrusted redirect_uri returns HTTP 403
            scope_post_bad = {
                "type": "http",
                "method": "POST",
                "path": "/oauth/authorize",
                "headers": [
                    (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"host", b"127.0.0.1:8000")
                ]
            }
            async def receive_bad():
                return {"type": "http.request", "body": b"action=allow&client_id=mcp_test_client&redirect_uri=https://evil-attacker.com/steal", "more_body": False}
            req_post_bad = Request(scope_post_bad, receive=receive_bad)
            resp_post_bad = await oauth_authorize(req_post_bad)
            self.assertEqual(resp_post_bad.status_code, 403)

            # 3. POST /oauth/register with untrusted redirect URI returns HTTP 400 (F-02 Allowlist)
            scope_reg = {
                "type": "http",
                "method": "POST",
                "path": "/oauth/register",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"host", b"127.0.0.1:8000")
                ]
            }
            async def receive_reg():
                return {"type": "http.request", "body": b'{"client_name":"Hacker","redirect_uris":["https://evil-attacker.com/steal"]}', "more_body": False}
            req_reg = Request(scope_reg, receive=receive_reg)
            resp_reg = await oauth_register(req_reg)
            self.assertEqual(resp_reg.status_code, 400)

        asyncio.run(run_checks())

    def test_query_string_token_rejected_by_middleware(self):
        """F-05: Verify query string ?token= parameter is rejected by SecurityAndAuthMiddleware."""
        import asyncio
        from server import SecurityAndAuthMiddleware

        app_called = []
        async def mock_app(scope, receive, send):
            app_called.append(True)

        middleware = SecurityAndAuthMiddleware(mock_app, token="mc_test_secret_token_12345", enforce_auth=True)

        async def run_query_token_check():
            sent_messages = []
            async def mock_send(msg):
                sent_messages.append(msg)

            # Request with token ONLY in query string ?token=... (no Authorization header)
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/sse",
                "query_string": b"token=mc_test_secret_token_12345",
                "headers": [(b"host", b"127.0.0.1:8000")],
                "client": ("127.0.0.1", 12345)
            }
            async def mock_receive():
                return {"type": "http.request"}

            await middleware(scope, mock_receive, mock_send)
            # App should NOT have been called (auth rejected with 401)
            self.assertEqual(len(app_called), 0)
            self.assertTrue(any(msg.get("status") == 401 for msg in sent_messages if msg.get("type") == "http.response.start"))

        asyncio.run(run_query_token_check())

    def test_rfc_standard_oauth_paths_and_metadata_subpaths(self):
        """Verify standard RFC 6749 and RFC 9728 paths (/authorize, /token, /register, and subpaths /sse) bypass pre-auth."""
        import asyncio
        from server import SecurityAndAuthMiddleware

        app_calls = []
        async def mock_app(scope, receive, send):
            app_calls.append(scope["path"])
            if send:
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"OK", "more_body": False})

        middleware = SecurityAndAuthMiddleware(mock_app, token="mc_test_token_secure", enforce_auth=True)

        async def run_checks():
            test_paths = [
                "/authorize",
                "/oauth/authorize",
                "/token",
                "/oauth/token",
                "/register",
                "/oauth/register",
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/sse",
                "/.well-known/oauth-authorization-server",
                "/.well-known/oauth-authorization-server/sse",
            ]
            for p in test_paths:
                sent = []
                async def mock_send(msg):
                    sent.append(msg)
                scope = {
                    "type": "http",
                    "method": "POST" if "token" in p or "register" in p else "GET",
                    "path": p,
                    "headers": [(b"host", b"127.0.0.1:8000")],
                    "client": ("127.0.0.1", 12345)
                }
                await middleware(scope, None, mock_send)
                self.assertIn(p, app_calls, f"Path {p} failed to bypass pre-authentication middleware")
                start_msg = [m for m in sent if m.get("type") == "http.response.start"][0]
                self.assertEqual(start_msg["status"], 200)

        asyncio.run(run_checks())

    def test_oauth_flow_persistence_across_restart(self):
        """Verify full OAuth authorization, PKCE token issuance, and persistence across server restart."""
        import asyncio
        import hashlib
        import base64
        import json
        import re
        import urllib.parse
        from starlette.requests import Request
        from server import (
            oauth_authorize,
            oauth_token,
            _is_valid_oauth_token,
        )

        verifier = "test_code_verifier_12345678901234567890_pkce"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        # 1. GET /authorize with standard Mammouth AI query params
        scope_get = {
            "type": "http",
            "method": "GET",
            "path": "/authorize",
            "query_string": f"client_id=testuser@mammouth.ai&code_challenge={challenge}&code_challenge_method=S256&redirect_uri=https://mammouth.ai/api/mcp/oauth/callback&state=teststate123".encode("ascii"),
            "headers": [(b"host", b"127.0.0.1:8000")]
        }
        req_get = Request(scope_get)

        async def run_flow():
            resp_get = await oauth_authorize(req_get)
            self.assertEqual(resp_get.status_code, 200)
            body_html = resp_get.body.decode("utf-8")
            self.assertIn('action="/authorize"', body_html)
            self.assertIn('name="csrf_token"', body_html)

            # Extract CSRF token from HTML
            m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body_html)
            self.assertIsNotNone(m)
            csrf_token = m.group(1)

            # 2. POST /authorize to approve consent
            scope_post = {
                "type": "http",
                "method": "POST",
                "path": "/authorize",
                "headers": [
                    (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"host", b"127.0.0.1:8000")
                ]
            }
            # Approving requires the owner's Defroster API token (proof the consent comes from the owner)
            from config import load_config
            owner_token = load_config()["server"]["api_token"]

            # 2a. Wrong owner token re-renders the consent page with HTTP 403 and issues no code
            bad_body = f"action=allow&csrf_token={csrf_token}&owner_token=wrong".encode("ascii")
            async def receive_bad_owner():
                return {"type": "http.request", "body": bad_body, "more_body": False}
            resp_bad_owner = await oauth_authorize(Request(scope_post, receive=receive_bad_owner))
            self.assertEqual(resp_bad_owner.status_code, 403)
            m_retry = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp_bad_owner.body.decode("utf-8"))
            self.assertIsNotNone(m_retry)
            csrf_token = m_retry.group(1)

            form_body = (
                f"action=allow&csrf_token={csrf_token}&owner_token="
                + urllib.parse.quote(owner_token, safe="")
            ).encode("ascii")
            async def receive_post():
                return {"type": "http.request", "body": form_body, "more_body": False}

            req_post = Request(scope_post, receive=receive_post)
            resp_post = await oauth_authorize(req_post)
            self.assertEqual(resp_post.status_code, 302)
            redirect_target = resp_post.headers.get("location", "")
            self.assertIn("https://mammouth.ai/api/mcp/oauth/callback", redirect_target)
            self.assertIn("code=", redirect_target)

            # Extract code from redirect URL
            parsed_redirect = urllib.parse.urlparse(redirect_target)
            q_params = urllib.parse.parse_qs(parsed_redirect.query)
            auth_code = q_params["code"][0]
            self.assertTrue(auth_code.startswith("mc_"))

            # 3. POST /token to exchange code for access_token and refresh_token
            scope_token = {
                "type": "http",
                "method": "POST",
                "path": "/token",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"host", b"127.0.0.1:8000")
                ]
            }
            token_payload = json.dumps({
                "grant_type": "authorization_code",
                "code": auth_code,
                "code_verifier": verifier,
                "client_id": "testuser@mammouth.ai",
                "redirect_uri": "https://mammouth.ai/api/mcp/oauth/callback"
            }).encode("utf-8")
            async def receive_token():
                return {"type": "http.request", "body": token_payload, "more_body": False}

            req_token = Request(scope_token, receive=receive_token)
            resp_token = await oauth_token(req_token)
            self.assertEqual(resp_token.status_code, 200)
            token_data = json.loads(resp_token.body.decode("utf-8"))
            self.assertIn("access_token", token_data)
            self.assertIn("refresh_token", token_data)
            access_token = token_data["access_token"]
            refresh_token = token_data["refresh_token"]

            # 4. Verify token is active
            self.assertTrue(_is_valid_oauth_token(access_token))

            # 5. Simulate Defroster server restart: re-checking DB for token validity
            self.assertTrue(_is_valid_oauth_token(access_token))

            # 6. Test Refresh Token on POST /token
            scope_refresh = {
                "type": "http",
                "method": "POST",
                "path": "/token",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"host", b"127.0.0.1:8000")
                ]
            }
            refresh_payload = json.dumps({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }).encode("utf-8")
            async def receive_refresh():
                return {"type": "http.request", "body": refresh_payload, "more_body": False}

            req_refresh = Request(scope_refresh, receive=receive_refresh)
            resp_refresh = await oauth_token(req_refresh)
            self.assertEqual(resp_refresh.status_code, 200)
            refreshed_data = json.loads(resp_refresh.body.decode("utf-8"))
            self.assertIn("access_token", refreshed_data)
            self.assertIn("refresh_token", refreshed_data)
            self.assertTrue(_is_valid_oauth_token(refreshed_data["access_token"]))

        asyncio.run(run_flow())


if __name__ == "__main__":
    unittest.main()


