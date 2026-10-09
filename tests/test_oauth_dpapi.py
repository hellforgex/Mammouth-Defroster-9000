import os
import sys
import unittest
import sqlite3
import time
import secrets
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from server import (
    OAUTH_DB_PATH,
    _init_oauth_db,
    _save_oauth_token,
    _is_valid_oauth_token,
    _refresh_oauth_token,
)
from config import _encrypt_dpapi, _decrypt_dpapi


class TestOAuthDPAPIEncryption(unittest.TestCase):
    """Test suite verifying DPAPI encryption and zero-plaintext fallback for OAuth tokens in SQLite."""

    def setUp(self):
        _init_oauth_db()
        self.test_access = f"mcp_at_{secrets.token_urlsafe(32)}"
        self.test_refresh = f"mcp_rt_{secrets.token_urlsafe(32)}"
        self.client_id = "test_dpapi_client"
        self.expires_at = time.time() + 3600

    def test_tokens_are_stored_dpapi_encrypted(self):
        """Verify tokens stored in SQLite start with 'dpapi:' and contain no plaintext."""
        _save_oauth_token(self.test_access, self.test_refresh, self.client_id, self.expires_at)

        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT access_token, refresh_token, client_id FROM oauth_tokens WHERE client_id = ?", (self.client_id,))
            rows = cur.fetchall()

        self.assertGreaterEqual(len(rows), 1)
        found = False
        for stored_at, stored_rt, cid in rows:
            # Must be DPAPI encrypted
            self.assertTrue(stored_at.startswith("dpapi:"), "access_token must start with dpapi:")
            self.assertTrue(stored_rt.startswith("dpapi:"), "refresh_token must start with dpapi:")

            # Must NOT contain plaintext token substring
            self.assertNotIn(self.test_access, stored_at)
            self.assertNotIn(self.test_refresh, stored_rt)

            # Decrypting should return original plaintext token
            dec_at = _decrypt_dpapi(stored_at)
            dec_rt = _decrypt_dpapi(stored_rt)
            if dec_at == self.test_access and dec_rt == self.test_refresh:
                found = True

        self.assertTrue(found, "Decrypted stored tokens must match original values")

    def test_token_validation_with_dpapi(self):
        """Verify _is_valid_oauth_token works transparently with DPAPI encrypted tokens."""
        _save_oauth_token(self.test_access, self.test_refresh, self.client_id, self.expires_at)
        self.assertTrue(_is_valid_oauth_token(self.test_access))

        # Random invalid token should be rejected
        self.assertFalse(_is_valid_oauth_token(f"mcp_at_{secrets.token_urlsafe(32)}"))

    def test_token_refresh_stores_encrypted_tokens(self):
        """Verify _refresh_oauth_token successfully rotates and encrypts new token pair."""
        _save_oauth_token(self.test_access, self.test_refresh, self.client_id, self.expires_at)

        refreshed = _refresh_oauth_token(self.test_refresh)
        self.assertIsNotNone(refreshed)
        new_at = refreshed["access_token"]
        new_rt = refreshed["refresh_token"]

        self.assertTrue(new_at.startswith("mcp_at_"))
        self.assertTrue(new_rt.startswith("mcp_rt_"))
        self.assertTrue(_is_valid_oauth_token(new_at))

        # Check DB row for the newly issued token
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT access_token, refresh_token FROM oauth_tokens WHERE client_id = ? ORDER BY rowid DESC LIMIT 1", (self.client_id,))
            latest_row = cur.fetchone()

        self.assertIsNotNone(latest_row)
        self.assertTrue(latest_row[0].startswith("dpapi:"))
        self.assertTrue(latest_row[1].startswith("dpapi:"))
        self.assertEqual(_decrypt_dpapi(latest_row[0]), new_at)
        self.assertEqual(_decrypt_dpapi(latest_row[1]), new_rt)

    def test_refresh_outlives_expired_access_token(self):
        """A refresh token stays usable after its access token expired (own refresh_expires_at)."""
        _save_oauth_token(self.test_access, self.test_refresh, self.client_id, time.time() - 10)
        self.assertFalse(_is_valid_oauth_token(self.test_access))

        refreshed = _refresh_oauth_token(self.test_refresh)
        self.assertIsNotNone(refreshed)
        self.assertTrue(_is_valid_oauth_token(refreshed["access_token"]))

    def test_frozen_build_uses_central_db_and_takes_over_local(self):
        """Release builds keep oauth.db in %APPDATA% and copy the install's DB there once."""
        import server
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "install"
            appdata = Path(tmp) / "appdata"
            root.mkdir()
            (root / "oauth.db").write_bytes(b"local-db")
            env = {"APPDATA": str(appdata), "MAMMOUTH_DEFROSTER_OAUTH_DB": ""}
            with patch.dict(os.environ, env), patch.object(server, "ROOT_DIR", root), \
                    patch.object(sys, "frozen", True, create=True):
                path = server._resolve_oauth_db_path()
                self.assertEqual(path, appdata / "MammouthDefroster9000" / "oauth.db")
                self.assertEqual(path.read_bytes(), b"local-db")
                # An existing central DB is never overwritten by a later install
                (root / "oauth.db").write_bytes(b"newer-install")
                self.assertEqual(server._resolve_oauth_db_path().read_bytes(), b"local-db")
            with patch.dict(os.environ, env), patch.object(server, "ROOT_DIR", root):
                self.assertEqual(server._resolve_oauth_db_path(), root / "oauth.db")

    def test_fail_closed_zero_plaintext_fallback(self):
        """Verify fail-closed principle: if DPAPI fails, error is raised and no plaintext is stored."""
        fake_token = f"mcp_at_fail_closed_test_{secrets.token_urlsafe(16)}"
        fake_refresh = f"mcp_rt_fail_closed_test_{secrets.token_urlsafe(16)}"

        # Mock CryptProtectData to raise an exception
        with patch("config.HAS_DPAPI", False):
            with self.assertRaises(RuntimeError):
                _save_oauth_token(fake_token, fake_refresh, "fail_closed_client", time.time() + 3600)

        # Verify NOTHING was inserted into SQLite in plaintext
        with sqlite3.connect(OAUTH_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM oauth_tokens WHERE access_token = ? OR refresh_token = ?", (fake_token, fake_refresh))
            rows = cur.fetchall()
            self.assertEqual(len(rows), 0, "No row should exist in plaintext after failed DPAPI encryption")


if __name__ == "__main__":
    unittest.main()
