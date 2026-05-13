"""Tests for runtime thread read receipts in WebSocket and HTTP surfaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
import json
import os
import tempfile
import unittest
from uuid import uuid4

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_thread_websocket import runtime_thread_changed_frame
from core.runtime.runtime_threads import (
    create_runtime_thread,
    mark_runtime_thread_completed_response_read,
    mark_runtime_thread_response_completed,
)
from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_turn
from tests.support.markers import slow_test_class


@slow_test_class("slow websocket integration suite; run with scripts/test_suite.py --level slow")
class RuntimeThreadReadReceiptTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify read receipt state is viewer-specific at runtime thread surfaces."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None, cookie: str = "") -> tuple[int, dict]:
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8"))

    def login_cookie(self, state) -> str:
        app = PlatformHost(state, start_path=state.repository_root)
        status, _payload = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        session = state.identity_store.collections.auth_sessions.find({})[-1]
        return f"maverick_session={session['session_id']}"

    def create_completed_thread(self, state):
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            state.runtime_store,
            session_id=str(uuid4()),
            workspace_id="default",
            agent_id="test-agent",
            requested_mode=None,
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=state.repository_root,
        )
        create_runtime_thread(
            state.runtime_store,
            workspace_id="default",
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title="Unread thread",
            now=now,
        )
        turn = queue_runtime_turn(state.runtime_store, turn_id="turn-a", session_id=session.session_id, input_text="hello", now=now)
        transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active", now=now + timedelta(seconds=1))
        transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="completed", now=now + timedelta(seconds=2))
        mark_runtime_thread_response_completed(
            state.runtime_store,
            workspace_id="default",
            runtime_session_id=session.session_id,
            turn_id=turn.turn_id,
            now=now + timedelta(seconds=3),
        )
        return session, now

    async def test_runtime_thread_changed_frame_uses_viewer_read_receipts(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        admin = state.identity_store.get_user_by_username(os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"))
        session, now = self.create_completed_thread(state)

        unread_frame = runtime_thread_changed_frame(
            state,
            workspace_id="default",
            viewer_user_id=admin.user_id,
            event={"action": "updated", "thread_id": session.session_id},
        )

        self.assertTrue(unread_frame["thread"]["has_unread_completed_response"])

        mark_runtime_thread_completed_response_read(
            state.runtime_store,
            thread_id=session.session_id,
            workspace_id="default",
            user_id=admin.user_id,
            now=now + timedelta(seconds=4),
        )
        read_frame = runtime_thread_changed_frame(
            state,
            workspace_id="default",
            viewer_user_id=admin.user_id,
            event={"action": "updated", "thread_id": session.session_id},
        )
        other_user_frame = runtime_thread_changed_frame(
            state,
            workspace_id="default",
            viewer_user_id="other-user",
            event={"action": "updated", "thread_id": session.session_id},
        )

        self.assertFalse(read_frame["thread"]["has_unread_completed_response"])
        self.assertTrue(other_user_frame["thread"]["has_unread_completed_response"])

    async def test_runtime_thread_read_endpoint_marks_completed_response_read(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        app = PlatformHost(state, start_path=state.repository_root)
        session, _now = self.create_completed_thread(state)

        status, before = self.invoke(app, path="/api/runtime/threads", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(before["threads"][0]["has_unread_completed_response"])

        status, after = self.invoke(
            app,
            path=f"/api/runtime/threads/{session.session_id}/read",
            method="POST",
            body={},
            cookie=cookie,
        )

        self.assertEqual(status, 200)
        self.assertFalse(after["thread"]["has_unread_completed_response"])
        self.assertFalse(after["threads"][0]["has_unread_completed_response"])
