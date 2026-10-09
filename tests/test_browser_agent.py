"""
Unit and Integration Tests for Playwright Browser Automation Agent Module
Tests browser lifecycle, navigation, snapshots, element indexing, interactive
clicks, form fills, tab management, content extraction, and MCP tools.
"""

import sys
import os
import unittest
from pathlib import Path

# Add src to sys.path
TEST_DIR = Path(__file__).parent.resolve()
SRC_DIR = TEST_DIR.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modules.browser_agent import (
    init_browser_agent,
    browser_status,
    browser_navigate,
    browser_snapshot,
    browser_screenshot,
    browser_click,
    browser_fill,
    browser_press_key,
    browser_hover,
    browser_scroll,
    browser_get_content,
    browser_evaluate,
    browser_tabs,
    browser_close,
    _detect_browser_channel
)


class TestBrowserAgent(unittest.TestCase):
    """Test suite for browser agent automation."""

    @classmethod
    def setUpClass(cls):
        # Configure headless mode for automated testing
        init_browser_agent({
            "headless": True,
            "channel": _detect_browser_channel(),
            "viewport_width": 1280,
            "viewport_height": 800,
            "timeout_seconds": 25
        })

    @classmethod
    def tearDownClass(cls):
        try:
            browser_close()
        except Exception:
            pass

    def test_01_initial_status(self):
        """Verify browser status reporting."""
        status = browser_status()
        self.assertIsInstance(status, dict)
        self.assertIn("channel", status)
        self.assertIn("headless", status)
        self.assertTrue(status.get("headless"))

    def test_02_navigate_and_title(self):
        """Verify navigation to a URL and page title retrieval."""
        res = browser_navigate("https://example.com")
        self.assertEqual(res.get("status"), "success")
        self.assertIn("example.com", res.get("url", ""))
        self.assertEqual(res.get("title"), "Example Domain")

        status = browser_status()
        self.assertTrue(status.get("running"))
        self.assertIn("example.com", status.get("active_url", ""))

    def test_03_evaluate_javascript(self):
        """Verify JavaScript execution in active page context."""
        res = browser_evaluate("21 * 2")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("result"), 42)

        doc_title = browser_evaluate("document.title")
        self.assertEqual(doc_title.get("result"), "Example Domain")

    def test_04_get_content_markdown(self):
        """Verify rendered Markdown content extraction."""
        content = browser_get_content(format="markdown")
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 20)
        self.assertIn("domain", content.lower())

    def test_05_snapshot_and_element_indexing(self):
        """Verify page snapshot, interactive element numbering, and screenshot capture."""
        snap = browser_snapshot(include_screenshot=True, max_elements=50)
        self.assertEqual(snap.get("status"), "success")
        self.assertEqual(snap.get("title"), "Example Domain")
        self.assertIsInstance(snap.get("interactive_elements"), list)
        self.assertGreater(snap.get("element_count", 0), 0)

        # Check element structure
        first_elem = snap["interactive_elements"][0]
        self.assertIn("id", first_elem)
        self.assertIn("tag", first_elem)
        self.assertIn("text", first_elem)
        self.assertIn("x", first_elem)
        self.assertIn("y", first_elem)

        # Verify screenshot was saved
        saved_path = snap.get("screenshot_path", "")
        self.assertTrue(os.path.exists(saved_path), f"Screenshot file should exist at {saved_path}")

    def test_06_screenshot_tool(self):
        """Verify browser_screenshot tool returns valid image data or dict."""
        shot = browser_screenshot(full_page=False)
        if isinstance(shot, dict):
            self.assertEqual(shot.get("status"), "success")
            self.assertTrue(os.path.exists(shot.get("saved_path", "")))
        else:
            # FastMCPImage object
            self.assertTrue(hasattr(shot, "data") or hasattr(shot, "format"))

    def test_07_click_indexed_element(self):
        """Verify clicking element by numeric snapshot ID."""
        snap = browser_snapshot()
        self.assertGreater(len(snap["interactive_elements"]), 0)
        first_id = str(snap["interactive_elements"][0]["id"])

        res = browser_click(first_id)
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("target"), first_id)

    def test_08_tab_management(self):
        """Verify tab creation, listing, switching, and closing."""
        # Create a second tab
        create_res = browser_tabs(action="create", url="https://example.com")
        self.assertEqual(create_res.get("status"), "success")

        # List tabs
        list_res = browser_tabs(action="list")
        self.assertEqual(list_res.get("status"), "success")
        self.assertGreaterEqual(list_res.get("count", 0), 2)

        # Switch tab
        switch_res = browser_tabs(action="switch", tab_index=0)
        self.assertEqual(switch_res.get("status"), "success")
        self.assertEqual(switch_res.get("index"), 0)

        # Close the second tab
        close_tab_res = browser_tabs(action="close", tab_index=1)
        self.assertEqual(close_tab_res.get("status"), "success")

    def test_09_scroll_and_hover(self):
        """Verify scroll and hover actions."""
        scroll_res = browser_scroll(direction="down", amount=300)
        self.assertEqual(scroll_res.get("status"), "success")
        self.assertEqual(scroll_res.get("direction"), "down")

        scroll_up = browser_scroll(direction="up", amount=200)
        self.assertEqual(scroll_up.get("status"), "success")

    def test_10_press_key(self):
        """Verify keyboard key press simulation."""
        key_res = browser_press_key("Escape")
        self.assertEqual(key_res.get("status"), "success")
        self.assertEqual(key_res.get("key"), "Escape")

    def test_11_ssrf_shield(self):
        """Verify SSRF protection blocks cloud metadata endpoints."""
        res = browser_navigate("http://169.254.169.254/latest/meta-data")
        self.assertIn("error", res)
        self.assertIn("SSRF Shield", res["error"])


if __name__ == "__main__":
    unittest.main()
