import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Ensure src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.task_scheduler import (
    scheduler_create_task,
    scheduler_list_tasks,
    scheduler_get_task,
    scheduler_update_task,
    scheduler_delete_task,
    scheduler_pause_task,
    scheduler_resume_task,
    scheduler_trigger_task_now,
    scheduler_get_presets,
    TaskSchedulerEngine,
    _get_db
)
from server import (
    task_schedule_create,
    task_schedule_list,
    task_schedule_control,
    task_schedule_delete,
    task_schedule_get_presets
)


class TestTaskScheduler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_tasks.db"
        self.db_patch = patch("modules.task_scheduler.DB_PATH", self.test_db)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_create_task_and_defaults(self):
        """Test task creation with default and customized values."""
        task = scheduler_create_task(
            name="⚽ Livebericht: FC Bayern vs. Dortmund",
            prompt="Suche nach Spielstand, Toren und erstelle Livebericht alle 5 Minuten.",
            interval_seconds=300,
            repeat_count=18,
            target="mammouth_web",
            start_immediately=False
        )
        self.assertIn("id", task)
        self.assertEqual(task["name"], "⚽ Livebericht: FC Bayern vs. Dortmund")
        self.assertEqual(task["interval_seconds"], 300)
        self.assertEqual(task["repeat_count"], 18)
        self.assertEqual(task["runs_done"], 0)
        self.assertEqual(task["status"], "active")
        self.assertEqual(task["target"], "mammouth_web")
        self.assertTrue(task["next_run"] != "")

    def test_create_task_validation(self):
        """Test validation for empty names or prompts."""
        res1 = scheduler_create_task(name="", prompt="Test prompt")
        self.assertIn("error", res1)

        res2 = scheduler_create_task(name="Test", prompt="")
        self.assertIn("error", res2)

    def test_get_and_list_tasks(self):
        """Test listing and retrieving scheduled tasks."""
        t1 = scheduler_create_task(name="Task 1", prompt="Prompt 1", interval_seconds=60)
        t2 = scheduler_create_task(name="Task 2", prompt="Prompt 2", interval_seconds=120)

        all_tasks = scheduler_list_tasks()
        self.assertGreaterEqual(len(all_tasks), 2)
        task_ids = [t["id"] for t in all_tasks]
        self.assertIn(t1["id"], task_ids)
        self.assertIn(t2["id"], task_ids)

        single = scheduler_get_task(t1["id"])
        self.assertEqual(single["name"], "Task 1")

        missing = scheduler_get_task(999999)
        self.assertIn("error", missing)

    def test_update_task(self):
        """Test updating properties of an existing task."""
        t = scheduler_create_task(name="Original Name", prompt="Original Prompt", interval_seconds=300)
        updated = scheduler_update_task(
            task_id=t["id"],
            name="Updated Name",
            interval_seconds=600,
            status="paused"
        )
        self.assertEqual(updated["name"], "Updated Name")
        self.assertEqual(updated["interval_seconds"], 600)
        self.assertEqual(updated["status"], "paused")

    def test_pause_and_resume_task(self):
        """Test pausing and resuming task execution."""
        t = scheduler_create_task(name="Pausable Task", prompt="Test", interval_seconds=180)
        paused = scheduler_pause_task(t["id"])
        self.assertEqual(paused["status"], "paused")

        resumed = scheduler_resume_task(t["id"])
        self.assertEqual(resumed["status"], "active")
        self.assertTrue(resumed["next_run"] != "")

    def test_delete_task(self):
        """Test task deletion."""
        t = scheduler_create_task(name="Task to Delete", prompt="Delete me", interval_seconds=60)
        res = scheduler_delete_task(t["id"])
        self.assertIn("Successfully deleted", res)

        check = scheduler_get_task(t["id"])
        self.assertIn("error", check)

    def test_presets(self):
        """Test preset templates retrieval and contents."""
        presets = scheduler_get_presets()
        self.assertGreaterEqual(len(presets), 3)

        preset_ids = [p["id"] for p in presets]
        self.assertIn("football_live", preset_ids)
        self.assertIn("crypto_ticker", preset_ids)

        football = next(p for p in presets if p["id"] == "football_live")
        self.assertEqual(football["interval_seconds"], 300)
        self.assertEqual(football["target"], "mammouth_web")
        self.assertIn("Fußball", football["name"])

    def test_engine_execution_and_repeat_limit(self):
        """Test TaskSchedulerEngine execution, repeat limits, and handler invocation."""
        engine = TaskSchedulerEngine.get_instance()
        mock_handler = MagicMock(return_value="Dispatched OK")
        engine.register_handler("mammouth_web", mock_handler)

        # Create task with repeat_count=2, starting immediately
        task = scheduler_create_task(
            name="Test Repeat Task",
            prompt="Test prompt",
            interval_seconds=30,
            repeat_count=2,
            target="mammouth_web",
            start_immediately=True
        )

        # Simulate first execution
        reports1 = engine.check_and_run_due_tasks()
        self.assertEqual(len(reports1), 1)
        self.assertEqual(reports1[0]["runs_done"], 1)
        self.assertEqual(reports1[0]["status"], "active")
        mock_handler.assert_called_once()

        # Manually force next_run to past to simulate interval elapsed
        scheduler_update_task(
            task_id=task["id"],
            status="active"
        )
        conn = _get_db()
        with conn:
            conn.execute("UPDATE scheduled_tasks SET next_run = ? WHERE id = ?", (
                (datetime.now() - timedelta(seconds=5)).isoformat(),
                task["id"]
            ))
        conn.close()

        # Simulate second execution
        reports2 = engine.check_and_run_due_tasks()
        self.assertEqual(len(reports2), 1)
        self.assertEqual(reports2[0]["runs_done"], 2)
        # Should now be completed because repeat_count was 2!
        self.assertEqual(reports2[0]["status"], "completed")

        # Verify in DB
        finished_task = scheduler_get_task(task["id"])
        self.assertEqual(finished_task["status"], "completed")
        self.assertEqual(finished_task["runs_done"], 2)

    def test_mcp_server_tools(self):
        """Test the MCP tool wrapper functions registered in server.py."""
        created = task_schedule_create(
            name="MCP Football Task",
            prompt="Liveticker Bayern Dortmund",
            interval_minutes=5.0,
            repeat_count=18,
            target="mammouth_web"
        )
        self.assertIn("id", created)
        self.assertEqual(created["interval_seconds"], 300)

        tasks = task_schedule_list()
        self.assertTrue(any(t["id"] == created["id"] for t in tasks))

        # Control: pause
        ctrl_res = task_schedule_control(created["id"], "pause")
        self.assertEqual(ctrl_res["status"], "paused")

        # Control: resume
        ctrl_res2 = task_schedule_control(created["id"], "resume")
        self.assertEqual(ctrl_res2["status"], "active")

        # Delete
        del_res = task_schedule_delete(created["id"])
        self.assertIn("Successfully deleted", del_res)

        # Presets
        presets = task_schedule_get_presets()
        self.assertIsInstance(presets, list)
        self.assertGreater(len(presets), 0)


if __name__ == "__main__":
    unittest.main()
