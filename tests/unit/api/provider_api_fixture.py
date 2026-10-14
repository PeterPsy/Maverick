"""ProviderApiFixture fixtures extracted without changing assertions."""

from __future__ import annotations
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import patch
from core.api.provider_api import handle_provider_api
from core.api.session_api import RequestSession


class ProviderApiFixture:
    def invoke(
        self,
        path: str,
        *,
        query: str = "",
        method: str = "GET",
        body: dict | None = None,
        state=None,
    ) -> tuple[str, dict]:
        state = state or self.make_state()
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="admin"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "REQUEST_METHOD": method,
            "wsgi.input": BytesIO(body_bytes),
            "CONTENT_LENGTH": str(len(body_bytes)),
            "CONTENT_TYPE": "application/json",
        }
        captured: dict[str, object] = {}
        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        with patch("core.api.provider_api.require_session", return_value=context):
            body = handle_provider_api(state, environ, start_response)
        assert body is not None
        return str(captured["status"]), json.loads(b"".join(body).decode("utf-8"))
