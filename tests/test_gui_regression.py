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
        app.after = MagicMock()
        app._switch_to_mammouth_tab = MagicMock()

        with patch("socket.socket.connect_ex", return_value=1), \
             patch("gui.threading.Thread") as mock_thread, \
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

    def test_dashboard_key_visibility_toggle_and_refresh(self):
        """Test that _toggle_dash_key_visibility and _refresh_all_endpoint_labels display the original key."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.config_data = {
            "server": {
                "host": "127.0.0.1",
                "port": 8000,
                "api_token": "original_live_key_999",
                "tunnel_mode": "Direct / LAN IP",
                "endpoint_path": "/sse"
            }
        }
        app.lbl_public_url = MagicMock()
        app.lbl_local_url = MagicMock()
        app.lbl_dash_key = MagicMock()
        app.btn_toggle_dash_key = MagicMock()
        app.dash_token_visible = True

        app._refresh_all_endpoint_labels()
        app.lbl_dash_key.configure.assert_called_with(text="original_live_key_999")

        # Toggle visibility to hidden
        app._toggle_dash_key_visibility()
        self.assertFalse(app.dash_token_visible)
        app.lbl_dash_key.configure.assert_called_with(text="•" * 28)
        app.btn_toggle_dash_key.configure.assert_called_with(text="👁️ Show Key")

        # Toggle visibility back to shown
        app._toggle_dash_key_visibility()
        self.assertTrue(app.dash_token_visible)
        app.lbl_dash_key.configure.assert_called_with(text="original_live_key_999")
        app.btn_toggle_dash_key.configure.assert_called_with(text="🔒 Hide Key")

    def test_find_cloudflared_binary(self):
        """Test that find_cloudflared_binary resolves existing binary or custom path."""
        from gui import find_cloudflared_binary, BASE_DIR

        # If cloudflared.exe exists in mcpserv, it must be discovered
        cf_local = BASE_DIR / "cloudflared.exe"
        if cf_local.exists():
            found = find_cloudflared_binary()
            self.assertIsNotNone(found)
            self.assertTrue(os.path.exists(found))

        # Test custom path resolution
        with patch("os.path.exists") as mock_exists, patch("os.path.isfile", return_value=True):
            mock_exists.return_value = True
            found_custom = find_cloudflared_binary("C:\\tools\\cloudflared.exe")
            self.assertEqual(found_custom, os.path.abspath("C:\\tools\\cloudflared.exe"))

    def test_mode_change_triggers_tunnel_when_online(self):
        """Test that switching tunnel mode while server is online triggers the tunnel."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.is_server_running = True
        app.config_data = {
            "server": {
                "port": 8888,
                "tunnel_mode": "Direct / LAN IP"
            }
        }
        app.opt_tunnel_mode = MagicMock()
        app._refresh_all_endpoint_labels = MagicMock()
        app._log = MagicMock()
        app._start_cloudflare_tunnel = MagicMock()

        with patch("gui.save_config"):
            app._on_dash_mode_changed("Cloudflare Tunnel")
            app._start_cloudflare_tunnel.assert_called_once_with(8888)


    def test_icon_candidates_discovery(self):
        """Test that icon candidates list covers _internal, root assets, and dev assets."""
        from gui import BASE_DIR
        from pathlib import Path
        
        candidates = [
            BASE_DIR / "assets" / "icon.ico",
            BASE_DIR / "_internal" / "assets" / "icon.ico",
            Path(__file__).parent.parent / "assets" / "icon.ico",
        ]
        # At least one candidate must exist in the repository layout
        found_any = any(c.exists() for c in candidates)
        self.assertTrue(found_any, "No icon.ico was found in any standard candidate path!")

    def test_tray_manager_icon_loading(self):
        """Test that DefrosterTrayApp.load_icon_image loads a valid image."""
        from tray_manager import DefrosterTrayApp
        tray_app = DefrosterTrayApp()
        img = tray_app.load_icon_image()
        self.assertIsNotNone(img)
        self.assertGreater(img.size[0], 0)
        self.assertGreater(img.size[1], 0)


