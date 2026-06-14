from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.service import create_runtime_session, record_runtime_event


class _RuntimeStoreProxy:
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.calls: list[tuple[str, int | None]] = []

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)

    def list_events(self, session_id: str):
        self.calls.append(("list_events", None))
        return self._wrapped.list_events(session_id)

    def list_recent_events(self, session_id: str, *, limit: int):
        self.calls.append(("list_recent_events", limit))
        return self._wrapped.list_recent_events(session_id, limit=limit)


class RuntimeSessionEventsApiTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str = "",
        query_string: str = "",
    ) -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "HTTP_HOST": "maverick.test",
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(payload),
        }
        if method != "GET":
            environ["HTTP_ORIGIN"] = "http://maverick.test"
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login_cookie(self, app: PlatformHost) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_limited_session_event_reads_use_recent_store_window(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
        for index in range(4):
            record_runtime_event(
                state.runtime_store,
                event_id=f"event-{index}",
                session_id=session.session_id,
                turn_id="turn-1",
                process_id=None,
                plane="turn",
                event_type="runtime.output.delta",
                payload={"text": str(index)},
                now=now + timedelta(milliseconds=index),
            )

        runtime_store = _RuntimeStoreProxy(state.runtime_store)
        state = replace(state, runtime_store=runtime_store)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login_cookie(app)

        status, payload, _headers = self.invoke(
            app,
            path="/api/runtime/sessions/sess-1/events",
            cookie=cookie,
            query_string="limit=2",
        )

        self.assertEqual(status, 200)
        self.assertEqual([item["event_id"] for item in payload["items"]], ["event-2", "event-3"])
        self.assertEqual(runtime_store.calls, [("list_recent_events", 2)])

    def test_unlimited_session_event_reads_keep_full_store_scan(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        record_runtime_event(
            state.runtime_store,
            event_id="event-1",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.output.delta",
            payload={"text": "hello"},
            now=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
        )

        runtime_store = _RuntimeStoreProxy(state.runtime_store)
        state = replace(state, runtime_store=runtime_store)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login_cookie(app)

        status, payload, _headers = self.invoke(app, path="/api/runtime/sessions/sess-1/events", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertEqual([item["event_id"] for item in payload["items"]], ["event-1"])
        self.assertEqual(runtime_store.calls, [("list_events", None)])


if __name__ == "__main__":
    unittest.main()
