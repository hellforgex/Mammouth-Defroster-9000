"""Regression tests for in-process restarts and registry-aware catalog status."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import server


def test_newly_enabled_shell_is_registered_once(monkeypatch):
    registered = []
    class FakeMCP:
        def tool(self, name=None):
            def decorate(fn):
                registered.append(name or fn.__name__)
                return fn
            return decorate

    cfg = {
        "server": {"tool_profile": "developer"},
        "modules": {"shell_processes": {"enabled": False}},
    }
    monkeypatch.setattr(server, "mcp", FakeMCP())
    monkeypatch.setattr(server, "load_config", lambda: cfg)
    monkeypatch.setattr(server, "_registered_tool_names", set())
    server.register_active_tools()
    assert "powershell_exec" not in registered
    cfg["modules"]["shell_processes"]["enabled"] = True
    server.register_active_tools()
    server.register_active_tools()
    assert registered.count("powershell_exec") == 1
    assert registered.count("defroster_catalog") == 1


def test_catalog_does_not_claim_missing_shell_is_loaded(monkeypatch):
    cfg = {
        "server": {"tool_profile": "developer"},
        "modules": {"shell_processes": {"enabled": True}},
    }
    monkeypatch.setattr(server, "load_config", lambda: cfg)
    monkeypatch.setattr(server, "_extract_tool_schema_def", lambda name: None)
    result = server.defroster_catalog(tool_schema="powershell_exec")
    assert result["status_in_active_profile"] == "not_registered"


def test_disabled_module_is_never_reported_loaded(monkeypatch):
    cfg = {
        "server": {"tool_profile": "developer"},
        "modules": {"shell_processes": {"enabled": False}},
    }
    monkeypatch.setattr(server, "load_config", lambda: cfg)
    monkeypatch.setattr(server, "_extract_tool_schema_def", lambda name: {"name": name})
    result = server.defroster_catalog(tool_schema="powershell_exec")
    assert result["status_in_active_profile"] == "disabled"
