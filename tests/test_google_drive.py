import unittest
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.google_drive import (
    gdrive_status,
    gdrive_list_files,
    gdrive_search_files,
    gdrive_get_metadata,
    gdrive_read_file,
    gdrive_download_to_workspace,
    gdrive_upload_from_workspace,
    gdrive_write_file,
    gdrive_update_file,
    gdrive_create_folder,
    gdrive_delete_file,
    get_active_access_token,
    get_drive_auth_headers,
    _OAuthCallbackHandler,
    complete_oauth_code_exchange,
    auto_authenticate_if_needed,
    _load_stored_token,
    _save_stored_token,
    disconnect_gdrive,
    TOKEN_FILE,
    CREDENTIALS_FILE
)


class TestGoogleDriveModule(unittest.TestCase):
    def setUp(self):
        self.mock_token = "mock-access-token-123"
        # Auth headers are cached in-process; start every test from a clean cache
        from modules.google_drive import _invalidate_auth_cache
        _invalidate_auth_cache()

    @patch("modules.google_drive.get_drive_auth_headers")
    def test_gdrive_status_unauthenticated(self, mock_get_headers):
        mock_get_headers.return_value = (None, "Google Drive is not authenticated.")
        status = gdrive_status()
        self.assertFalse(status["authenticated"])
        self.assertIn("not authenticated", status["error"])

    @patch("modules.google_drive.get_drive_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_status_authenticated(self, mock_client_cls, mock_get_headers):
        mock_get_headers.return_value = ({"Authorization": f"Bearer {self.mock_token}"}, None)
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "user": {"emailAddress": "test@mammouth.ai", "displayName": "Mammouth Tester"},
            "storageQuota": {"limit": "107374182400", "usage": "10737418240"}
        }
        mock_client.get.return_value = mock_resp

        status = gdrive_status()
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["user_email"], "test@mammouth.ai")
        self.assertEqual(status["user_name"], "Mammouth Tester")
        self.assertEqual(status["storage_limit_gb"], 100.0)
        self.assertEqual(status["storage_usage_gb"], 10.0)

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_list_files(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "files": [
                {"id": "file1", "name": "project.md", "mimeType": "text/markdown"},
                {"id": "file2", "name": "data.csv", "mimeType": "text/csv"}
            ]
        }
        mock_client.get.return_value = mock_resp

        files = gdrive_list_files(folder_id="root", page_size=10)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["name"], "project.md")
        self.assertEqual(files[1]["id"], "file2")

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_search_files(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "files": [{"id": "res1", "name": "quarterly_report.pdf", "mimeType": "application/pdf"}]
        }
        mock_client.get.return_value = mock_resp

        files = gdrive_search_files("report")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "quarterly_report.pdf")

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_read_google_doc_export(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        # 1. Metadata check response
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {"id": "doc1", "name": "MyDoc", "mimeType": "application/vnd.google-apps.document"}

        # 2. Export response
        export_resp = MagicMock()
        export_resp.status_code = 200
        export_resp.text = "# Exported Google Doc Content\nThis is document text."

        mock_client.get.side_effect = [meta_resp, export_resp]

        content = gdrive_read_file("doc1")
        self.assertIn("# Exported Google Doc Content", content)

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_write_file(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "new_file_id",
            "name": "ai_notes.txt",
            "mimeType": "text/plain"
        }
        mock_client.post.return_value = mock_resp

        res = gdrive_write_file("ai_notes.txt", "Hello from Mammouth AI!")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["file_id"], "new_file_id")
        self.assertEqual(res["bytes_written"], 23)

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_update_file(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "existing_id",
            "name": "ai_notes.txt"
        }
        mock_client.patch.return_value = mock_resp

        res = gdrive_update_file("existing_id", "Updated content!")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["file_id"], "existing_id")
        self.assertEqual(res["bytes_written"], 16)

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_create_folder(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "folder_id_123",
            "name": "Project Archive",
            "mimeType": "application/vnd.google-apps.folder"
        }
        mock_client.post.return_value = mock_resp

        res = gdrive_create_folder("Project Archive")
        self.assertEqual(res["id"], "folder_id_123")
        self.assertEqual(res["name"], "Project Archive")

    @patch("modules.google_drive._ensure_auth_headers")
    @patch("httpx.Client")
    def test_gdrive_delete_file_trash(self, mock_client_cls, mock_auth):
        mock_auth.return_value = {"Authorization": f"Bearer {self.mock_token}"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "file_to_trash", "trashed": True}
        mock_client.patch.return_value = mock_resp

        res = gdrive_delete_file("file_to_trash", permanent=False)
        self.assertEqual(res["status"], "moved_to_trash")
        self.assertEqual(res["file_id"], "file_to_trash")

    @patch("modules.google_drive._load_stored_token")
    @patch("modules.google_drive._load_client_credentials")
    def test_get_drive_auth_headers_oauth(self, mock_client, mock_token):
        mock_token.return_value = {
            "access_token": "valid-oauth-token",
            "expires_at": 9999999999
        }
        mock_client.return_value = {"client_id": "test_id", "client_secret": "test_sec"}
        headers, err = get_drive_auth_headers()
        self.assertIsNone(err)
        self.assertEqual(headers.get("Authorization"), "Bearer valid-oauth-token")

    @patch("modules.google_drive._load_stored_token", return_value=None)
    @patch("modules.google_drive._get_service_account_token", return_value=None)
    def test_get_drive_auth_headers_unauthenticated(self, mock_sa, mock_token):
        headers, err = get_drive_auth_headers()
        self.assertIsNone(headers)
        self.assertIsNotNone(err)
        self.assertIn("not authenticated", err)

    @patch("modules.google_drive.complete_oauth_code_exchange")
    def test_oauth_callback_handler_automated_exchange(self, mock_exchange):
        mock_exchange.return_value = {"success": True, "token_data": {"access_token": "tok123"}}

        # Mock request, client_address and server
        handler = _OAuthCallbackHandler.__new__(_OAuthCallbackHandler)
        handler.path = "/?code=oauth_code_xyz"
        handler.server = MagicMock()
        handler.server.server_port = 8085
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_GET()

        mock_exchange.assert_called_once_with("oauth_code_xyz", "http://127.0.0.1:8085")
        self.assertTrue(_OAuthCallbackHandler.exchange_success)
        self.assertEqual(_OAuthCallbackHandler.auth_code, "oauth_code_xyz")
        handler.send_response.assert_called_once_with(200)

    @patch("modules.google_drive.get_drive_auth_headers")
    def test_auto_authenticate_if_needed_already_authenticated(self, mock_headers):
        mock_headers.return_value = ({"Authorization": "Bearer abc"}, None)
        self.assertTrue(auto_authenticate_if_needed(timeout_seconds=5))

    def test_dpapi_fail_closed_zero_plaintext_fallback(self):
        """Item 8 / Finding M-1: Verify zero plaintext fallback for Google Drive token DPAPI encryption."""
        import modules.google_drive as gd
        # 1. Successful round-trip if DPAPI available
        if gd.HAS_DPAPI:
            secret = "oauth_refresh_token_xyz_999"
            enc = gd._encrypt_dpapi(secret)
            self.assertTrue(enc.startswith("dpapi:"))
            self.assertEqual(gd._decrypt_dpapi(enc), secret)

        # 2. Hard fail-closed when DPAPI unavailable
        orig_has = gd.HAS_DPAPI
        try:
            gd.HAS_DPAPI = False
            with self.assertRaises(RuntimeError) as ctx:
                gd._encrypt_dpapi("secret_token")
            self.assertIn("Plaintext storage is prohibited", str(ctx.exception))

            with self.assertRaises(RuntimeError) as ctx:
                gd._decrypt_dpapi("dpapi:somerawbytes")
            self.assertIn("DPAPI (pywin32) is required", str(ctx.exception))
        finally:
            gd.HAS_DPAPI = orig_has


if __name__ == "__main__":
    unittest.main()
