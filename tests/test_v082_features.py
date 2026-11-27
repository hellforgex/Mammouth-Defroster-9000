"""Tests for Mammouth Defroster 9000 v0.8.2: secret-file protection, optional tool annotations,
known folders in system_get_specs, and bounded directory listings."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

import config  # noqa: E402
import server  # noqa: E402
from modules import file_ops, system_monitor  # noqa: E402


def _passthrough_validate(raw_path, for_write=False):
    return Path(raw_path)


class TestSecretFileProtection(unittest.TestCase):
    def test_secret_file_detection(self):
        for name in (".env", ".env.local", "prod.env", "credentials.json", "gdrive_token.json",
                     "service_account.json", "storage_state.json", "api.token.json", "oauth.db",
                     "id_rsa", "id_ed25519", "key.pfx", "key.p12", "putty.ppk"):
            with self.subTest(name=name):
                self.assertTrue(file_ops.is_secret_file(Path("somewhere") / name))
        for name in (".env.example", "credentials.json.sample", "notes.txt", "README.md", "id_rsa.pub",
                     "environment.py", "config.json"):
            with self.subTest(name=name):
                self.assertFalse(file_ops.is_secret_file(Path("somewhere") / name))

    def test_defroster_own_config_files_are_secret(self):
        self.assertTrue(file_ops.is_secret_file(file_ops.BASE_DIR / "config.json"))
        self.assertTrue(file_ops.is_secret_file(file_ops.BASE_DIR / "hosts.json"))

    def test_file_read_blocks_secret_files_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / ".env"
            secret.write_text("TOKEN=abc123", encoding="utf-8")
            normal = Path(tmp) / "notes.txt"
            normal.write_text("hello", encoding="utf-8")
            with mock.patch.object(file_ops, "_validate_path", _passthrough_validate):
                with mock.patch.object(file_ops, "_secret_protection_enabled", return_value=True):
                    blocked = file_ops.file_read(str(secret))
                    self.assertIn("Security Shield", blocked)
                    self.assertNotIn("abc123", blocked)
                    self.assertEqual(file_ops.file_read(str(normal)), "hello")
                with mock.patch.object(file_ops, "_secret_protection_enabled", return_value=False):
                    self.assertEqual(file_ops.file_read(str(secret)), "TOKEN=abc123")

    def test_file_search_text_skips_secret_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("needle=1", encoding="utf-8")
            (Path(tmp) / "notes.txt").write_text("a needle here", encoding="utf-8")
            with mock.patch.object(file_ops, "_validate_path", _passthrough_validate):
                with mock.patch.object(file_ops, "_secret_protection_enabled", return_value=True):
                    files = {Path(r["file"]).name for r in file_ops.file_search_text(tmp, "needle", file_pattern="*")}
                    self.assertEqual(files, {"notes.txt"})
                with mock.patch.object(file_ops, "_secret_protection_enabled", return_value=False):
                    files = {Path(r["file"]).name for r in file_ops.file_search_text(tmp, "needle", file_pattern="*")}
                    self.assertEqual(files, {".env", "notes.txt"})

    def test_protection_fails_closed_when_config_unreadable(self):
        with mock.patch.object(config, "load_config", side_effect=RuntimeError("boom")):
            self.assertTrue(file_ops._secret_protection_enabled())


class TestBoundedDirectoryListing(unittest.TestCase):
    def test_max_entries_truncates_with_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(7):
                (Path(tmp) / f"f{i}.txt").write_text("x", encoding="utf-8")
            with mock.patch.object(file_ops, "_validate_path", _passthrough_validate):
                full = file_ops.directory_list(tmp)
                self.assertEqual(len(full), 7)
                self.assertFalse(any(e.get("truncated") for e in full))

                cut = file_ops.directory_list(tmp, max_entries=3)
                self.assertEqual(len(cut), 4)
                self.assertTrue(cut[-1]["truncated"])
                self.assertEqual(cut[-1]["total_entries"], 7)
                self.assertEqual(cut[-1]["shown"], 3)

    def test_clean_wrapper_exposes_max_entries(self):
        import inspect
        self.assertIn("max_entries", inspect.signature(file_ops.directory_list_clean).parameters)


class TestToolAnnotations(unittest.TestCase):
    def _dict_tool(self, name):
        return {"name": name, "description": "d", "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"audience": "user"}}

    def test_annotations_stripped_by_default(self):
        with mock.patch.object(server, "load_config", return_value={"server": {"expose_tool_annotations": False}}):
            tool = self._dict_tool("file_read")
            server._sanitize_mcp_tool_schema(tool)
            self.assertNotIn("annotations", tool)

    def test_annotations_advertised_when_enabled(self):
        with mock.patch.object(server, "load_config", return_value={"server": {"expose_tool_annotations": True}}):
            ro = self._dict_tool("file_read")
            server._sanitize_mcp_tool_schema(ro)
            self.assertTrue(ro["annotations"]["readOnlyHint"])
            self.assertNotIn("destructiveHint", ro["annotations"])

            ps = self._dict_tool("powershell_exec")
            server._sanitize_mcp_tool_schema(ps)
            self.assertFalse(ps["annotations"]["readOnlyHint"])
            self.assertTrue(ps["annotations"]["destructiveHint"])

            unknown = self._dict_tool("not_a_defroster_tool")
            server._sanitize_mcp_tool_schema(unknown)
            self.assertNotIn("annotations", unknown)

    def test_annotations_set_on_tool_objects_when_enabled(self):
        class MockTool:
            def __init__(self):
                self.name = "directory_list"
                self.description = "d"
                self.input_schema = {"type": "object", "properties": {}}
                self.annotations = None

        with mock.patch.object(server, "load_config", return_value={"server": {"expose_tool_annotations": True}}):
            tool = MockTool()
            server._sanitize_mcp_tool_schema(tool)
            ann = tool.annotations
            dumped = ann if isinstance(ann, dict) else ann.model_dump(by_alias=True)
            value = dumped["readOnlyHint"]
            self.assertTrue(value)

    def test_every_profile_tool_has_a_hint(self):
        names = set()
        for profile in config.TOOL_PROFILES.values():
            names.update(profile.get("tools", []))
        missing = sorted(n for n in names if n not in server._TOOL_ANNOTATION_HINTS)
        self.assertEqual(missing, [], f"Tools without annotation hints: {missing}")

    def test_hint_shape_follows_mcp_spec(self):
        for name, hints in server._TOOL_ANNOTATION_HINTS.items():
            with self.subTest(tool=name):
                self.assertIn("readOnlyHint", hints)
                self.assertIn("openWorldHint", hints)
                if hints["readOnlyHint"]:
                    self.assertNotIn("destructiveHint", hints)
                else:
                    self.assertIn("destructiveHint", hints)
                    self.assertIn("idempotentHint", hints)


class TestKnownFolders(unittest.TestCase):
    def test_known_folders_has_expected_keys(self):
        folders = system_monitor._known_folders()
        for key in ("home", "desktop", "documents", "downloads", "pictures", "music", "videos"):
            self.assertIn(key, folders)
            self.assertIsInstance(folders[key], str)
            self.assertTrue(folders[key])

    def test_system_get_specs_includes_known_folders(self):
        specs = system_monitor.system_get_specs()
        self.assertIn("known_folders", specs)
        self.assertIn("desktop", specs["known_folders"])


class TestV082Release(unittest.TestCase):
    def test_config_defaults_and_example_agree(self):
        server_defaults = config.DEFAULT_CONFIG["server"]
        self.assertTrue(server_defaults["protect_secret_files"])
        self.assertFalse(server_defaults["expose_tool_annotations"])
        self.assertFalse(server_defaults["allow_shell_downloads"])
        example = json.loads((SRC_DIR / "config.example.json").read_text(encoding="utf-8"))
        self.assertTrue(example["server"]["protect_secret_files"])
        self.assertFalse(example["server"]["expose_tool_annotations"])
        self.assertFalse(example["server"]["allow_shell_downloads"])

    def test_changelog_has_v082_entry_first(self):
        text = (SRC_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## [0.8.2]"), text.index("## [0.8.1]"))

    def test_instructions_mention_known_folders(self):
        self.assertIn("known_folders", server.mcp.instructions or "")


class TestDefaultPort(unittest.TestCase):
    def test_default_port_is_8742_everywhere(self):
        self.assertEqual(config.DEFAULT_CONFIG["server"]["port"], 8742)
        example = json.loads((SRC_DIR / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["server"]["port"], 8742)
        self.assertIn("http://localhost:8742", example["server"]["allowed_origins"])
        for rel in ("server.py", "gui.py", "tray_manager.py", "start_server.ps1"):
            with self.subTest(file=rel):
                text = (SRC_DIR / rel).read_text(encoding="utf-8")
                self.assertNotIn("8000", text)
                self.assertIn("8742", text)

    def test_localhost_origin_on_new_default_port_is_allowed(self):
        self.assertTrue(server.is_allowed_origin("http://127.0.0.1:8742"))
        self.assertTrue(server.is_allowed_origin("http://localhost:8742"))


class TestShellDownloadsGuiPersistence(unittest.TestCase):
    def test_shell_downloads_toggle_and_save_skills(self):
        from unittest.mock import MagicMock
        from gui import MammouthControlCenter

        class NoTk:
            pass

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.tk = NoTk()
        app.config_data = {"server": {}, "modules": {"shell_processes": {"enabled": True}}}
        app.module_switches = {"shell_processes": MagicMock()}
        app.module_switches["shell_processes"].get.return_value = True
        app.var_admin_shell = MagicMock()
        app.var_admin_shell.get.return_value = True
        app.var_shell_downloads = MagicMock()
        app.var_shell_downloads.get.return_value = True
        app.sw_shell_downloads = MagicMock()
        app.is_server_running = False
        app._log = MagicMock()
        app._count_active_tools = MagicMock(return_value=10)

        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            app._on_shell_downloads_toggle()
            app.sw_shell_downloads.configure.assert_called_with(
                text="🌐 HTTP / Downloads Allowed (irm, iwr, curl, wget)"
            )

        with mock.patch("gui.save_config") as mock_save, mock.patch("tkinter.messagebox.showinfo"):
            app._save_skills()
            mock_save.assert_called_once()
            self.assertTrue(app.config_data["server"]["allow_shell_downloads"])

        # Also verify cancel reverts the toggle
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            app._on_shell_downloads_toggle()
            app.var_shell_downloads.set.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
