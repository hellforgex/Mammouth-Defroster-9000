import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.system_monitor import (
    system_get_event_logs,
    system_list_event_channels,
)


class TestSystemMonitorEvents(unittest.TestCase):
    """Test suite for enhanced Windows Event Log query tools using Get-WinEvent."""

    def test_system_get_event_logs_default_system(self):
        """Test querying the standard System event log with default parameters."""
        logs = system_get_event_logs(log_name="System", count=5)
        self.assertIsInstance(logs, list)
        self.assertGreater(len(logs), 0)
        first = logs[0]
        if "error" not in first and "message" not in first:
            self.assertIn("TimeCreated", first)
            self.assertIn("EventID", first)
            self.assertIn("Level", first)
            self.assertIn("ProviderName", first)
            self.assertIn("Message", first)
            self.assertEqual(first.get("LogName"), "System")

    def test_system_get_event_logs_kernel_pnp_channel(self):
        """Test querying the ETW channel Microsoft-Windows-Kernel-PnP/Device Management for Event 1010."""
        logs = system_get_event_logs(
            log_name="Microsoft-Windows-Kernel-PnP/Device Management",
            event_id=1010,
            count=3
        )
        self.assertIsInstance(logs, list)
        self.assertGreater(len(logs), 0)
        first = logs[0]
        if "error" not in first and "message" not in first:
            self.assertEqual(first.get("EventID"), 1010)
            self.assertEqual(first.get("LogName"), "Microsoft-Windows-Kernel-PnP/Device Management")
            self.assertIn("Level", first)
            self.assertIn("TimeCreated", first)
            self.assertIn("Message", first)

    def test_system_get_event_logs_aliases(self):
        """Test parameter aliases: channel, level, id, and limit."""
        logs = system_get_event_logs(
            channel="Microsoft-Windows-Kernel-PnP/Device Management",
            id=1010,
            limit=2
        )
        self.assertIsInstance(logs, list)
        self.assertGreater(len(logs), 0)
        first = logs[0]
        if "error" not in first and "message" not in first:
            self.assertEqual(first.get("EventID"), 1010)

    def test_system_get_event_logs_level_filters(self):
        """Test valid level filter parsing."""
        for lvl in ["Information", "Error", "Warning", "Critical", "Verbose", "All"]:
            logs = system_get_event_logs(log_name="System", entry_type=lvl, count=2)
            self.assertIsInstance(logs, list)

    def test_system_get_event_logs_invalid_level(self):
        """Test invalid level string is rejected with structured error."""
        res = system_get_event_logs(log_name="System", entry_type="SuperFatal")
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)
        self.assertIn("error", res[0])
        self.assertIn("Invalid entry_type", res[0]["error"])

    def test_system_get_event_logs_invalid_event_id(self):
        """Test invalid event ID values are rejected."""
        res_negative = system_get_event_logs(event_id=-5)
        self.assertIn("error", res_negative[0])

        res_huge = system_get_event_logs(event_id=999999)
        self.assertIn("error", res_huge[0])

        res_str = system_get_event_logs(event_id="not_an_int")
        self.assertIn("error", res_str[0])

    def test_system_get_event_logs_injection_prevention(self):
        """Test that command injection characters in log_name are rejected."""
        injections = [
            "System; calc.exe",
            "System | whoami",
            "System && dir",
            "System`nGet-Process",
            "System$(whoami)",
            "System' OR '1'='1",
        ]
        for inj in injections:
            res = system_get_event_logs(log_name=inj)
            self.assertIsInstance(res, list)
            self.assertEqual(len(res), 1)
            self.assertIn("error", res[0], f"Failed to reject injection: {inj}")

    def test_system_get_event_logs_nonexistent_channel(self):
        """Test querying nonexistent channel returns a clean error message, not an unhandled crash."""
        res = system_get_event_logs(log_name="NonExistentDefrosterChannelXYZ_123")
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)
        self.assertIn("error", res[0])

    def test_system_get_event_logs_no_matching_events(self):
        """Test querying an unused event ID in System log returns empty or friendly message."""
        res = system_get_event_logs(log_name="System", event_id=64999, count=5)
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)
        self.assertTrue("message" in res[0] or "error" in res[0])

    def test_system_list_event_channels_pattern(self):
        """Test listing event channels filtered by pattern."""
        channels = system_list_event_channels(pattern="Kernel-PnP", limit=10)
        self.assertIsInstance(channels, list)
        self.assertGreater(len(channels), 0)
        names = [c.get("LogName") for c in channels if isinstance(c, dict)]
        self.assertIn("Microsoft-Windows-Kernel-PnP/Device Management", names)
        first = channels[0]
        self.assertIn("LogName", first)
        self.assertIn("RecordCount", first)
        self.assertIn("IsEnabled", first)

    def test_system_list_event_channels_injection_rejected(self):
        """Test pattern injection characters are rejected."""
        res = system_list_event_channels(pattern="*Kernel*; calc.exe")
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)
        self.assertIn("error", res[0])

    def test_system_get_event_logs_timeout_handling(self):
        """Test timeout during subprocess returns structured error."""
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=20)):
            res = system_get_event_logs(log_name="System")
            self.assertIsInstance(res, list)
            self.assertEqual(len(res), 1)
            self.assertIn("error", res[0])
            self.assertIn("Timeout", res[0]["error"])


if __name__ == "__main__":
    unittest.main()
