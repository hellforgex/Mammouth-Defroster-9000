import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from modules.unreal_engine import _validate_unreal_python_code, _validate_console_command, ALLOWED_MODULES


class TestUnrealEngineSecurityAllowlist(unittest.TestCase):
    def test_ue_allowlist_blocks_unauthorized_imports(self):
        """Test import allowlist blocks all unauthorized modules."""
        blocked_imports = [
            "import os",
            "import sys",
            "import subprocess",
            "import runpy\nrunpy.run_path('C:/evil.py')",
            "from runpy import run_path",
            "import code",
            "import codeop",
            "import zipimport",
            "import sqlite3",
            "import xmlrpc",
            "import threading",
            "import setuptools",
            "import venv",
            "import socketserver",
            "import timeit",
            "import compileall",
            "import urllib.request",
            "import socket",
            "import requests",
            "import http.client",
            "import pathlib",
            "from pathlib import Path",
            "import codecs",
            "import tempfile",
            "import io",
            "import inspect",
            "import dis",
            "import gc",
            "import traceback",
            "import fileinput",
            "import linecache",
            "import zipfile",
            "import tarfile",
            "import asyncio",
            "import multiprocessing",
            "from sys import modules",
            "from os import system",
            "from . import local_mod",
            "from .. import parent_mod"
        ]
        for code in blocked_imports:
            with self.assertRaises(PermissionError, msg=f"Expected '{code}' to be blocked by allowlist"):
                _validate_unreal_python_code(code)

    def test_ue_allowlist_allows_authorized_modules(self):
        """Test that allowed modules pass AST validation."""
        valid_codes = [
            "import unreal\nunreal.log('Testing UE')",
            "import math\nx = math.sqrt(16.0)",
            "import string\ns = string.ascii_letters",
            "import enum\nclass Status(enum.Enum): OK = 1",
            "import dataclasses\n@dataclasses.dataclass\nclass Item: name: str",
            "import typing\nx: typing.List[int] = [1, 2, 3]",
            "import collections\nd = collections.deque()",
            "import functools\nimport itertools",
            "import json\nd = json.dumps({'success': True})",
            "import re\nm = re.match(r'\\d+', '123')",
            "import datetime\nnow = datetime.datetime.now()",
            "import hashlib\nh = hashlib.sha256(b'test').hexdigest()",
            "import random\nr = random.randint(1, 10)",
            "import uuid\nu = str(uuid.uuid4())",
            "import decimal\nd = decimal.Decimal('10.5')",
            "import copy\nc = copy.deepcopy([1, 2])",
            "import statistics\nm = statistics.mean([1, 2, 3])",
            "import time\nt = time.time()",
            "from math import sqrt, sin, cos",
            "from enum import Enum, auto",
            "from dataclasses import dataclass",
            "from typing import Optional, List, Dict",
            "from json import dumps, loads",
            "from datetime import datetime, timezone"
        ]
        for code in valid_codes:
            _validate_unreal_python_code(code)

    def test_ue_filter_blocks_forbidden_calls_and_dunders(self):
        """Test forbidden builtins (open, exec, eval) and dunders are blocked."""
        bad_codes = [
            "open('C:/secret.txt')",
            "exec('x = 1')",
            "eval('1 + 1')",
            "compile('pass', '', 'exec')",
            "getattr(__builtins__, 'open')",
            "[].__class__.__base__.__subclasses__()",
            "x = ().__class__.__bases__[0].__subclasses__()",
            "print(__globals__)",
            "print(__dict__)",
            "print(__code__)",
            "print(int.__mro__)",
            "print(Status.__members__)"
        ]
        for code in bad_codes:
            with self.assertRaises(PermissionError, msg=f"Expected '{code}' to be blocked"):
                _validate_unreal_python_code(code)

    def test_ue_syntax_error_fails_closed(self):
        """Test invalid Python syntax fails-closed."""
        bad_syntax = "def foo(: broken"
        with self.assertRaises(PermissionError):
            _validate_unreal_python_code(bad_syntax)

    def test_console_commands_validation(self):
        """Test console command allow/blocklist and semicolon splitting."""
        blocked_console = [
            "quit",
            "exit",
            "crash",
            "exec test.cfg",
            "open Level_01",
            "travel Map_02",
            "restart",
            "debug crash",
            "obj dump",
            "python script.py",
            "py evil.py",
            "stat fps; quit",
            "r.SetRes 1920x1080; py 'evil.py'"
        ]
        for cmd in blocked_console:
            with self.assertRaises(PermissionError, msg=f"Expected console '{cmd}' to be blocked"):
                _validate_console_command(cmd)

        valid_console = [
            "stat fps",
            "stat unit",
            "r.SetRes 1920x1080",
            "HighResShot 2",
            "ShowFlag.Lighting 1",
            "CAMERA ALIGN"
        ]
        for cmd in valid_console:
            _validate_console_command(cmd)


if __name__ == "__main__":
    unittest.main()
