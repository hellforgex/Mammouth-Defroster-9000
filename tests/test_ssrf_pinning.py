import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.web_tools import _validate_url_ssrf_safe, _resolve_and_validate_ip


class TestSSRFProtection(unittest.TestCase):
    def test_ssrf_blocks_localhost_and_loopback(self):
        """Test localhost and 127.0.0.1 are blocked."""
        bad_urls = [
            "http://localhost:8000/api",
            "http://127.0.0.1:8000",
            "https://127.0.0.1/admin",
            "http://test.localhost",
            "http://[::1]:8000"
        ]
        for url in bad_urls:
            with self.assertRaises(PermissionError, msg=f"Expected '{url}' to be blocked"):
                _validate_url_ssrf_safe(url)

    def test_ssrf_blocks_private_and_metadata_subnets(self):
        """Test private subnets (10.x, 192.168.x, 172.16.x) and metadata IPs are blocked."""
        bad_urls = [
            "http://192.168.1.1/router",
            "http://10.0.0.5:8080",
            "http://172.16.0.1",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/"
        ]
        for url in bad_urls:
            with self.assertRaises(PermissionError, msg=f"Expected '{url}' to be blocked"):
                _validate_url_ssrf_safe(url)

    def test_ssrf_invalid_schemes_rejected(self):
        """Test non-http/https schemes (file://, gopher://) are rejected."""
        bad_schemes = [
            "file:///etc/passwd",
            "file:///C:/Windows/win.ini",
            "gopher://127.0.0.1:70",
            "ftp://ftp.example.com"
        ]
        for url in bad_schemes:
            with self.assertRaises(ValueError, msg=f"Expected '{url}' to be rejected"):
                _validate_url_ssrf_safe(url)


if __name__ == "__main__":
    unittest.main()
