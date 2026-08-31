import unittest
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from server import _failed_ip_attempts, _is_ip_locked_out, _record_failed_auth, _record_successful_auth, MAX_LOCKOUT_ENTRIES


class TestAuthLockout(unittest.TestCase):
    def setUp(self):
        _failed_ip_attempts.clear()

    def test_progressive_backoff_per_ip(self):
        """Test progressive exponential backoff after 5 consecutive failures."""
        client_ip = "192.168.1.100"
        now = time.time()

        # 1-4 failures: no lockout cooldown
        for i in range(1, 5):
            delay = _record_failed_auth(client_ip, now)
            self.assertEqual(delay, 0.0)
            is_locked, _ = _is_ip_locked_out(client_ip, now)
            self.assertFalse(is_locked)

        # 5th failure: 2^0 = 1s delay
        delay_5 = _record_failed_auth(client_ip, now)
        self.assertEqual(delay_5, 1.0)
        is_locked, rem = _is_ip_locked_out(client_ip, now)
        self.assertTrue(is_locked)
        self.assertAlmostEqual(rem, 1.0, places=1)

        # 6th failure: 2^1 = 2s delay
        delay_6 = _record_failed_auth(client_ip, now)
        self.assertEqual(delay_6, 2.0)

        # 7th failure: 2^2 = 4s delay
        delay_7 = _record_failed_auth(client_ip, now)
        self.assertEqual(delay_7, 4.0)

        # 12th failure: 2^7 = 128s -> capped at 60s
        for _ in range(5):
            _record_failed_auth(client_ip, now)
        delay_capped = _record_failed_auth(client_ip, now)
        self.assertEqual(delay_capped, 60.0)

    def test_successful_auth_resets_backoff(self):
        """Test that valid authentication resets the failure counter for the IP."""
        client_ip = "192.168.1.101"
        now = time.time()

        for _ in range(6):
            _record_failed_auth(client_ip, now)

        is_locked, _ = _is_ip_locked_out(client_ip, now)
        self.assertTrue(is_locked)

        # Successful auth resets IP
        _record_successful_auth(client_ip)

        is_locked_after, _ = _is_ip_locked_out(client_ip, now)
        self.assertFalse(is_locked_after)
        self.assertNotIn(client_ip, _failed_ip_attempts)

    def test_lockout_dict_bounding(self):
        """Test that _failed_ip_attempts does not exceed MAX_LOCKOUT_ENTRIES."""
        now = time.time()

        for i in range(MAX_LOCKOUT_ENTRIES + 50):
            ip = f"10.0.{i // 255}.{i % 255}"
            _record_failed_auth(ip, now)

        self.assertLessEqual(len(_failed_ip_attempts), MAX_LOCKOUT_ENTRIES)


if __name__ == "__main__":
    unittest.main()
