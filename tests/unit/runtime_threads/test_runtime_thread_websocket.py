"""Unit coverage for runtime thread WebSocket catalog snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_thread_websocket import (
    encode_thread_websocket_frame,
    runtime_thread_snapshot_frame,
    stream_runtime_thread_events,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class RuntimeThreadWebSocketFrameTest(unittest.TestCase):
    def make_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def test_snapshot_uses_stored_thread_facts_without_scanning_turns(self) -> None:
        store = self.make_store()
        state = SimpleNamespace(runtime_store=store)
        started_at = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        completed_at = started_at + timedelta(seconds=2)
        store.save_session(
            RuntimeSessionRecord(
                session_id="session-1",
                workspace_id="default",
                agent_id="test-agent",
                status="running",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root="/workspace",
                workdir="/workspace",
                runtime_root="/workspace/.maverick/runtime/session-1",
                started_at=started_at,
                updated_at=started_at,
                ended_at=None,
                last_progress_at=started_at,
            )
        )
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-completed",
                session_id="session-1",
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
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="thread-stale",
                workspace_id="default",
                runtime_session_id="session-1",
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

        def fail_list_turns(_session_id: str):
            raise AssertionError("catalog snapshots must not scan runtime turns")

        store.list_turns = fail_list_turns  # type: ignore[method-assign]

        frame = runtime_thread_snapshot_frame(state, workspace_id="default", viewer_user_id=None)

        self.assertEqual(frame["threads"][0]["availability"], "active")
        self.assertNotIn("last_completed_turn_id", frame["threads"][0])
        self.assertNotIn("system_prompt", frame["threads"][0])
        self.assertEqual(store.get_thread("thread-stale").availability, "active")
        self.assertIsNone(store.get_thread("thread-stale").last_completed_turn_id)

    def test_snapshot_covers_complete_thread_catalog_with_summary_payload(self) -> None:
        store = self.make_store()
        state = SimpleNamespace(runtime_store=store)
        started_at = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        long_system_prompt = "Private prompt " + ("x" * 4000)
        for index in range(275):
            updated_at = started_at + timedelta(minutes=index)
            store.save_session(
                RuntimeSessionRecord(
                    session_id=f"session-{index:02d}",
                    workspace_id="default",
                    agent_id="test-agent",
                    status="running",
                    requested_mode=None,
                    effective_mode="sandbox",
                    workspace_root="/workspace",
                    workdir="/workspace",
                    runtime_root=f"/workspace/.maverick/runtime/session-{index:02d}",
                    started_at=started_at,
                    updated_at=updated_at,
                    ended_at=None,
                    last_progress_at=updated_at,
                    system_prompt=long_system_prompt,
                )
            )
            store.save_thread(
                RuntimeThreadRecord(
                    thread_id=f"thread-{index:03d}",
                    workspace_id="default",
                    runtime_session_id=f"session-{index:02d}",
                    title=f"Thread {index:03d}",
                    agent_label="test-agent",
                    agent_type_id="",
                    agent_role_id="",
                    source_app_id="test-agent",
                    system_prompt=long_system_prompt,
                    project_id=None,
                    archived=False,
                    availability="free",
                    created_at=started_at,
                    updated_at=updated_at,
                )
            )

        frame = runtime_thread_snapshot_frame(state, workspace_id="default", viewer_user_id=None)
        encoded = encode_thread_websocket_frame(frame)

        self.assertEqual(len(frame["threads"]), 275)
        self.assertNotIn("items", frame["threads_page"])
        self.assertEqual(frame["threads_page"]["limit"], 275)
        self.assertFalse(frame["threads_page"]["has_more"])
        self.assertIsNone(frame["threads_page"]["cursor"])
        self.assertEqual(frame["threads_page"]["sort"], "recency_desc")
        self.assertEqual(frame["threads_page"]["total"], 275)
        self.assertTrue(all("system_prompt" not in thread for thread in frame["threads"]))
        self.assertTrue(all("provider_id" not in thread for thread in frame["threads"]))
        self.assertTrue(all("title_generation_input_hash" not in thread for thread in frame["threads"]))
        self.assertNotIn(long_system_prompt, encoded)


class RuntimeThreadWebSocketSchedulingTest(unittest.IsolatedAsyncioTestCase):
    def make_state(self) -> SimpleNamespace:
        return SimpleNamespace(runtime_thread_event_bus=RuntimeThreadEventBus())

    def request_context(self) -> SimpleNamespace:
        return SimpleNamespace(
            workspace_id="default",
            user=SimpleNamespace(user_id="user-a"),
        )

    async def test_snapshot_projection_does_not_block_the_asgi_event_loop(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        fallback_release = threading.Timer(0.5, release.set)
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})
        sent: list[dict] = []

        def blocking_snapshot(*_args, **_kwargs) -> dict:
            entered.set()
            release.wait(timeout=1)
            return {
                "type": "runtime.thread.snapshot",
                "workspace_id": "default",
                "threads": [],
            }

        async def receive() -> dict:
            return await receive_queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        fallback_release.start()
        try:
            with (
                patch("core.api.runtime_thread_websocket.resolve_request_session", return_value=self.request_context()),
                patch("core.api.runtime_thread_websocket.runtime_thread_snapshot_frame", side_effect=blocking_snapshot),
            ):
                stream_task = asyncio.create_task(
                    stream_runtime_thread_events(
                        state=self.make_state(),
                        scope={"type": "websocket", "path": "/ws/runtime/threads", "headers": []},
                        receive=receive,
                        send=send,
                    )
                )
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                event_loop_resumed_before_fallback = not release.is_set()
                release.set()
                await receive_queue.put({"type": "websocket.disconnect"})
                await asyncio.wait_for(stream_task, timeout=1)
        finally:
            release.set()
            fallback_release.cancel()

        self.assertTrue(event_loop_resumed_before_fallback)
        self.assertTrue(any(message.get("type") == "websocket.accept" for message in sent))

    async def test_heartbeat_does_not_cancel_the_pending_client_receive(self) -> None:
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})
        heartbeat_sent = asyncio.Event()
        receive_cancellations = 0

        async def receive() -> dict:
            nonlocal receive_cancellations
            try:
                return await receive_queue.get()
            except asyncio.CancelledError:
                receive_cancellations += 1
                raise

        async def send(message: dict) -> None:
            if "runtime.thread.heartbeat" in str(message.get("text") or ""):
                heartbeat_sent.set()

        snapshot = {
            "type": "runtime.thread.snapshot",
            "workspace_id": "default",
            "threads": [],
        }
        with (
            patch("core.api.runtime_thread_websocket.resolve_request_session", return_value=self.request_context()),
            patch("core.api.runtime_thread_websocket.runtime_thread_snapshot_frame", return_value=snapshot),
        ):
            stream_task = asyncio.create_task(
                stream_runtime_thread_events(
                    state=self.make_state(),
                    scope={"type": "websocket", "path": "/ws/runtime/threads", "headers": []},
                    receive=receive,
                    send=send,
                    heartbeat_interval_seconds=0.01,
                )
            )
            await asyncio.wait_for(heartbeat_sent.wait(), timeout=1)
            cancellations_before_disconnect = receive_cancellations
            await receive_queue.put({"type": "websocket.disconnect"})
            await asyncio.wait_for(stream_task, timeout=1)

        self.assertEqual(cancellations_before_disconnect, 0)


if __name__ == "__main__":
    unittest.main()
