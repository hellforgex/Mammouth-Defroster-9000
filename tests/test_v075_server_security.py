"""
Regression tests for Mammouth Defroster 9000 v0.7.5 Server Security Fixes:
1. Fix 2: defroster_execute_tool profile allowlist enforcement, require_module checks, and allow_admin_shell gates.
2. Fix 3: Query token (?token=...) disabled by default (401 unless server.allow_query_token=True opt-in).
3. Fix 4: OPTIONS CORS preflight reflects only allowed origins (allowed_origins or allow_origin_regex), omitting ACAO for arbitrary/untrusted origins.
"""

import unittest
from unittest.mock import patch
import os
import sys
import copy
import asyncio
from starlette.testclient import TestClient

# Ensure src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import server
from config import load_config


async def _dummy_app(scope, receive, send):
    """Minimal ASGI responder for middleware integration testing."""
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"OK"})


class TestV075ServerSecurity(unittest.TestCase):
    def setUp(self):
        self.base_cfg = load_config()

    # =========================================================================
    # Fix 2: defroster_execute_tool Profile & Permission Gates
    # =========================================================================

    def test_defroster_execute_tool_blocks_tool_outside_active_profile(self):
        """Tool not present in active profile must be rejected with 'tool not in active profile'."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        mock_cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"

        with patch("server.load_config", return_value=mock_cfg):
            # 'mouse_get_position' and 'task_create' are not in 'mammouth_safe' profile
            res = asyncio.run(server.defroster_execute_tool("mouse_get_position", {}))
            self.assertEqual(res.get("status"), "error")
            self.assertEqual(res.get("tool"), "mouse_get_position")
            self.assertEqual(res.get("error"), "tool not in active profile")

            res_task = asyncio.run(server.defroster_execute_tool("task_create", {"title": "Forbidden"}))
            self.assertEqual(res_task.get("status"), "error")
            self.assertEqual(res_task.get("tool"), "task_create")
            self.assertEqual(res_task.get("error"), "tool not in active profile")

    def test_defroster_execute_tool_allows_tool_in_active_profile(self):
        """Tool present in active profile must execute successfully."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        mock_cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"

        with patch("server.load_config", return_value=mock_cfg):
            # 'desktop_get_screen_info' is in 'mammouth_safe' profile
            res = asyncio.run(server.defroster_execute_tool("desktop_get_screen_info", {}))
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("tool"), "desktop_get_screen_info")
            self.assertIn("width", res.get("result", {}))

    def test_defroster_execute_tool_dynamic_profile_switching(self):
        """Switching profile enables execution of tools registered in the new profile."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        # file_replace_chunk is in 'developer' profile but NOT in 'mammouth_safe'
        mock_cfg.setdefault("server", {})["tool_profile"] = "mammouth_safe"
        with patch("server.load_config", return_value=mock_cfg):
            res_safe = asyncio.run(server.defroster_execute_tool("file_replace_chunk", {}))
            self.assertEqual(res_safe.get("status"), "error")
            self.assertEqual(res_safe.get("error"), "tool not in active profile")

        # Switch to developer profile
        mock_cfg["server"]["tool_profile"] = "developer"
        with patch("server.load_config", return_value=mock_cfg):
            res_dev = asyncio.run(server.defroster_execute_tool("file_replace_chunk", {}))
            # It passed the profile check (even if file arguments fail validation)
            self.assertNotEqual(res_dev.get("error"), "tool not in active profile")

    def test_defroster_execute_tool_blocks_disabled_module(self):
        """Tools belonging to a disabled module must be rejected even if profile is 'all'."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        mock_cfg.setdefault("server", {})["tool_profile"] = "all"
        mock_cfg.setdefault("modules", {}).setdefault("tasks_kanban", {})["enabled"] = False

        with patch("server.load_config", return_value=mock_cfg):
            res = asyncio.run(server.defroster_execute_tool("task_create", {"title": "Test"}))
            self.assertEqual(res.get("status"), "error")
            self.assertIn("disabled in Defroster settings", res.get("error", ""))

    def test_defroster_execute_tool_enforces_allow_admin_shell_gate(self):
        """Admin modifying actions must be blocked in Read-Only mode (allow_admin_shell=False)."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        mock_cfg.setdefault("server", {})["tool_profile"] = "developer"
        mock_cfg.setdefault("server", {})["allow_admin_shell"] = False
        # Enable the module so the admin-shell gate (not the module gate) is exercised
        mock_cfg.setdefault("modules", {}).setdefault("shell_processes", {})["enabled"] = True

        import modules.shell_processes as shell_mod
        # Shell tools are only registered at import when the module is enabled; register them for this test
        registered = []
        for fn in (server.desktop_open, server.powershell_exec):
            key = f"tool:{fn.__name__}@"
            if key not in server.mcp.local_provider._components:
                server.mcp.tool()(server.require_module("shell_processes")(fn))
                registered.append(key)
        extra = [patch.object(shell_mod, "load_config", return_value=mock_cfg)] if hasattr(shell_mod, "load_config") else []
        self.addCleanup(lambda: [server.mcp.local_provider._components.pop(k, None) for k in registered])
        for p_ in extra:
            p_.start()
            self.addCleanup(p_.stop)

        with patch("server.load_config", return_value=mock_cfg):
            # desktop_open with an executable target requires admin shell
            res_exec = asyncio.run(server.defroster_execute_tool("desktop_open", {"target": "calc.exe"}))
            self.assertEqual(res_exec.get("status"), "error")
            self.assertIn("Admin shell required", res_exec.get("error", ""))

            # powershell_exec with a disallowed modifying command requires admin shell
            res_ps = asyncio.run(server.defroster_execute_tool("powershell_exec", {"command": "New-Item test.txt"}))
            result_obj = res_ps.get("result", {})
            self.assertTrue(
                result_obj.get("status") == "permission_denied" or "Read-Only Shell" in str(res_ps),
                f"Expected permission denial for admin shell command, got {res_ps}"
            )

    def test_defroster_execute_tool_blocks_recursion(self):
        """Executing defroster_execute_tool through itself must fail immediately."""
        res = asyncio.run(server.defroster_execute_tool("defroster_execute_tool", {}))
        self.assertEqual(res.get("status"), "error")
        self.assertIn("recursively", res.get("error", ""))

    # =========================================================================
    # Fix 3: Query Parameter Token Authentication Default (Mammouth.ai compatibility)
    # =========================================================================

    def test_build_app_defaults_allow_query_token_to_false(self):
        """build_app must configure SecurityAndAuthMiddleware with allow_query_token=False unless explicitly enabled."""
        mock_cfg = copy.deepcopy(self.base_cfg)
        mock_cfg["server"].pop("allow_query_token", None)

        with patch("server.load_config", return_value=mock_cfg):
            app = server.build_app()
            mw_sec = next(mw for mw in app.user_middleware if mw.cls == server.SecurityAndAuthMiddleware)
            self.assertFalse(mw_sec.kwargs.get("allow_query_token"), "Default allow_query_token must be False (fail-closed)")

        mock_cfg["server"]["allow_query_token"] = True
        with patch("server.load_config", return_value=mock_cfg):
            app_enabled = server.build_app()
            mw_sec_enabled = next(mw for mw in app_enabled.user_middleware if mw.cls == server.SecurityAndAuthMiddleware)
            self.assertTrue(mw_sec_enabled.kwargs.get("allow_query_token"), "Explicit allow_query_token=True must enable query tokens (opt-in)")

    def test_query_token_blocked_when_explicitly_disabled(self):
        """When allow_query_token=False is configured, passing ?token=<valid> returns 401."""
        test_token = "mc_test_secret_token_1234567890123456789012"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True, allow_query_token=False)
        client = TestClient(app)

        # POST /mcp with query token when disabled -> 401
        resp_post = client.post(f"/mcp?token={test_token}")
        self.assertEqual(resp_post.status_code, 401)

        # GET /mcp with query token when disabled -> 401
        resp_get = client.get(f"/mcp?token={test_token}")
        self.assertEqual(resp_get.status_code, 401)

        # Bearer authorization header works as expected -> 200
        resp_bearer = client.get("/mcp", headers={"Authorization": f"Bearer {test_token}"})
        self.assertEqual(resp_bearer.status_code, 200)

    def test_query_token_allowed_when_opted_in(self):
        """When allow_query_token=True is explicitly configured, the URL token is accepted."""
        test_token = "mc_test_secret_token_optin_1234567890123"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True, allow_query_token=True)
        client = TestClient(app)

        resp = client.post(f"/mcp?token={test_token}")
        self.assertEqual(resp.status_code, 200)

    # =========================================================================
    # Fix 4: OPTIONS Handler CORS Origin Reflection Guard
    # =========================================================================

    def test_is_allowed_origin_helper(self):
        """Verify is_allowed_origin helper strictly validates origins."""
        self.assertTrue(server.is_allowed_origin("https://mammouth.ai"))
        self.assertTrue(server.is_allowed_origin("https://app.mammouth.ai"))
        self.assertTrue(server.is_allowed_origin("https://claude.ai"))
        self.assertTrue(server.is_allowed_origin("http://localhost"))
        self.assertTrue(server.is_allowed_origin("http://127.0.0.1"))
        self.assertTrue(server.is_allowed_origin("http://localhost:3000"))
        self.assertTrue(server.is_allowed_origin("http://127.0.0.1:8000"))

        # Untrusted / attacker origins must return False
        self.assertFalse(server.is_allowed_origin("https://evil.example"))
        self.assertFalse(server.is_allowed_origin("https://attacker.com"))
        self.assertFalse(server.is_allowed_origin("https://mammouth.ai.evil.com"))
        self.assertFalse(server.is_allowed_origin("*"))
        self.assertFalse(server.is_allowed_origin(""))
        self.assertFalse(server.is_allowed_origin(None))

    def test_options_untrusted_origin_omits_acao_header(self):
        """OPTIONS /mcp with untrusted Origin must NOT emit Access-Control-Allow-Origin."""
        test_token = "mc_test_token_options_guard_1234567890"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True)
        client = TestClient(app)

        resp = client.options("/mcp", headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("access-control-allow-origin", resp.headers)

    def test_options_trusted_origin_reflects_acao_header(self):
        """OPTIONS /mcp with trusted Origin reflects the origin and allows credentials."""
        test_token = "mc_test_token_options_guard_1234567890"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True)
        client = TestClient(app)

        resp = client.options("/mcp", headers={"Origin": "https://mammouth.ai"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "https://mammouth.ai")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_options_allowed_regex_origin_reflects_acao_header(self):
        """OPTIONS /mcp with origin matching regex reflects the origin."""
        test_token = "mc_test_token_options_guard_1234567890"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True)
        client = TestClient(app)

        resp = client.options("/mcp", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")

    def test_options_missing_origin_header(self):
        """OPTIONS /mcp without Origin header succeeds without emitting ACAO."""
        test_token = "mc_test_token_options_guard_1234567890"
        app = server.SecurityAndAuthMiddleware(_dummy_app, token=test_token, enforce_auth=True)
        client = TestClient(app)

        resp = client.options("/mcp")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("access-control-allow-origin", resp.headers)


if __name__ == "__main__":
    unittest.main()
