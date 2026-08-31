import unittest
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.file_ops import _validate_path, _normalize_and_resolve_path, file_write, file_read


class TestFileSandbox(unittest.TestCase):
    def test_unc_prefix_normalization(self):
        """Test UNC prefixes are normalized."""
        if os.name == 'nt':
            p1 = _normalize_and_resolve_path(r"\\?\C:\Windows\System32")
            self.assertTrue(p1.casefold().startswith(r"c:\windows\system32".casefold()))
            self.assertFalse(p1.startswith("\\\\?\\"))

    def test_blocked_write_roots_casefolding(self):
        """Test system directories are blocked for writing regardless of case."""
        if os.name == 'nt':
            bad_paths = [
                r"c:\windows\test.txt",
                r"C:\WINDOWS\system32\drivers\etc\hosts",
                r"\\?\C:\Program Files\evil.exe",
                r"c:\program files (x86)\test.dll",
                r"C:\ProgramData\payload.bat",
            ]
            for bp in bad_paths:
                with self.assertRaises(PermissionError):
                    _validate_path(bp, for_write=True)

    def test_blocked_sensitive_user_dirs(self):
        """Test sensitive user credential directories (.ssh, .aws, etc.) are blocked for write."""
        if os.name == 'nt':
            sensitive_paths = [
                r"C:\Users\admin\.ssh\authorized_keys",
                r"C:\Users\User\.aws\credentials",
                r"C:\Users\Default\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\evil.vbs",
                r"C:\Users\User\.azure\tokens.json",
                r"C:\Users\User\.kube\config",
                r"C:\Users\User\.gnupg\secring.gpg"
            ]
            for sp in sensitive_paths:
                with self.assertRaises(PermissionError):
                    _validate_path(sp, for_write=True)

    def test_null_byte_rejection(self):
        """Test paths with null bytes are rejected with ValueError."""
        with self.assertRaises(ValueError):
            _validate_path("test\0file.txt", for_write=False)
        with self.assertRaises(ValueError):
            _validate_path("test\0file.txt", for_write=True)


if __name__ == "__main__":
    unittest.main()
