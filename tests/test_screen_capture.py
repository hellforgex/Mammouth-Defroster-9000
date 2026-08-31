import unittest
from unittest.mock import patch, MagicMock
from PIL import Image as RealPILImage
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.screen_capture import screen_capture, screen_grant_consent, screen_revoke_consent


class TestScreenCaptureConsent(unittest.TestCase):
    def setUp(self):
        screen_revoke_consent()

    def test_consent_required_by_default(self):
        """Test that screen_capture returns consent_required without prior consent."""
        res = screen_capture(monitor=1)
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("status"), "consent_required")

    def test_consent_grant_once(self):
        """Test single-use consent allows 1 capture then revokes."""
        grant_res = screen_grant_consent("once")
        self.assertEqual(grant_res.get("status"), "success")
        self.assertEqual(grant_res.get("consent_mode"), "once")

        real_img = RealPILImage.new("RGB", (1920, 1080), color=(100, 100, 100))
        with patch("modules.screen_capture.ImageGrab") as mock_grab, \
             patch("modules.screen_capture.mss", None):
            mock_grab.grab.return_value = real_img

            # First capture: should succeed past consent gate
            res1 = screen_capture(monitor=1, save_to_workspace=False)
            if isinstance(res1, dict):
                self.assertNotEqual(res1.get("status"), "consent_required")

            # Second capture: single-use consent consumed, must return consent_required
            res2 = screen_capture(monitor=1, save_to_workspace=False)
            self.assertIsInstance(res2, dict)
            self.assertEqual(res2.get("status"), "consent_required")

    def test_consent_grant_always(self):
        """Test session consent persists across multiple captures."""
        screen_grant_consent("always")

        real_img = RealPILImage.new("RGB", (1920, 1080), color=(50, 50, 50))
        with patch("modules.screen_capture.ImageGrab") as mock_grab, \
             patch("modules.screen_capture.mss", None):
            mock_grab.grab.return_value = real_img

            res1 = screen_capture(monitor=1, save_to_workspace=False)
            res2 = screen_capture(monitor=1, save_to_workspace=False)
            if isinstance(res1, dict):
                self.assertNotEqual(res1.get("status"), "consent_required")
            if isinstance(res2, dict):
                self.assertNotEqual(res2.get("status"), "consent_required")


if __name__ == "__main__":
    unittest.main()
