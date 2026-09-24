import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui import redact_secrets, MammouthControlCenter, APP_VERSION
from modules.updater import check_for_update, download_and_verify_update, apply_update_and_restart
from config import load_config, DEFAULT_CONFIG


class TestSecretRedaction(unittest.TestCase):
    def test_oauth_access_and_refresh_tokens(self):
        msg = "Received token mcp_at_a1b2c3d4e5f6g7h8i9j0 and refresh token mcp_rt_0987654321fedcba in response"
        redacted = redact_secrets(msg)
        self.assertNotIn("mcp_at_a1b2c3d4e5f6g7h8i9j0", redacted)
        self.assertNotIn("mcp_rt_0987654321fedcba", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_bearer_header_redaction(self):
        msg = "Headers: {'Authorization': 'Bearer sk-mammouth-super-secret-token-1234567890'}"
        redacted = redact_secrets(msg)
        self.assertNotIn("sk-mammouth-super-secret-token-1234567890", redacted)
        self.assertIn("Bearer [REDACTED]", redacted)

    def test_query_param_tokens_and_codes(self):
        msg = "GET /oauth/callback?code=oauth_auth_code_secret_456&state=xyz123&token=tok_987654321"
        redacted = redact_secrets(msg)
        self.assertNotIn("oauth_auth_code_secret_456", redacted)
        self.assertNotIn("tok_987654321", redacted)
        self.assertIn("code=[REDACTED]", redacted)
        self.assertIn("token=[REDACTED]", redacted)
        self.assertIn("state=xyz123", redacted)

    def test_mc_prefix_keys(self):
        msg = "Client registered with key mc_abcdef1234567890 successfully"
        redacted = redact_secrets(msg)
        self.assertNotIn("mc_abcdef1234567890", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_normal_messages_preserved(self):
        msg = "Server listening on 127.0.0.1:8000 /sse endpoint ready"
        redacted = redact_secrets(msg)
        self.assertEqual(redacted, msg)


class TestAutoUpdater(unittest.TestCase):
    def test_check_for_update_newer_version(self):
        mock_release = {
            "tag_name": "v0.5.0",
            "name": "v0.5.0 — Release",
            "body": "Major upgrades",
            "assets": [
                {
                    "name": "MammouthDefroster9000-v0.5.0-windows-x64.zip",
                    "browser_download_url": "https://github.com/test/download.zip",
                    "size": 52428800
                },
                {
                    "name": "MammouthDefroster9000-v0.5.0-windows-x64.zip.sha256",
                    "browser_download_url": "https://github.com/test/download.zip.sha256"
                }
            ]
        }
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_release
            instance.get.return_value = mock_resp

            result = check_for_update("v0.4.0")
            self.assertIsNotNone(result)
            self.assertEqual(result["version"], "v0.5.0")
            self.assertEqual(result["zip_name"], "MammouthDefroster9000-v0.5.0-windows-x64.zip")
            self.assertEqual(result["zip_url"], "https://github.com/test/download.zip")
            self.assertEqual(result["sha256_url"], "https://github.com/test/download.zip.sha256")

    def test_check_for_update_older_or_equal_version(self):
        mock_release = {
            "tag_name": "v0.4.0",
            "name": "v0.4.0 — Release",
            "assets": []
        }
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_release
            instance.get.return_value = mock_resp

            result = check_for_update("v0.4.0")
            self.assertIsNone(result)

    def test_apply_update_and_restart_script_generation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "test_update.zip")
            with open(zip_path, "wb") as f:
                f.write(b"PK00mockzip")

            with patch("subprocess.Popen") as mock_popen:
                success = apply_update_and_restart(zip_path, tmp_dir, 99999)
                self.assertTrue(success)
                mock_popen.assert_called_once()
                
                batch_file = os.path.join(tmp_dir, "apply_update.bat")
                self.assertTrue(os.path.exists(batch_file))
                with open(batch_file, "r", encoding="utf-8") as f:
                    content = f.read()
                # Verify safe update extraction logic that excludes user data
                self.assertIn("config.json", content)
                self.assertIn("oauth.db", content)
                self.assertIn("MammouthDefroster9000.exe", content)
                # Verify disk space cleanup
                self.assertIn("Cleaning up temporary update files", content)
                self.assertIn("rmdir /s /q", content)


class TestConfigurationDefaults(unittest.TestCase):
    def test_embedded_browser_config_defaults(self):
        self.assertIn("embedded_browser", DEFAULT_CONFIG)
        eb = DEFAULT_CONFIG["embedded_browser"]
        self.assertTrue(eb.get("enabled"))
        self.assertEqual(eb.get("start_page"), "https://mammouth.ai")
        self.assertTrue(eb.get("auto_open_on_server_start"))
        self.assertIn("user_data_dir", eb)

    def test_auto_check_updates_default(self):
        self.assertIn("auto_check_updates", DEFAULT_CONFIG["server"])
        self.assertTrue(DEFAULT_CONFIG["server"]["auto_check_updates"])

    def test_auto_start_server_default(self):
        self.assertIn("auto_start_server", DEFAULT_CONFIG["server"])
        self.assertTrue(DEFAULT_CONFIG["server"]["auto_start_server"])


class NoTk:
    pass


class TestGuiV040Logic(unittest.TestCase):
    def setUp(self):
        self.app = MammouthControlCenter.__new__(MammouthControlCenter)
        self.app.tk = NoTk()
        self.app.config_data = {
            "server": {
                "host": "127.0.0.1",
                "port": 8000,
                "api_token": "test_tok",
                "allow_admin_shell": False,
                "tunnel_mode": "Direct / LAN IP",
                "endpoint_path": "/sse",
                "enforce_auth": True,
                "enable_tls": False,
                "enforce_workspace_sandbox": True,
                "workspace_root": "./workspace",
                "auto_check_updates": True
            },
            "modules": {
                "screen_capture": {"require_consent": True},
                "google_drive": {}
            },
            "embedded_browser": {
                "auto_open_on_server_start": True,
                "start_page": "https://mammouth.ai"
            }
        }
        self.app._log = MagicMock()
        self.app._refresh_all_endpoint_labels = MagicMock()
        self.app.dash_mode_menu = MagicMock()
        self.app.dash_path_menu = MagicMock()
        self.app.tabview = MagicMock()
        self.app.after = MagicMock()

    def test_admin_shell_toggle_reflection(self):
        self.app.var_admin_shell = MagicMock()
        self.app.var_admin_shell.get.return_value = True
        self.app.sw_admin_shell = MagicMock()

        with patch("customtkinter.windows.widgets.core_widget_classes.CTkBaseClass"):
            # When admin shell is toggled
            with patch("tkinter.messagebox.askyesno", return_value=True):
                self.app._on_admin_shell_toggle()
                self.app.sw_admin_shell.configure.assert_called_with(
                    text="⚡ Admin / Modifizierend (Vollzugriff)"
                )

    def test_save_settings_persists_browser_and_updater(self):
        self.app.entry_port = MagicMock()
        self.app.entry_port.get.return_value = "8000"
        self.app.opt_host = MagicMock()
        self.app.opt_host.get.return_value = "127.0.0.1"
        self.app.opt_tunnel_mode = MagicMock()
        self.app.opt_tunnel_mode.get.return_value = "Direct / LAN IP"
        self.app.opt_endpoint_path = MagicMock()
        self.app.opt_endpoint_path.get.return_value = "/sse"
        self.app.var_enforce_auth = MagicMock()
        self.app.var_enforce_auth.get.return_value = True
        self.app.entry_token = MagicMock()
        self.app.entry_token.get.return_value = "saved_test_tok"
        self.app.var_enable_tls = MagicMock()
        self.app.var_enable_tls.get.return_value = False
        self.app.var_sandbox = MagicMock()
        self.app.var_sandbox.get.return_value = True
        self.app.entry_workspace = MagicMock()
        self.app.entry_workspace.get.return_value = "./workspace"

        # Tab 2 / consolidated shell permission
        self.app.var_admin_shell = MagicMock()
        self.app.var_admin_shell.get.return_value = True

        # New v0.4.0 settings
        self.app.var_browser_auto_open = MagicMock()
        self.app.var_browser_auto_open.get.return_value = True
        self.app.entry_browser_start_url = MagicMock()
        self.app.entry_browser_start_url.get.return_value = "https://custom.mammouth.ai"
        self.app.var_auto_check_updates = MagicMock()
        self.app.var_auto_check_updates.get.return_value = False

        self.app.mammouth_browser = MagicMock()

        with patch("gui.save_config") as mock_save, \
             patch("tkinter.messagebox.showinfo"):
            self.app._save_settings()

            mock_save.assert_called_once()
            cfg = self.app.config_data
            self.assertTrue(cfg["server"]["allow_admin_shell"])
            self.assertFalse(cfg["server"]["auto_check_updates"])
            self.assertTrue(cfg["embedded_browser"]["auto_open_on_server_start"])
            self.assertEqual(cfg["embedded_browser"]["start_page"], "https://custom.mammouth.ai")
            self.assertEqual(self.app.mammouth_browser.start_url, "https://custom.mammouth.ai")

    def test_auto_open_mammouth_on_server_start(self):
        self.app.is_server_running = False
        self.app.status_badge = MagicMock()
        self.app.btn_toggle_server = MagicMock()
        self.app._calculate_active_endpoint_url = MagicMock(return_value="http://127.0.0.1:8000/sse")

        # Mock socket to ensure port is reported as free
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1  # 1 = connection failed, port is free

        with patch("socket.socket", return_value=mock_sock), \
             patch("gui.threading.Thread"), \
             patch("uvicorn.Config"), \
             patch("uvicorn.Server"), \
             patch("gui.build_app"):
            self.app._start_server()

            self.assertTrue(self.app.is_server_running)
            # Verify after() was called with 500ms and _switch_to_mammouth_tab callback
            self.app.after.assert_called_with(500, self.app._switch_to_mammouth_tab)

    def test_calculate_active_endpoint_url_never_exposes_token(self):
        self.app.config_data["server"]["enforce_auth"] = True
        self.app.config_data["server"]["api_token"] = "tok_mammouth_secret_123"
        self.app.config_data["server"]["tunnel_mode"] = "Direct / LAN IP"
        self.app.config_data["server"]["endpoint_path"] = "/sse"

        # Active endpoint url must be clean and never contain query tokens
        url = self.app._calculate_active_endpoint_url()
        self.assertNotIn("token=", url)
        self.assertNotIn("tok_mammouth_secret_123", url)

    def test_update_banner_on_update_found(self):
        self.app.btn_update_badge = MagicMock()
        self.app.update_banner = MagicMock()
        self.app.lbl_update_banner_text = MagicMock()
        self.app.endpoint_card = MagicMock()

        update_info = {"version": "v0.4.1", "name": "v0.4.1 Release"}
        self.app._on_update_found(update_info)

        self.assertEqual(self.app.available_update, update_info)
        self.app.btn_update_badge.configure.assert_called_with(text="🔄 Update: v0.4.1")
        self.app.btn_update_badge.pack.assert_called_with(side="left", padx=(0, 8))
        self.app.lbl_update_banner_text.configure.assert_called()
        self.app.update_banner.pack.assert_called_with(fill="x", padx=10, pady=(10, 0), before=self.app.endpoint_card)


class TestInstallerPowerShellSyntax(unittest.TestCase):
    def test_install_ps1_syntax_valid(self):
        ps1_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "install.ps1"))
        self.assertTrue(os.path.exists(ps1_path), f"install.ps1 not found at {ps1_path}")

        # Validate PowerShell script syntax using Parser::ParseFile
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"& {{ $errs = $null; $toks = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{ps1_path}', [ref]$toks, [ref]$errs); if ($errs.Count -eq 0) {{ 'SYNTAX_OK' }} else {{ $errs | ForEach-Object {{ $_.ToString() }} }} }}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"PowerShell syntax check failed:\n{res.stderr}")
        self.assertIn("SYNTAX_OK", res.stdout)

    def test_install_ps1_cleanup_logic(self):
        ps1_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "install.ps1"))
        content = Path(ps1_path).read_text(encoding="utf-8")
        self.assertIn("Remove-Item $TempZip", content)
        self.assertIn("MDefInst_*", content)
        self.assertIn("MammouthDefroster9000*", content)


