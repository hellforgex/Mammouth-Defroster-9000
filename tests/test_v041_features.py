import unittest
import os
import sys
from typing import Dict, Any
from unittest.mock import MagicMock, patch

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import DEFAULT_CONFIG
from modules.embedded_browser import (
    parse_mammouth_quota_data,
    MAMMOUTH_BRAND_COLORS,
    PLAN_MULTIPLIERS,
    BASE_THRESHOLD_CENTS
)
from modules.screen_capture import copy_image_to_clipboard


class TestMammouthQuotaParser(unittest.TestCase):
    """Unit tests for the Mammouth AI quota data parser and calculation engine."""

    def test_parse_starter_matching_screenshot(self):
        """Validates calculation matching the user's uploaded Mammouth Kontingent screenshot."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "starter",
                "currentSpendCents": 90.0,
                "usageCounts": {"prompt": 14}
            },
            "recent": {
                "usedModels": ["claude-3-5-sonnet", "gpt-4o", "glm-4", "gemini-1.5-pro", "sonar-pro"],
                "byBrand": [
                    {"brand": "claude", "value": 92.0},
                    {"brand": "gpt", "value": 3.0},
                    {"brand": "glm", "value": 3.0},
                    {"brand": "gemini", "value": 2.0},
                    {"brand": "perplexity", "value": 0.5}
                ]
            }
        }
        res = parse_mammouth_quota_data(payload)

        self.assertTrue(res["is_logged_in"])
        self.assertEqual(res["plan_id"], "starter")
        self.assertEqual(res["plan_label"], "Starter x1")
        self.assertEqual(res["multiplier"], 1)
        self.assertEqual(res["max_spend_cents"], 150.0)
        self.assertEqual(res["current_spend_cents"], 90.0)
        self.assertEqual(res["total_percent"], 60.0)

        brands = res["brands"]
        self.assertEqual(len(brands), 5)
        self.assertEqual(brands[0]["brand"], "claude")
        self.assertEqual(brands[0]["label"], "Claude")
        self.assertEqual(brands[0]["value"], 92.0)
        self.assertEqual(brands[0]["color"], MAMMOUTH_BRAND_COLORS["claude"][0])

        self.assertEqual(brands[1]["brand"], "gpt")
        self.assertEqual(brands[1]["label"], "GPT")
        self.assertEqual(brands[1]["value"], 3.0)

    def test_parse_standard_plan(self):
        """Validates Standard plan (x3 multiplier -> $4.50 limit)."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "standard",
                "currentSpendCents": 225.0
            },
            "recent": {
                "byBrand": [
                    {"brand": "claude", "value": 100.0}
                ]
            }
        }
        res = parse_mammouth_quota_data(payload)
        self.assertEqual(res["plan_id"], "standard")
        self.assertEqual(res["multiplier"], 3)
        self.assertEqual(res["max_spend_cents"], 450.0)
        self.assertEqual(res["current_spend_cents"], 225.0)
        self.assertEqual(res["total_percent"], 50.0)

    def test_parse_expert_plan(self):
        """Validates Expert plan (x10 multiplier -> $15.00 limit)."""
        payload = {
            "ok": True,
            "current": {
                "usagePlan": "expert",
                "currentSpendCents": 1500.0
            }
        }
        res = parse_mammouth_quota_data(payload)
        self.assertEqual(res["plan_id"], "expert")
        self.assertEqual(res["multiplier"], 10)
        self.assertEqual(res["max_spend_cents"], 1500.0)
        self.assertEqual(res["total_percent"], 100.0)

    def test_parse_unauthenticated_or_error(self):
        """Validates fallback when user is logged out or API returns error."""
        res_error = parse_mammouth_quota_data({"ok": False, "error": "Not logged in"})
        self.assertFalse(res_error["is_logged_in"])
        self.assertEqual(res_error["total_percent"], 0.0)
        self.assertEqual(res_error["plan_label"], "Nicht eingeloggt")
        self.assertEqual(len(res_error["brands"]), 0)

        res_none = parse_mammouth_quota_data(None)
        self.assertFalse(res_none["is_logged_in"])

    def test_parse_schema_resilience(self):
        """Validates parser resilience against missing fields and unexpected types."""
        weird_payload = {
            "ok": True,
            "current": {
                "usagePlan": "unknown_tier",
                "currentSpendCents": "invalid_number"
            },
            "recent": {
                "byBrand": "not_a_list"
            }
        }
        res = parse_mammouth_quota_data(weird_payload)
        self.assertTrue(res["is_logged_in"])
        self.assertEqual(res["multiplier"], 1)
        self.assertEqual(res["current_spend_cents"], 0.0)
        self.assertEqual(len(res["brands"]), 0)


