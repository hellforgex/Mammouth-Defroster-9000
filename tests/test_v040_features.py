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

    def test_calculate_active_endpoint_url_with_token(self):
        self.app._calculate_active_endpoint_url = MagicMock(return_value="https://test.ts.net/sse")
        self.app.config_data["server"]["enforce_auth"] = True
        self.app.config_data["server"]["api_token"] = "tok_mammouth_secret_123"

        # Active endpoint url with token must append token
        url_with_tok = self.app._calculate_active_endpoint_url_with_token()
        self.assertEqual(url_with_tok, "https://test.ts.net/sse?token=tok_mammouth_secret_123")

        # When auth is disabled, token should not be appended
        self.app.config_data["server"]["enforce_auth"] = False
        url_no_tok = self.app._calculate_active_endpoint_url_with_token()
        self.assertEqual(url_no_tok, "https://test.ts.net/sse")

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


if __name__ == "__main__":
    unittest.main()
