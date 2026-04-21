"""Tests for the runtime WebSocket host surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from uuid import uuid4

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_websocket import WEBSOCKET_UNAUTHORIZED, stream_runtime_session_events
from core.runtime.service import create_runtime_session, record_runtime_event, transition_runtime_session


class RuntimeWebSocketTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify runtime WebSocket streams are app-agnostic and workspace-scoped."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
        shutil.copytree(source_apps_root / "base-shell", repo_root / "apps" / "base-shell", ignore=shutil.ignore_patterns("node_modules"))
        shutil.copytree(source_apps_root / "chat", repo_root / "apps" / "chat", ignore=shutil.ignore_patterns("node_modules"))
        shutil.copytree(source_apps_root / "agents", repo_root / "apps" / "agents", ignore=shutil.ignore_patterns("node_modules"))
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict, dict[str, str]]:
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
                "username": os.environ.get("MAVERICK3_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK3_ADMIN_PASSWORD", "maverick3"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def create_session_with_events(self, state) -> tuple[str, list[str]]:
        session = create_runtime_session(
            state.runtime_store,
            session_id=str(uuid4()),
            workspace_id="default",
            agent_id="chat",
            requested_mode=None,
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=state.repository_root,
        )
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        first = record_runtime_event(
            state.runtime_store,
            event_id="event-1",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.turn.started",
            payload={},
            now=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        )
        second = record_runtime_event(
            state.runtime_store,
            event_id="event-2",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.output.delta",
            payload={"text": "hello"},
            now=first.created_at + timedelta(milliseconds=1),
        )
        third = record_runtime_event(
            state.runtime_store,
            event_id="event-3",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.turn.completed",
            payload={},
            now=second.created_at + timedelta(milliseconds=1),
        )
        return session.session_id, [first.event_id, second.event_id, third.event_id]

    async def collect_websocket_messages(self, state, *, session_id: str, cookie: str, query_string: bytes = b"") -> list[dict]:
        sent: list[dict] = []
        received = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session_id}",
                "query_string": query_string,
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )
        return sent

    async def test_runtime_websocket_streams_ordered_persisted_events(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie)

        self.assertEqual(sent[0]["type"], "websocket.accept")
        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        event_frames = [frame for frame in frames if frame["type"] == "runtime.event"]
        self.assertEqual([frame["event"]["event_id"] for frame in event_frames], ["event-1", "event-2", "event-3"])
        self.assertEqual(event_frames[-1]["event"]["event_type"], "runtime.turn.completed")
        self.assertEqual(frames[-1]["type"], "runtime.replay_complete")
        self.assertEqual(frames[-1]["last_event_id"], "event-3")

    async def test_runtime_websocket_replays_after_last_seen_event_id(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie, query_string=b"last_event_id=event-1")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        event_frames = [frame for frame in frames if frame["type"] == "runtime.event"]
        self.assertEqual([frame["event"]["event_id"] for frame in event_frames], ["event-2", "event-3"])

    async def test_runtime_websocket_rejects_unauthenticated_clients(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        session_id, _event_ids = self.create_session_with_events(state)
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "websocket.connect"}

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session_id}",
                "query_string": b"",
                "headers": [],
            },
            receive=receive,
            send=send,
        )

        self.assertEqual(sent, [{"type": "websocket.close", "code": WEBSOCKET_UNAUTHORIZED}])

    async def test_runtime_websocket_sends_transport_heartbeat_without_runtime_event(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session = create_runtime_session(
            state.runtime_store,
            session_id=str(uuid4()),
            workspace_id="default",
            agent_id="chat",
            requested_mode=None,
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=state.repository_root,
        )
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        sent: list[dict] = []
        received = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session.session_id}",
                "query_string": b"",
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
            heartbeat_interval_seconds=0,
        )

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.heartbeat")
        self.assertEqual(state.runtime_store.list_events(session.session_id), [])

    async def test_runtime_websocket_pushes_live_events_without_replay_polling(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session = create_runtime_session(
            state.runtime_store,
            session_id=str(uuid4()),
            workspace_id="default",
            agent_id="chat",
            requested_mode=None,
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=state.repository_root,
        )
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        sent: list[dict] = []
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})

        async def receive() -> dict:
            return await receive_queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        stream_task = asyncio.create_task(
            stream_runtime_session_events(
                state=state,
                scope={
                    "type": "websocket",
                    "path": f"/ws/runtime/sessions/{session.session_id}",
                    "query_string": b"",
                    "headers": [(b"cookie", cookie.encode("latin1"))],
                },
                receive=receive,
                send=send,
            )
        )
        while not any(message.get("type") == "websocket.accept" for message in sent):
            await asyncio.sleep(0)

        record_runtime_event(
            state.runtime_store,
            event_id="live-event-1",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.output.delta",
            payload={"text": "live"},
            event_bus=state.runtime_event_bus,
        )
        while not any("live-event-1" in message.get("text", "") for message in sent):
            await asyncio.sleep(0)
        await receive_queue.put({"type": "websocket.disconnect"})
        await stream_task

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        event_frames = [frame for frame in frames if frame["type"] == "runtime.event"]
        self.assertEqual([frame["event"]["event_id"] for frame in event_frames], ["live-event-1"])


if __name__ == "__main__":
    unittest.main()
