import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import DEFAULT_CONFIG, load_config
from modules.embedded_browser import MammouthBrowserFrame


class TestV072BrowserWindowAndLaunch(unittest.TestCase):
    def test_default_config_embedded_browser_settings(self):
        """Verify embedded browser default settings in configuration."""
        emb = DEFAULT_CONFIG.get("embedded_browser", {})
        self.assertTrue(emb.get("enabled"))
        self.assertTrue(emb.get("auto_open_on_server_start"))
        self.assertEqual(emb.get("start_page"), "https://mammouth.ai")

    def test_browser_frame_anti_shrink_geometry_guards(self):
        """Verify that set_tab_visible applies min dimensions and doesn't shrink HWND to 1x1."""
        with patch("modules.embedded_browser.user32") as mock_u32, \
             patch("customtkinter.CTkFrame"):
            frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
            frame.hwnd = 12345
            frame.is_embedded = True
            frame.viewport = MagicMock()
            frame.viewport.winfo_width.return_value = 1
            frame.viewport.winfo_height.return_value = 1
            frame.winfo_width = MagicMock(return_value=1)
            frame.winfo_height = MagicMock(return_value=1)
            frame.update_idletasks = MagicMock()
            frame.focus_browser = MagicMock()
            frame.after = MagicMock()

            # When tab becomes visible
            frame.set_tab_visible(True)

            self.assertTrue(frame._is_visible)
            mock_u32.ShowWindow.assert_called_with(12345, 5)  # SW_SHOW
            # MoveWindow must use min 400x300, NEVER 1x1
            mock_u32.MoveWindow.assert_called_with(12345, 0, 0, 400, 300, True)
            frame.focus_browser.assert_called_once()
            # Deferred resize should be scheduled
            self.assertEqual(frame.after.call_count, 2)

    def test_send_chat_prompt_initializes_if_needed(self):
        """Verify that send_chat_prompt ensures initialization when hwnd is None."""
        with patch("modules.embedded_browser.HAS_WEBVIEW2", True):
            frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
            frame.hwnd = None
            frame.is_embedded = False
            frame.ensure_initialized = MagicMock()
            frame.after = MagicMock()

            res = frame.send_chat_prompt("Hello Mammouth", auto_submit=True)
            self.assertTrue(res)
            frame.ensure_initialized.assert_called_once()
            frame.after.assert_called_once()

    def test_gui_top_bar_and_dashboard_buttons(self):
        """Verify that btn_open_mammouth is packed and dashboard button is present."""
        with patch("customtkinter.CTk.__init__"), \
             patch("gui.MammouthControlCenter.withdraw"), \
             patch("gui.load_config", return_value={"server": {"auto_start_server": True}, "embedded_browser": {"auto_open_on_server_start": True}}), \
             patch("gui.SplashScreen"), \
             patch("gui.MammouthControlCenter._build_ui"):
            from gui import MammouthControlCenter
            # Verify _switch_to_mammouth_tab sets active tab
            app = MammouthControlCenter.__new__(MammouthControlCenter)
            app.tabview = MagicMock()
            app._update_nav_highlight = MagicMock()
            app._on_tab_changed = MagicMock()

            app._switch_to_mammouth_tab()
            app.tabview.set.assert_called_with("💬 Mammouth AI Web")
            app._update_nav_highlight.assert_called_with("💬 Mammouth AI Web")
            app._on_tab_changed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