class TestTaskSchedulerGuiRegression(unittest.TestCase):
    def test_gui_scheduler_initialization_and_handlers(self):
        """Test that MammouthControlCenter initializes TaskSchedulerEngine with all required handlers."""
        from gui import MammouthControlCenter
        from modules.task_scheduler import TaskSchedulerEngine

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.after = MagicMock()
        app._switch_to_mammouth_tab = MagicMock()
        app.mammouth_browser = MagicMock()

        app._init_task_scheduler()
        self.assertTrue(hasattr(app, "task_countdown_labels"))
        self.assertIsInstance(app.task_countdown_labels, dict)

        engine = TaskSchedulerEngine.get_instance()
        self.assertIn("mammouth_web", engine._handlers)
        self.assertIn("mammouth_code", engine._handlers)
        self.assertIn("powershell", engine._handlers)
        self.assertIn("notification", engine._handlers)

        # Test web trigger handler invocation
        res = app._on_trigger_mammouth_web_task({
            "name": "Livebericht Test",
            "prompt": "Test prompt",
            "runs_done": 0,
            "switch_tab": True,
            "auto_submit": True
        })
        self.assertEqual(res, "Dispatched to Mammouth AI Web")
        app.after.assert_called()

    def test_browser_has_send_chat_prompt(self):
        """Test that MammouthBrowserFrame defines send_chat_prompt."""
        from modules.embedded_browser import MammouthBrowserFrame
        self.assertTrue(hasattr(MammouthBrowserFrame, "send_chat_prompt"))

    def test_zen_mode_toggle_behavior(self):
        """Test that toggle_zen_mode collapses/restores sidebar and updates UI elements."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app.sidebar_visible = True
        app.zen_mode_active = False
        app.sidebar = MagicMock()
        app.content_area = MagicMock()
        app.btn_toggle_sidebar = MagicMock()
        app.btn_zen_header = MagicMock()
        app.mammouth_browser = MagicMock()
        app._select_nav_tab = MagicMock()
        app._log = MagicMock()

        # Activate Zen Mode
        app.toggle_zen_mode(True)
        self.assertTrue(app.zen_mode_active)
        self.assertFalse(app.sidebar_visible)
        app.sidebar.pack_forget.assert_called_once()
        app.btn_toggle_sidebar.configure.assert_called_with(text="☰")
        app._select_nav_tab.assert_called_with("💬 Mammouth AI Web")
        app.mammouth_browser.set_zen_state.assert_called_with(True)

        # Deactivate Zen Mode
        app.toggle_zen_mode(False)
        self.assertFalse(app.zen_mode_active)
        self.assertTrue(app.sidebar_visible)
        app.sidebar.pack.assert_called_once()
        app.btn_toggle_sidebar.configure.assert_called_with(text="◀")
        app.mammouth_browser.set_zen_state.assert_called_with(False)

    def test_global_hotkey_manager_lifecycle(self):
        """Test global hotkey registration, status inspection, and unregistration."""
        from modules.global_hotkey import register_global_hotkey, unregister_global_hotkey, is_global_hotkey_registered

        called = []
        registered = register_global_hotkey(lambda: called.append(True), key="F12", modifiers="Ctrl+Alt", hotkey_id=9998)
        if registered:
            self.assertTrue(is_global_hotkey_registered())
            unregister_global_hotkey()
            self.assertFalse(is_global_hotkey_registered())
        else:
            # Running in non-interactive / headless service session (Win32 error: 5 Access Denied)
            self.assertFalse(is_global_hotkey_registered())

    def test_theme_palette_constants(self):
        """Verify Mammouth AI brand theme palette constants are defined."""
        from gui import THEME_BG, THEME_HEADER_BG, THEME_CARD_BG, THEME_ACCENT, THEME_SUCCESS

        self.assertEqual(THEME_BG, ("#F2EBE1", "#242428"))
        self.assertEqual(THEME_HEADER_BG, ("#EDE3D4", "#1E1E22"))
        self.assertEqual(THEME_CARD_BG, ("#FCFAF7", "#2F2F33"))
        self.assertEqual(THEME_ACCENT, ("#9F6C45", "#B88557"))
        self.assertEqual(THEME_SUCCESS, ("#2E7D32", "#10B981"))

    def test_memory_vault_gui_methods(self):
        """Verify MammouthControlCenter contains Memory Vault methods and handlers."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        self.assertTrue(hasattr(app, "_setup_memory_tab"))
        self.assertTrue(hasattr(app, "_refresh_memory_list"))
        self.assertTrue(hasattr(app, "_render_memory_cards"))
        self.assertTrue(hasattr(app, "_add_memory"))
        self.assertTrue(hasattr(app, "_edit_memory"))
        self.assertTrue(hasattr(app, "_delete_memory"))
        self.assertTrue(hasattr(app, "_copy_memory_content"))

    def test_memory_dialog_exists(self):
        """Verify MemoryDialog class is defined."""
        from gui import MemoryDialog
        self.assertTrue(callable(MemoryDialog))


