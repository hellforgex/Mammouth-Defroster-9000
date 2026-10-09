"""
Runtime verification script for compiled MammouthDefroster9000-server.exe binary.
Executes live Windows blackbox testing for sovereign security gates:
  (a) request without token => 401 Unauthorized
  (b) 5x bad token => 429 Too Many Requests progressive backoff
  (c) empty api_token in config.json => fails closed (401) via auto-generated token
  (d) token tamper => 401 rejection via constant-time compare_digest
"""

import sys
import os
import time
import json
import socket
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.error

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.3)
    return False

def make_http_request(url: str, token: str = None, headers: dict = None) -> tuple[int, dict, str]:
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, dict(e.headers), body
    except Exception as e:
        return 0, {}, str(e)

def run_runtime_checks(server_exe_path: str, test_port: int = 8991):
    print("=" * 60)
    print("MAMMOUTH DEFROSTER 9000 - COMPILED BINARY RUNTIME VERIFICATION")
    print("=" * 60)
    print(f"Target Binary: {server_exe_path}")
    print(f"Target Port:   {test_port}")

    if not os.path.exists(server_exe_path):
        raise FileNotFoundError(f"Binary not found: {server_exe_path}")

    dist_dir = os.path.dirname(os.path.abspath(server_exe_path))
    config_path = os.path.join(dist_dir, "config.json")
    
    # Backup original config
    original_config_content = None
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            original_config_content = f.read()

    # Step 1: Set empty api_token in config.json to test fail-closed auto-generation
    test_cfg = {
        "server": {
            "host": "127.0.0.1",
            "port": test_port,
            "api_token": "",  # Empty token to test fail-closed auto-generation
            "enforce_auth": True,
            "auto_start_server": True,
            "auto_tunnel": False,
            "enable_tls": False
        },
        "modules": {}
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(test_cfg, f, indent=2)

    env = os.environ.copy()
    env["PORT"] = str(test_port)
    env["HOST"] = "127.0.0.1"

    proc = subprocess.Popen(
        [server_exe_path],
        cwd=dist_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        print("[1/5] Waiting for compiled server to initialize...")
        if not wait_for_server(test_port, timeout=20.0):
            stdout, stderr = proc.communicate(timeout=2)
            print("STDOUT:", stdout)
            print("STDERR:", stderr)
            raise RuntimeError("Server binary failed to bind to port in time!")
        print("  -> Server is listening on 127.0.0.1:" + str(test_port))

        base_url = f"http://127.0.0.1:{test_port}"
        protected_url = f"{base_url}/sse"

        # Check (a): Request without token => 401
        print("\n[2/5] Check (a): Request WITHOUT token...")
        status_a, headers_a, _ = make_http_request(protected_url, token=None)
        print(f"  -> HTTP Status: {status_a}")
        assert status_a == 401, f"Expected 401 for unauthenticated request, got {status_a}"
        assert "www-authenticate" in [k.lower() for k in headers_a.keys()], "Expected WWW-Authenticate header"
        print("  -> PASS: Request without token rejected with HTTP 401")

        # Check (c): Read config.json to confirm token was auto-generated (fail-closed)
        print("\n[3/5] Check (c): Verifying empty api_token auto-generation (Fail-closed)...")
        with open(config_path, "r", encoding="utf-8") as f:
            updated_cfg = json.load(f)
        auto_token = updated_cfg.get("server", {}).get("api_token", "")
        print(f"  -> Auto-generated token: {auto_token[:6]}... (length: {len(auto_token)})")
        assert len(auto_token) >= 24, "Auto-generated token is invalid or missing"
        print("  -> PASS: Empty api_token triggered fail-closed auto-generation")

        # Check (d): Token tamper => compare_digest rejection
        print("\n[4/5] Check (d): Request with TAMPERED token...")
        # Flip the last character of the real token
        tampered_char = "X" if auto_token[-1] != "X" else "Y"
        tampered_token = auto_token[:-1] + tampered_char
        status_d, _, _ = make_http_request(protected_url, token=tampered_token)
        print(f"  -> HTTP Status: {status_d}")
        assert status_d == 401, f"Expected 401 for tampered token, got {status_d}"
        print("  -> PASS: Tampered token rejected with HTTP 401 via compare_digest")

        # Check (b): 5x bad token => progressive backoff (HTTP 429) for remote clients
        print("\n[5/5] Check (b): Testing progressive backoff (5x bad token lockout for remote client)...")
        remote_headers = {"X-Forwarded-For": "198.51.100.77"}
        for attempt in range(1, 6):
            bad_tok = f"attacker_token_{attempt}"
            st, _, _ = make_http_request(protected_url, token=bad_tok, headers=remote_headers)
            print(f"  -> Attempt {attempt}/5: HTTP Status: {st}")
            assert st == 401, f"Expected 401 on attempt {attempt}, got {st}"

        # Now lockout is active for 198.51.100.77: The 6th request must trigger progressive backoff lockout -> HTTP 429
        status_b, headers_b, body_b = make_http_request(protected_url, token="any_token", headers=remote_headers)
        print(f"  -> Locked-out attempt (6th): HTTP Status: {status_b}")
        assert status_b == 429, f"Expected 429 Too Many Requests after 5 failures, got {status_b}"
        retry_after = headers_b.get('retry-after', headers_b.get('Retry-After'))
        print(f"  -> Lockout response headers: Retry-After={retry_after}")
        print("  -> PASS: Progressive backoff active! Returns HTTP 429 after 5 failures for remote client")

        print("\n" + "=" * 60)
        print("ALL 4 RUNTIME CHECKS (a, b, c, d) PASSED ON COMPILED EXE!")
        print("=" * 60)
        return True

    finally:
        print("\nCleaning up server process...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Restore original config
        if original_config_content is not None:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(original_config_content)

if __name__ == "__main__":
    exe_target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "dist", "MammouthDefroster9000", "MammouthDefroster9000-server.exe"
    )
    exe_target = os.path.abspath(exe_target)
    success = run_runtime_checks(exe_target, test_port=8991)
    sys.exit(0 if success else 1)