class TestOAuthHardening(unittest.TestCase):
    def test_verify_pkce_enforces_s256_and_rejects_plain(self):
        from server import _verify_pkce
        import hashlib
        import base64

        # S256 test
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge_s256 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        self.assertTrue(_verify_pkce(verifier, challenge_s256, "S256"))
        self.assertFalse(_verify_pkce("wrong_verifier", challenge_s256, "S256"))

        # Plain test must be strictly rejected per RFC 7636 / OAuth 2.1 hardening
        challenge_plain = "plain_secret_code_12345"
        self.assertFalse(_verify_pkce(challenge_plain, challenge_plain, "plain"))

    def test_get_base_url_https_for_public_tunnels(self):
        from server import _get_base_url
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"host", b"desktop-sdm42jr.taila2d74a.ts.net"),
            ],
            "scheme": "http"
        }
        req = Request(scope)
        base = _get_base_url(req)
        self.assertEqual(base, "https://desktop-sdm42jr.taila2d74a.ts.net")

    def test_anti_clickjacking_headers(self):
        from server import SecurityAndAuthMiddleware
        from starlette.responses import PlainTextResponse

        async def dummy_app(scope, receive, send):
            response = PlainTextResponse("OK")
            await response(scope, receive, send)

        middleware = SecurityAndAuthMiddleware(dummy_app, token="mc_test", enforce_auth=False)

        # Test OAuth route gets CSP frame-ancestors and no X-Frame-Options: DENY
        sent_messages_oauth = []
        async def send_oauth(msg):
            sent_messages_oauth.append(msg)

        scope_oauth = {"type": "http", "method": "GET", "path": "/oauth/authorize", "headers": []}
        import asyncio
        asyncio.run(middleware(scope_oauth, None, send_oauth))

        start_msg = [m for m in sent_messages_oauth if m["type"] == "http.response.start"][0]
        headers_oauth = dict(start_msg["headers"])
        self.assertIn(b"content-security-policy", headers_oauth)
        self.assertIn(b"frame-ancestors 'self' https://mammouth.ai", headers_oauth[b"content-security-policy"])
        self.assertNotIn(b"x-frame-options", headers_oauth)

        # Test MCP route gets X-Frame-Options: DENY
        sent_messages_mcp = []
        async def send_mcp(msg):
            sent_messages_mcp.append(msg)

        scope_mcp = {"type": "http", "method": "GET", "path": "/mcp", "headers": []}
        asyncio.run(middleware(scope_mcp, None, send_mcp))

        start_msg_mcp = [m for m in sent_messages_mcp if m["type"] == "http.response.start"][0]
        headers_mcp = dict(start_msg_mcp["headers"])
        self.assertEqual(headers_mcp.get(b"x-frame-options"), b"DENY")