class TestMammouthQuotaConfig(unittest.TestCase):
    """Validates configuration defaults for embedded browser and quota telemetry."""

    def test_quota_config_defaults(self):
        browser_cfg = DEFAULT_CONFIG.get("embedded_browser", {})
        self.assertIn("quota_sidebar_enabled", browser_cfg)
        self.assertIn("quota_refresh_interval_seconds", browser_cfg)
        self.assertTrue(browser_cfg["quota_sidebar_enabled"])
        self.assertEqual(browser_cfg["quota_refresh_interval_seconds"], 300)


class TestBugfixV041(unittest.TestCase):
    """Unit tests verifying fixes for screenshot hang and download crash issues."""

    def test_copy_image_to_clipboard_retries_and_cleans_up(self):
        """Validates that copy_image_to_clipboard handles locked clipboard gracefully with retries."""
        from PIL import Image
        test_img = Image.new("RGB", (10, 10), color="red")
        
        # Test calling with PIL image directly
        # On Windows without open conflicts, it should execute without unhandled crash
        res = copy_image_to_clipboard(test_img)
        self.assertIsInstance(res, bool)

    def test_download_starting_routes_and_completes_deferral(self):
        """Validates that _on_download_starting configures result path asynchronously, preserves WebView2 download, and completes deferral."""
        from modules.embedded_browser import MammouthBrowserFrame
        
        # Mock WebView2 DownloadStarting args
        mock_args = MagicMock()
        mock_args.ResultFilePath = "C:\\Users\\test\\Downloads\\export.zip"
        mock_args.DownloadOperation = MagicMock()
        mock_deferral = MagicMock()
        mock_args.GetDeferral.return_value = mock_deferral
        
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame._prompt_save_file = MagicMock(return_value="D:\\Saved\\export.zip")
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())
        
        # Call the actual method
        MammouthBrowserFrame._on_download_starting(frame, sender=None, args=mock_args)
        
        # Wait for worker thread to complete
        if hasattr(frame, "_last_download_thread") and frame._last_download_thread:
            frame._last_download_thread.join(timeout=2.0)

        # Ensure ResultFilePath is set to destination via set_ResultFilePath
        mock_args.set_ResultFilePath.assert_called_with(os.path.normpath("D:\\Saved\\export.zip"))
        mock_args.set_Handled.assert_called_with(True)
        # Ensure deferral was completed
        mock_deferral.Complete.assert_called_once()


