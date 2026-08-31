import unittest
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.remote_execution import (
    _generate_hmac_challenge,
    _compute_hmac_response,
    _verify_hmac_response,
    _ACTIVE_NONCES,
    NONCE_TTL_SECONDS
)


class TestRemoteExecutionHMAC(unittest.TestCase):
    def setUp(self):
        _ACTIVE_NONCES.clear()

    def test_hmac_valid_challenge_response(self):
        """Test successful HMAC generation and verification."""
        token = "MySecureToken123!"
        nonce = _generate_hmac_challenge()
        self.assertIn(nonce, _ACTIVE_NONCES)

        response_hmac = _compute_hmac_response(token, nonce)
        is_valid = _verify_hmac_response(token, nonce, response_hmac)
        self.assertTrue(is_valid)

        # Single-use test: subsequent verification of same nonce must fail
        self.assertFalse(_verify_hmac_response(token, nonce, response_hmac))

    def test_hmac_invalid_token_fails(self):
        """Test verification fails with incorrect token."""
        token = "RealToken"
        bad_token = "AttackerToken"
        nonce = _generate_hmac_challenge()

        bad_hmac = _compute_hmac_response(bad_token, nonce)
        is_valid = _verify_hmac_response(token, nonce, bad_hmac)
        self.assertFalse(is_valid)

    def test_hmac_expired_nonce_fails(self):
        """Test that expired nonces (>30s) fail closed."""
        token = "MyToken"
        nonce = _generate_hmac_challenge()
        # Artificially age the nonce
        _ACTIVE_NONCES[nonce] = time.time() - (NONCE_TTL_SECONDS + 5)

        hmac_val = _compute_hmac_response(token, nonce)
        self.assertFalse(_verify_hmac_response(token, nonce, hmac_val))


if __name__ == "__main__":
    unittest.main()