class TestEmbeddedBrowserFeatures(unittest.TestCase):
    def test_is_download_uri_detection(self):
        from modules.embedded_browser import _is_download_uri

        # Download file extensions
        self.assertTrue(_is_download_uri("https://mammouth.ai/files/export_123.zip"))
        self.assertTrue(_is_download_uri("https://s3.amazonaws.com/bucket/data.csv?token=secret"))
        self.assertTrue(_is_download_uri("https://cdn.mammouth.ai/doc.pdf"))
        self.assertTrue(_is_download_uri("https://mammouth.ai/api/v1/export/session.json"))
        self.assertTrue(_is_download_uri("https://mammouth.ai/api/export_chat"))
        self.assertTrue(_is_download_uri("https://mammouth.ai/v1/artifacts/download?id=99"))

        self.assertFalse(_is_download_uri("https://mammouth.ai"))
        self.assertFalse(_is_download_uri("https://mammouth.ai/chat/conv_123"))
        self.assertFalse(_is_download_uri("https://accounts.google.com/o/oauth2/v2/auth"))
        self.assertFalse(_is_download_uri(""))

    def test_is_trusted_browser_origin(self):
        from modules.embedded_browser import _is_trusted_browser_origin

        self.assertTrue(_is_trusted_browser_origin("https://mammouth.ai/chat"))
        self.assertTrue(_is_trusted_browser_origin("https://app.mammouth.ai"))
        self.assertTrue(_is_trusted_browser_origin("http://127.0.0.1:8000/oauth/authorize"))
        self.assertTrue(_is_trusted_browser_origin("http://localhost:8000"))
        self.assertTrue(_is_trusted_browser_origin("blob:https://mammouth.ai/123"))

        # Untrusted external origins
        self.assertFalse(_is_trusted_browser_origin("https://malicious-site.com"))
        self.assertFalse(_is_trusted_browser_origin("https://attacker.org/steal"))
        self.assertFalse(_is_trusted_browser_origin(""))

    def test_embedded_browser_download_settings(self):
        from webview.platforms import edgechromium
        self.assertTrue(edgechromium.webview_settings.get("ALLOW_DOWNLOADS"))

    def test_show_download_notification(self):
        from modules.embedded_browser import MammouthBrowserFrame
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.lbl_download_status = MagicMock()
        frame.after = MagicMock()

        frame._show_download_notification("✓ Fertig heruntergeladen", success=True)
        frame.lbl_download_status.configure.assert_called_with(
            text="✓ Fertig heruntergeladen",
            text_color="#10B981"
        )
        frame.after.assert_called_with(6000, unittest.mock.ANY)

        frame._show_download_notification("⚠ Fehler aufgetreten", success=False)
        frame.lbl_download_status.configure.assert_called_with(
            text="⚠ Fehler aufgetreten",
            text_color="#EF4444"
        )

    def test_on_download_starting_dialog_ok(self):
        from modules.embedded_browser import MammouthBrowserFrame
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.lbl_download_status = MagicMock()
        frame.after = MagicMock()
        frame._prompt_save_file = MagicMock(return_value="C:\\Users\\User\\Downloads\\report.pdf")

        mock_op = MagicMock()
        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Temp\\report.pdf"
        mock_args.DownloadOperation = mock_op
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral

        frame._on_download_starting(None, mock_args)

        mock_args.set_ResultFilePath.assert_called_with("C:\\Users\\User\\Downloads\\report.pdf")
        mock_args.set_Handled.assert_called_with(True)
        mock_deferral.Complete.assert_called_once()
        self.assertTrue(any("StateChanged" in str(c) for c in mock_op.mock_calls))

    def test_on_download_starting_dialog_cancel(self):
        from modules.embedded_browser import MammouthBrowserFrame
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.lbl_download_status = MagicMock()
        frame.after = MagicMock()
        frame._prompt_save_file = MagicMock(return_value=None)

        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Temp\\report.pdf"
        mock_args.DownloadOperation = MagicMock()
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral

        frame._on_download_starting(None, mock_args)

        mock_args.set_Cancel.assert_called_with(True)
        mock_deferral.Complete.assert_called_once()

    def test_on_download_starting_fallback_on_exception(self):
        from modules.embedded_browser import MammouthBrowserFrame
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.lbl_download_status = MagicMock()
        frame.after = MagicMock()
        frame._prompt_save_file = MagicMock(side_effect=RuntimeError("GUI disabled"))

        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Temp\\artifact.zip"
        mock_args.DownloadOperation = MagicMock()
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral

        frame._on_download_starting(None, mock_args)

        # Must fallback to saving in Downloads folder instead of dropping download
        self.assertTrue(mock_args.set_ResultFilePath.called)
        saved_path = mock_args.set_ResultFilePath.call_args[0][0]
        self.assertTrue(saved_path.endswith("artifact.zip"))
        mock_args.set_Handled.assert_called_with(True)
        mock_deferral.Complete.assert_called_once()

