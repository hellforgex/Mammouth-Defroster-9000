import unittest
import os
import sys
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from server import require_module
from modules.file_ops import directory_list, directory_tree, file_read, file_write, file_search_text
from modules.tasks_kanban import task_update, task_delete, task_list
from modules.memory import memory_recall, memory_list
from mcp.types import TextContent

class TestMcpToolSchemas(unittest.TestCase):
    def test_require_module_empty_list_returns_text_content(self):
        """Test that require_module wraps empty list return into TextContent('[]') to prevent IndexError in MCP clients."""
        @require_module('memory')
        def empty_fn():
            return []

        with patch('server.load_config', return_value={'modules': {'memory': {'enabled': True}}}):
            res = empty_fn()
            self.assertIsInstance(res, list)
            self.assertEqual(len(res), 1)
            self.assertIsInstance(res[0], TextContent)
            self.assertEqual(res[0].text, '[]')

    def test_require_module_nonempty_list_preserved(self):
        """Test that non-empty lists are returned intact."""
        @require_module('memory')
        def items_fn():
            return [{'id': 1}]

        with patch('server.load_config', return_value={'modules': {'memory': {'enabled': True}}}):
            res = items_fn()
            self.assertEqual(res, [{'id': 1}])

    def test_directory_list_path_alias(self):
        """Test directory_list accepts path parameter alias."""
        res = directory_list(path='.')
        self.assertIsInstance(res, list)

    def test_directory_tree_path_alias(self):
        """Test directory_tree accepts path parameter alias."""
        res = directory_tree(path='.')
        self.assertIsInstance(res, dict)
        self.assertIn('name', res)

    def test_file_search_text_aliases(self):
        """Test file_search_text accepts path and query parameter aliases."""
        res = file_search_text(path='.', query='def test')
        self.assertIsInstance(res, list)

    def test_memory_recall_query_alias(self):
        """Test memory_recall accepts search_query alias."""
        res = memory_recall(search_query='test_query_key')
        self.assertIsInstance(res, list)

    def test_task_id_alias(self):
        """Test task_update and task_delete accept id alias."""
        del_res = task_delete(id=999999)
        self.assertIn('not found', del_res.lower())

if __name__ == '__main__':
    unittest.main()
