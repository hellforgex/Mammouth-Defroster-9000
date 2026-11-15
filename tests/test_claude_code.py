"""Unit tests for Claude Code & Cloud Sessions integration (modules/claude_code.py and server tools).
"""

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure src/ is on sys.path
SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modules.claude_code import (
    _strip_jsonc,
    _merge_claude_mcp_entry,
    get_tailscale_public_domain,
    save_active_tunnel_info,
    get_active_tunnel_info,
    resolve_public_tunnel_url,
    resolve_active_server_url,
    get_claude_executable,
    get_claude_code_status,
    sync_claude_code_mcp,
    launch_claude_terminal,
    run_claude_task,
)


class TestClaudeCodeModule(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="claude_test_")
        self.workspace_dir = Path(self.test_dir) / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_strip_jsonc(self):
        # Line comments, block comments, trailing commas, strings with comment characters
        jsonc_input = """
        {
            // Single line comment
            "name": "mammouth // not a comment",
            /* Multi-line
               comment */
            "nested": {
                "url": "https://mammouth.ai/*test*/",
                "port": 8000,
            },
            "array": [1, 2, 3,],
        }
        """
        cleaned = _strip_jsonc(jsonc_input)
        parsed = json.loads(cleaned)
        self.assertEqual(parsed["name"], "mammouth // not a comment")
        self.assertEqual(parsed["nested"]["url"], "https://mammouth.ai/*test*/")
        self.assertEqual(parsed["nested"]["port"], 8000)
        self.assertEqual(parsed["array"], [1, 2, 3])

    def test_merge_claude_mcp_entry_new_file(self):
        mcp_file = self.workspace_dir / ".mcp.json"
        entry = {
            "type": "http",
            "url": "https://my-tunnel.example.com/mcp",
            "headers": {"Authorization": "Bearer test-tok"}
        }
        _merge_claude_mcp_entry(mcp_file, entry, server_name="mammouth-defroster-9000")
        self.assertTrue(mcp_file.is_file())

        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        self.assertIn("mcpServers", data)
        self.assertEqual(data["mcpServers"]["mammouth-defroster-9000"]["type"], "http")
        self.assertEqual(data["mcpServers"]["mammouth-defroster-9000"]["url"], "https://my-tunnel.example.com/mcp")

    def test_merge_claude_mcp_entry_preserves_existing_servers_and_creates_backup(self):
        mcp_file = self.workspace_dir / ".mcp.json"
        initial_data = {
            "$schema": "https://json.schemastore.org/mcp.json",
            "mcpServers": {
                "sqlite": {
                    "command": "uvx",
                    "args": ["mcp-server-sqlite", "--db-path", "test.db"]
                }
            }
        }
        mcp_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

        new_entry = {
            "type": "http",
            "url": "https://custom.tailscale.net/mcp",
            "headers": {"Authorization": "Bearer mc_secret"}
        }
        _merge_claude_mcp_entry(mcp_file, new_entry, server_name="mammouth-defroster-9000")

        # Verify backup was created
        backup_file = self.workspace_dir / ".mcp.json.bak"
        self.assertTrue(backup_file.is_file())
        self.assertIn("mcp-server-sqlite", backup_file.read_text(encoding="utf-8"))

        # Verify merged content has both servers
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        self.assertIn("sqlite", data["mcpServers"])
        self.assertIn("mammouth-defroster-9000", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["sqlite"]["command"], "uvx")
        self.assertEqual(data["mcpServers"]["mammouth-defroster-9000"]["url"], "https://custom.tailscale.net/mcp")

    def test_tailscale_public_domain_detection(self):
        fake_status_json = json.dumps({
            "CertDomains": ["my-node.ts.net"],
            "Self": {"DNSName": "my-node.magic.ts.net."}
        })
        with patch("modules.claude_code.find_tailscale_binary", return_value="C:\\fake\\tailscale.exe"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=fake_status_json, stderr="")
                domain = get_tailscale_public_domain()
                self.assertEqual(domain, "https://my-node.ts.net")

    def test_active_tunnel_persistence(self):
        tmp_tunnel_file = Path(self.test_dir) / "tunnel_info.json"
        with patch("modules.claude_code.TUNNEL_INFO_FILE", tmp_tunnel_file):
            save_active_tunnel_info("https://defroster.trycloudflare.com", "Cloudflare Tunnel")
            info = get_active_tunnel_info()
            self.assertEqual(info["tunnel_url"], "https://defroster.trycloudflare.com")
            self.assertEqual(info["tunnel_mode"], "Cloudflare Tunnel")
            self.assertGreater(info["updated_at"], 0)

            # Test clearing
            save_active_tunnel_info(None, "")
            cleared = get_active_tunnel_info()
            self.assertIsNone(cleared["tunnel_url"])

    def test_resolve_public_tunnel_url(self):
        tmp_tunnel_file = Path(self.test_dir) / "tunnel_info.json"
        with patch("modules.claude_code.TUNNEL_INFO_FILE", tmp_tunnel_file):
            # 1. When live tunnel is active
            save_active_tunnel_info("https://active-subdomain.trycloudflare.com/", "Cloudflare Tunnel")
            res = resolve_public_tunnel_url(endpoint_path="/mcp")
            self.assertEqual(res, "https://active-subdomain.trycloudflare.com/mcp")

            # 2. When live tunnel is cleared but custom_public_url is in config
            save_active_tunnel_info(None, "")
            fake_config = {"server": {"custom_public_url": "https://defroster.customdomain.org/mcp"}}
            with patch("config.load_config", return_value=fake_config):
                res = resolve_public_tunnel_url(endpoint_path="/mcp")
                self.assertEqual(res, "https://defroster.customdomain.org/mcp")

    def test_resolve_active_server_url(self):
        # target_cloud=True with public tunnel
        with patch("modules.claude_code.resolve_public_tunnel_url", return_value="https://tunnel.example.com/mcp"):
            cloud_url = resolve_active_server_url(target_cloud=True)
            self.assertEqual(cloud_url, "https://tunnel.example.com/mcp")

        # target_cloud=False falls back to local bind
        fake_config = {"server": {"host": "127.0.0.1", "port": 8000}}
        with patch("config.load_config", return_value=fake_config):
            local_url = resolve_active_server_url(target_cloud=False)
            self.assertEqual(local_url, "http://127.0.0.1:8000/mcp")

    def test_sync_claude_code_mcp_workspace_cloud_vs_local(self):
        ws_mcp = self.workspace_dir / ".mcp.json"
        
        # Cloud sync with public URL defaults to secure env_var mode
        res = sync_claude_code_mcp(
            workspace_path=str(self.workspace_dir),
            server_url="https://cloud-tunnel.mammouth.ai/mcp",
            api_token="mc_live_12345",
            target_cloud=True,
            sync_global=False
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["cloud_ready"])
        self.assertEqual(res["auth_mode"], "env_var")

        data = json.loads(ws_mcp.read_text(encoding="utf-8"))
        entry = data["mcpServers"]["mammouth-defroster-9000"]
        self.assertEqual(entry["type"], "http")
        self.assertEqual(entry["url"], "https://cloud-tunnel.mammouth.ai/mcp")
        self.assertEqual(entry["headers"]["Authorization"], "Bearer ${MAMMOUTH_DEFROSTER_TOKEN}")

    def test_sync_claude_code_mcp_explicit_token_mode(self):
        ws_mcp = self.workspace_dir / ".mcp.json"
        
        # Explicit opt-out of env_var mode uses static token
        res = sync_claude_code_mcp(
            workspace_path=str(self.workspace_dir),
            server_url="https://cloud-tunnel.mammouth.ai/mcp",
            api_token="mc_live_12345",
            target_cloud=True,
            use_env_var=False,
            sync_global=False
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["cloud_ready"])
        self.assertEqual(res["auth_mode"], "token")

        data = json.loads(ws_mcp.read_text(encoding="utf-8"))
        entry = data["mcpServers"]["mammouth-defroster-9000"]
        self.assertEqual(entry["type"], "http")
        self.assertEqual(entry["url"], "https://cloud-tunnel.mammouth.ai/mcp")
        self.assertEqual(entry["headers"]["Authorization"], "Bearer mc_live_12345")

    def test_sync_claude_code_mcp_with_env_var(self):
        ws_mcp = self.workspace_dir / ".mcp.json"
        res = sync_claude_code_mcp(
            workspace_path=str(self.workspace_dir),
            server_url="https://cloud-tunnel.mammouth.ai/mcp",
            api_token="mc_ignored_token",
            target_cloud=True,
            use_env_var=True,
            sync_global=False
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["auth_mode"], "env_var")

        data = json.loads(ws_mcp.read_text(encoding="utf-8"))
        entry = data["mcpServers"]["mammouth-defroster-9000"]
        self.assertEqual(entry["headers"]["Authorization"], "Bearer ${MAMMOUTH_DEFROSTER_TOKEN}")

    def test_get_claude_code_status(self):
        ws_mcp = self.workspace_dir / ".mcp.json"
        initial_data = {
            "mcpServers": {
                "mammouth-defroster-9000": {
                    "type": "http",
                    "url": "https://pub.tunnel.com/mcp",
                    "headers": {"Authorization": "Bearer test"}
                }
            }
        }
        ws_mcp.write_text(json.dumps(initial_data), encoding="utf-8")

        fake_exe = Path(self.test_dir) / "claude.cmd"
        fake_exe.touch()

        with patch("modules.claude_code.get_claude_executable", return_value=str(fake_exe)):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="claude-code 0.2.14\n", stderr="")
                st = get_claude_code_status(workspace_path=str(self.workspace_dir))
                self.assertTrue(st["installed"])
                self.assertIn("0.2.14", st["version"])
                self.assertTrue(st["workspace_mcp_synced"])
                self.assertTrue(st["cloud_ready"])
                self.assertEqual(st["configured_url"], "https://pub.tunnel.com/mcp")

    def test_launch_claude_terminal_admin_shell_guard(self):
        # When allow_admin_shell is False -> PermissionError
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            with self.assertRaises(PermissionError) as ctx:
                launch_claude_terminal(workspace_path=str(self.workspace_dir), cloud=True)
            self.assertIn("Admin shell required", str(ctx.exception))

    def test_run_claude_task_admin_shell_guard(self):
        # When allow_admin_shell is False -> PermissionError
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": False}}):
            with self.assertRaises(PermissionError) as ctx:
                run_claude_task("check version", workspace_path=str(self.workspace_dir), cloud=True)
            self.assertIn("Admin shell required", str(ctx.exception))

    def test_cors_origins_include_claude_and_anthropic(self):
        from config import DEFAULT_CONFIG
        allowed = DEFAULT_CONFIG["server"]["allowed_origins"]
        self.assertIn("https://claude.ai", allowed)
        self.assertIn("https://code.claude.ai", allowed)
        self.assertIn("https://app.claude.ai", allowed)
        self.assertIn("https://console.anthropic.com", allowed)

    def test_server_claude_tools_registration_and_hints(self):
        import server
        self.assertIn("claude_code_status", server._DEFROSTER_TOOL_TO_MODULE)
        self.assertEqual(server._DEFROSTER_TOOL_TO_MODULE["claude_code_status"], "claude_code")
        self.assertEqual(server._DEFROSTER_TOOL_TO_MODULE["claude_code_sync_mcp"], "claude_code")
        self.assertEqual(server._DEFROSTER_TOOL_TO_MODULE["claude_code_launch_terminal"], "claude_code")
        self.assertEqual(server._DEFROSTER_TOOL_TO_MODULE["claude_code_run_task"], "claude_code")

        self.assertIn("claude_code_status", server._MULTILINGUAL_TOOL_HINTS)
        self.assertIn("claude_code_sync_mcp", server._MULTILINGUAL_TOOL_HINTS)
        self.assertIn("claude_code_launch_terminal", server._MULTILINGUAL_TOOL_HINTS)
        self.assertIn("claude_code_run_task", server._MULTILINGUAL_TOOL_HINTS)

    def test_require_module_claude_code_guard(self):
        import server
        fake_config = {"modules": {"claude_code": {"enabled": False}}}
        guarded_status = server.require_module("claude_code")(server.claude_code_status)
        with patch("server.load_config", return_value=fake_config):
            with self.assertRaises(PermissionError) as ctx:
                guarded_status()
            self.assertIn("claude_code", str(ctx.exception))

    def test_strip_jsonc_preserves_commas_inside_strings(self):
        # A string containing a comma followed by a brace must NOT be mutated
        jsonc_input = '{"pattern": "item, }", "array": [1, 2, ], }'
        cleaned = _strip_jsonc(jsonc_input)
        parsed = json.loads(cleaned)
        self.assertEqual(parsed["pattern"], "item, }")
        self.assertEqual(parsed["array"], [1, 2])

    def test_merge_claude_mcp_entry_claude_json_no_schema(self):
        # ~/.claude.json should never receive $schema: mcp.json
        claude_file = self.workspace_dir / ".claude.json"
        claude_file.write_text(json.dumps({"theme": "dark", "hasCompletedOnboarding": True}), encoding="utf-8")
        entry = {"type": "http", "url": "http://127.0.0.1:8000/mcp"}
        _merge_claude_mcp_entry(claude_file, entry)
        data = json.loads(claude_file.read_text(encoding="utf-8"))
        self.assertNotIn("$schema", data)
        self.assertEqual(data["theme"], "dark")
        self.assertIn("mammouth-defroster-9000", data["mcpServers"])

    def test_sync_claude_code_mcp_global_uses_local_url(self):
        # When syncing for cloud sessions, global config should still use local URL so local sessions work when tunnel is off
        fake_global = self.workspace_dir / ".claude.json"
        with patch("modules.claude_code.DEFAULT_CLAUDE_CONFIG_FILE", fake_global):
            res = sync_claude_code_mcp(
                workspace_path=str(self.workspace_dir),
                server_url="https://ephemeral.trycloudflare.com/mcp",
                api_token="mc_tok_123",
                target_cloud=True,
                sync_global=True,
                update_claude_md=True
            )
            self.assertTrue(res["success"])
            global_data = json.loads(fake_global.read_text(encoding="utf-8"))
            global_url = global_data["mcpServers"]["mammouth-defroster-9000"]["url"]
            self.assertNotIn("trycloudflare", global_url)
            self.assertIn("127.0.0.1", global_url)

            # Also verify CLAUDE.md was created in workspace
            claude_md = self.workspace_dir / "CLAUDE.md"
            self.assertTrue(claude_md.is_file())
            self.assertIn("Mammouth Defroster 9000", claude_md.read_text(encoding="utf-8"))

    def test_get_claude_executable_dynamic_npm_prefix(self):
        fake_bin_dir = Path(self.test_dir) / "custom_node"
        fake_bin_dir.mkdir(parents=True, exist_ok=True)
        fake_claude = fake_bin_dir / "claude.cmd"
        fake_claude.touch()

        with patch("shutil.which") as mock_which:
            def side_effect(cmd):
                if cmd in ("npm", "npm.cmd"):
                    return "C:\\custom\\npm.cmd"
                return None
            mock_which.side_effect = side_effect

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=str(fake_bin_dir) + "\n", stderr="")
                found = get_claude_executable()
                self.assertIsNotNone(found)
                self.assertEqual(Path(found).resolve(), fake_claude.resolve())

    def test_defroster_catalog_contains_claude_category(self):
        import server
        res = server.defroster_catalog(search="claude")
        self.assertIn("claude", res["categories"])
        tools = res["categories"]["claude"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("claude_code_status", tool_names)
        self.assertIn("claude_code_sync_mcp", tool_names)
        self.assertIn("claude_code_launch_terminal", tool_names)
        self.assertIn("claude_code_run_task", tool_names)

    def test_launch_claude_terminal_cmd_empty_title_syntax(self):
        with patch("config.load_config", return_value={"server": {"allow_admin_shell": True}}):
            with patch("modules.claude_code.get_claude_executable", return_value="C:\\fake\\claude.cmd"):
                with patch("subprocess.Popen") as mock_popen:
                    res = launch_claude_terminal(
                        workspace_path=str(self.workspace_dir),
                        cloud=True,
                        preferred_terminal="powershell"
                    )
                    self.assertTrue(res["success"])
                    cmd_called = mock_popen.call_args[0][0]
                    # cmd.exe /c start "" powershell.exe syntax
                    self.assertEqual(cmd_called[0], "cmd.exe")
                    self.assertEqual(cmd_called[1], "/c")
                    self.assertEqual(cmd_called[2], "start")
                    self.assertEqual(cmd_called[3], "")
                    self.assertEqual(cmd_called[4], "powershell.exe")


if __name__ == "__main__":
    unittest.main()