class TestGuiStartupAndSchedulerTasksRegression(unittest.TestCase):
    def test_gui_datetime_module_imports(self):
        """Verify datetime, timezone, and timedelta are imported at module level in gui.py."""
        import gui
        from datetime import datetime, timezone, timedelta

        self.assertIs(gui.datetime, datetime)
        self.assertIs(gui.timezone, timezone)
        self.assertIs(gui.timedelta, timedelta)

        # Ensure datetime methods work directly on gui.datetime
        now = gui.datetime.now()
        self.assertIsInstance(now, datetime)
        parsed = gui.datetime.fromisoformat("2026-10-28T14:30:00")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.hour, 14)

    def test_splash_screen_close_unmasks_safely(self):
        """Verify SplashScreen.close unsets topmost, withdraws, flushes idletasks, and safely destroys the window."""
        from gui import SplashScreen

        mock_parent = MagicMock()
        with patch.object(SplashScreen, "__init__", return_value=None):
            splash = SplashScreen(mock_parent)
            splash.attributes = MagicMock()
            splash.grab_release = MagicMock()
            splash.withdraw = MagicMock()
            splash.update_idletasks = MagicMock()
            splash.destroy = MagicMock()

            splash.close()

            splash.attributes.assert_called_with("-topmost", False)
            splash.grab_release.assert_called_once()
            splash.withdraw.assert_called_once()
            splash.update_idletasks.assert_called_once()
            splash.destroy.assert_called_once()

            # Multiple calls to close should not raise exceptions
            splash.destroy.side_effect = Exception("already destroyed")
            try:
                splash.close()
            except Exception as e:
                self.fail(f"splash.close() raised an unexpected exception: {e}")

    def test_startup_exception_closes_splash_screen(self):
        """Verify that any exception during MammouthControlCenter.__init__ destroys splash immediately."""
        from gui import MammouthControlCenter, SplashScreen

        mock_splash = MagicMock(spec=SplashScreen)

        with patch("gui.SplashScreen", return_value=mock_splash), \
             patch("gui.load_config", side_effect=RuntimeError("Simulated configuration error")), \
             patch.object(MammouthControlCenter, "withdraw"):

            with self.assertRaises(RuntimeError) as ctx:
                MammouthControlCenter()

            self.assertIn("Simulated configuration error", str(ctx.exception))
            # Verify splash close was invoked to unmask error dialogues
            mock_splash.close.assert_called_once()

    def test_main_crash_handler_logs_and_unmasks(self):
        """Verify main() catches initialization crashes, writes crash log, cleans up root, and displays topmost dialog."""
        import gui
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            test_crash_log = Path(tmpdir) / "gui_crash.log"
            mock_tk = MagicMock()
            mock_tk_instance = MagicMock()
            mock_tk.return_value = mock_tk_instance
            mock_msgbox = MagicMock()

            with patch.object(gui, "BASE_DIR", Path(tmpdir)), \
                 patch.object(gui, "MammouthControlCenter", side_effect=RuntimeError("Fatal startup boom")), \
                 patch("tkinter.Tk", mock_tk), \
                 patch("tkinter.messagebox.showerror", mock_msgbox), \
                 patch("os._exit") as mock_exit:

                gui.main()

                # Verify crash log was created and contains the error
                self.assertTrue(test_crash_log.exists(), "gui_crash.log was not created!")
                log_content = test_crash_log.read_text(encoding="utf-8")
                self.assertIn("Fatal startup boom", log_content)

                # Verify error dialog was presented with topmost attributes
                mock_tk_instance.withdraw.assert_called_once()
                mock_tk_instance.attributes.assert_called_with("-topmost", True)
                mock_msgbox.assert_called_once()
                mock_tk_instance.destroy.assert_called_once()
                mock_exit.assert_called_once_with(0)

    def test_update_task_countdowns_with_active_and_various_task_states(self):
        """Verify _update_task_countdowns formats countdowns, handles active/due/paused/completed states, and emojis."""
        from gui import MammouthControlCenter
        from datetime import datetime, timedelta

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.task_countdown_labels = {}
        app.lbl_task_stat_next = MagicMock()

        # Labels for 6 tasks
        lbl1 = MagicMock()
        lbl2 = MagicMock()
        lbl3 = MagicMock()
        lbl4 = MagicMock()
        lbl5 = MagicMock()
        lbl6 = MagicMock()
        app.task_countdown_labels = {
            1: lbl1,
            2: lbl2,
            3: lbl3,
            4: lbl4,
            5: lbl5,
            6: lbl6
        }

        now = datetime.now()
        future_next = (now + timedelta(seconds=125)).isoformat()
        past_next = (now - timedelta(seconds=10)).isoformat()

        fake_tasks = [
            {"id": 1, "name": "⚽ Live-Monitor Pokal", "status": "active", "next_run": future_next},
            {"id": 2, "name": "Past Due Task", "status": "active", "next_run": past_next},
            {"id": 3, "name": "Paused Task", "status": "paused", "next_run": future_next},
            {"id": 4, "name": "Completed Task", "status": "completed", "next_run": ""},
            {"id": 5, "name": "Stopped Task", "status": "stopped", "next_run": ""},
            {"id": 6, "name": "Malformed Task", "status": "active", "next_run": "INVALID_DATE_FORMAT_123"},
        ]

        with patch("gui.scheduler_list_tasks", return_value=fake_tasks):
            app._update_task_countdowns()

            # Task 1: Future countdown (approx 02:05 min)
            lbl1.configure.assert_called()
            call_text_1 = lbl1.configure.call_args[1].get("text", "")
            self.assertIn("Next trigger: 02:0", call_text_1)

            # Task 2: Executing
            lbl2.configure.assert_called_with(text="⏳ Executing...", text_color=("#059669", "#10B981"))

            # Task 3: Paused
            lbl3.configure.assert_called_with(text="⏸️ Paused", text_color=("#D97706", "#FBBF24"))

            # Task 4: Completed
            lbl4.configure.assert_called()
            self.assertIn("Completed", lbl4.configure.call_args[1].get("text", ""))

            # Task 5: Stopped
            lbl5.configure.assert_called_with(text="⏹️ Stopped", text_color=("#DC2626", "#F87171"))

            # Task 6: Fallback for malformed date string without crash
            lbl6.configure.assert_called()
            self.assertIn("INVALID_DATE_FORMAT", lbl6.configure.call_args[1].get("text", ""))

            # KPI Next Stat Label should show earliest active task (Task 2 is earliest since in past -> Executing...)
            app.lbl_task_stat_next.configure.assert_called()

    def test_update_task_countdowns_no_active_tasks(self):
        """Verify _update_task_countdowns updates next stat when no active tasks exist."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.task_countdown_labels = {10: MagicMock()}
        app.lbl_task_stat_next = MagicMock()

        fake_tasks = [
            {"id": 10, "name": "Archived Task", "status": "completed", "next_run": ""}
        ]

        with patch("gui.scheduler_list_tasks", return_value=fake_tasks):
            app._update_task_countdowns()
            app.lbl_task_stat_next.configure.assert_called_with(text="No active task")

    def test_update_task_countdowns_exception_resilience(self):
        """Verify _update_task_countdowns catches database errors gracefully and logs."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.task_countdown_labels = {1: MagicMock()}

        with patch("gui.scheduler_list_tasks", side_effect=RuntimeError("Database lock")):
            # Should not raise exception
            app._update_task_countdowns()
            app._log.assert_called()
            self.assertIn("[TASK COUNTDOWN ERROR]", app._log.call_args[0][0])

    def test_refresh_task_cards_with_real_sqlite_active_tasks(self):
        """Verify _refresh_task_cards populates cards and triggers countdown calculation against real SQLite tasks."""
        import tempfile
        from pathlib import Path
        from gui import MammouthControlCenter
        from modules.task_scheduler import (
            scheduler_create_task,
            scheduler_pause_task,
            _get_db
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            real_test_db = Path(tmpdir) / "tasks.db"
            with patch("modules.task_scheduler.DB_PATH", real_test_db):
                # Populate real tasks in SQLite
                t1 = scheduler_create_task(
                    name="⚽ Live Pokal Ticker",
                    prompt="Provide live game updates every 5 minutes.",
                    interval_seconds=300,
                    start_immediately=False
                )
                t2 = scheduler_create_task(
                    name="Immediate Monitor",
                    prompt="Check system status immediately.",
                    interval_seconds=60,
                    start_immediately=True
                )
                t3 = scheduler_create_task(
                    name="Paused Alert",
                    prompt="Check crypto alert when unpaused.",
                    interval_seconds=120,
                    start_immediately=False
                )
                scheduler_pause_task(t3["id"])

                app = MammouthControlCenter.__new__(MammouthControlCenter)
                app._log = MagicMock()
                app.tasks_scroll = MagicMock()
                app.tasks_scroll.winfo_children.return_value = []
                app.lbl_task_stat_running = MagicMock()
                app.lbl_task_stat_total = MagicMock()
                app.lbl_task_stat_next = MagicMock()

                # Mock CTkFrame / CTkLabel creation in _refresh_task_cards so it runs headless
                with patch("customtkinter.CTkFrame") as mock_frame, \
                     patch("customtkinter.CTkLabel") as mock_label, \
                     patch("customtkinter.CTkButton") as mock_btn, \
                     patch("customtkinter.CTkFont") as mock_font:

                    app._refresh_task_cards()

                    # Check KPI metrics updated properly from real DB
                    app.lbl_task_stat_running.configure.assert_called_with(text="2 active")
                    app.lbl_task_stat_total.configure.assert_called_with(text="0")

                    # Verify 3 tasks were registered into countdown labels
                    self.assertEqual(len(app.task_countdown_labels), 3)
                    self.assertIn(t1["id"], app.task_countdown_labels)
                    self.assertIn(t2["id"], app.task_countdown_labels)
                    self.assertIn(t3["id"], app.task_countdown_labels)

                    # Verify stat label for next task was configured
                    app.lbl_task_stat_next.configure.assert_called()

    def test_update_task_countdowns_with_timezone_aware_next_run(self):
        """Verify _update_task_countdowns handles timezone-aware ISO strings without raising TypeError."""
        from gui import MammouthControlCenter
        from datetime import datetime, timezone, timedelta

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        lbl1 = MagicMock()
        lbl2 = MagicMock()
        app.task_countdown_labels = {1: lbl1, 2: lbl2}
        app.lbl_task_stat_next = MagicMock()

        # UTC timestamp ending with Z and timestamp with explicit +02:00 offset
        now_utc = datetime.now(timezone.utc)
        utc_next = (now_utc + timedelta(seconds=180)).isoformat().replace("+00:00", "Z")
        offset_next = (now_utc + timedelta(seconds=300)).isoformat()

        fake_tasks = [
            {"id": 1, "name": "UTC Task", "status": "active", "next_run": utc_next},
            {"id": 2, "name": "Offset Task", "status": "active", "next_run": offset_next},
        ]

        with patch("gui.scheduler_list_tasks", return_value=fake_tasks):
            # Should not raise TypeError: can't subtract offset-naive and offset-aware datetimes
            app._update_task_countdowns()

            lbl1.configure.assert_called()
            call_text = lbl1.configure.call_args[1].get("text", "")
            self.assertIn("Next trigger:", call_text)
            self.assertIn("min", call_text)

            app.lbl_task_stat_next.configure.assert_called()
            stat_text = app.lbl_task_stat_next.configure.call_args[1].get("text", "")
            self.assertIn("UTC Task", stat_text)

    def test_update_task_countdowns_empty_labels_resets_next_stat(self):
        """Verify _update_task_countdowns resets lbl_task_stat_next to 'No active task' when labels dict is empty."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.task_countdown_labels = {}
        app.lbl_task_stat_next = MagicMock()

        app._update_task_countdowns()
        app.lbl_task_stat_next.configure.assert_called_with(text="No active task")

    def test_refresh_task_cards_empty_tasks_resets_next_stat(self):
        """Verify _refresh_task_cards resets lbl_task_stat_next to 'No active task' when no tasks exist in DB."""
        from gui import MammouthControlCenter

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        app.tasks_scroll = MagicMock()
        app.tasks_scroll.winfo_children.return_value = []
        app.lbl_task_stat_running = MagicMock()
        app.lbl_task_stat_total = MagicMock()
        app.lbl_task_stat_next = MagicMock()

        with patch("gui.scheduler_list_tasks", return_value=[]), \
             patch("customtkinter.CTkFrame"), \
             patch("customtkinter.CTkLabel"), \
             patch("customtkinter.CTkButton"), \
             patch("customtkinter.CTkFont"):

            app._refresh_task_cards()

            app.lbl_task_stat_running.configure.assert_called_with(text="0 active")
            app.lbl_task_stat_total.configure.assert_called_with(text="0")
            app.lbl_task_stat_next.configure.assert_called_with(text="No active task")

    def test_update_task_countdowns_individual_label_error_isolation(self):
        """Verify that a failing or destroyed label widget on Task 1 does not prevent Task 2 from updating."""
        from gui import MammouthControlCenter
        from datetime import datetime, timedelta

        app = MammouthControlCenter.__new__(MammouthControlCenter)
        app._log = MagicMock()
        lbl1 = MagicMock()
        lbl1.configure.side_effect = RuntimeError("Widget destroyed or TclError")
        lbl2 = MagicMock()
        app.task_countdown_labels = {1: lbl1, 2: lbl2}
        app.lbl_task_stat_next = MagicMock()

        now = datetime.now()
        fake_tasks = [
            {"id": 1, "name": "Broken Widget Task", "status": "active", "next_run": (now + timedelta(seconds=60)).isoformat()},
            {"id": 2, "name": "Healthy Task", "status": "active", "next_run": (now + timedelta(seconds=120)).isoformat()},
        ]

        with patch("gui.scheduler_list_tasks", return_value=fake_tasks):
            app._update_task_countdowns()

            # Task 2 must still receive its configuration call despite Task 1 throwing an error
            lbl2.configure.assert_called()
            call_text = lbl2.configure.call_args[1].get("text", "")
            self.assertIn("Next trigger: 0", call_text)
            self.assertIn("min", call_text)
            # Stat label must still update
            app.lbl_task_stat_next.configure.assert_called()


if __name__ == "__main__":
    unittest.main()


