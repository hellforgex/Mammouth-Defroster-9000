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
        app.after = MagicMock()
        app._switch_to_mammouth_tab = MagicMock()

        with patch("socket.socket.connect_ex", return_value=1), \
             patch("gui.threading.Thread") as mock_thread, \
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


    def test_icon_candidates_discovery(self):
        """Test that icon candidates list covers _internal, root assets, and dev assets."""
        from gui import BASE_DIR
        from pathlib import Path
        
        candidates = [
            BASE_DIR / "assets" / "icon.ico",
            BASE_DIR / "_internal" / "assets" / "icon.ico",
            Path(__file__).parent.parent / "assets" / "icon.ico",
        ]
        # At least one candidate must exist in the repository layout
        found_any = any(c.exists() for c in candidates)
        self.assertTrue(found_any, "No icon.ico was found in any standard candidate path!")

    def test_tray_manager_icon_loading(self):
        """Test that DefrosterTrayApp.load_icon_image loads a valid image."""
        from tray_manager import DefrosterTrayApp
        tray_app = DefrosterTrayApp()
        img = tray_app.load_icon_image()
        self.assertIsNotNone(img)
        self.assertGreater(img.size[0], 0)
        self.assertGreater(img.size[1], 0)


class TestTaskSchedulerGuiRegression(unittest.TestCase):
    def test_gui_scheduler_initialization_and_handlers(self):
        """Test that MammouthControlCenter initializes TaskSchedulerEngine with all required handlers."""
        from gui import MammouthControlCenter
        from modules.task_scheduler import TaskSchedulerEngine

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.after = MagicMock()
        app._switch_to_mammouth_tab = MagicMock()
        app.mammouth_browser = MagicMock()

        app._init_task_scheduler()
        self.assertTrue(hasattr(app, "task_countdown_labels"))
        self.assertIsInstance(app.task_countdown_labels, dict)

        engine = TaskSchedulerEngine.get_instance()
        self.assertIn("mammouth_web", engine._handlers)
        self.assertIn("mammouth_code", engine._handlers)
        self.assertIn("powershell", engine._handlers)
        self.assertIn("notification", engine._handlers)

        # Test web trigger handler invocation
        res = app._on_trigger_mammouth_web_task({
            "name": "Livebericht Test",
            "prompt": "Test prompt",
            "runs_done": 0,
            "switch_tab": True,
            "auto_submit": True
        })
        self.assertEqual(res, "Dispatched to Mammouth AI Web")
        app.after.assert_called()

    def test_browser_has_send_chat_prompt(self):
        """Test that MammouthBrowserFrame defines send_chat_prompt."""
        from modules.embedded_browser import MammouthBrowserFrame
        self.assertTrue(hasattr(MammouthBrowserFrame, "send_chat_prompt"))

    def test_zen_mode_toggle_behavior(self):
        """Test that toggle_zen_mode collapses/restores sidebar and updates UI elements."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.sidebar_visible = True
        app.zen_mode_active = False
        app.sidebar = MagicMock()
        app.content_area = MagicMock()
        app.btn_toggle_sidebar = MagicMock()
        app.btn_zen_header = MagicMock()
        app.mammouth_browser = MagicMock()
        app._select_nav_tab = MagicMock()
        app._log = MagicMock()

        # Activate Zen Mode
        app.toggle_zen_mode(True)
        self.assertTrue(app.zen_mode_active)
        self.assertFalse(app.sidebar_visible)
        app.sidebar.pack_forget.assert_called_once()
        app.btn_toggle_sidebar.configure.assert_called_with(text="☰")
        app._select_nav_tab.assert_called_with("💬 Mammouth AI Web")
        app.mammouth_browser.set_zen_state.assert_called_with(True)

        # Deactivate Zen Mode
        app.toggle_zen_mode(False)
        self.assertFalse(app.zen_mode_active)
        self.assertTrue(app.sidebar_visible)
        app.sidebar.pack.assert_called_once()
        app.btn_toggle_sidebar.configure.assert_called_with(text="◀")
        app.mammouth_browser.set_zen_state.assert_called_with(False)

    def test_global_hotkey_manager_lifecycle(self):
        """Test global hotkey registration, status inspection, and unregistration."""
        from modules.global_hotkey import register_global_hotkey, unregister_global_hotkey, is_global_hotkey_registered

        called = []
        registered = register_global_hotkey(lambda: called.append(True), key="F12", modifiers="Ctrl+Alt", hotkey_id=9998)
        self.assertTrue(registered)
        self.assertTrue(is_global_hotkey_registered())

        unregister_global_hotkey()
        self.assertFalse(is_global_hotkey_registered())

    def test_theme_palette_constants(self):
        """Verify Mammouth AI brand theme palette constants are defined."""
        from gui import THEME_BG, THEME_HEADER_BG, THEME_CARD_BG, THEME_ACCENT, THEME_SUCCESS

        self.assertEqual(THEME_BG, ("#F2EBE1", "#242428"))
        self.assertEqual(THEME_HEADER_BG, ("#EDE3D4", "#1E1E22"))
        self.assertEqual(THEME_CARD_BG, ("#FCFAF7", "#2F2F33"))
        self.assertEqual(THEME_ACCENT, ("#9F6C45", "#B88557"))
        self.assertEqual(THEME_SUCCESS, ("#2E7D32", "#10B981"))


if __name__ == "__main__":
    unittest.main()


