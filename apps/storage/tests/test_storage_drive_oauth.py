"""Google Drive OAuth tests for Storage."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from errors import StorageValidationError  # noqa: E402
from service import handle_action  # noqa: E402


class StorageDriveOAuthTest(unittest.TestCase):
    def test_missing_secrets_and_start_flow_keep_state_redaction_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_status, missing = _handle(root, {"action": "drive_connections.start_oauth"})
            status, started = _handle(
                root,
                {
                    "action": "drive_connections.start_oauth",
                    "redirect_uri": "https://maverick.local/apps/storage/oauth/callback",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
            )
            state_payload = json.loads((root / "data" / "drive_connections.json").read_text(encoding="utf-8"))

        self.assertEqual(missing_status, 200)
        self.assertEqual(missing["status"], "not_configured")
        self.assertIn("google-drive-oauth-client-id", missing["missing_secrets"])
        self.assertIn("google-drive-oauth-client-secret", missing["missing_secrets"])
        self.assertEqual(status, 200)
        self.assertEqual(started["status"], "authorization_required")
        self.assertEqual(started["provider"], "google_drive")
        self.assertEqual(started["access_mode"], "full_rw")
        query = parse_qs(urlparse(started["authorization_url"]).query)
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["redirect_uri"], ["https://maverick.local/apps/storage/oauth/callback"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertIn("https://www.googleapis.com/auth/drive", query["scope"][0].split())
        self.assertEqual(started["state"], query["state"][0])
        self.assertNotIn(started["state"], json.dumps(state_payload, sort_keys=True))
        self.assertEqual(state_payload["connections"][0]["status"], "pending")

    def test_start_flow_requires_client_secret_before_google_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            status, payload = _handle(
                root,
                {
                    "action": "drive_connections.start_oauth",
                    "redirect_uri": "https://maverick.local/apps/storage/oauth/callback",
                    "_app_secrets": {"google-drive-oauth-client-id": "client-id"},
                },
            )
            state_payload = json.loads((root / "data" / "drive_connections.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "not_configured")
        self.assertIn("google-drive-oauth-client-secret", payload["missing_secrets"])
        self.assertNotIn("authorization_url", payload)
        self.assertEqual(state_payload["connections"], [])

    def test_invalid_access_mode_is_rejected_before_oauth_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(StorageValidationError) as captured:
                _handle(
                    root,
                    {
                        "action": "drive_connections.start_oauth",
                        "access_mode": "drive_everything",
                        "_app_secrets": {"google-drive-oauth-client-id": "client-id"},
                    },
                )
        self.assertIn("access mode", captured.exception.detail)
        self.assertEqual(captured.exception.allowed_values["access_mode"], ["full_read", "full_rw", "picker_limited"])

    def test_complete_flow_returns_resource_scoped_secret_write_without_persisting_tokens(self) -> None:
        calls: list[tuple[str, str, dict[str, object]]] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append((method, url, request))
            if url == "https://oauth2.googleapis.com/token":
                self.assertEqual(request["data"]["client_id"], "client-id")
                self.assertEqual(request["data"]["client_secret"], "client-secret")
                return 200, {
                    "access_token": "access-token-raw",
                    "refresh_token": "refresh-token-raw",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/drive openid email",
                }
            if url == "https://www.googleapis.com/oauth2/v2/userinfo":
                self.assertEqual(request["headers"]["Authorization"], "Bearer access-token-raw")
                return 200, {"email": "ana@example.com", "name": "Ana Example", "id": "google-subject"}
            raise AssertionError(f"Unexpected OAuth request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _status, started = _handle(
                root,
                {
                    "action": "drive_connections.start_oauth",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
            )
            status, completed = _handle(
                root,
                {
                    "action": "drive_connections.complete_oauth",
                    "state": started["state"],
                    "code": "oauth-code",
                    "_workspace_id": "default",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
                allow_platform_secret_writes=True,
                oauth_transport=transport,
            )
            persisted_text = (root / "data" / "drive_connections.json").read_text(encoding="utf-8")

        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "connected")
        self.assertEqual(completed["connection"]["account_email"], "ana@example.com")
        self.assertEqual(completed["connection"]["access_mode"], "full_rw")
        secret_write = completed["platform_secret_writes"][0]
        self.assertEqual(secret_write["logical_name"], "google-drive-refresh-token")
        self.assertEqual(secret_write["resource_type"], "drive_connection")
        self.assertEqual(secret_write["resource_id"], completed["connection_id"])
        self.assertEqual(secret_write["raw_value"], "refresh-token-raw")
        self.assertEqual(
            completed["credential"]["secret_ref"],
            f"platform:secret-alias/default-storage-google-drive-refresh-token-drive_connection-{completed['connection_id']}",
        )
        self.assertEqual(
            completed["credential"]["grant_id"],
            f"grant:default:storage:google-drive-refresh-token:drive_connection:{completed['connection_id']}",
        )
        public_payload = dict(completed)
        public_payload.pop("platform_secret_writes")
        self.assertNotIn("refresh-token-raw", json.dumps(public_payload, sort_keys=True))
        self.assertNotIn("access-token-raw", persisted_text)
        self.assertNotIn("refresh-token-raw", persisted_text)
        self.assertEqual([call[0] for call in calls], ["POST", "GET"])

    def test_complete_flow_validates_granted_scope(self) -> None:
        def transport(method: str, url: str, _request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": "https://www.googleapis.com/auth/drive.readonly openid email",
                }
            return 200, {"email": "ana@example.com"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _status, started = _handle(
                root,
                {
                    "action": "drive_connections.start_oauth",
                    "access_mode": "full_rw",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
            )
            with self.assertRaises(StorageValidationError) as captured:
                _handle(
                    root,
                    {
                        "action": "drive_connections.complete_oauth",
                        "state": started["state"],
                        "code": "oauth-code",
                        "_app_secrets": {
                            "google-drive-oauth-client-id": "client-id",
                            "google-drive-oauth-client-secret": "client-secret",
                        },
                    },
                    allow_platform_secret_writes=True,
                    oauth_transport=transport,
                )
        self.assertIn("required Drive scope", captured.exception.detail)

    def test_disconnect_is_local_audited_and_does_not_require_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _status, started = _handle(
                root,
                {
                    "action": "drive_connections.start_oauth",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
            )
            _status, completed = _handle(
                root,
                {
                    "action": "drive_connections.complete_oauth",
                    "state": started["state"],
                    "code": "oauth-code",
                    "_app_secrets": {
                        "google-drive-oauth-client-id": "client-id",
                        "google-drive-oauth-client-secret": "client-secret",
                    },
                },
                allow_platform_secret_writes=True,
                oauth_transport=_successful_transport,
            )
            status, disconnected = _handle(
                root,
                {"action": "drive_connections.disconnect", "connection_id": completed["connection_id"]},
            )
            persisted = json.loads((root / "data" / "drive_connections.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(disconnected["status"], "disconnected")
        self.assertEqual(disconnected["connection"]["credential"]["status"], "disconnected")
        self.assertEqual(disconnected["core_secret_revocation"]["status"], "not_supported_by_storage_backend")
        self.assertTrue(
            any(item["action"] == "drive.connections.disconnect" for item in persisted["audit_log"])
        )
        self.assertNotIn("refresh-token-raw", json.dumps(persisted, sort_keys=True))


def _successful_transport(method: str, url: str, _request: dict[str, object]) -> tuple[int, dict[str, object]]:
    if url == "https://oauth2.googleapis.com/token":
        return 200, {
            "access_token": "access-token-raw",
            "refresh_token": "refresh-token-raw",
            "scope": "https://www.googleapis.com/auth/drive openid email",
        }
    if url == "https://www.googleapis.com/oauth2/v2/userinfo":
        return 200, {"email": "ana@example.com", "name": "Ana Example"}
    raise AssertionError(f"Unexpected OAuth request: {method} {url}")


def _handle(
    root: Path,
    body: dict[str, object],
    *,
    allow_platform_secret_writes: bool = False,
    oauth_transport=None,
) -> tuple[int, dict[str, object]]:
    return handle_action(
        root / "data",
        root / "storage" / "uploaded",
        root / "storage" / "generated",
        body,
        allow_platform_secret_writes=allow_platform_secret_writes,
        oauth_transport=oauth_transport,
    )


if __name__ == "__main__":
    unittest.main()
