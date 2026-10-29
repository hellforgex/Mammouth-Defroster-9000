import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import DEFAULT_CONFIG
from modules.shell_processes import _validate_shell_command, desktop_open
from modules.putty_ssh import _sanitize_param, ssh_exec_command, ssh_transfer_file
from modules.mammouth_code import run_mammouth_task, launch_mammouth_terminal, install_or_update_mammouth_code
from modules.updater import _verify_zip_slip_safe


class TestV072SecurityAndFeatures(unittest.TestCase):
    def test_a01_mammouth_code_defaults_and_gates(self):
        """A-01: mammouth_code module disabled by default and gated by admin shell."""
        self.assertFalse(DEFAULT_CONFIG["modules"]["mammouth_code"]["enabled"])
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            with self.assertRaises(PermissionError):
                run_mammouth_task("create file test.py")
            with self.assertRaises(PermissionError):
                launch_mammouth_terminal()
            with self.assertRaises(PermissionError):
                install_or_update_mammouth_code()

    def test_b01_colon_parameter_path_guard(self):
        """B-01: Parameter colon syntax (-Path:C:\\...) blocked in Read-Only mode."""
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Content -Path:C:\\Windows\\win.ini", allow_admin=False)
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-Content -LiteralPath:C:\\Users\\Public\\secret.txt", allow_admin=False)

    def test_b02_universal_cmdlet_path_guard(self):
        """B-02: File inspection cmdlets like Select-String outside workspace are blocked."""
        with self.assertRaises(PermissionError):
            _validate_shell_command("Select-String -Path C:\\Windows\\win.ini -Pattern admin", allow_admin=False)

    def test_b03_root_recurse_colon_guard(self):
        """B-03: Root recurse traversal blocked even when using colon syntax."""
        with self.assertRaises(PermissionError):
            _validate_shell_command("Get-ChildItem -Path:C:\\ -Recurse", allow_admin=False)
        with self.assertRaises(PermissionError):
            _validate_shell_command("dir /s C:\\", allow_admin=False)

    def test_b07_admin_blacklist_defense_in_depth(self):
        """B-07: Verify curl, wget, Start-Process, pwsh -c, and python -c are blocked in admin mode."""
        blocked_commands = [
            "curl.exe https://example.com/payload.exe",
            "wget https://example.com/payload.exe",
            "Start-Process powershell.exe",
            "saps notepad.exe",
            'pwsh.exe -c "Get-Process"',
            'python.exe -c "import urllib.request"',
            'py -c "import os"',
            'Invoke-Command -ScriptBlock { dir }'
        ]
        for cmd in blocked_commands:
            with self.assertRaises(PermissionError, msg=f"Command '{cmd}' should be blocked"):
                _validate_shell_command(cmd, allow_admin=True)

    def test_b08_desktop_open_admin_gate(self):
        """B-08: desktop_open rejects arguments and executable launches in Read-Only mode."""
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            # Passing arguments is blocked
            with self.assertRaises(PermissionError):
                desktop_open("notepad.exe", arguments="test.txt")
            # Executables are blocked
            with self.assertRaises(PermissionError):
                desktop_open("powershell.exe")
            with self.assertRaises(PermissionError):
                desktop_open("script.bat")
            with self.assertRaises(PermissionError):
                desktop_open("tool.ps1")
            # URLs are permitted
            with patch("os.startfile"):
                res = desktop_open("https://mammouth.ai")
                self.assertEqual(res["status"], "success")

    def test_b09_putty_ssh_defaults_and_gates(self):
        """B-09: putty_ssh disabled by default, gated on admin, and param sanitization rejects leading '-'."""
        self.assertFalse(DEFAULT_CONFIG["modules"]["putty_ssh"]["enabled"])
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            with self.assertRaises(PermissionError):
                ssh_exec_command("192.168.1.10", "whoami")
            with self.assertRaises(PermissionError):
                ssh_transfer_file("192.168.1.10", "local.txt", "/tmp/remote.txt")

        # Leading '-' rejected in parameter sanitization
        with self.assertRaises(ValueError):
            _sanitize_param("-load", "session")
        with self.assertRaises(ValueError):
            _sanitize_param("-P 22", "port")

    def test_c01_zip_slip_verification(self):
        """C-01 / C-04: Verify archive traversal checks detect and prevent Zip-Slip."""
        import zipfile
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            zip_path = tf.name

        try:
            # Create malicious zip with directory traversal
            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("../../etc/cron.d/evil", "malicious payload")
            self.assertFalse(_verify_zip_slip_safe(zip_path))

            # Create safe zip
            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("subfolder/safe_file.txt", "harmless content")
            self.assertTrue(_verify_zip_slip_safe(zip_path))
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def test_daily_autoupdate_check_gate(self):
        """Verify startup auto-update check enforces 1x daily interval unless manual."""
        from gui import MammouthControlCenter
        # Mock instance
        mock_gui = MagicMock()
        mock_gui.config_data = {
            "server": {
                "auto_check_updates": True,
                "last_update_check_time": time.time() - 3600  # 1 hour ago
            }
        }
        mock_gui._log = MagicMock()

        # Non-manual call should skip
        MammouthControlCenter._check_updates_async(mock_gui, manual=False)
        mock_gui._log.assert_called_with("[UPDATER] Daily update check skipped (last checked less than 24 hours ago).")


if __name__ == "__main__":
    unittest.main()
