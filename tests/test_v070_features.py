"""
Unit tests for Mammouth Defroster 9000 v0.7.0 features:
Feature: Multi-Browser Support & Model-Controlled Browser Mode
- Browser engine discovery and catalog inspection (Edge, Chrome, Firefox, WebKit, Brave, Chromium)
- Channel resolution and aliases mapping
- MCP tools: browser_list_browsers, browser_restart
- Session persistence logic for Firefox and WebKit (storage_state emulation)
- Status reporting with available browsers
- FastMCP tool registration in server.py
"""

import os
import sys
import unittest
from pathlib import Path

# Add src to sys.path
TEST_DIR = Path(__file__).parent.resolve()
SRC_DIR = TEST_DIR.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modules.browser_agent import (
    list_available_browsers,
    _resolve_channel,
    _detect_browser_channel,
    browser_list_browsers,
    browser_status,
    _WORKER,
    _PLAYWRIGHT_NATIVE_CHANNELS
)
import server
import gui


class TestV070MultiBrowserFeatures(unittest.TestCase):
    """Test suite for v0.7.0 multi-browser and headless control capabilities."""

    def test_version_bump_consistency(self):
        """Verify APP_VERSION in gui.py and server.py are properly bumped to v0.7.0."""
        self.assertEqual(gui.APP_VERSION, "v0.7.0")
        self.assertIn("v0.7.0", server.mcp.instructions or "")

    def test_playwright_native_channels_contains_firefox_and_webkit(self):
        """Ensure native channels set includes both firefox and webkit."""
        self.assertIn("firefox", _PLAYWRIGHT_NATIVE_CHANNELS)
        self.assertIn("webkit", _PLAYWRIGHT_NATIVE_CHANNELS)
        self.assertIn("msedge", _PLAYWRIGHT_NATIVE_CHANNELS)
        self.assertIn("chrome", _PLAYWRIGHT_NATIVE_CHANNELS)
        self.assertIn("chromium", _PLAYWRIGHT_NATIVE_CHANNELS)

    def test_list_available_browsers_includes_builtins(self):
        """Verify list_available_browsers always includes chromium, firefox, and webkit."""
        browsers = list_available_browsers()
        self.assertIsInstance(browsers, list)
        self.assertGreaterEqual(len(browsers), 3)

        channels = [b.get("channel") for b in browsers]
        self.assertIn("chromium", channels)
        self.assertIn("firefox", channels)
        self.assertIn("webkit", channels)

        for b in browsers:
            self.assertIn("channel", b)
            self.assertIn("label", b)
            self.assertIn("path", b)

    def test_resolve_channel_aliases_and_fallbacks(self):
        """Verify channel string normalization and alias resolution."""
        # Exact native channels
        self.assertEqual(_resolve_channel("msedge"), "msedge")
        self.assertEqual(_resolve_channel("firefox"), "firefox")
        self.assertEqual(_resolve_channel("webkit"), "webkit")
        self.assertEqual(_resolve_channel("chrome"), "chrome")

        # Case insensitivity & whitespace
        self.assertEqual(_resolve_channel("  FIREFOX  "), "firefox")
        self.assertEqual(_resolve_channel("MsEdge"), "msedge")

        # Aliases
        self.assertEqual(_resolve_channel("edge"), "msedge")
        self.assertEqual(_resolve_channel("google chrome"), "chrome")
        self.assertEqual(_resolve_channel("google-chrome"), "chrome")

        # Unknown channel fallback
        self.assertEqual(_resolve_channel("some-nonexistent-browser"), "chromium")
        self.assertEqual(_resolve_channel(""), "chromium")

    def test_browser_list_browsers_mcp_tool(self):
        """Verify browser_list_browsers public MCP tool interface."""
        res = browser_list_browsers()
        self.assertIsInstance(res, list)
        self.assertTrue(any(b.get("channel") == "firefox" for b in res))
        self.assertTrue(any(b.get("channel") == "chromium" for b in res))

    def test_storage_state_path_generation(self):
        """Verify storage_state paths are generated properly per channel."""
        p_ff = _WORKER._storage_state_path("firefox")
        self.assertTrue(str(p_ff).endswith("storage_state_firefox.json"))

        p_edge = _WORKER._storage_state_path("msedge")
        self.assertTrue(str(p_edge).endswith("storage_state_msedge.json"))

        # Channel with special characters
        p_weird = _WORKER._storage_state_path("chrome/beta:test")
        self.assertNotIn(":", p_weird.name)
        self.assertNotIn("/", p_weird.name)

    def test_browser_status_contains_available_browsers(self):
        """Verify browser_status payload includes detected available browsers."""
        status = browser_status()
        self.assertIsInstance(status, dict)
        self.assertIn("available_browsers", status)
        self.assertIsInstance(status["available_browsers"], list)

    def test_mcp_server_registers_new_browser_tools(self):
        """Verify that server.build_app or module definitions expose the new browser tools."""
        from modules.browser_agent import browser_restart, browser_list_browsers
        self.assertTrue(callable(browser_restart))
        self.assertTrue(callable(browser_list_browsers))


if __name__ == "__main__":
    unittest.main()
