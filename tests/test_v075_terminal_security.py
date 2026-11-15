"""Regression tests for v0.7.5 Claude Code security fixes:
- Fix 1: PowerShell command injection in launch_claude_terminal
- Fix 6: Plaintext API token elimination in .mcp.json and ~/.claude.json
"""

import base64
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on sys.path
SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modules.claude_code import (  # noqa: E402
    launch_claude_terminal,
    sync_claude_code_mcp,
    SERVER_NAME,
)


class TestV075ClaudeCodeSecurity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="claude_sec_test_")
        self.workspace_dir = Path(self.test_dir) / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _decode_powershell_script(self, encoded_cmd: str) -> str:
        """Decode base64-encoded UTF-16LE PowerShell script."""
        raw_bytes = base64.b64decode(encoded_cmd)
        return raw_bytes.decode("utf-16le")

    def test_powershell_no_injection_all_quote_variants_and_metacharacters(self):
        """Fix 1: Verify prompt containing all 5 quote variants (' ‘ ’ ‚ ‛), semicolons,

        $(), and backticks is NOT interpolated into the PowerShell script string.
        """
        # All 5 single-quote variants recognized by PowerShell parser:
        # ' (\u0027), ‘ (\u2018), ’ (\u2019), ‚ (\u201a), ‛ (\u201b)
        malicious_prompt = (
            "Analyze ' ‘ ’ ‚ ‛ ; Write-Output INJECTED ; $(calc.exe) `Start-Process calc`"
        )
        fake_exe = "C:\\Tools\\claude.cmd"

        with (
            patch("config.load_config", return_value={"server": {"allow_admin_shell": True}}),
            patch("modules.claude_code.get_claude_executable", return_value=fake_exe),
            patch("subprocess.Popen") as mock_popen,
        ):
            res = launch_claude_terminal(
                prompt=malicious_prompt,
                workspace_path=str(self.workspace_dir),
                cloud=True,
                continue_session=True,
                preferred_terminal="powershell",
            )
            self.assertTrue(res["success"])
            self.assertTrue(mock_popen.called)

            call_args = mock_popen.call_args
            cmd = call_args[0][0]
            env = call_args[1].get("env", {})

            # Extract the EncodedCommand flag
            self.assertIn("-EncodedCommand", cmd)
            idx = cmd.index("-EncodedCommand")
            encoded_str = cmd[idx + 1]

            decoded_script = self._decode_powershell_script(encoded_str)

            # Ensure the generated script contains ONLY constant references
            self.assertIn("Set-Location -LiteralPath $env:MD_CLAUDE_WS", decoded_script)
            self.assertIn("[System.Console]::Title = $env:MD_CLAUDE_TITLE", decoded_script)
            self.assertIn("& $env:MD_CLAUDE_EXE", decoded_script)
            self.assertIn("--cloud", decoded_script)
            self.assertIn("-c", decoded_script)
            self.assertIn("-p $env:MD_CLAUDE_PROMPT", decoded_script)

            # Verify ZERO user input or malicious tokens are in the script string
            self.assertNotIn("INJECTED", decoded_script)
            self.assertNotIn("calc.exe", decoded_script)
            self.assertNotIn("Start-Process", decoded_script)
            self.assertNotIn("Write-Output", decoded_script)
            self.assertNotIn("‘", decoded_script)
            self.assertNotIn("’", decoded_script)
            self.assertNotIn("‚", decoded_script)
            self.assertNotIn("‛", decoded_script)
            self.assertNotIn(malicious_prompt, decoded_script)
            self.assertNotIn(str(self.workspace_dir), decoded_script)
            self.assertNotIn(fake_exe, decoded_script)

            # Verify the child environment receives the exact unmodified user values
            self.assertEqual(env.get("MD_CLAUDE_PROMPT"), malicious_prompt)
            self.assertEqual(env.get("MD_CLAUDE_WS"), str(self.workspace_dir))
            self.assertEqual(env.get("MD_CLAUDE_EXE"), fake_exe)
            self.assertEqual(env.get("MD_CLAUDE_TITLE"), "Claude Code (Cloud Session)")

    def test_powershell_quote_variants_isolated(self):
        """Fix 1: Test each of the 5 quote variants individually in prompt to verify isolation."""
        quote_chars = [
            ("ascii_single", "'", "\u0027"),
            ("left_single", "‘", "\u2018"),
            ("right_single", "’", "\u2019"),
            ("single_low_9", "‚", "\u201a"),
            ("single_high_rev_9", "‛", "\u201b"),
        ]

        fake_exe = "C:\\Tools\\claude.cmd"

        for label, q_char, unicode_point in quote_chars:
            with self.subTest(quote=label, char=q_char, codepoint=unicode_point):
                probe_prompt = f"query {q_char} ; Invoke-Expression 'calc' ; {q_char}"
                with (
                    patch("config.load_config", return_value={"server": {"allow_admin_shell": True}}),
                    patch("modules.claude_code.get_claude_executable", return_value=fake_exe),
                    patch("subprocess.Popen") as mock_popen,
                ):
                    res = launch_claude_terminal(
                        prompt=probe_prompt,
                        workspace_path=str(self.workspace_dir),
                        cloud=False,
                        continue_session=False,
                        preferred_terminal="powershell",
                    )
                    self.assertTrue(res["success"])
                    cmd = mock_popen.call_args[0][0]
                    env = mock_popen.call_args[1].get("env", {})
                    idx = cmd.index("-EncodedCommand")
                    decoded = self._decode_powershell_script(cmd[idx + 1])

                    self.assertNotIn(q_char, decoded)
                    self.assertNotIn("Invoke-Expression", decoded)
                    self.assertNotIn("calc", decoded)
                    self.assertIn("-p $env:MD_CLAUDE_PROMPT", decoded)
                    self.assertEqual(env.get("MD_CLAUDE_PROMPT"), probe_prompt)

    def test_wt_terminal_path_avoids_cmd_metacharacter_injection(self):
        """Fix 1: Verify Windows Terminal (wt) path directly invokes wt.exe without cmd.exe /c start,

        preventing cmd.exe metacharacter injection (&, |, ^, %) via workspace_path.
        """
        fake_exe = "C:\\Tools\\claude.cmd"
        fake_wt = "C:\\Windows\\System32\\wt.exe"
        ws_with_metachars = self.workspace_dir / "project & calc.exe ^ %PATH%"
        ws_with_metachars.mkdir(parents=True, exist_ok=True)

        with (
            patch("config.load_config", return_value={"server": {"allow_admin_shell": True}}),
            patch("modules.claude_code.get_claude_executable", return_value=fake_exe),
            patch("modules.claude_code._find_windows_terminal", return_value=fake_wt),
            patch("subprocess.Popen") as mock_popen,
        ):
            res = launch_claude_terminal(
                workspace_path=str(ws_with_metachars),
                cloud=True,
                preferred_terminal="wt",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["terminal"], "Windows Terminal (wt.exe)")

            cmd = mock_popen.call_args[0][0]

            # Direct launch of wt.exe - cmd.exe is NOT used
            self.assertEqual(cmd[0], fake_wt)
            self.assertNotIn("cmd.exe", cmd)
            self.assertNotIn("start", cmd)

            # Workspace path is safely passed as argument to -d
            self.assertIn("-d", cmd)
            d_idx = cmd.index("-d")
            self.assertEqual(cmd[d_idx + 1], str(ws_with_metachars))

            # Script is encoded and contains only constants
            self.assertIn("-EncodedCommand", cmd)
            enc_idx = cmd.index("-EncodedCommand")
            decoded = self._decode_powershell_script(cmd[enc_idx + 1])
            self.assertNotIn(str(ws_with_metachars), decoded)
            self.assertIn("$env:MD_CLAUDE_WS", decoded)

    def test_workspace_path_control_characters_rejected(self):
        """Fix 1: Reject workspace paths containing newline or null control characters."""
        with (
            patch("config.load_config", return_value={"server": {"allow_admin_shell": True}}),
            patch("modules.claude_code.get_claude_executable", return_value="C:\\Tools\\claude.cmd"),
        ):
            res = launch_claude_terminal(
                workspace_path="C:\\dangerous\npath",
                cloud=True,
            )
            self.assertFalse(res["success"])
            self.assertIn("control characters", res["error"])

    def test_sync_claude_code_mcp_defaults_to_env_var_both_workspace_and_global(self):
        """Fix 6: Default sync_claude_code_mcp uses Bearer ${MAMMOUTH_DEFROSTER_TOKEN}

        for both workspace .mcp.json and global ~/.claude.json to prevent plaintext token leaks.
        """
        fake_global = self.workspace_dir / ".fake_claude.json"
        ws_mcp = self.workspace_dir / ".mcp.json"

        with patch("modules.claude_code.DEFAULT_CLAUDE_CONFIG_FILE", fake_global):
            # Call sync_claude_code_mcp with api_token but without specifying use_env_var
            res = sync_claude_code_mcp(
                workspace_path=str(self.workspace_dir),
                server_url="https://cloud.mammouth.ai/mcp",
                api_token="mc_secret_1234567890abcdef",
                target_cloud=True,
                sync_global=True,
                update_claude_md=False,
            )
            self.assertTrue(res["success"])
            # Default auth_mode must be env_var
            self.assertEqual(res["auth_mode"], "env_var")

            # Workspace .mcp.json must use environment variable placeholder, NOT plaintext token
            ws_data = json.loads(ws_mcp.read_text(encoding="utf-8"))
            ws_headers = ws_data["mcpServers"][SERVER_NAME]["headers"]
            self.assertEqual(ws_headers["Authorization"], "Bearer ${MAMMOUTH_DEFROSTER_TOKEN}")
            self.assertNotIn("mc_secret_1234567890abcdef", ws_mcp.read_text(encoding="utf-8"))

            # Global ~/.claude.json must ALSO use environment variable placeholder, NOT plaintext token
            global_data = json.loads(fake_global.read_text(encoding="utf-8"))
            global_headers = global_data["mcpServers"][SERVER_NAME]["headers"]
            self.assertEqual(global_headers["Authorization"], "Bearer ${MAMMOUTH_DEFROSTER_TOKEN}")
            self.assertNotIn("mc_secret_1234567890abcdef", fake_global.read_text(encoding="utf-8"))

    def test_sync_claude_code_mcp_explicit_token_mode_opt_out(self):
        """Fix 6: When use_env_var=False is explicitly specified, write static token to both configs."""
        fake_global = self.workspace_dir / ".fake_claude.json"
        ws_mcp = self.workspace_dir / ".mcp.json"

        with patch("modules.claude_code.DEFAULT_CLAUDE_CONFIG_FILE", fake_global):
            res = sync_claude_code_mcp(
                workspace_path=str(self.workspace_dir),
                server_url="https://cloud.mammouth.ai/mcp",
                api_token="mc_explicit_static_token",
                target_cloud=True,
                use_env_var=False,
                sync_global=True,
                update_claude_md=False,
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["auth_mode"], "token")

            # Workspace .mcp.json has static token
            ws_data = json.loads(ws_mcp.read_text(encoding="utf-8"))
            self.assertEqual(
                ws_data["mcpServers"][SERVER_NAME]["headers"]["Authorization"],
                "Bearer mc_explicit_static_token",
            )

            # Global ~/.claude.json has static token
            global_data = json.loads(fake_global.read_text(encoding="utf-8"))
            self.assertEqual(
                global_data["mcpServers"][SERVER_NAME]["headers"]["Authorization"],
                "Bearer mc_explicit_static_token",
            )


if __name__ == "__main__":
    unittest.main()