class TestSecurityAuditBlockerFixes(unittest.TestCase):
    """Verifies that fail-closed security gates H-1, H-2, and H-3 are properly enforced."""

    def test_h1_middleware_auto_generates_token_and_fails_closed(self):
        """H-1: Ensure middleware fails closed with empty token by auto-generating a secure token."""
        import asyncio
        from server import SecurityAndAuthMiddleware

        dummy_app = MagicMock()
        middleware = SecurityAndAuthMiddleware(
            app=dummy_app,
            token="",
            enforce_auth=True
        )

        # Token must not be empty - an auto-generated token must be assigned
        self.assertTrue(middleware.token.startswith("mc_"))
        self.assertGreater(len(middleware.token), 32)

        # Simulated request without Authorization header must fail closed (401)
        async def run_req(headers, path="/sse"):
            messages = []
            async def mock_receive():
                return {"type": "http.request"}
            async def mock_send(msg):
                messages.append(msg)
            scope = {
                "type": "http",
                "path": path,
                "headers": headers,
                "client": ("127.0.0.1", 12345),
            }
            await middleware(scope, mock_receive, mock_send)
            return messages

        # 1. No auth -> 401
        res = asyncio.run(run_req([]))
        self.assertTrue(any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in res))

        # 2. Bad auth -> 401
        res_bad = asyncio.run(run_req([(b"authorization", b"Bearer wrong-token")]))
        self.assertTrue(any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in res_bad))

        # 3. Good auth -> passes to app
        good_auth = f"Bearer {middleware.token}".encode("utf-8")
        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
        middleware.app = fake_app
        res_good = asyncio.run(run_req([(b"authorization", good_auth)]))
        self.assertTrue(any(m.get("type") == "http.response.start" and m.get("status") == 200 for m in res_good))

    def test_h2_updater_checksum_mandatory_and_verified(self):
        """H-2: Ensure updater refuses updates without SHA256 checksum asset or when checksum mismatches."""
        from modules.updater import check_for_update, download_and_verify_update
        import hashlib

        # 1. check_for_update returns None when .sha256 asset is missing
        release_no_sha = {
            "tag_name": "v9.9.9",
            "assets": [
                {"name": "MammouthDefroster9000-v9.9.9-windows-x64.zip", "browser_download_url": "https://example.com/app.zip", "size": 1000}
            ]
        }
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = release_no_sha
        mock_client.get.return_value = mock_resp
        mock_client.__enter__.return_value = mock_client

        with patch("httpx.Client", return_value=mock_client):
            info = check_for_update("0.3.2")
            self.assertIsNone(info, "check_for_update must reject releases without .sha256 asset")

        # 2. download_and_verify_update fails closed without sha256_url
        ok, err = download_and_verify_update({"download_url": "https://example.com/app.zip"})
        self.assertFalse(ok)
        self.assertIn("Security Error", err)

        # 3. download_and_verify_update fails when hash mismatches
        fake_zip_bytes = b"PK\x03\x04fakearchivecontent"
        correct_hash = hashlib.sha256(fake_zip_bytes).hexdigest()
        bad_hash = "0000000000000000000000000000000000000000000000000000000000000000"

        sha_resp = MagicMock()
        sha_resp.status_code = 200
        sha_resp.text = f"{bad_hash}  app.zip\n"

        stream_resp = MagicMock()
        stream_resp.status_code = 200
        stream_resp.iter_bytes.return_value = [fake_zip_bytes]
        stream_resp.__enter__.return_value = stream_resp

        mock_dl_client = MagicMock()
        mock_dl_client.get.return_value = sha_resp
        mock_dl_client.stream.return_value = stream_resp
        mock_dl_client.__enter__.return_value = mock_dl_client

        with patch("httpx.Client", return_value=mock_dl_client):
            ok, err = download_and_verify_update({
                "zip_url": "https://example.com/app.zip",
                "zip_name": "app.zip",
                "zip_size": len(fake_zip_bytes),
                "sha256_url": "https://example.com/app.zip.sha256"
            })
            self.assertFalse(ok)
            self.assertIn("Checksum mismatch", err)

        # 4. download_and_verify_update succeeds when hash matches
        sha_resp.text = f"{correct_hash}  app.zip\n"
        with patch("httpx.Client", return_value=mock_dl_client):
            ok, res_path = download_and_verify_update({
                "zip_url": "https://example.com/app.zip",
                "zip_name": "app.zip",
                "zip_size": len(fake_zip_bytes),
                "sha256_url": "https://example.com/app.zip.sha256"
            })
            self.assertTrue(ok)
            self.assertTrue(res_path.endswith("app.zip"))
            self.assertTrue(os.path.exists(res_path))

    def test_h3_remote_execution_hmac_enforced(self):
        """H-3: Ensure RemoteExecutionConfig generates session key and pongs require HMAC challenge/response."""
        from modules.remote_execution import (
            RemoteExecutionConfig,
            _RemoteExecutionBroadcastConnection,
            _RemoteExecutionMessage,
            _generate_hmac_challenge,
            _compute_hmac_response,
            _ACTIVE_NONCES
        )

        # 1. Auto-generates token if empty
        cfg = RemoteExecutionConfig(api_token="")
        self.assertTrue(cfg.api_token.startswith("ue_sec_"))
        self.assertGreater(len(cfg.api_token), 20)

        conn = _RemoteExecutionBroadcastConnection(cfg, "local_test_node")
        from modules.remote_execution import _RemoteExecutionBroadcastNodes
        conn._nodes = _RemoteExecutionBroadcastNodes()

        # 2. Pong missing challenge_nonce or challenge_hmac is dropped
        msg_no_hmac = _RemoteExecutionMessage("pong", "remote_node_1", data={"engine_version": "5.3"})
        conn._handle_pong_message(msg_no_hmac)
        self.assertEqual(len(conn.remote_nodes), 0, "Pong without nonce/hmac must be dropped")

        # 3. Pong with bad hmac is dropped
        nonce = _generate_hmac_challenge()
        msg_bad_hmac = _RemoteExecutionMessage("pong", "remote_node_2", data={
            "challenge_nonce": nonce,
            "challenge_hmac": "invalid_hmac_signature"
        })
        conn._handle_pong_message(msg_bad_hmac)
        self.assertEqual(len(conn.remote_nodes), 0, "Pong with invalid HMAC must be dropped")

        # 4. Valid pong is accepted
        valid_nonce = _generate_hmac_challenge()
        valid_hmac = _compute_hmac_response(cfg.api_token, valid_nonce)
        msg_valid = _RemoteExecutionMessage("pong", "remote_node_3", data={
            "challenge_nonce": valid_nonce,
            "challenge_hmac": valid_hmac,
            "engine_version": "5.3.2"
        })
        conn._handle_pong_message(msg_valid)
        self.assertEqual(len(conn.remote_nodes), 1)
        self.assertEqual(conn.remote_nodes[0]["node_id"], "remote_node_3")


if __name__ == "__main__":
    unittest.main()
