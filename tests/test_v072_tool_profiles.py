import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import json
import mcp.types as mcp_types
from config import DEFAULT_CONFIG, TOOL_PROFILES, get_tool_profile, load_config, save_config
from server import (
    mcp,
    defroster_catalog,
    _sanitize_mcp_tool_schema,
    _DEFROSTER_TOOL_TO_MODULE
)


def _run(coro):
    return asyncio.run(coro)


async def _get_tools_list():
    if hasattr(mcp, "_list_tools_mcp"):
        req = mcp_types.ListToolsRequest(method="tools/list")
        res = await mcp._list_tools_mcp(req)
        return res.tools
    elif hasattr(mcp, "list_tools"):
        tools = await mcp.list_tools()
        return tools
    elif hasattr(mcp, "_list_tools"):
        return await mcp._list_tools()
    return []


def test_default_config_tool_profile():
    """Verify that default configuration specifies 'mammouth_safe' profile."""
    assert DEFAULT_CONFIG["server"]["tool_profile"] == "mammouth_safe"
    prof = get_tool_profile("mammouth_safe")
    assert prof["id"] == "mammouth_safe"
    assert "defroster_catalog" in prof["tools"]
    assert "file_read" in prof["tools"]
    assert "file_write" in prof["tools"]


def test_tool_profiles_coverage():
    """Verify all 6 tool profiles are registered with valid metadata."""
    expected_profiles = ["mammouth_safe", "developer", "web_vision", "automation", "all", "custom"]
    for pid in expected_profiles:
        assert pid in TOOL_PROFILES
        p = TOOL_PROFILES[pid]
        assert "name" in p
        assert "label" in p
        assert "description" in p
        assert "icon" in p


def test_mammouth_safe_promoted_tools_count():
    """Verify that mammouth_safe advertises <= 11 tools within platform schema budget."""
    async def _test():
        cfg = load_config()
        cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"
        save_config(cfg)

        tools = await _get_tools_list()
        tool_names = [t.name for t in tools]

        assert "defroster_catalog" in tool_names
        assert "file_read" in tool_names
        assert "file_write" in tool_names
        assert "screen_capture" in tool_names
        assert "browser_navigate" in tool_names
        assert "browser_snapshot" in tool_names
        assert "memory_save" in tool_names
        assert "memory_recall" in tool_names
        assert "system_get_specs" in tool_names
        assert "clipboard_get_text" in tool_names

        # Count must be exactly 10 or 11 (if command_run enabled)
        assert len(tool_names) in (10, 11)

    _run(_test())


def test_mammouth_safe_schema_token_budget():
    """Verify that the total schema size for mammouth_safe is safely under 3,500 tokens."""
    async def _test():
        cfg = load_config()
        cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"
        save_config(cfg)

        tools = await _get_tools_list()

        schemas = [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]
        json_bytes = json.dumps(schemas, default=str).encode("utf-8")
        approx_tokens = len(json_bytes) // 4

        # Must be well below the ~7,719 limit
        assert approx_tokens < 3500, f"Mammouth Safe schema size ({approx_tokens} tokens) exceeds 3,500 token budget!"

    _run(_test())


def test_all_tool_schemas_strictly_valid():
    """Verify that no tool schema contains empty dicts {} or untyped properties."""
    async def _test():
        tools = await _get_tools_list()

        for tool in tools:
            schema = tool.inputSchema if hasattr(tool, "inputSchema") else getattr(tool, "parameters", {})
            props = schema.get("properties", {})
            for p_name, p_val in props.items():
                assert p_val != {}, f"Empty property dict in tool {tool.name}, param {p_name}"
                assert ("type" in p_val or "anyOf" in p_val or "oneOf" in p_val or "$ref" in p_val), \
                    f"Missing type/anyOf in tool {tool.name}, param {p_name}"
                if "anyOf" in p_val:
                    for idx, sub in enumerate(p_val["anyOf"]):
                        assert sub != {}, f"Empty anyOf[{idx}] dict in tool {tool.name}, param {p_name}"
                        assert ("type" in sub or "$ref" in sub), f"Missing type in anyOf[{idx}] for tool {tool.name}, param {p_name}"

    _run(_test())


def test_dynamic_profile_switching():
    """Verify that defroster_catalog can switch profiles dynamically and updates tools/list."""
    async def _test():
        # 1. Switch to developer
        cat_res = defroster_catalog(switch_profile="developer")
        assert cat_res["active_tool_profile"]["id"] == "developer"

        tools_dev = await _get_tools_list()
        dev_names = [t.name for t in tools_dev]
        assert "file_replace_chunk" in dev_names
        assert "file_search_text" in dev_names

        # 2. Switch back to mammouth_safe
        cat_safe = defroster_catalog(switch_profile="mammouth_safe")
        assert cat_safe["active_tool_profile"]["id"] == "mammouth_safe"

        tools_safe = await _get_tools_list()
        safe_names = [t.name for t in tools_safe]
        assert "file_replace_chunk" not in safe_names
        assert "defroster_catalog" in safe_names

    _run(_test())


def test_unadvertised_tool_execution():
    """Verify that unadvertised tools (e.g. gdrive_status in mammouth_safe) can still be invoked."""
    async def _test():
        cfg = load_config()
        cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"
        save_config(cfg)

        # Calling gdrive_status directly via FastMCP call_tool
        res = await mcp.call_tool("gdrive_status", {})
        assert res is not None
        assert isinstance(res.structured_content, dict)

    _run(_test())


def test_schema_sanitizer_repairs_untyped():
    """Verify that _sanitize_mcp_tool_schema repairs empty or untyped schema constructs."""
    class DummyTool:
        def __init__(self):
            self.inputSchema = {
                "properties": {
                    "empty_prop": {},
                    "untyped_prop": {"description": "some note"},
                    "empty_anyof": {"anyOf": [{}, {"type": "null"}]}
                }
            }

    dummy = DummyTool()
    _sanitize_mcp_tool_schema(dummy)
    props = dummy.inputSchema["properties"]

    assert props["empty_prop"]["type"] == "string"
    assert props["untyped_prop"]["type"] == "string"
    assert props["empty_anyof"]["anyOf"][0]["type"] == "string"


def test_mcp_standard_schema_cleanliness():
    """Verify that tools/list output conforms strictly to standard MCP 2024-11-05 (no outputSchema or _meta)."""
    async def _test():
        tools = await _get_tools_list()
        for t in tools:
            if hasattr(t, 'to_mcp_tool'):
                m = t.to_mcp_tool()
                _sanitize_mcp_tool_schema(m)
                d = m.model_dump(by_alias=True, exclude_none=True)
                assert 'outputSchema' not in d, f"outputSchema found in {t.name}"
                assert '_meta' not in d, f"_meta found in {t.name}"
                assert 'name' in d
                assert 'inputSchema' in d

    _run(_test())
