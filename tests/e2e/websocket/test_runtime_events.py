"""Tests for the runtime WebSocket host surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
import asyncio, json, os, tempfile, unittest
from uuid import uuid4

from core.api.app_events import APP_EVENTS_WS_PATH, AppEventBus, stream_app_events
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_thread_websocket import runtime_thread_snapshot_frame, stream_runtime_thread_events
from core.api.runtime_websocket import WEBSOCKET_NOT_FOUND, WEBSOCKET_UNAUTHORIZED, initial_runtime_event_page, stream_runtime_session_events
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session, record_runtime_event, transition_runtime_session
from core.runtime.store import RuntimeEventPage
from core.shared.entrypoints import EntrypointShutdownController
from tests.support.markers import slow_test_class


@slow_test_class("slow websocket integration suite; run with scripts/test_suite.py --level slow")
class RuntimeWebSocketTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify runtime WebSocket streams are app-agnostic and workspace-scoped."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None, cookie: str = "") -> tuple[int, dict, dict[str, str]]:
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
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login_cookie(self, state) -> str:
        app = PlatformHost(state, start_path=state.repository_root)
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

    def create_session_with_events(self, state) -> tuple[str, list[str]]:
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

    def insert_corrupt_session(self, state, *, session_id: str = "corrupt-session") -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        repo_root = state.repository_root
        state.runtime_store.collections.sessions.update_one(
            {"session_id": session_id},
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

    async def test_runtime_websocket_streams_ordered_persisted_events(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie)

        self.assertEqual(sent[0]["type"], "websocket.accept")
        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual([event["event_id"] for event in frames[0]["events"]], ["event-1", "event-2", "event-3"])
        self.assertEqual(frames[0]["events"][-1]["event_type"], "runtime.turn.completed")
        self.assertEqual(frames[0]["last_event_id"], "event-3")

    async def test_runtime_websocket_replays_after_last_seen_event_id(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie, query_string=b"last_event_id=event-1")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual([event["event_id"] for event in frames[0]["events"]], ["event-2", "event-3"])
        self.assertEqual(frames[0]["last_event_id"], "event-3")

    async def test_runtime_websocket_rehydrates_tail_when_cursor_is_current(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie, query_string=b"last_event_id=event-3")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual([event["event_id"] for event in frames[0]["events"]], ["event-1", "event-2", "event-3"])
        self.assertEqual(frames[0]["last_event_id"], "event-3")

    async def test_runtime_websocket_initial_snapshot_is_bounded(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie, query_string=b"initial_event_limit=2")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual([event["event_id"] for event in frames[0]["events"]], ["event-2", "event-3"])
        self.assertEqual(frames[0]["oldest_event_id"], "event-2")
        self.assertTrue(frames[0]["has_more_before"])

    async def test_runtime_websocket_initial_snapshot_includes_turn_metadata_for_cut_tail(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)
        created_at = datetime(2026, 4, 19, 9, 59, 59, tzinfo=UTC)
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-1",
                session_id=session_id,
                workspace_id="default",
                status="completed",
                input_text="important user request",
                created_at=created_at,
                updated_at=created_at + timedelta(seconds=1),
                started_at=created_at + timedelta(milliseconds=500),
                completed_at=created_at + timedelta(seconds=1),
                failure_reason=None,
            )
        )

        sent = await self.collect_websocket_messages(state, session_id=session_id, cookie=cookie, query_string=b"initial_event_limit=2")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual([event["event_id"] for event in frames[0]["events"]], ["event-2", "event-3"])
        self.assertEqual([turn["turn_id"] for turn in frames[0]["turns"]], ["turn-1"])
        self.assertEqual(frames[0]["turns"][0]["input_text"], "important user request")

    async def test_runtime_websocket_initial_snapshot_compacts_replay_only_payloads(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
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
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        record_runtime_event(
            state.runtime_store,
            event_id="event-step",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.step.updated",
            payload={"label": "turn diff updated", "raw": "x" * 20000},
            now=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        )
        record_runtime_event(
            state.runtime_store,
            event_id="event-tool",
            session_id=session.session_id,
            turn_id="turn-1",
            process_id=None,
            plane="turn",
            event_type="runtime.tool_call.completed",
            payload={"name": "command", "stdout": "y" * 20000, "summary": "done"},
            now=datetime(2026, 4, 19, 10, 0, 1, tzinfo=UTC),
        )

        sent = await self.collect_websocket_messages(state, session_id=session.session_id, cookie=cookie)

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        events = {event["event_id"]: event for event in frames[0]["events"]}
        self.assertNotIn("raw", events["event-step"]["payload"])
        self.assertEqual(len(events["event-tool"]["payload"]["stdout"]), 8000)
        self.assertTrue(events["event-tool"]["payload"]["stdout_truncated"])
        self.assertEqual(events["event-tool"]["payload"]["stdout_original_chars"], 20000)

    async def test_runtime_websocket_initial_snapshot_uses_bounded_event_page_not_recovery_tail(self) -> None:
        event = RuntimeEventRecord(
            event_id="event-2",
            workspace_id="default",
            session_id="session-1",
            plane="turn",
            event_type="runtime.output.delta",
            turn_id="turn-1",
            process_id=None,
            payload={"text": "hello"},
            created_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        )

        class _RuntimeStore:
            def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
                raise AssertionError("initial snapshots must not use recovery-skipping recent event reads")

            def list_turns(self, session_id: str):
                return []

            def has_events_before(self, session_id: str, *, before_event_id: str | None) -> bool:
                raise AssertionError("bounded event pages already report older-history availability")

            def list_event_page(self, session_id: str, *, before_event_id: str | None = None, limit: int = 200):
                return RuntimeEventPage(
                    events=[event],
                    has_more_before=True,
                    before_event_id=before_event_id,
                    oldest_event_id=event.event_id,
                    newest_event_id=event.event_id,
                )

        page = initial_runtime_event_page(
            type("State", (), {"runtime_store": _RuntimeStore()})(),
            "session-1",
            last_event_id=None,
            limit=2,
        )

        self.assertEqual([item.event_id for item in page.events], ["event-2"])
        self.assertTrue(page.has_more_before)

    async def test_runtime_websocket_serves_older_history_page(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)
        sent: list[dict] = []
        received = [
            {"type": "websocket.connect"},
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "runtime.history.before", "before_event_id": "event-2", "limit": 2}),
            },
            {"type": "websocket.disconnect"},
        ]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session_id}",
                "query_string": b"initial_event_limit=2",
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        history_frames = [frame for frame in frames if frame["type"] == "runtime.history.page"]
        self.assertEqual(len(history_frames), 1)
        self.assertEqual([event["event_id"] for event in history_frames[0]["events"]], ["event-1"])
        self.assertFalse(history_frames[0]["has_more_before"])

    async def test_runtime_websocket_history_page_with_unknown_cursor_is_empty(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        session_id, _event_ids = self.create_session_with_events(state)
        sent: list[dict] = []
        received = [
            {"type": "websocket.connect"},
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "runtime.history.before", "before_event_id": "missing-event", "limit": 2}),
            },
            {"type": "websocket.disconnect"},
        ]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session_id}",
                "query_string": b"initial_event_limit=2",
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        history_frames = [frame for frame in frames if frame["type"] == "runtime.history.page"]
        self.assertEqual(len(history_frames), 1)
        self.assertEqual(history_frames[0]["events"], [])
        self.assertFalse(history_frames[0]["has_more_before"])

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

    async def test_runtime_websocket_closes_for_invalid_session_visibility(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        self.insert_corrupt_session(state)

        sent = await self.collect_websocket_messages(state, session_id="corrupt-session", cookie=cookie)

        self.assertEqual(sent, [{"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND}])

    async def test_runtime_websocket_sends_transport_heartbeat_without_runtime_event(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
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
        self.assertEqual(frames[0]["type"], "runtime.snapshot")
        self.assertEqual(frames[0]["session"]["session_id"], session.session_id)
        self.assertEqual(frames[0]["events"], [])
        self.assertIsNone(frames[0]["last_event_id"])
        self.assertEqual(state.runtime_store.list_events(session.session_id), [])

    async def test_runtime_websocket_pushes_live_events_without_replay_polling(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
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

    async def test_runtime_thread_websocket_sends_initial_thread_snapshot(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
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
        sent: list[dict] = []
        received = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_thread_events(
            state=state,
            scope={
                "type": "websocket",
                "path": "/ws/runtime/threads",
                "query_string": b"",
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "runtime.thread.snapshot")
        self.assertEqual([thread["runtime_session_id"] for thread in frames[0]["threads"]], [session.session_id])

    async def test_runtime_thread_websocket_snapshot_reconciles_stale_thread_availability(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
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
        started_at = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        completed_at = started_at + timedelta(seconds=2)
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-completed",
                session_id=session.session_id,
                workspace_id="default",
                status="completed",
                input_text="done",
                created_at=started_at,
                updated_at=completed_at,
                started_at=started_at + timedelta(milliseconds=100),
                completed_at=completed_at,
                failure_reason=None,
            )
        )
        state.runtime_store.save_thread(
            RuntimeThreadRecord(
                thread_id="thread-stale",
                workspace_id="default",
                runtime_session_id=session.session_id,
                title="Stale thread",
                agent_label="test-agent",
                agent_type_id="",
                agent_role_id="",
                source_app_id="test-agent",
                system_prompt="",
                project_id=None,
                archived=False,
                availability="active",
                created_at=started_at,
                updated_at=started_at,
            )
        )

        frame = runtime_thread_snapshot_frame(state, workspace_id="default", viewer_user_id=None)

        thread = next(item for item in frame["threads"] if item["runtime_session_id"] == session.session_id)
        self.assertEqual(thread["availability"], "free")
        self.assertEqual(thread["last_completed_turn_id"], "turn-completed")
        self.assertEqual(state.runtime_store.get_thread("thread-stale").availability, "free")

    async def test_runtime_thread_websocket_pushes_live_thread_changes(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
        app = PlatformHost(state, start_path=state.repository_root)
        sent: list[dict] = []
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})

        async def receive() -> dict:
            return await receive_queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        stream_task = asyncio.create_task(
            stream_runtime_thread_events(
                state=state,
                scope={
                    "type": "websocket",
                    "path": "/ws/runtime/threads",
                    "query_string": b"",
                    "headers": [(b"cookie", cookie.encode("latin1"))],
                },
                receive=receive,
                send=send,
            )
        )
        while not any(message.get("type") == "websocket.accept" for message in sent):
            await asyncio.sleep(0)

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
        status, payload, _headers = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": session.session_id, "title": "Live thread"},
            cookie=cookie,
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["thread"]["runtime_session_id"], session.session_id)

        while not any("runtime.thread.changed" in message.get("text", "") for message in sent):
            await asyncio.sleep(0)
        await receive_queue.put({"type": "websocket.disconnect"})
        await stream_task

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        changed = [frame for frame in frames if frame["type"] == "runtime.thread.changed"]
        self.assertEqual(changed[-1]["action"], "created")
        self.assertEqual(changed[-1]["thread"]["runtime_session_id"], session.session_id)

    async def test_app_event_websocket_pushes_data_changes_without_polling(self) -> None:
        bus = AppEventBus()
        sent: list[dict] = []
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})

        async def receive() -> dict:
            return await receive_queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        stream_task = asyncio.create_task(
            stream_app_events(
                bus=bus,
                scope={"type": "websocket", "path": APP_EVENTS_WS_PATH},
                receive=receive,
                send=send,
            )
        )
        while not any(message.get("type") == "websocket.accept" for message in sent):
            await asyncio.sleep(0)

        bus.publish({"type": "maverick.app.data-changed", "owner_app_id": "sample-app", "resource": "records"})
        while not any("maverick.app.data-changed" in message.get("text", "") for message in sent):
            await asyncio.sleep(0)
        await receive_queue.put({"type": "websocket.disconnect"})
        await stream_task

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames, [{"type": "maverick.app.data-changed", "owner_app_id": "sample-app", "resource": "records"}])

    async def test_runtime_websocket_exits_when_host_shutdown_begins(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        cookie = self.login_cookie(state)
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
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        controller = EntrypointShutdownController()
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
                shutdown_controller=controller,
            )
        )
        while not any(message.get("type") == "websocket.accept" for message in sent):
            await asyncio.sleep(0)

        controller.begin_shutdown()
        await asyncio.wait_for(stream_task, timeout=2.0)

    async def test_app_event_websocket_exits_when_host_shutdown_begins(self) -> None:
        bus = AppEventBus()
        controller = EntrypointShutdownController()
        sent: list[dict] = []
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})

        async def receive() -> dict:
            return await receive_queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        stream_task = asyncio.create_task(
            stream_app_events(
                bus=bus,
                scope={"type": "websocket", "path": APP_EVENTS_WS_PATH},
                receive=receive,
                send=send,
                shutdown_controller=controller,
            )
        )
        while not any(message.get("type") == "websocket.accept" for message in sent):
            await asyncio.sleep(0)

        controller.begin_shutdown()
        await asyncio.wait_for(stream_task, timeout=2.0)


if __name__ == "__main__":
    unittest.main()
