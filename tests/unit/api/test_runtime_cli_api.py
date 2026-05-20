"""Tests for the runtime-token CLI HTTP bridge."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_cli_api import handle_runtime_cli_api


class RuntimeCliApiTest(unittest.TestCase):
    def test_runtime_cli_uses_payload_error_status_for_http_response(self) -> None:
        state = SimpleNamespace(
            runtime_store=SimpleNamespace(
                get_session=lambda _session_id: SimpleNamespace(
                    effective_mode="sandbox",
                    owner_user_id="user:admin",
                    session_id="sess-1",
                    status="running",
                    workspace_id="default",
                )
            )
        )

        with patch(
            "core.api.runtime_cli_api._runtime_claims",
            return_value=({"runtime_session_id": "sess-1", "workspace_id": "default", "mode": "sandbox"}, None),
        ):
            with patch("core.api.runtime_cli_api._runtime_actor_authority", return_value=("admin", "user:admin", "admin")):
                with patch(
                    "core.api.runtime_cli_api.run_cli_json",
                    return_value={"status_code": 400, "error": "unsupported"},
                ):
                    status, payload = self._invoke_runtime_cli(state, {"argv": ["app", "vault", "cli", "run", "vault"]})

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["error"], "unsupported")

    def _invoke_runtime_cli(self, state: SimpleNamespace, payload: dict) -> tuple[str, dict]:
        body = json.dumps(payload).encode("utf-8")
        status_holder: list[str] = []

        response = handle_runtime_cli_api(
            state,
            {
                "CONTENT_LENGTH": str(len(body)),
                "PATH_INFO": "/api/runtime/cli",
                "REQUEST_METHOD": "POST",
                "wsgi.input": BytesIO(body),
            },
            lambda status, _headers: status_holder.append(status),
            start_path=Path("/repo"),
        )

        self.assertIsNotNone(response)
        assert response is not None
        return status_holder[0], json.loads(b"".join(response).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
