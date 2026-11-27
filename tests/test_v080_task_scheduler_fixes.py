"""Regression tests for Mammouth Defroster 9000 v0.8.0 Automated Task Scheduler fixes."""

import asyncio
import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import config
import gui
import modules.task_scheduler as ts
import server
from modules.embedded_browser import MammouthBrowserFrame


class TestV080AutomatedTasksFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_v080_tasks.db"
        self.db_patch = patch("modules.task_scheduler.DB_PATH", self.test_db)
        self.db_patch.start()

    def tearDown(self):
        eng = ts.TaskSchedulerEngine.get_instance()
        eng.stop_background_loop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_mammouth_safe_exposes_scheduler_tools_within_budget(self):
        """Verify streamlined task_schedule_* tools are allowed in mammouth_safe and within 7,719 token budget."""
        safe_tools = config.TOOL_PROFILES["mammouth_safe"]["tools"]
        for name in ("task_schedule_create", "task_schedule_manage"):
            self.assertIn(name, safe_tools)

        async def _check():
            cfg = config.load_config()
            cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"
            with patch("server.load_config", return_value=cfg):
                tools = await server.mcp.list_tools()
                names = [t.name for t in tools]
                self.assertLessEqual(len(names), 28)
                for req_name in ("task_schedule_create", "task_schedule_manage"):
                    self.assertIn(req_name, names)
                schemas = [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]
                approx_tokens = len(json.dumps(schemas, default=str).encode("utf-8")) // 4
                self.assertLess(approx_tokens, 7719)

        asyncio.run(_check())

    def test_server_task_schedule_create_resolves_auto_target(self):
        """Verify task_schedule_create target='auto' resolves to configured default_chat_tab."""
        cfg_cg = {"embedded_browser": {"default_chat_tab": "chatgpt"}, "modules": {}}
        with patch("server.load_config", return_value=cfg_cg):
            t1 = server.task_schedule_create(name="Auto CG", prompt="Ping CG", interval_minutes=5)
            self.assertEqual(t1["target"], "chatgpt_web")
            ts.scheduler_delete_task(t1["id"])

        cfg_mm = {"embedded_browser": {"default_chat_tab": "mammouth"}, "modules": {}}
        with patch("server.load_config", return_value=cfg_mm):
            t2 = server.task_schedule_create(name="Auto MM", prompt="Ping MM", interval_minutes=5)
            self.assertEqual(t2["target"], "mammouth_web")
            ts.scheduler_delete_task(t2["id"])

    def test_timezone_aware_next_run_due_dispatch_and_completed_resume(self):
        """Verify UTC/offset next_run triggers due tasks and resuming a completed task resets runs_done."""
        eng = ts.TaskSchedulerEngine.get_instance()
        called = []
        eng.register_handler("chatgpt_web", lambda t: called.append(t["id"]) or "Dispatched OK")

        t = ts.scheduler_create_task(
            name="TZ Task",
            prompt="Test UTC",
            interval_seconds=60,
            repeat_count=1,
            target="chatgpt_web",
            start_immediately=False,
        )
        past_utc = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        conn = ts._get_db()
        with conn:
            conn.execute("UPDATE scheduled_tasks SET next_run = ? WHERE id = ?", (past_utc, t["id"]))
        conn.close()

        reports = eng.check_and_run_due_tasks()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "completed")
        self.assertEqual(called, [t["id"]])

        resumed = ts.scheduler_resume_task(t["id"])
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(resumed["runs_done"], 0)
        self.assertTrue(resumed["next_run"])

    def test_background_loop_executes_due_task_and_async_result_update(self):
        """Verify start_background_loop executes due tasks on daemon thread and async result updates task_runs."""
        eng = ts.TaskSchedulerEngine.get_instance()
        ev = threading.Event()
        eng.register_handler("notification", lambda t: (ev.set(), "Alert sent")[1])

        t = ts.scheduler_create_task(
            name="BG Loop Task",
            prompt="Hello",
            interval_seconds=60,
            repeat_count=1,
            target="notification",
            start_immediately=True,
        )
        eng.start_background_loop(poll_interval=0.1)
        try:
            self.assertTrue(ev.wait(timeout=3.0), "Background loop did not dispatch due task in time")
            time.sleep(0.15)
            history = ts.scheduler_get_history(t["id"])
            self.assertGreaterEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "success")

            ts.scheduler_update_run_result(t["id"], 1, "success", 0, "Exit 0: Done", duration_ms=42)
            updated = ts.scheduler_get_task(t["id"])
            self.assertEqual(updated["last_result"], "Exit 0: Done")
            history2 = ts.scheduler_get_history(t["id"])
            self.assertEqual(history2[0]["output_summary"], "Exit 0: Done")
            self.assertEqual(history2[0]["duration_ms"], 42)
        finally:
            eng.stop_background_loop()

    def test_register_default_handlers_preserves_existing_gui_handlers(self):
        """Verify register_default_handlers only fills missing targets when overwrite=False."""
        eng = ts.TaskSchedulerEngine()
        gui_ps = MagicMock(return_value="GUI PS")
        eng.register_handler("powershell", gui_ps)
        ts.register_default_handlers(eng, overwrite=False)

        self.assertIs(eng._handlers["powershell"], gui_ps)
        self.assertIn("mammouth_code", eng._handlers)
        self.assertIn("notification", eng._handlers)

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    def test_gui_after_is_thread_safe_from_background_thread(self):
        """Verify background thread calling app.after() queues onto _bg_after_queue and executes on Tk main thread."""
        app = gui.MammouthControlCenter()
        try:
            ran_on_thread = []
            done = threading.Event()

            def bg_call():
                app.after(0, lambda: (ran_on_thread.append(threading.current_thread().ident), done.set()))

            t = threading.Thread(target=bg_call)
            t.start()
            t.join(timeout=2.0)

            deadline = time.time() + 2.0
            while not done.is_set() and time.time() < deadline:
                app.update()
                time.sleep(0.02)

            self.assertTrue(done.is_set(), "Background after() callback was never flushed by main thread pump")
            self.assertEqual(ran_on_thread[0], threading.main_thread().ident)
            self.assertTrue(ts.TaskSchedulerEngine.get_instance()._running)
        finally:
            app.destroy()
            self.assertFalse(ts.TaskSchedulerEngine.get_instance()._running)

    @patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
    def test_splash_close_does_not_cancel_main_window_scheduler_timers(self):
        """Regression test: SplashScreen.close() must not cancel _pump_bg_after_queue or _on_scheduler_tick."""
        app = gui.MammouthControlCenter()
        try:
            self.assertIsNotNone(app.splash)
            # Process finish_loading (~350ms) so SplashScreen.close() & destroy() actually run
            deadline = time.time() + 1.5
            while app.splash is not None and time.time() < deadline:
                app.update()
                time.sleep(0.03)
            self.assertIsNone(app.splash, "Splash screen should have closed")

            # After splash closes, background after() calls must still be pumped by the main window!
            ran = threading.Event()
            t = threading.Thread(target=lambda: app.after(0, ran.set))
            t.start()
            t.join(timeout=2.0)

            deadline2 = time.time() + 1.5
            while not ran.is_set() and time.time() < deadline2:
                app.update()
                time.sleep(0.02)

            self.assertTrue(ran.is_set(), "SplashScreen.destroy() wiped out _pump_bg_after_queue timer!")
            self.assertGreater(len(list(app.tk.call("after", "info"))), 0)
        finally:
            app.destroy()

    def test_embedded_browser_waits_for_navigation_before_injecting(self):
        """Verify send_chat_prompt defers injection while _nav_completed is False and injects once ready."""
        frame = MammouthBrowserFrame.__new__(MammouthBrowserFrame)
        frame.hwnd = 12345
        frame.is_embedded = True
        frame.brand_name = "ChatGPT"
        frame.start_url = "https://chatgpt.com"
        frame._nav_completed = False
        frame.winfo_toplevel = MagicMock()
        frame.winfo_toplevel.return_value.winfo_id.return_value = 999
        frame.edge = MagicMock()
        frame.edge.webview.CoreWebView2 = MagicMock()
        frame.edge.webview.Source = "about:blank"

        scheduled = []

        def fake_after(ms, fn):
            scheduled.append((ms, fn))
            return "aid"

        frame.after = fake_after

        with patch("modules.embedded_browser.HAS_WEBVIEW2", True), patch("modules.embedded_browser.user32"):
            ok = frame.send_chat_prompt("Delayed prompt", auto_submit=True, delay_ms=100)
            self.assertTrue(ok)
            self.assertEqual(len(scheduled), 1)

            # First callback runs while still on about:blank -> must reschedule instead of injecting
            scheduled[0][1]()
            frame.edge.webview.CoreWebView2.ExecuteScriptAsync.assert_not_called()
            self.assertEqual(len(scheduled), 2)

            # Complete navigation and run next retry -> must inject now
            frame._nav_completed = True
            frame.edge.webview.Source = "https://chatgpt.com"
            scheduled[1][1]()
            frame.edge.webview.CoreWebView2.ExecuteScriptAsync.assert_called_once()
            js_code = frame.edge.webview.CoreWebView2.ExecuteScriptAsync.call_args[0][0]
            self.assertIn("DataTransfer", js_code)
            self.assertIn("diktier", js_code)
            import inspect
            self.assertIn("GetForegroundWindow", inspect.getsource(MammouthBrowserFrame.send_chat_prompt))


if __name__ == "__main__":
    unittest.main()
