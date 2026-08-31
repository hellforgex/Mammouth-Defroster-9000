import unittest
from unittest.mock import MagicMock, patch
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestGuiStartServerRegression(unittest.TestCase):
    def test_start_server_host_port_resolution(self):
        """Test that _start_server does not raise NameError for host or port."""
        from gui import MammouthControlCenter

        # Use __new__ to avoid initializing Tkinter GUI in headless/test environments
        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.is_server_running = False
        app.uvicorn_server = None
        app.config_data = {
            "server": {
                "host": "127.0.0.1",
                "port": 8080,
                "enforce_auth": False,
                "api_token": "test-token-1234",
                "auto_tunnel": False
            }
        }
        app._log = MagicMock()
        app._refresh_all_endpoint_labels = MagicMock()
        app._calculate_active_endpoint_url = MagicMock(return_value="http://127.0.0.1:8080/sse")
        app.status_badge = MagicMock()
        app.btn_toggle_server = MagicMock()

        with patch("gui.threading.Thread") as mock_thread, \
             patch("uvicorn.Config") as mock_uvicorn_cfg, \
             patch("uvicorn.Server") as mock_uvicorn_server, \
             patch("gui.build_app") as mock_build_app:

            # Execute _start_server
            app._start_server()

            self.assertTrue(app.is_server_running)
            mock_uvicorn_cfg.assert_called_once()
            _, kwargs = mock_uvicorn_cfg.call_args
            self.assertEqual(kwargs.get("host"), "127.0.0.1")
            self.assertEqual(kwargs.get("port"), 8080)
            mock_build_app.assert_called_once_with(token="")


if __name__ == "__main__":
    unittest.main()
