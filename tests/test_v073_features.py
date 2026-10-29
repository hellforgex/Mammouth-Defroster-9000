import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import gui
import server
from modules.updater import apply_update_and_restart


class TestV073Features(unittest.TestCase):
    def test_version_bump_v073(self):
        """Verify version strings are properly bumped to v0.7.3."""
        self.assertEqual(gui.APP_VERSION, "v0.7.3")
        self.assertIn("v0.7.3", server.mcp.instructions or "")

    def test_apply_update_and_restart_script_robustness(self):
        """Verify apply_update_and_restart generates robust robocopy batch script with process wait and logging."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_zip = os.path.join(tmpdir, "update.zip")
            with open(dummy_zip, "w") as f:
                f.write("dummy")

            with patch("subprocess.Popen") as mock_popen:
                success = apply_update_and_restart(dummy_zip, r"C:\MammouthDefroster", 12345)
                self.assertTrue(success)
                mock_popen.assert_called_once()

            # Read the generated batch script
            bat_path = os.path.join(tmpdir, "apply_update.bat")
            self.assertTrue(os.path.exists(bat_path), "apply_update.bat should be created")
            script = open(bat_path, "r", encoding="utf-8").read()

            self.assertIn("WaitForExit(15000)", script, "Must wait cleanly for process PID to exit")
            self.assertIn("taskkill /f /im MammouthDefroster9000-server.exe", script, "Must terminate background server")
            self.assertIn("robocopy", script, "Must use robocopy for robust file transfer")
            self.assertIn("/R:5 /W:1", script, "Robocopy must configure retries on locked files")
            self.assertIn("/XF config.json oauth.db tasks.db memory.db hosts.json credentials.json", script, "Must exclude user databases")
            self.assertIn("Unblock-File", script, "Must unblock binaries to prevent SmartScreen issues")
            self.assertIn('start "" /D "%~2"', script, "Must set working directory explicitly on relaunch")
            self.assertIn("updater.log", script, "Must log execution output")

    def test_check_updates_async_manual_opens_dialog(self):
        """Verify _check_updates_async opens dialog immediately when update found on manual check."""
        mock_gui = MagicMock()
        mock_gui.config_data = {"server": {}}
        mock_gui._log = MagicMock()
        mock_gui._on_update_found = MagicMock()
        mock_gui._show_update_dialog = MagicMock()

        dummy_update = {"version": "v9.9.9", "zip_url": "http://example.com/upd.zip", "sha256_url": "http://example.com/sha"}
        with patch("gui.check_for_update", return_value=dummy_update), \
             patch("gui.save_config"):
            # Call worker logic directly
            gui.MammouthControlCenter._check_updates_async(mock_gui, manual=True)
            # Give worker thread a moment to execute
            import time
            time.sleep(0.1)

            # Verify dialog opened
            mock_gui.after.assert_any_call(0, mock_gui._show_update_dialog)


if __name__ == "__main__":
    unittest.main()
