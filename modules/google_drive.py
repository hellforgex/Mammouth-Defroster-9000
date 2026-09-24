import os
import sys
import json
import time
import hashlib
import urllib.parse
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional, Tuple

import httpx

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()

CONFIG_FILE = BASE_DIR / "config.json"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "gdrive_token.json"
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_SCOPES = "https://www.googleapis.com/auth/drive"

# Application identification for Defroster 9000
DEFAULT_USER_AGENT = "Defroster9000/0.3.0 (Mammouth.ai)"
DEFAULT_CLIENT_ID = os.environ.get("DEFROSTER_GDRIVE_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("DEFROSTER_GDRIVE_CLIENT_SECRET", "")

# DPAPI encryption for token storage (Fail-closed per SECURITY.md:40)
try:
    import win32crypt
    import base64
    HAS_DPAPI = True
except ImportError:
    HAS_DPAPI = False

def _encrypt_dpapi(plaintext: str) -> str:
    """Encrypt token using Windows DPAPI (Fail-closed per SECURITY.md:40)."""
    if not plaintext:
        return ""
    if not HAS_DPAPI:
        raise RuntimeError("Windows DPAPI (pywin32) is required for Google Drive token encryption. Plaintext storage is prohibited.")
    try:
        data_bytes = plaintext.encode("utf-8")
        encrypted = win32crypt.CryptProtectData(data_bytes, "MammouthGDriveSecret", None, None, None, 0)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    except Exception as ex:
        raise RuntimeError(f"DPAPI Encryption Error: {ex}. Plaintext token storage is prohibited.")

def _decrypt_dpapi(ciphertext: str) -> str:
    """Decrypt token using Windows DPAPI."""
    if not ciphertext or not ciphertext.startswith("dpapi:"):
        return ciphertext
    if not HAS_DPAPI:
        raise RuntimeError("Windows DPAPI (pywin32) is required for Google Drive token decryption.")
    try:
        raw_b64 = ciphertext[len("dpapi:"):]
        raw_bytes = base64.b64decode(raw_b64.encode("ascii"))
        _, decrypted_blob = win32crypt.CryptUnprotectData(raw_bytes, None, None, None, 0)
        return decrypted_blob.decode("utf-8")
    except Exception as ex:
        raise RuntimeError(f"DPAPI Decryption Error: {ex}")

# Try importing sandbox path validator from file_ops
try:
    from modules.file_ops import _validate_path, _get_sandbox_config
except ImportError:
    def _get_sandbox_config() -> Tuple[bool, Path]:
        return True, (BASE_DIR / "workspace").resolve()

    def _validate_path(target_path_str: str, for_write: bool = False) -> Path:
        raw_path = Path(target_path_str)
        if not raw_path.is_absolute():
            resolved = ((BASE_DIR / "workspace") / raw_path).resolve()
        else:
            resolved = raw_path.resolve()
        return resolved


def _load_client_credentials() -> Optional[Dict[str, Any]]:
    """Load OAuth 2.0 client credentials from credentials.json, config.json, or environment."""
    # 1. Check credentials.json
    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if "installed" in data:
                return data["installed"]
            elif "web" in data:
                return data["web"]
            elif "client_id" in data:
                return data
        except Exception:
            pass

    # 2. Check config.json module settings
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            gd_cfg = cfg.get("modules", {}).get("google_drive", {})
            cid = gd_cfg.get("client_id", "").strip()
            csec = gd_cfg.get("client_secret", "").strip()
            if csec.startswith("dpapi:"):
                csec = _decrypt_dpapi(csec)
            if cid:
                return {
                    "client_id": cid,
                    "client_secret": csec
                }
        except Exception:
            pass

    # 3. Check environment variables
    if DEFAULT_CLIENT_ID:
        return {
            "client_id": DEFAULT_CLIENT_ID,
            "client_secret": DEFAULT_CLIENT_SECRET
        }

    return None


def _load_stored_token() -> Optional[Dict[str, Any]]:
    """Load and decrypt stored OAuth token from gdrive_token.json."""
    if not TOKEN_FILE.exists():
        return None
    try:
        raw_content = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if raw_content.startswith("dpapi:"):
            raw_content = _decrypt_dpapi(raw_content)
        return json.loads(raw_content)
    except Exception:
        return None


def _save_stored_token(token_data: Dict[str, Any]) -> None:
    """Save token to gdrive_token.json with DPAPI encryption."""
    serialized = json.dumps(token_data, indent=2)
    encrypted = _encrypt_dpapi(serialized)
    TOKEN_FILE.write_text(encrypted, encoding="utf-8")


def _refresh_access_token(client_info: Dict[str, Any], token_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Refresh expired access token using the OAuth refresh_token."""
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None

    client_id = client_info.get("client_id")
    client_secret = client_info.get("client_secret")
    if not client_id or not client_secret:
        return None

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = client.post(OAUTH_TOKEN_URL, data=payload)
            if resp.status_code == 200:
                new_data = resp.json()
                token_data["access_token"] = new_data["access_token"]
                token_data["expires_at"] = time.time() + new_data.get("expires_in", 3600) - 60
                if "refresh_token" in new_data:
                    token_data["refresh_token"] = new_data["refresh_token"]
                _save_stored_token(token_data)
                return token_data
    except Exception:
        pass
    return None


def _get_service_account_token() -> Optional[str]:
    """Generate an access token using Service Account credentials if present."""
    if not SERVICE_ACCOUNT_FILE.exists():
        return None
    try:
        sa_data = json.loads(SERVICE_ACCOUNT_FILE.read_text(encoding="utf-8"))
        private_key = sa_data.get("private_key")
        client_email = sa_data.get("client_email")
        token_uri = sa_data.get("token_uri", OAUTH_TOKEN_URL)

        if not private_key or not client_email:
            return None

        # Check if google-auth is installed for official handling
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            creds = service_account.Credentials.from_service_account_info(
                sa_data,
                scopes=[DRIVE_SCOPES]
            )
            req = google.auth.transport.requests.Request()
            creds.refresh(req)
            return creds.token
        except ImportError:
            pass

        # Fallback using cryptography if google-auth is not installed
        try:
            import base64
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            now = int(time.time())
            header = {"alg": "RS256", "typ": "JWT"}
            claims = {
                "iss": client_email,
                "scope": DRIVE_SCOPES,
                "aud": token_uri,
                "exp": now + 3600,
                "iat": now,
            }

            def b64url(data: bytes) -> str:
                return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

            hdr_b64 = b64url(json.dumps(header).encode("utf-8"))
            claims_b64 = b64url(json.dumps(claims).encode("utf-8"))
            signing_input = f"{hdr_b64}.{claims_b64}".encode("ascii")

            priv_key_obj = load_pem_private_key(private_key.encode("utf-8"), password=None)
            signature = priv_key_obj.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
            sig_b64 = b64url(signature)
            jwt_token = f"{hdr_b64}.{claims_b64}.{sig_b64}"

            with httpx.Client(timeout=15.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
                resp = client.post(
                    token_uri,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": jwt_token,
                    }
                )
                if resp.status_code == 200:
                    return resp.json().get("access_token")
        except Exception:
            pass
    except Exception:
        pass
    return None


def get_drive_auth_headers() -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Get HTTP authorization headers for Google Drive requests (OAuth Bearer or Service Account).
    
    Returns (headers_dict, error_message).
    """
    # 1. Try OAuth 2.0 User Token
    token_data = _load_stored_token()
    client_info = _load_client_credentials()

    if token_data:
        expires_at = token_data.get("expires_at", 0)
        access_token = token_data.get("access_token")

        if access_token and time.time() < expires_at:
            return {"Authorization": f"Bearer {access_token}"}, None

        # Expired: attempt refresh
        if client_info:
            refreshed = _refresh_access_token(client_info, token_data)
            if refreshed and "access_token" in refreshed:
                return {"Authorization": f"Bearer {refreshed['access_token']}"}, None

    # 2. Try Service Account Token
    sa_token = _get_service_account_token()
    if sa_token:
        return {"Authorization": f"Bearer {sa_token}"}, None

    # 3. If nothing active
    return None, "Google Drive is not authenticated. Please click 'Launch Login Browser' in the Cockpit GUI to sign in with your Google account."


def get_active_access_token() -> Tuple[Optional[str], Optional[str]]:
    """Get active access token."""
    headers, err = get_drive_auth_headers()
    if headers:
        auth_hdr = headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            return auth_hdr[7:], None
    return None, err


# =========================================================================
# OAUTH 2.0 DESKTOP LOOPBACK SERVER (AUTOMATED CODE EXCHANGE)
# =========================================================================

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    auth_error: Optional[str] = None
    exchange_success: bool = False
    active_code_verifier: Optional[str] = None

    def log_message(self, format, *args):
        pass  # Suppress default server console output

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            code = params["code"][0]
            _OAuthCallbackHandler.auth_code = code
            port = getattr(self.server, "server_port", 8085)
            redirect_uri = f"http://127.0.0.1:{port}"

            # AUTOMATICALLY COMPLETE OAUTH EXCHANGE IMMEDIATELY!
            res = complete_oauth_code_exchange(code, redirect_uri)
            if res.get("success"):
                _OAuthCallbackHandler.exchange_success = True
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                success_html = """
                <!DOCTYPE html>
                <html>
                <head><title>Mammouth Defroster 9000 - Connected</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0A0A0C; color: #F3F4F6; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                    .card { background: #14151B; border: 1px solid #22242E; padding: 40px; border-radius: 12px; text-align: center; max-width: 450px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
                    h1 { color: #10B981; font-size: 22px; margin-bottom: 12px; }
                    p { color: #9CA3AF; font-size: 14px; line-height: 1.5; }
                </style>
                </head>
                <body>
                <div class="card">
                    <h1>🦣 Google Drive Connected!</h1>
                    <p>Authentication was completed automatically. Mammouth Defroster 9000 now has access to Google Drive.</p>
                    <p style="margin-top: 20px; font-size: 12px; color: #64748B;">You can safely close this browser window and return to the application.</p>
                </div>
                </body>
                </html>
                """
                self.wfile.write(success_html.encode("utf-8"))
            else:
                _OAuthCallbackHandler.auth_error = res.get("error", "Token exchange failed")
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                err_html = f"<html><body style='background:#0A0A0C;color:#EF4444;font-family:sans-serif;padding:40px;'><h2>Authentication Failed</h2><p>{res.get('error')}</p></body></html>"
                self.wfile.write(err_html.encode("utf-8"))
        else:
            err = params.get("error", ["Unknown error"])[0]
            _OAuthCallbackHandler.auth_error = err
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            err_html = f"<html><body style='background:#0A0A0C;color:#EF4444;font-family:sans-serif;padding:40px;'><h2>Authentication Failed</h2><p>{err}</p></body></html>"
            self.wfile.write(err_html.encode("utf-8"))


def start_oauth_flow(port: int = 8085, timeout_seconds: int = 120) -> Dict[str, Any]:
    """Start desktop loopback server and return OAuth authorization URL with PKCE."""
    import secrets
    import base64

    client_info = _load_client_credentials()
    if not client_info or not client_info.get("client_id"):
        return {
            "success": False,
            "error": (
                "No Google Cloud OAuth Client ID configured.\n\n"
                "To connect Google Drive as 'Defroster 9000':\n"
                "1. Go to Google Cloud Console (APIs & Services > Credentials)\n"
                "2. Create an OAuth 2.0 Client ID for 'Desktop app' named 'Defroster 9000'\n"
                "3. In Cockpit Settings (Section 7), paste your Client ID or click 'Import credentials.json'."
            )
        }

    client_id = client_info.get("client_id")
    client_secret = client_info.get("client_secret", "")

    redirect_uri = f"http://127.0.0.1:{port}"

    # Generate PKCE verifier and challenge (RFC 7636)
    verifier_bytes = secrets.token_bytes(32)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    _OAuthCallbackHandler.active_code_verifier = code_verifier

    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    auth_url = f"{OAUTH_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.auth_error = None
    _OAuthCallbackHandler.exchange_success = False

    def run_server():
        try:
            httpd = HTTPServer(("127.0.0.1", port), _OAuthCallbackHandler)
            httpd.server_port = port
            httpd.timeout = 2.0
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                httpd.handle_request()
                if _OAuthCallbackHandler.exchange_success or _OAuthCallbackHandler.auth_error:
                    break
            httpd.server_close()
        except Exception:
            pass

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    return {
        "success": True,
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "server_thread": server_thread
    }


def complete_oauth_code_exchange(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange authorization code for access and refresh tokens with PKCE."""
    client_info = _load_client_credentials() or {}

    payload = {
        "client_id": client_info.get("client_id", DEFAULT_CLIENT_ID),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if getattr(_OAuthCallbackHandler, "active_code_verifier", None):
        payload["code_verifier"] = _OAuthCallbackHandler.active_code_verifier
    if client_info.get("client_secret"):
        payload["client_secret"] = client_info["client_secret"]

    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = client.post(OAUTH_TOKEN_URL, data=payload)
            if resp.status_code == 200:
                token_data = resp.json()
                token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600) - 60
                _save_stored_token(token_data)
                return {"success": True, "token_data": token_data}
            else:
                return {"success": False, "error": f"Token exchange failed: {resp.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def auto_authenticate_if_needed(timeout_seconds: int = 60) -> bool:
    """Check if authenticated, and if not, automatically launch OAuth browser flow and wait for completion."""
    headers, _ = get_drive_auth_headers()
    if headers:
        return True

    res = start_oauth_flow(timeout_seconds=timeout_seconds)
    if not res.get("success"):
        return False

    import webbrowser
    webbrowser.open(res["auth_url"])

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        headers, _ = get_drive_auth_headers()
        if headers:
            return True
        time.sleep(1.0)
    return False


def disconnect_gdrive() -> bool:
    """Disconnect Google Drive by removing the stored token and credentials files."""
    for p in [TOKEN_FILE, CREDENTIALS_FILE]:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    return True


# =========================================================================
# MCP TOOLS IMPLEMENTATION
# =========================================================================

def gdrive_status() -> Dict[str, Any]:
    """Check Google Drive connectivity, authentication details, and storage quota."""
    headers, err = get_drive_auth_headers()

    if not headers:
        return {
            "authenticated": False,
            "error": err,
            "credentials_file_exists": CREDENTIALS_FILE.exists(),
            "token_file_exists": TOKEN_FILE.exists(),
            "service_account_file_exists": SERVICE_ACCOUNT_FILE.exists()
        }

    # If OAuth or Service account
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = client.get(
                f"{DRIVE_API_BASE}/about",
                headers=headers,
                params={"fields": "user,storageQuota"}
            )
            if resp.status_code == 200:
                data = resp.json()
                user = data.get("user", {})
                quota = data.get("storageQuota", {})
                
                limit_bytes = int(quota.get("limit", 0))
                usage_bytes = int(quota.get("usage", 0))
                limit_gb = round(limit_bytes / (1024**3), 2) if limit_bytes > 0 else "Unlimited"
                usage_gb = round(usage_bytes / (1024**3), 2)

                return {
                    "authenticated": True,
                    "auth_type": "oauth2",
                    "user_email": user.get("emailAddress", "Unknown"),
                    "user_name": user.get("displayName", "Unknown"),
                    "storage_usage_gb": usage_gb,
                    "storage_limit_gb": limit_gb,
                    "storage_in_drive_gb": round(int(quota.get("usageInDrive", 0)) / (1024**3), 2),
                    "storage_in_trash_gb": round(int(quota.get("usageInDriveTrash", 0)) / (1024**3), 2)
                }
            else:
                return {
                    "authenticated": False,
                    "error": f"API error checking status ({resp.status_code}): {resp.text}"
                }
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


def _ensure_auth_headers() -> Dict[str, str]:
    """Ensure valid authorization headers or auto-trigger authentication."""
    headers, err = get_drive_auth_headers()
    if not headers:
        if auto_authenticate_if_needed(45):
            headers, err = get_drive_auth_headers()
    if not headers:
        raise PermissionError(err)
    return headers


def gdrive_list_files(
    folder_id: str = "root",
    query: str = "",
    page_size: int = 25
) -> List[Dict[str, Any]]:
    """List files and folders inside a Google Drive folder or matching a custom search query.
    
    Args:
        folder_id: Parent folder ID (default 'root').
        query: Additional Drive search query (e.g. "name contains 'report'").
        page_size: Number of files to return (1-100, default 25).
    """
    headers = _ensure_auth_headers()

    q_parts = [f"'{folder_id}' in parents", "trashed = false"]
    if query:
        q_parts.append(f"({query})")
    full_query = " and ".join(q_parts)

    params = {
        "q": full_query,
        "pageSize": min(max(1, page_size), 100),
        "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,parents)"
    }

    with httpx.Client(timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.get(f"{DRIVE_API_BASE}/files", headers=headers, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Google Drive API error ({resp.status_code}): {resp.text}")
        files = resp.json().get("files", [])
        return files


def gdrive_search_files(query: str, page_size: int = 25) -> List[Dict[str, Any]]:
    """Search Google Drive files by name or full-text content across the entire drive.
    
    Args:
        query: Search term (searches filename and document text).
        page_size: Maximum results to return (default 25).
    """
    headers = _ensure_auth_headers()

    clean_query = query.replace("'", "\\'")
    drive_q = f"(name contains '{clean_query}' or fullText contains '{clean_query}') and trashed = false"

    params = {
        "q": drive_q,
        "pageSize": min(max(1, page_size), 100),
        "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,parents)"
    }

    with httpx.Client(timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.get(f"{DRIVE_API_BASE}/files", headers=headers, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Google Drive API error ({resp.status_code}): {resp.text}")
        return resp.json().get("files", [])


def gdrive_get_metadata(file_id: str) -> Dict[str, Any]:
    """Get detailed metadata of a Google Drive file or folder by ID.
    
    Args:
        file_id: Google Drive file or folder ID.
    """
    headers = _ensure_auth_headers()
    params = {"fields": "id,name,mimeType,size,createdTime,modifiedTime,webViewLink,webContentLink,parents,owners,shared"}

    with httpx.Client(timeout=15.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.get(f"{DRIVE_API_BASE}/files/{file_id}", headers=headers, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Google Drive API error ({resp.status_code}): {resp.text}")
        return resp.json()


def gdrive_read_file(file_id: str, max_chars: int = 50000) -> str:
    """Read and extract text content from a Google Drive file.
    
    Automatically exports Google Docs to plain text / markdown and Google Sheets to CSV.
    
    Args:
        file_id: Google Drive file ID.
        max_chars: Maximum characters to return (default 50,000).
    """
    headers = _ensure_auth_headers()

    with httpx.Client(timeout=30.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        # First check mimeType
        meta_resp = client.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=headers,
            params={"fields": "id,name,mimeType,size"}
        )
        if meta_resp.status_code != 200:
            raise RuntimeError(f"Could not fetch file metadata: {meta_resp.text}")
        
        meta = meta_resp.json()
        mime = meta.get("mimeType", "")

        # Google Docs export
        if mime == "application/vnd.google-apps.document":
            resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/plain"}
            )
        # Google Sheets export
        elif mime == "application/vnd.google-apps.spreadsheet":
            resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/csv"}
            )
        # Google Presentations export
        elif mime == "application/vnd.google-apps.presentation":
            resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/plain"}
            )
        # Standard file download
        else:
            resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media"}
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Download failed ({resp.status_code}): {resp.text}")

        content_text = resp.text
        if len(content_text) > max_chars:
            return content_text[:max_chars] + f"\n\n[... Truncated, total length is {len(content_text)} characters ...]"
        return content_text


def gdrive_download_to_workspace(file_id: str, destination_filename: str = "") -> Dict[str, Any]:
    """Download any file from Google Drive directly into the sandboxed local workspace.
    
    Args:
        file_id: Google Drive file ID.
        destination_filename: Optional filename in workspace. If omitted, Drive file's original name is used.
    """
    headers = _ensure_auth_headers()

    with httpx.Client(timeout=60.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        # Get metadata for filename and mimeType
        meta_resp = client.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            headers=headers,
            params={"fields": "id,name,mimeType,size"}
        )
        if meta_resp.status_code != 200:
            raise RuntimeError(f"Could not fetch file metadata: {meta_resp.text}")
        
        meta = meta_resp.json()
        drive_name = meta.get("name", f"gdrive_{file_id}")
        mime = meta.get("mimeType", "")

        target_name = destination_filename.strip() or drive_name
        
        # Handle Google Docs / Sheets automatic extensions
        if mime == "application/vnd.google-apps.document" and not target_name.endswith(".txt") and not target_name.endswith(".md"):
            target_name += ".txt"
            download_resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/plain"}
            )
        elif mime == "application/vnd.google-apps.spreadsheet" and not target_name.endswith(".csv"):
            target_name += ".csv"
            download_resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/csv"}
            )
        else:
            download_resp = client.get(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media"}
            )

        if download_resp.status_code != 200:
            raise RuntimeError(f"Download failed ({download_resp.status_code}): {download_resp.text}")

        # Validate path against sandbox
        dest_path = _validate_path(target_name, for_write=True)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(download_resp.content)

        return {
            "status": "success",
            "file_id": file_id,
            "drive_name": drive_name,
            "saved_to": str(dest_path),
            "size_bytes": len(download_resp.content)
        }


def gdrive_upload_from_workspace(
    local_filename: str,
    folder_id: str = "root",
    drive_filename: str = ""
) -> Dict[str, Any]:
    """Upload a file from the sandboxed local workspace to Google Drive.
    
    Args:
        local_filename: Relative or absolute path to file in workspace.
        folder_id: Parent folder ID in Google Drive (default 'root').
        drive_filename: Optional name for the uploaded file in Drive. If omitted, local filename is used.
    """
    headers_base = _ensure_auth_headers()

    # Validate local file path
    src_path = _validate_path(local_filename, for_write=False)
    if not src_path.exists() or not src_path.is_file():
        raise FileNotFoundError(f"Local file '{local_filename}' not found in workspace.")

    upload_name = drive_filename.strip() or src_path.name
    file_bytes = src_path.read_bytes()

    metadata = {
        "name": upload_name,
        "parents": [folder_id]
    }

    # Multipart upload payload
    boundary = "-------MammouthDefrosterBoundary" + str(int(time.time()))
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = dict(headers_base)
    headers["Content-Type"] = f"multipart/related; boundary={boundary}"
    headers["Content-Length"] = str(len(body))

    with httpx.Client(timeout=60.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.post(
            f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart",
            headers=headers,
            content=body
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")
        
        data = resp.json()
        return {
            "status": "success",
            "file_id": data.get("id"),
            "name": data.get("name"),
            "mimeType": data.get("mimeType"),
            "uploaded_bytes": len(file_bytes)
        }


def gdrive_write_file(
    name: str,
    content: str,
    folder_id: str = "root",
    mime_type: str = "text/plain"
) -> Dict[str, Any]:
    """Create a new file directly in Google Drive with text/code/markdown content.
    
    Args:
        name: Name of the file (e.g. 'notes.txt', 'script.py', 'document.md').
        content: Text content to write into the file.
        folder_id: Parent folder ID in Google Drive (default 'root').
        mime_type: MIME type of the file (default 'text/plain').
    """
    headers_base = _ensure_auth_headers()

    content_bytes = content.encode("utf-8")
    metadata = {
        "name": name,
        "parents": [folder_id],
        "mimeType": mime_type
    }

    boundary = "-------MammouthDefrosterBoundary" + str(int(time.time()))
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}; charset=UTF-8\r\n\r\n"
    ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = dict(headers_base)
    headers["Content-Type"] = f"multipart/related; boundary={boundary}"
    headers["Content-Length"] = str(len(body))

    with httpx.Client(timeout=45.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.post(
            f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart",
            headers=headers,
            content=body
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Write file failed ({resp.status_code}): {resp.text}")
        
        data = resp.json()
        return {
            "status": "success",
            "file_id": data.get("id"),
            "name": data.get("name"),
            "mimeType": data.get("mimeType"),
            "bytes_written": len(content_bytes)
        }


def gdrive_update_file(file_id: str, content: str) -> Dict[str, Any]:
    """Update or overwrite the content of an existing file in Google Drive.
    
    Args:
        file_id: Google Drive file ID to update.
        content: New text content to overwrite the file with.
    """
    headers_base = _ensure_auth_headers()

    content_bytes = content.encode("utf-8")
    headers = dict(headers_base)
    headers["Content-Type"] = "text/plain; charset=UTF-8"

    with httpx.Client(timeout=45.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.patch(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}?uploadType=media",
            headers=headers,
            content=content_bytes
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Update file content failed ({resp.status_code}): {resp.text}")
        
        data = resp.json()
        return {
            "status": "success",
            "file_id": data.get("id"),
            "name": data.get("name"),
            "bytes_written": len(content_bytes)
        }


def gdrive_create_folder(folder_name: str, parent_id: str = "root") -> Dict[str, Any]:
    """Create a new folder in Google Drive.
    
    Args:
        folder_name: Name of the new folder.
        parent_id: Parent folder ID (default 'root').
    """
    headers_base = _ensure_auth_headers()

    headers = dict(headers_base)
    headers["Content-Type"] = "application/json"
    payload = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }

    with httpx.Client(timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        resp = client.post(f"{DRIVE_API_BASE}/files", headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Create folder failed ({resp.status_code}): {resp.text}")
        return resp.json()


def gdrive_delete_file(file_id: str, permanent: bool = False) -> Dict[str, Any]:
    """Trash or permanently delete a file or folder from Google Drive.
    
    Args:
        file_id: Google Drive file or folder ID.
        permanent: If True, permanently deletes the file. If False (default), moves it to trash.
    """
    headers = _ensure_auth_headers()

    with httpx.Client(timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        if permanent:
            resp = client.delete(f"{DRIVE_API_BASE}/files/{file_id}", headers=headers)
            if resp.status_code not in (200, 204):
                raise RuntimeError(f"Permanent delete failed ({resp.status_code}): {resp.text}")
            return {"status": "permanently_deleted", "file_id": file_id}
        else:
            resp = client.patch(
                f"{DRIVE_API_BASE}/files/{file_id}",
                headers=headers,
                json={"trashed": True}
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Move to trash failed ({resp.status_code}): {resp.text}")
            return {"status": "moved_to_trash", "file_id": file_id}