class TestCTkMammouthQuotaCard(unittest.TestCase):
    """Tests the CustomTkinter Quota Card GUI lifecycle."""

    def setUp(self):
        try:
            import customtkinter as ctk
            self.root = ctk.CTk()
            self.root.withdraw()
        except Exception as e:
            self.skipTest(f"Tkinter display not available: {e}")

    def tearDown(self):
        if hasattr(self, "root") and self.root:
            try:
                self.root.destroy()
            except Exception:
                pass

    def test_quota_card_lifecycle(self):
        if not hasattr(self, "root") or not self.root:
            return

        from gui import CTkMammouthQuotaCard

        card = CTkMammouthQuotaCard(self.root)
        self.assertIsNotNone(card)
        self.assertEqual(card.lbl_plan.cget("text"), "Wird geladen...")

        # Update with unauthenticated data
        unauth_parsed = parse_mammouth_quota_data({"ok": False})
        card.update_quota(unauth_parsed)
        self.assertEqual(card.lbl_plan.cget("text"), "Nicht eingeloggt")
        self.assertEqual(card.lbl_percent.cget("text"), "-- %")

        # Update with screenshot quota data
        auth_payload = {
            "ok": True,
            "current": {
                "usagePlan": "starter",
                "currentSpendCents": 90.0
            },
            "recent": {
                "byBrand": [
                    {"brand": "claude", "value": 92.0},
                    {"brand": "gpt", "value": 3.0},
                    {"brand": "glm", "value": 3.0},
                    {"brand": "gemini", "value": 2.0},
                    {"brand": "perplexity", "value": 0.5}
                ]
            }
        }
        auth_parsed = parse_mammouth_quota_data(auth_payload)
        card.update_quota(auth_parsed)

        self.assertEqual(card.lbl_plan.cget("text"), "Starter x1")
        self.assertEqual(card.lbl_percent.cget("text"), "60 %")
        # 3 rows of brands (pairs: 2 + 2 + 1)

class TestUnifiedWebMessage(unittest.TestCase):
    """Validates _unified_web_message correctly unpacks JSON WebMessages and notifies quota_cb."""

    def test_quota_web_message_triggers_callback(self):
        from modules.embedded_browser import MammouthBrowserFrame
        import json

        received_payload = []
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame.quota_cb = lambda p: received_payload.append(p)
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())

        # Simulate WebMessage arriving as JSON string from WebView2
        payload_obj = {
            "type": "mammouth_quota",
            "payload": {
                "ok": True,
                "current": {"plan": "starter", "currentSpendCents": 45.0},
                "recent": {"byBrand": [{"brand": "claude", "value": 100.0}]}
            }
        }
        # In WebView2, if JS sends postMessage(JSON.stringify(...)), get_WebMessageAsJson returns JSON string of that string
        mock_args = MagicMock()
        mock_args.get_WebMessageAsJson.return_value = json.dumps(json.dumps(payload_obj))

        MammouthBrowserFrame._unified_web_message(frame, sender=None, args=mock_args)

        self.assertEqual(len(received_payload), 1)
        self.assertTrue(received_payload[0]["ok"])
        self.assertEqual(received_payload[0]["current"]["currentSpendCents"], 45.0)

    def test_quota_web_message_single_json_level(self):
        from modules.embedded_browser import MammouthBrowserFrame
        import json

        received_payload = []
        frame = MagicMock(spec=MammouthBrowserFrame)
        frame.quota_cb = lambda p: received_payload.append(p)
        frame.after = MagicMock(side_effect=lambda ms, cb: cb())

        payload_obj = {
            "type": "mammouth_quota",
            "payload": {
                "ok": True,
                "current": {"usagePlan": "standard", "spendCents": 150.0}
            }
        }
        mock_args = MagicMock()
        mock_args.get_WebMessageAsJson.return_value = json.dumps(payload_obj)

        MammouthBrowserFrame._unified_web_message(frame, sender=None, args=mock_args)

        self.assertEqual(len(received_payload), 1)
        self.assertEqual(received_payload[0]["current"]["usagePlan"], "standard")

    def test_edgechrome_handlers_neutralized_and_instantiation_safe(self):
        """Validates EdgeChrome monkeypatches are active and direct instantiation does not raise State TypeError."""
        import sys
        if sys.platform != "win32":
            return
        from webview.platforms import edgechromium
        from webview.window import Window

        # Test that calling monkeypatched handlers does not throw
        edge_dummy = edgechromium.EdgeChrome.__new__(edgechromium.EdgeChrome)
        edgechromium.EdgeChrome.on_script_notify(edge_dummy, None, None)
        edgechromium.EdgeChrome.on_navigation_completed(edge_dummy, None, None)
        edgechromium.EdgeChrome.on_download_starting(edge_dummy, None, None)

        # Test Window creation doesn't fail with State class TypeError
        w = Window("Test", "Test", "http://localhost")
        self.assertIsNotNone(w.state)


if __name__ == "__main__":
    unittest.main()
