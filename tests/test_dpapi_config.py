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

    def test_save_config_preserves_plaintext_token(self):
        """Test that save_config saves the original plaintext key and does not hash it with DPAPI."""
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            tmp_path = Path(tmp.name)
        try:
            import config
            orig_file = config.CONFIG_FILE
            config.CONFIG_FILE = tmp_path
            cfg_data = {"server": {"api_token": "original_secret_key_456"}}
            save_config(cfg_data)

            with open(tmp_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["server"]["api_token"], "original_secret_key_456")
            self.assertFalse(saved["server"]["api_token"].startswith("dpapi:"))
        finally:
            config.CONFIG_FILE = orig_file
            if tmp_path.exists():
                tmp_path.unlink()

    def test_load_config_migrates_dpapi_to_original_key(self):
        """Test that load_config automatically converts legacy dpapi: tokens to original plaintext keys."""
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            tmp_path = Path(tmp.name)
        try:
            import config
            orig_file = config.CONFIG_FILE
            config.CONFIG_FILE = tmp_path

            token_val = "migrated_token_secret_789"
            encrypted_tok = _encrypt_dpapi(token_val)
            initial_cfg = {"server": {"api_token": encrypted_tok}}
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(initial_cfg, f)

            loaded = load_config()
            # Token returned must be the decrypted original key
            if encrypted_tok.startswith("dpapi:"):
                self.assertEqual(loaded["server"]["api_token"], token_val)
            self.assertFalse(loaded["server"]["api_token"].startswith("dpapi:"))

            # And it must be saved back to disk in plaintext
            with open(tmp_path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertFalse(on_disk["server"]["api_token"].startswith("dpapi:"))
        finally:
            config.CONFIG_FILE = orig_file
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
