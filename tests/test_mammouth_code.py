import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

# Ensure src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.mammouth_code import (
    get_mammouth_executable,
    get_mammouth_code_status,
    launch_mammouth_terminal,
    run_mammouth_task,
    sync_opencode_mcp_config,
    get_configured_api_key
)


class TestMammouthCodeModule(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ws_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("modules.mammouth_code.shutil.which")
    @patch("os.path.isfile")
    def test_get_mammouth_executable_which(self, mock_isfile, mock_which):
        mock_isfile.return_value = True
        mock_which.return_value = "C:\\Tools\\mammouth.exe"

        with patch("modules.mammouth_code.DEFAULT_MAMMOUTH_EXE", Path("C:\\NonExistent\\mammouth.exe")):
            exe = get_mammouth_executable()
            self.assertEqual(exe, "C:\\Tools\\mammouth.exe")

    @patch("modules.mammouth_code.get_mammouth_executable")
    @patch("subprocess.run")
    def test_get_status_installed(self, mock_run, mock_get_exe):
        mock_get_exe.return_value = "C:\\Users\\test\\.mammouth\\bin\\mammouth.exe"
        mock_isfile = MagicMock(return_value=True)

        mock_proc = MagicMock()
        mock_proc.stdout = "mammouth 1.18.31\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        with patch("os.path.isfile", mock_isfile):
            st = get_mammouth_code_status()
            self.assertTrue(st["installed"])
            self.assertIn("1.18.31", st["version"])
            self.assertEqual(st["executable_path"], "C:\\Users\\test\\.mammouth\\bin\\mammouth.exe")

    @patch("modules.mammouth_code.get_mammouth_executable", return_value=None)
    def test_get_status_not_installed(self, mock_get_exe):
        st = get_mammouth_code_status()
        self.assertFalse(st["installed"])
        self.assertEqual(st["executable_path"], "")

    @patch("modules.mammouth_code.get_mammouth_executable", return_value="C:\\Tools\\mammouth.exe")
    @patch("modules.mammouth_code._find_windows_terminal", return_value="C:\\Windows\\wt.exe")
    @patch("modules.mammouth_code.get_configured_api_key", return_value="mc_key_secret_123")
    @patch("subprocess.Popen")
    def test_launch_terminal_wt(self, mock_popen, mock_key, mock_find_wt, mock_get_exe):
        import base64
        res = launch_mammouth_terminal(workspace_path=str(self.ws_path), continue_session=True, preferred_terminal="wt")
        self.assertTrue(res["success"])
        self.assertIn("Windows Terminal", res["terminal"])
        self.assertTrue(res["continued_session"])

        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        self.assertEqual(cmd_args[:4], ["cmd.exe", "/c", "start", ""])
        self.assertEqual(cmd_args[4], "C:\\Windows\\wt.exe")
        self.assertIn("-d", cmd_args)
        self.assertIn("-EncodedCommand", cmd_args)
        encoded_idx = cmd_args.index("-EncodedCommand") + 1
        decoded_script = base64.b64decode(cmd_args[encoded_idx]).decode("utf-16le")
        self.assertIn("-c", decoded_script)
        # The API key must not appear on the command line (visible in process listings);
        # it is handed to the child through its environment instead.
        self.assertNotIn("mc_key_secret_123", decoded_script)
        self.assertIn("C:\\Tools\\mammouth.exe", decoded_script)
        child_env = mock_popen.call_args.kwargs.get("env") or {}
        self.assertEqual(child_env.get("MAMMOUTH_API_KEY"), "mc_key_secret_123")

    @patch("modules.mammouth_code.get_mammouth_executable", return_value="C:\\Tools\\mammouth.exe")
    @patch("modules.mammouth_code._find_windows_terminal", return_value=None)
    @patch("modules.mammouth_code.get_configured_api_key", return_value="")
    @patch("subprocess.Popen")
    def test_launch_terminal_powershell_fallback(self, mock_popen, mock_key, mock_find_wt, mock_get_exe):
        import base64
        res = launch_mammouth_terminal(workspace_path=str(self.ws_path), continue_session=False)
        self.assertTrue(res["success"])
        self.assertIn("PowerShell", res["terminal"])

        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        self.assertEqual(cmd_args[:4], ["cmd.exe", "/c", "start", "Mammouth Code"])
        self.assertEqual(cmd_args[4], "powershell.exe")
        self.assertIn("-EncodedCommand", cmd_args)
        encoded_idx = cmd_args.index("-EncodedCommand") + 1
        decoded_script = base64.b64decode(cmd_args[encoded_idx]).decode("utf-16le")
        self.assertIn("C:\\Tools\\mammouth.exe", decoded_script)

    @patch("modules.mammouth_code.get_mammouth_executable", return_value="C:\\Tools\\mammouth.exe")
    @patch("modules.mammouth_code.get_configured_api_key", return_value="mc_api_key_456")
    @patch("subprocess.run")
    def test_run_mammouth_task_success(self, mock_run, mock_key, mock_exe):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Created test API endpoints successfully."
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = run_mammouth_task(
            prompt="Build api endpoints",
            workspace_path=str(self.ws_path),
            timeout_seconds=60,
            auto_approve=True
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["returncode"], 0)
        self.assertIn("Created test API", res["output"])

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd, ["C:\\Tools\\mammouth.exe", "run", "--auto", "Build api endpoints"])
        self.assertEqual(kwargs["env"]["MAMMOUTH_API_KEY"], "mc_api_key_456")

    @patch("modules.mammouth_code.get_mammouth_executable", return_value="C:\\Tools\\mammouth.exe")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="mammouth", timeout=10))
    def test_run_mammouth_task_timeout(self, mock_run, mock_exe):
        res = run_mammouth_task(
            prompt="Long running task",
            workspace_path=str(self.ws_path),
            timeout_seconds=10
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["returncode"], -2)
        self.assertIn("timed out", res["error"].lower())

    def test_sync_opencode_mcp_config_workspace(self):
        target_ws = str(self.ws_path)
        server_url = "http://127.0.0.1:8000/sse"
        api_token = "mc_test_token_789"

        # Mock global config file to a temp location so we don't overwrite user's actual ~/.config
        global_temp = self.ws_path / "global_opencode" / "opencode.json"
        global_temp.parent.mkdir(parents=True, exist_ok=True)

        with patch("modules.mammouth_code.DEFAULT_OPENCODE_CONFIG_FILE", global_temp), \
             patch("modules.mammouth_code.DEFAULT_OPENCODE_CONFIG_DIR", global_temp.parent):
            res = sync_opencode_mcp_config(
                workspace_path=target_ws,
                server_url=server_url,
                api_token=api_token
            )
            self.assertTrue(res["success"])

        # Check local workspace opencode.json
        local_cfg_file = self.ws_path / "opencode.json"
        self.assertTrue(local_cfg_file.exists())
        with open(local_cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("mcp", data)
        self.assertIn("mammouth-defroster-9000", data["mcp"])
        entry = data["mcp"]["mammouth-defroster-9000"]
        self.assertEqual(entry["url"], server_url)
        # The workspace file may end up in a repo, so it references an env var instead of the token
        self.assertEqual(entry["headers"]["Authorization"], "Bearer {env:MAMMOUTH_DEFROSTER_TOKEN}")
        self.assertNotIn(api_token, local_cfg_file.read_text(encoding="utf-8"))
        self.assertTrue(entry["enabled"])

        # The global (per-user) config keeps the real token
        with open(global_temp, "r", encoding="utf-8") as f:
            global_entry = json.load(f)["mcp"]["mammouth-defroster-9000"]
        self.assertEqual(global_entry["headers"]["Authorization"], f"Bearer {api_token}")


if __name__ == "__main__":
    unittest.main()
