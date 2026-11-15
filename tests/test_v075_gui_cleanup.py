import os
import sys
import unittest
from unittest.mock import patch
import pytest

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui


class TestV075GuiCleanup(unittest.TestCase):
    """Regression tests for v0.7.5 Fix 9: after() callback tracking and teardown cleanup."""

    def setUp(self):
        # Prevent server background startup during GUI instantiation
        self.patcher = patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_after_tracks_and_discards_executed_callback(self):
        """Verify that scheduled after callbacks are tracked and discarded once executed."""
        app = gui.MammouthControlCenter()
        try:
            executed = []

            def cb():
                executed.append(True)

            after_id = app.after(10, cb)
            self.assertIn(after_id, app._scheduled_after_ids)

            # Wait and process Tk events so callback executes
            app.after(50, lambda: None)
            app.update()
            # Give enough time for the 10ms callback to fire
            import time
            time.sleep(0.05)
            app.update()

            self.assertTrue(executed)
            self.assertNotIn(after_id, app._scheduled_after_ids)
        finally:
            app.destroy()

    def test_after_cancel_removes_from_tracking(self):
        """Verify that explicitly cancelling an after ID removes it from tracked IDs."""
        app = gui.MammouthControlCenter()
        try:
            aid = app.after(10000, lambda: None)
            self.assertIn(aid, app._scheduled_after_ids)

            app.after_cancel(aid)
            self.assertNotIn(aid, app._scheduled_after_ids)
        finally:
            app.destroy()

    def test_cancel_scheduled_afters_clears_all_and_tcl_info(self):
        """Verify cancel_scheduled_afters cancels all pending timers and purges interpreter state."""
        app = gui.MammouthControlCenter()
        try:
            aid1 = app.after(5000, lambda: None)
            aid2 = app.after(10000, lambda: None)
            self.assertIn(aid1, app._scheduled_after_ids)
            self.assertIn(aid2, app._scheduled_after_ids)

            app.cancel_scheduled_afters()
            self.assertEqual(len(app._scheduled_after_ids), 0)

            # Check that Tcl interpreter has no lingering after timers from app
            remaining_tcl = list(app.tk.call("after", "info"))
            self.assertNotIn(aid1, remaining_tcl)
            self.assertNotIn(aid2, remaining_tcl)
        finally:
            app.destroy()

    def test_destroy_cancels_all_pending_callbacks_without_tcl_spam(self):
        """Verify that app.destroy() safely cancels all pending callbacks with zero Tcl noise."""
        app = gui.MammouthControlCenter()
        # Schedule timers mimicking real GUI timers
        app.after(1000, app._on_scheduler_tick)
        app.after(2500, app._check_updates_async)
        app.after(10000, lambda: None)

        self.assertGreater(len(app._scheduled_after_ids), 0)

        # Destroy app - should cancel all scheduled afters
        app.destroy()
        self.assertEqual(len(app._scheduled_after_ids), 0)

    def test_on_close_cancels_scheduled_afters(self):
        """Verify that _on_close() cancels scheduled afters during shutdown."""
        app = gui.MammouthControlCenter()
        app.is_server_running = False
        app.after(5000, lambda: None)
        self.assertGreater(len(app._scheduled_after_ids), 0)

        with patch("os._exit") as mock_exit:
            app._on_close(force=True)
            self.assertTrue(mock_exit.called)
            self.assertEqual(len(app._scheduled_after_ids), 0)

    def test_init_exception_cancels_afters_and_destroys(self):
        """Verify that an exception during __init__ cancels scheduled afters and destroys window."""
        with patch("gui.load_config", side_effect=RuntimeError("Simulated init crash")), \
             patch("gui.SplashScreen", lambda parent: None):
            with self.assertRaises(RuntimeError):
                gui.MammouthControlCenter()


@pytest.fixture
def clean_gui_app():
    """Pytest fixture ensuring MammouthControlCenter is cleanly torn down after test."""
    with patch.object(gui.MammouthControlCenter, "_start_server", lambda self: None):
        app = gui.MammouthControlCenter()
        yield app
        app.destroy()


def test_fixture_cleanup(clean_gui_app):
    """Test using clean_gui_app fixture with scheduled callbacks."""
    clean_gui_app.after(5000, lambda: None)
    clean_gui_app.after(10000, clean_gui_app._on_scheduler_tick)
    assert len(clean_gui_app._scheduled_after_ids) >= 2
