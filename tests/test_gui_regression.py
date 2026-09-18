import unittest
from unittest.mock import MagicMock, patch
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestGuiStartServerRegression(unittest.TestCase):
    def test_start_server_host_port_resolution(self):
        """Test that _start_server does not raise NameError for host or port."""
        from gui import MammouthControlCenter

        # Use __new__ to avoid initializing Tkinter GUI in headless/test environments
        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.is_server_running = False
        app.uvicorn_server = None
        app.config_data = {
            "server": {
                "host": "127.0.0.1",
                "port": 8080,
                "enforce_auth": False,
                "api_token": "test-token-1234",
                "auto_tunnel": False
            }
        }
        app._log = MagicMock()
        app._refresh_all_endpoint_labels = MagicMock()
        app._calculate_active_endpoint_url = MagicMock(return_value="http://127.0.0.1:8080/sse")
        app.status_badge = MagicMock()
        app.btn_toggle_server = MagicMock()

        with patch("gui.threading.Thread") as mock_thread, \
             patch("uvicorn.Config") as mock_uvicorn_cfg, \
             patch("uvicorn.Server") as mock_uvicorn_server, \
             patch("gui.build_app") as mock_build_app:

            # Execute _start_server
            app._start_server()

            self.assertTrue(app.is_server_running)
            mock_uvicorn_cfg.assert_called_once()
            _, kwargs = mock_uvicorn_cfg.call_args
            self.assertEqual(kwargs.get("host"), "127.0.0.1")
            self.assertEqual(kwargs.get("port"), 8080)
            mock_build_app.assert_called_once_with(token="")

    def test_dashboard_key_visibility_toggle_and_refresh(self):
        """Test that _toggle_dash_key_visibility and _refresh_all_endpoint_labels display the original key."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.config_data = {
            "server": {
                "host": "127.0.0.1",
                "port": 8000,
                "api_token": "original_live_key_999",
                "tunnel_mode": "Direct / LAN IP",
                "endpoint_path": "/sse"
            }
        }
        app.lbl_public_url = MagicMock()
        app.lbl_local_url = MagicMock()
        app.lbl_dash_key = MagicMock()
        app.btn_toggle_dash_key = MagicMock()
        app.dash_token_visible = True

        app._refresh_all_endpoint_labels()
        app.lbl_dash_key.configure.assert_called_with(text="original_live_key_999")

        # Toggle visibility to hidden
        app._toggle_dash_key_visibility()
        self.assertFalse(app.dash_token_visible)
        app.lbl_dash_key.configure.assert_called_with(text="•" * 28)
        app.btn_toggle_dash_key.configure.assert_called_with(text="👁️ Show Key")

        # Toggle visibility back to shown
        app._toggle_dash_key_visibility()
        self.assertTrue(app.dash_token_visible)
        app.lbl_dash_key.configure.assert_called_with(text="original_live_key_999")
        app.btn_toggle_dash_key.configure.assert_called_with(text="🔒 Hide Key")

    def test_find_cloudflared_binary(self):
        """Test that find_cloudflared_binary resolves existing binary or custom path."""
        from gui import find_cloudflared_binary, BASE_DIR

        # If cloudflared.exe exists in mcpserv, it must be discovered
        cf_local = BASE_DIR / "cloudflared.exe"
        if cf_local.exists():
            found = find_cloudflared_binary()
            self.assertIsNotNone(found)
            self.assertTrue(os.path.exists(found))

        # Test custom path resolution
        with patch("os.path.exists") as mock_exists, patch("os.path.isfile", return_value=True):
            mock_exists.return_value = True
            found_custom = find_cloudflared_binary("C:\\tools\\cloudflared.exe")
            self.assertEqual(found_custom, os.path.abspath("C:\\tools\\cloudflared.exe"))

    def test_mode_change_triggers_tunnel_when_online(self):
        """Test that switching tunnel mode while server is online triggers the tunnel."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.is_server_running = True
        app.config_data = {
            "server": {
                "port": 8888,
                "tunnel_mode": "Direct / LAN IP"
            }
        }
        app.opt_tunnel_mode = MagicMock()
        app._refresh_all_endpoint_labels = MagicMock()
        app._log = MagicMock()
        app._start_cloudflare_tunnel = MagicMock()

        with patch("gui.save_config"):
            app._on_dash_mode_changed("Cloudflare Tunnel")
            app._start_cloudflare_tunnel.assert_called_once_with(8888)


if __name__ == "__main__":
    unittest.main()
