import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.putty_ssh import ssh_exec_command, ssh_open_putty_window, ssh_transfer_file


class TestPuttySecurity(unittest.TestCase):
    @patch("modules.putty_ssh.shutil.which", return_value="plink.exe")
    def test_ssh_exec_pwfile_usage_and_cleanup(self, mock_which):
        pw_file_seen = []

        def fake_run(cmd, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "Linux server 5.15.0"
            mock_proc.stderr = ""
            if "-pwfile" in cmd:
                idx = cmd.index("-pwfile")
                pw_path = cmd[idx + 1]
                pw_file_seen.append(pw_path)
                self.assertTrue(os.path.exists(pw_path), "Temp password file must exist during subprocess execution")
                with open(pw_path, "r", encoding="utf-8") as f:
                    self.assertIn("SuperSecretPassword123!", f.read())
            return mock_proc

        with patch("modules.putty_ssh.subprocess.run", side_effect=fake_run) as mock_run:
            res = ssh_exec_command(
                host="192.168.1.50",
                command="uname -a",
                username="testuser",
                password="SuperSecretPassword123!"
            )

            self.assertEqual(res["exit_code"], 0)
            plink_calls = [c for c in mock_run.call_args_list if "plink.exe" in c[0][0][0]]
            self.assertEqual(len(plink_calls), 1)
            cli_list = plink_calls[0][0][0]

            # Verify -pw is ABSENT and -pwfile is PRESENT
            self.assertNotIn("-pw", cli_list)
            self.assertNotIn("SuperSecretPassword123!", cli_list)
            self.assertIn("-pwfile", cli_list)

            # Verify temporary password file is DELETED after run completes
            self.assertEqual(len(pw_file_seen), 1)
            self.assertFalse(os.path.exists(pw_file_seen[0]), "Temp password file must be removed after execution")

    @patch("modules.putty_ssh.shutil.which", return_value="pscp.exe")
    def test_ssh_transfer_pwfile_usage_and_cleanup(self, mock_which):
        pw_file_seen = []

        def fake_run(cmd, **kwargs):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            if "-pwfile" in cmd:
                idx = cmd.index("-pwfile")
                pw_path = cmd[idx + 1]
                pw_file_seen.append(pw_path)
                self.assertTrue(os.path.exists(pw_path))
            return mock_proc

        with patch("modules.putty_ssh.subprocess.run", side_effect=fake_run) as mock_run:
            res = ssh_transfer_file(
                host="192.168.1.50",
                local_path="local.txt",
                remote_path="/tmp/remote.txt",
                direction="upload",
                username="testuser",
                password="SecretTransferPw456!"
            )

            self.assertEqual(res["status"], "success")
            pscp_calls = [c for c in mock_run.call_args_list if "pscp.exe" in c[0][0][0]]
            self.assertEqual(len(pscp_calls), 1)
            cli_list = pscp_calls[0][0][0]

            # Verify -pw is ABSENT and -pwfile is PRESENT
            self.assertNotIn("-pw", cli_list)
            self.assertNotIn("SecretTransferPw456!", cli_list)
            self.assertIn("-pwfile", cli_list)

            # Verify temporary password file is DELETED
            self.assertEqual(len(pw_file_seen), 1)
            self.assertFalse(os.path.exists(pw_file_seen[0]))

    @patch("modules.putty_ssh.shutil.which", return_value="putty.exe")
    @patch("modules.putty_ssh.subprocess.Popen")
    def test_ssh_open_putty_window_no_pw_in_cli(self, mock_popen, mock_which):
        res = ssh_open_putty_window(
            host_or_alias="192.168.1.50",
            username="testuser",
            password="SecretWindowPw789!"
        )

        self.assertEqual(res["status"], "success")
        mock_popen.assert_called_once()
        cmd_args, _ = mock_popen.call_args
        cli_list = cmd_args[0]

        # Verify -pw is NOT in CLI
        self.assertNotIn("-pw", cli_list)
        self.assertNotIn("SecretWindowPw789!", cli_list)


if __name__ == "__main__":
    unittest.main()
