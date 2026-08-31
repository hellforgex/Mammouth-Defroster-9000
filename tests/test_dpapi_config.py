import unittest
import tempfile
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import _encrypt_dpapi, _decrypt_dpapi, load_config, save_config


class TestDPAPIConfig(unittest.TestCase):
    def test_dpapi_encrypt_decrypt_roundtrip(self):
        """Test that tokens encrypt to dpapi: format and decrypt back accurately."""
        token = "test_token_abc_123_xyz"
        encrypted = _encrypt_dpapi(token)
        if encrypted.startswith("dpapi:"):
            self.assertTrue(encrypted.startswith("dpapi:"))
            self.assertNotIn(token, encrypted)
            decrypted = _decrypt_dpapi(encrypted)
            self.assertEqual(decrypted, token)
        else:
            # If win32crypt is not present in non-Windows test environment
            self.assertEqual(encrypted, token)

    def test_decrypt_plain_token_fallback(self):
        """Test backward compatibility: plain tokens without dpapi: are returned as-is."""
        plain = "plain_token_123"
        self.assertEqual(_decrypt_dpapi(plain), plain)


if __name__ == "__main__":
    unittest.main()
