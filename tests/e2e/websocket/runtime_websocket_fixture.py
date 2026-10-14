"""RuntimeWebsocketFixture fixtures extracted without changing assertions."""

from __future__ import annotations
from datetime import UTC, datetime
from io import BytesIO
import json, os
from core.api.platform_host import PlatformHost


class RuntimeWebsocketFixture:
    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None, cookie: str = "") -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "HTTP_HOST": "loopino.localhost",
            "HTTP_ORIGIN": "http://loopino.localhost",
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(payload),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login_cookie(self, state) -> str:
        app = PlatformHost(state, start_path=state.repository_root)
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("LOOPINO_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("LOOPINO_ADMIN_PASSWORD", "loopino"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def insert_corrupt_session(self, state, *, session_id: str = "corrupt-session") -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        repo_root = state.repository_root
        state.runtime_store.collections.sessions.update_one(
            {"workspace_id": "default", "session_id": session_id},
            {
                "$set": {
                    "workspace_id": "default",
                    "agent_id": "chat",
                    "status": "running",
                    "requested_mode": None,
                    "effective_mode": "sandbox",
                    "workspace_root": str(repo_root / "workspaces" / "default"),
                    "workdir": str(repo_root / "workspaces" / "default"),
                    "runtime_root": str(
                        repo_root / "workspaces" / "default" / "runtime" / "sessions" / session_id
                    ),
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                    "last_progress_at": now,
                    "session_kind": "chat_root",
                    "thread_visibility": "not-hidden",
                }
            },
            upsert=True,
        )
