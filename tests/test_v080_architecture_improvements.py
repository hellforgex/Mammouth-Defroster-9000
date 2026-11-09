"""
Unit and integration tests for Mammouth Defroster 9000 Architecture & Robustness Overhaul:
1. Unified Tool Catalog & On-Demand Machine-Readable Schemas
2. Standardized Execution Contract & Runtime Telemetry (duration_ms, error codes)
3. Robust Browser Automation (Selector Priority, State Verification)
4. Hardened Task Automation & Scheduling (dry_run preview, test_run, execution history)
5. Read-Only System Health Probe (defroster_health_check)
"""

import os
import sys
import json
import pytest
from pathlib import Path

# Add src root to sys.path
SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import server
from modules.shell_processes import powershell_exec, cmd_exec
from modules.task_scheduler import scheduler_create_task, scheduler_delete_task, scheduler_test_run, scheduler_get_history


def test_defroster_catalog_three_tier_metrics():
    """Verify defroster_catalog outputs distinct 3-tier inventory metrics."""
    res = server.defroster_catalog()
    assert res["status"] == "success"
    assert "tool_inventory_metrics" in res
    metrics = res["tool_inventory_metrics"]
    assert "loaded_in_profile" in metrics
    assert "activated_in_config" in metrics
    assert "total_catalog_suite" in metrics
    assert metrics["loaded_in_profile"] <= metrics["activated_in_config"]
    assert metrics["activated_in_config"] <= metrics["total_catalog_suite"]


def test_defroster_catalog_on_demand_tool_schema():
    """Verify on-demand machine-readable tool schema retrieval."""
    res = server.defroster_catalog(tool_schema="powershell_exec")
    assert res["status"] == "success"
    assert res["tool_name"] == "powershell_exec"
    assert res["status_in_active_profile"] in ("loaded", "available", "disabled")
    assert "schema" in res
    assert res["schema"]["name"] == "powershell_exec"
    params = res["schema"]["parameters"]
    assert params["type"] == "object"
    assert "command" in params["properties"]
    assert "command" in params["required"]


def test_defroster_health_check_read_only_probe():
    """Verify defroster_health_check executes without side-effects and returns valid system health."""
    h = server.defroster_health_check()
    assert h["status"] in ("healthy", "degraded")
    assert "duration_ms" in h
    assert h["duration_ms"] >= 0
    assert "runtime" in h
    assert "security" in h
    assert "storage" in h
    assert "dependencies" in h
    assert h["security"]["workspace_exists"] is True
    assert h["security"]["dpapi_available"] is True


def test_powershell_exec_standardized_contract():
    """Verify powershell_exec returns status, duration_ms, and structured error codes."""
    # 1. Success case
    ok_res = powershell_exec("Write-Output 'Defroster Test'")
    assert ok_res["status"] == "success"
    assert ok_res["error_code"] is None
    assert ok_res["exit_code"] == 0
    assert "Defroster Test" in ok_res["stdout"]
    assert "duration_ms" in ok_res
    assert ok_res["duration_ms"] >= 0

    # 2. Permission denied case (Read-Only shell security)
    blocked_res = powershell_exec("Remove-Item C:\\test -Recurse")
    assert blocked_res["status"] == "permission_denied"
    assert blocked_res["error_code"] == "ERR_SECURITY_SHIELD"
    assert blocked_res["exit_code"] == -1
    assert "Security Error" in blocked_res["stderr"]


def test_task_scheduler_dry_run_and_history():
    """Verify task automation preview, test_run, and execution run history tracking."""
    task = scheduler_create_task(
        name="Auto Test Health Probe",
        prompt="system_get_specs",
        interval_seconds=600,
        repeat_count=3,
        target="powershell"
    )
    tid = task["id"]
    try:
        # 1. Preview / Dry Run
        preview = scheduler_test_run(tid, dry_run=True)
        assert preview["status"] == "preview"
        assert preview["dry_run"] is True
        assert preview["task_id"] == tid
        assert "Would dispatch prompt" in preview["simulated_action"]

        # 2. Single Test Run
        test_exec = scheduler_test_run(tid, dry_run=False)
        assert test_exec["status"] == "success"
        assert test_exec["dry_run"] is False
        assert test_exec["duration_ms"] >= 0

        # 3. Execution History Log
        history = scheduler_get_history(tid, limit=10)
        assert len(history) >= 1
        run_record = history[0]
        assert run_record["task_id"] == tid
        assert run_record["status"] == "test_success"
        assert "started_at" in run_record
        assert "finished_at" in run_record
        assert "duration_ms" in run_record
    finally:
        scheduler_delete_task(tid)


def test_task_schedule_control_actions():
    """Verify task_schedule_control accepts new actions."""
    task = server.task_schedule_create(name="Control Action Test", prompt="Echo 1", interval_minutes=5)
    tid = task["id"]
    try:
        p_res = server.task_schedule_control(tid, "preview")
        assert p_res["status"] == "preview"

        h_res = server.task_schedule_control(tid, "history")
        assert h_res["status"] == "success"
        assert "history" in h_res

        t_res = server.task_schedule_control(tid, "test_run")
        assert t_res["status"] == "success"
    finally:
        server.task_schedule_delete(tid)
