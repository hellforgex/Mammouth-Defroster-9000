import unittest
import os
import sys
import tempfile
import sqlite3
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import modules.memory as mem


class TestMemoryModule(unittest.TestCase):
    def setUp(self):
        # Create a temporary database for isolation
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        mem.DB_PATH = self.db_path
        mem._schema_ready_paths.clear()
        # Initialize an empty schema directly so auto-migration does not trigger
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_and_recall_basic(self):
        msg = mem.memory_save(key="test_k1", content="Hello world memory", category="general")
        self.assertIn("Successfully saved", msg)

        results = mem.memory_recall(query="Hello")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "test_k1")
        self.assertEqual(results[0]["content"], "Hello world memory")
        self.assertEqual(results[0]["category"], "general")

    def test_save_with_aliases(self):
        # Test value alias
        msg1 = mem.memory_save(name="alias_key_1", value="Value content")
        self.assertIn("Successfully saved", msg1)
        rec1 = mem.memory_get(key="alias_key_1")
        self.assertEqual(rec1["content"], "Value content")

        # Test text alias
        msg2 = mem.memory_save(key="alias_key_2", text="Text content")
        self.assertIn("Successfully saved", msg2)
        rec2 = mem.memory_get(name="alias_key_2")
        self.assertEqual(rec2["content"], "Text content")

        # Test note alias
        msg3 = mem.memory_save(key="alias_key_3", note="Note content")
        self.assertIn("Successfully saved", msg3)
        rec3 = mem.memory_get(id="alias_key_3")
        self.assertEqual(rec3["content"], "Note content")

    def test_recall_with_aliases(self):
        mem.memory_save(key="search_target", content="Specific needle in haystack", category="search_test")

        r1 = mem.memory_recall(search_query="needle")
        self.assertEqual(len(r1), 1)

        r2 = mem.memory_recall(q="needle")
        self.assertEqual(len(r2), 1)

        r3 = mem.memory_recall(keyword="needle")
        self.assertEqual(len(r3), 1)

        r4 = mem.memory_recall(search="needle")
        self.assertEqual(len(r4), 1)

    def test_empty_key_or_content_handling(self):
        res1 = mem.memory_save(key="", content="data")
        self.assertTrue(res1.startswith("Error"))

        res2 = mem.memory_save(key="valid_key", content="")
        self.assertTrue(res2.startswith("Error"))

    def test_delete_and_not_found(self):
        mem.memory_save(key="to_delete", content="delete me")
        del_res = mem.memory_delete(key="to_delete")
        self.assertIn("Successfully deleted", del_res)

        # Deleting again should say not found
        del_res2 = mem.memory_delete(key="to_delete")
        self.assertIn("was not found", del_res2)

    def test_get_all_categories_and_stats(self):
        mem.memory_save(key="k1", content="content 1", category="alpha")
        mem.memory_save(key="k2", content="content 22", category="beta")
        mem.memory_save(key="k3", content="content 333", category="alpha")

        cats = mem.memory_get_categories()
        self.assertIn("alpha", cats)
        self.assertIn("beta", cats)

        stats = mem.memory_get_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["categories"], 2)
        self.assertGreater(stats["total_chars"], 0)

        all_entries = mem.memory_get_all()
        self.assertEqual(len(all_entries), 3)

        alpha_entries = mem.memory_get_all(category="alpha")
        self.assertEqual(len(alpha_entries), 2)

    def test_auto_migration_from_sibling(self):
        # Create an isolated fake legacy folder structure
        with tempfile.TemporaryDirectory() as fake_root:
            fake_root_path = Path(fake_root)
            old_version = fake_root_path / "MammouthDefroster9000-v0.4.0"
            old_version.mkdir()
            old_db = old_version / "memory.db"
            conn = sqlite3.connect(old_db)
            conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, key TEXT UNIQUE, content TEXT, category TEXT, created_at TEXT, updated_at TEXT)")
            conn.execute("INSERT INTO memories (key, content, category, created_at, updated_at) VALUES ('migrated_key', 'migrated_val', 'legacy', '2026-01-01', '2026-01-01')")
            conn.commit()
            conn.close()

            new_version = fake_root_path / "MammouthDefroster9000-v0.6.0"
            new_version.mkdir()
            target_db = new_version / "memory.db"

            orig_base = mem.BASE_DIR
            orig_db = mem.DB_PATH
            try:
                mem.BASE_DIR = new_version
                mem.DB_PATH = target_db
                mem._auto_migrate_legacy_db()
                self.assertTrue(target_db.exists())
                res = mem.memory_get(key="migrated_key")
                self.assertEqual(res["content"], "migrated_val")
            finally:
                mem.BASE_DIR = orig_base
                mem.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()

