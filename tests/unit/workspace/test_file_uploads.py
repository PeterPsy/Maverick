from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.api.session_api import RequestSession
from core.api.workspace_files_api import handle_workspace_files_api
from core.identity.service import build_auth_session, build_user_record
from core.workspaces.models import WorkspaceQuotaRecord
from core.workspaces.file_uploads import save_workspace_upload


class WorkspaceFileUploadsTestCase(unittest.TestCase):
    def test_save_workspace_upload_rejects_decoded_payload_over_limit(self) -> None:
        content = base64.b64encode(b"too-large").decode("ascii")

        with patch("core.workspaces.file_uploads.MAX_UPLOAD_BYTES", 4):
            with self.assertRaises(ValueError) as raised:
                save_workspace_upload(
                    workspace_id="default",
                    filename="payload.txt",
                    content_type="text/plain",
                    content_base64=content,
                )

        self.assertEqual(str(raised.exception), "upload_too_large")

    def test_workspace_upload_api_rejects_quota_exhaustion_before_write(self) -> None:
        body = {
            "filename": "payload.txt",
            "content_type": "text/plain",
            "content_base64": base64.b64encode(b"too-large").decode("ascii"),
        }
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        class QuotaStore:
            def get_quota(self, workspace_id: str) -> WorkspaceQuotaRecord:
                now = datetime(2026, 4, 29, tzinfo=UTC)
                return WorkspaceQuotaRecord(
                    workspace_id=workspace_id,
                    max_agent_instances=None,
                    max_installed_apps=None,
                    max_storage_bytes=4,
                    created_at=now,
                    updated_at=now,
                )

        raw = json.dumps(body).encode("utf-8")
        now = datetime(2026, 4, 29, tzinfo=UTC)
        context = RequestSession(
            user=build_user_record(user_id="user:admin", username="admin", now=now),
            session=build_auth_session(session_id="session-1", user_id="user:admin", expires_at=now + timedelta(hours=1)),
            workspace_id="default",
        )

        with patch("core.api.workspace_files_api.require_session", return_value=context):
            response = handle_workspace_files_api(
                SimpleNamespace(workspace_store=QuotaStore()),
                {
                    "PATH_INFO": "/api/workspace-files/uploads",
                    "REQUEST_METHOD": "POST",
                    "CONTENT_LENGTH": str(len(raw)),
                    "wsgi.input": BytesIO(raw),
                },
                start_response,
                start_path=Path.cwd(),
            )

        self.assertEqual(captured["status"], "413 Payload Too Large")
        self.assertIn(b"workspace_storage_quota_exceeded", b"".join(response or []))


if __name__ == "__main__":
    unittest.main()
