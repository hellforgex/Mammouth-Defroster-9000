import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from config import TOOL_PROFILES, get_tool_profile
from server import defroster_catalog, mcp
from modules.file_ops import file_read, file_write, _validate_path


def test_mammouth_safe_has_directory_list():
    """Verify that directory_list is in the base mammouth_safe profile."""
    safe_profile = TOOL_PROFILES["mammouth_safe"]
    assert "directory_list" in safe_profile["tools"]
    assert "file_read" in safe_profile["tools"]
    assert safe_profile["token_estimate"] <= 3000


def test_workspace_alias_resolution_in_file_ops(tmp_path, monkeypatch):
    """Verify that workspace:/ and @workspace/ path aliases resolve inside the workspace root."""
    test_ws = tmp_path / "test_workspace"
    test_ws.mkdir()
    sample_file = test_ws / "sample.txt"
    sample_file.write_text("Hello from workspace alias!", encoding="utf-8")

    # Mock _get_sandbox_config to return our test workspace
    import modules.file_ops as fops
    monkeypatch.setattr(fops, "_get_sandbox_config", lambda: (True, test_ws))

    # Test reading with workspace:/ alias
    p1 = _validate_path("workspace:/sample.txt")
    assert p1 == sample_file.resolve()

    # Test reading with @workspace/ alias
    p2 = _validate_path("@workspace/sample.txt")
    assert p2 == sample_file.resolve()

    # Test with backslash
    p3 = _validate_path(r"workspace:\sample.txt")
    assert p3 == sample_file.resolve()

    # Test reading file content via file_read using alias
    res = file_read("workspace:/sample.txt")
    assert "Hello from workspace alias!" in res


def test_helpful_sandbox_violation_error(tmp_path, monkeypatch):
    """Verify that sandbox violation error provides helpful guidance."""
    test_ws = tmp_path / "test_workspace"
    test_ws.mkdir()

    import modules.file_ops as fops
    monkeypatch.setattr(fops, "_get_sandbox_config", lambda: (True, test_ws))

    with pytest.raises(PermissionError) as excinfo:
        _validate_path("C:/Windows/System32/drivers/etc/hosts")

    err_msg = str(excinfo.value)
    assert "Sandbox Violation" in err_msg
    assert "directory_list" in err_msg
    assert "workspace:/" in err_msg


def test_schema_budget_status_non_contradictory():
    """Verify that defroster_catalog returns a non-contradictory schema budget message."""
    # Test mammouth_safe
    res_safe = defroster_catalog(switch_profile="mammouth_safe")
    safe_info = res_safe["active_tool_profile"]
    assert "Safe" in safe_info["schema_budget_status"]
    assert "7,719" in safe_info["schema_budget_status"]
    assert "< 3,000" not in safe_info["schema_budget_status"]

    # Test developer (3,800 tokens)
    res_dev = defroster_catalog(switch_profile="developer")
    dev_info = res_dev["active_tool_profile"]
    assert "Safe" in dev_info["schema_budget_status"]
    assert "3,800" in dev_info["schema_budget_status"]
    assert "7,719" in dev_info["schema_budget_status"]
    assert "< 3,000" not in dev_info["schema_budget_status"]
