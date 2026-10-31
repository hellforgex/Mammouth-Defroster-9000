"""Unit tests for Claude OAuth integration (RFC 9728, RFC 8414, RFC 7591, PKCE S256, and Claude.ai / Claude Code compatibility).
"""

import os
import sys
import json
import time
import base64
import hashlib
import secrets
import urllib.parse
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SRC_DIR = Path(__file__).parent.parent.resolve()
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from server import (
    _is_trusted_oauth_redirect_uri,
    _resolve_base_url,
    oauth_protected_resource,
    oauth_authorization_server,
    openid_configuration,
    oauth_register,
    oauth_authorize,
    oauth_token,
    _save_oauth_client,
    _get_oauth_client,
    _is_valid_oauth_token,
    _token_hash,
    SecurityAndAuthMiddleware,
)
from modules.claude_code import (
    sync_claude_code_mcp,
    get_claude_code_status,
)
from config import load_config


class TestClaudeOAuthIntegration(unittest.TestCase):
    """Test suite verifying Claude OAuth 2.1 compliance and seamless integration."""

    def test_trusted_oauth_redirect_uris(self):
        """Verify redirect URI allowlist trusts Claude.ai, Anthropic, Mammouth AI, and loopback."""
        # Claude.ai & Anthropic domains (must be HTTPS)
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://claude.ai/api/mcp/auth_callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://app.claude.ai/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://code.claude.ai/oauth/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://console.anthropic.com/mcp/callback"))

        # Mammouth AI domains (must be HTTPS)
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://mammouth.ai/api/mcp/oauth/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://app.mammouth.ai/callback"))

        # Loopback / Localhost (HTTP and HTTPS allowed)
        self.assertTrue(_is_trusted_oauth_redirect_uri("http://localhost:8787/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("http://127.0.0.1:54321/oauth/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("http://localhost/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("https://localhost:8443/callback"))
        self.assertTrue(_is_trusted_oauth_redirect_uri("http://[::1]:8000/callback"))

        # Insecure or untrusted domains rejected
        self.assertFalse(_is_trusted_oauth_redirect_uri("http://claude.ai/insecure"))
        self.assertFalse(_is_trusted_oauth_redirect_uri("http://mammouth.ai/insecure"))
        self.assertFalse(_is_trusted_oauth_redirect_uri("https://evil-attacker.com/steal"))
        self.assertFalse(_is_trusted_oauth_redirect_uri("https://notclaude.ai/callback"))
        self.assertFalse(_is_trusted_oauth_redirect_uri("javascript:alert(1)"))
        self.assertFalse(_is_trusted_oauth_redirect_uri(""))

    def test_resolve_base_url_tunnel_and_custom_domain(self):
        """Verify base URL resolution prioritizes custom domains, public tunnels, and standard headers."""
        # 1. Custom URL in config
        with patch("server.load_config", return_value={"server": {"custom_public_url": "https://mcp.customcorp.com"}}):
            url = _resolve_base_url({"host": "127.0.0.1:8000"})
            self.assertEqual(url, "https://mcp.customcorp.com")

        # 2. Cloudflare Tunnel host header
        with patch("server.load_config", return_value={"server": {}}):
            url = _resolve_base_url({"host": "quick-start.trycloudflare.com"})
            self.assertEqual(url, "https://quick-start.trycloudflare.com")

        # 3. Tailscale Funnel host header
        with patch("server.load_config", return_value={"server": {}}):
            url = _resolve_base_url({"host": "myhost.ts.net"})
            self.assertEqual(url, "https://myhost.ts.net")

        # 4. Localhost fallback
        with patch("server.load_config", return_value={"server": {}}):
            url = _resolve_base_url({"host": "127.0.0.1:8000"}, default_scheme="http", default_host="127.0.0.1:8000")
            self.assertEqual(url, "http://127.0.0.1:8000")

    def test_dynamic_client_registration_rfc7591_for_claude(self):
        """Verify RFC 7591 dynamic client registration for Claude.ai with standard response fields."""
        import asyncio

        async def run_dcr_test():
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/oauth/register",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"host", b"claude-tunnel.trycloudflare.com")
                ],
                "client": ("127.0.0.1", 12345)
            }
            # Claude.ai DCR request
            dcr_payload = json.dumps({
                "client_name": "Claude",
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "token_endpoint_auth_method": "client_secret_post"
            }).encode("utf-8")

            async def receive():
                return {"type": "http.request", "body": dcr_payload, "more_body": False}

            resp = await oauth_register(Request(scope, receive=receive))
            self.assertEqual(resp.status_code, 201)
            data = json.loads(resp.body.decode("utf-8"))

            self.assertIn("client_id", data)
            self.assertTrue(data["client_id"].startswith("mcp_"))
            self.assertIn("client_secret", data)
            self.assertEqual(data["client_secret_expires_at"], 0)
            self.assertEqual(data["client_name"], "Claude")
            self.assertEqual(data["redirect_uris"], ["https://claude.ai/api/mcp/auth_callback"])
            self.assertEqual(data["token_endpoint_auth_method"], "client_secret_post")
            self.assertIn("client_id_issued_at", data)
            self.assertIsInstance(data["client_id_issued_at"], int)

            # Client was persisted in oauth.db
            stored = _get_oauth_client(data["client_id"])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["client_name"], "Claude")

        asyncio.run(run_dcr_test())

    def test_rfc9728_protected_resource_metadata_endpoints(self):
        """Verify Protected Resource Metadata exposes canonical resource, authorization_servers, and scopes."""
        import asyncio

        async def run_metadata_test():
            for p in ("/.well-known/oauth-protected-resource", "/mcp/.well-known/oauth-protected-resource"):
                scope = {
                    "type": "http",
                    "method": "GET",
                    "path": p,
                    "query_string": b"",
                    "headers": [(b"host", b"defroster.example.com"), (b"x-forwarded-proto", b"https")]
                }
                resp = await oauth_protected_resource(Request(scope))
                self.assertEqual(resp.status_code, 200)
                data = json.loads(resp.body.decode("utf-8"))

                self.assertIn("resource", data)
                self.assertEqual(data["resource"], "https://defroster.example.com/mcp")
                self.assertEqual(data["authorization_servers"], ["https://defroster.example.com"])
                self.assertEqual(data["bearer_methods_supported"], ["header"])
                self.assertIn("mcp", data["scopes_supported"])

        asyncio.run(run_metadata_test())

    def test_rfc8414_and_openid_discovery_metadata(self):
        """Verify RFC 8414 and OIDC discovery endpoints advertise supported endpoints, PKCE, and methods."""
        import asyncio

        async def run_discovery_test():
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/.well-known/oauth-authorization-server",
                "query_string": b"",
                "headers": [(b"host", b"defroster.example.com"), (b"x-forwarded-proto", b"https")]
            }
            resp_oauth = await oauth_authorization_server(Request(scope))
            self.assertEqual(resp_oauth.status_code, 200)
            data_oauth = json.loads(resp_oauth.body.decode("utf-8"))

            self.assertEqual(data_oauth["issuer"], "https://defroster.example.com")
            self.assertEqual(data_oauth["authorization_endpoint"], "https://defroster.example.com/oauth/authorize")
            self.assertEqual(data_oauth["token_endpoint"], "https://defroster.example.com/oauth/token")
            self.assertEqual(data_oauth["registration_endpoint"], "https://defroster.example.com/oauth/register")
            self.assertIn("S256", data_oauth["code_challenge_methods_supported"])
            self.assertIn("mcp", data_oauth["scopes_supported"])

            # OIDC compatibility endpoint
            resp_oidc = await openid_configuration(Request(scope))
            self.assertEqual(resp_oidc.status_code, 200)
            data_oidc = json.loads(resp_oidc.body.decode("utf-8"))
            self.assertEqual(data_oidc["issuer"], "https://defroster.example.com")
            self.assertIn("mcp", data_oidc["scopes_supported"])
            self.assertIn("openid", data_oidc["scopes_supported"])

        asyncio.run(run_discovery_test())

    def test_claude_oauth_consent_and_token_exchange(self):
        """Full end-to-end OAuth flow for Claude.ai: auto-registration, consent with owner token, and PKCE exchange."""
        import asyncio

        async def run_full_flow():
            verifier = "claude_pkce_verifier_string_0123456789_abcdefg"
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

            # 1. GET /oauth/authorize for Claude.ai
            claude_redirect = "https://claude.ai/api/mcp/auth_callback"
            scope_get = {
                "type": "http",
                "method": "GET",
                "path": "/oauth/authorize",
                "query_string": f"client_id=claude_web_client&redirect_uri={urllib.parse.quote(claude_redirect)}&response_type=code&state=claude_state_777&code_challenge={challenge}&code_challenge_method=S256".encode("ascii"),
                "headers": [(b"host", b"defroster.example.com"), (b"x-forwarded-proto", b"https")]
            }
            resp_get = await oauth_authorize(Request(scope_get))
            self.assertEqual(resp_get.status_code, 200)
            html = resp_get.body.decode("utf-8")
            self.assertIn("Claude", html)
            self.assertIn('name="csrf_token"', html)

            import re
            m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
            self.assertIsNotNone(m)
            csrf_token = m.group(1)

            # 2. POST /oauth/authorize with valid Defroster API token
            owner_token = load_config()["server"]["api_token"]
            post_body = (
                f"action=allow&csrf_token={csrf_token}&owner_token="
                + urllib.parse.quote(owner_token, safe="")
            ).encode("ascii")

            scope_post = {
                "type": "http",
                "method": "POST",
                "path": "/oauth/authorize",
                "headers": [
                    (b"content-type", b"application/x-www-form-urlencoded"),
                    (b"host", b"defroster.example.com")
                ],
                "client": ("127.0.0.1", 12345)
            }
            async def receive_post():
                return {"type": "http.request", "body": post_body, "more_body": False}

            resp_post = await oauth_authorize(Request(scope_post, receive=receive_post))
            self.assertEqual(resp_post.status_code, 302)
            location = resp_post.headers.get("location", "")
            self.assertIn("https://claude.ai/api/mcp/auth_callback", location)
            self.assertIn("code=", location)
            self.assertIn("state=claude_state_777", location)

            parsed_loc = urllib.parse.urlparse(location)
            params = urllib.parse.parse_qs(parsed_loc.query)
            auth_code = params["code"][0]

            # 3. POST /oauth/token for PKCE exchange
            token_payload = json.dumps({
                "grant_type": "authorization_code",
                "code": auth_code,
                "code_verifier": verifier,
                "client_id": "claude_web_client",
                "redirect_uri": claude_redirect
            }).encode("utf-8")

            scope_token = {
                "type": "http",
                "method": "POST",
                "path": "/oauth/token",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"host", b"defroster.example.com")
                ]
            }
            async def receive_token():
                return {"type": "http.request", "body": token_payload, "more_body": False}

            resp_token = await oauth_token(Request(scope_token, receive=receive_token))
            self.assertEqual(resp_token.status_code, 200)
            self.assertEqual(resp_token.headers.get("cache-control"), "no-store")
            self.assertEqual(resp_token.headers.get("pragma"), "no-cache")

            token_data = json.loads(resp_token.body.decode("utf-8"))
            self.assertIn("access_token", token_data)
            self.assertIn("refresh_token", token_data)
            self.assertEqual(token_data["token_type"], "Bearer")
            self.assertEqual(token_data["scope"], "mcp")

            # Validate that access_token works
            self.assertTrue(_is_valid_oauth_token(token_data["access_token"]))

        asyncio.run(run_full_flow())

    def test_security_middleware_headers_and_subpath_bypass(self):
        """Verify SecurityAndAuthMiddleware allows Claude framing, exposes WWW-Authenticate, and bypasses subpaths."""
        import asyncio

        app_called_paths = []
        async def dummy_app(scope, receive, send):
            app_called_paths.append(scope["path"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK", "more_body": False})

        middleware = SecurityAndAuthMiddleware(dummy_app, token="mc_test_sec_token", enforce_auth=True)

        async def run_middleware_tests():
            # 1. 401 response contains WWW-Authenticate with resource_metadata and realm
            sent = []
            async def send_capture(msg):
                sent.append(msg)

            scope_unauth = {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(b"host", b"tunnel.ts.net"), (b"x-forwarded-proto", b"https")],
                "client": ("192.168.1.50", 50000)
            }
            await middleware(scope_unauth, None, send_capture)
            start_msg = [m for m in sent if m.get("type") == "http.response.start"][0]
            self.assertEqual(start_msg["status"], 401)
            headers = dict(start_msg["headers"])
            www_auth = headers.get(b"www-authenticate", b"").decode("latin1")
            self.assertIn("realm=\"MammouthDefroster9000\"", www_auth)
            self.assertIn("resource_metadata=\"https://tunnel.ts.net/.well-known/oauth-protected-resource\"", www_auth)

            # 2. Subpath discovery bypasses authentication without credentials
            subpaths = [
                "/.well-known/oauth-protected-resource",
                "/mcp/.well-known/oauth-protected-resource",
                "/sse/.well-known/oauth-protected-resource",
                "/.well-known/oauth-authorization-server",
                "/mcp/.well-known/oauth-authorization-server",
                "/.well-known/openid-configuration",
                "/mcp/.well-known/openid-configuration",
                "/mcp/oauth/register",
                "/mcp/oauth/authorize",
                "/mcp/oauth/token",
            ]
            for sp in subpaths:
                sent_sp = []
                async def send_sp_cap(msg):
                    sent_sp.append(msg)
                scope_sp = {
                    "type": "http",
                    "method": "POST" if "token" in sp or "register" in sp else "GET",
                    "path": sp,
                    "headers": [(b"host", b"tunnel.ts.net")],
                    "client": ("192.168.1.50", 50000)
                }
                await middleware(scope_sp, None, send_sp_cap)
                self.assertIn(sp, app_called_paths, f"Subpath {sp} failed to bypass pre-authentication")
                resp_headers = dict([m for m in sent_sp if m.get("type") == "http.response.start"][0]["headers"])
                csp = resp_headers.get(b"content-security-policy", b"").decode("latin1")
                # Anti-clickjacking check: allows Claude and Mammouth AI framing
                self.assertIn("frame-ancestors 'self' https://mammouth.ai", csp)
                self.assertIn("https://claude.ai", csp)

        asyncio.run(run_middleware_tests())

    def test_claude_code_sync_with_oauth_mode(self):
        """Verify sync_claude_code_mcp with use_oauth=True creates entry without static headers."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp(prefix="claude_oauth_test_")
        try:
            ws_dir = Path(temp_dir) / "workspace"
            ws_dir.mkdir()

            res = sync_claude_code_mcp(
                workspace_path=str(ws_dir),
                server_url="https://tunnel.example.com/mcp",
                use_oauth=True,
                sync_global=False,
                update_claude_md=True
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["auth_mode"], "oauth")

            ws_mcp = ws_dir / ".mcp.json"
            data = json.loads(ws_mcp.read_text(encoding="utf-8"))
            entry = data["mcpServers"]["mammouth-defroster-9000"]
            self.assertEqual(entry["url"], "https://tunnel.example.com/mcp")
            self.assertNotIn("headers", entry)

            # Status recognizes it as cloud ready despite absence of static headers
            st = get_claude_code_status(workspace_path=str(ws_dir))
            self.assertTrue(st["cloud_ready"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
