from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from core.api.asgi_application import PlatformAsgiHost
from core.api.job_websocket import JOB_EVENTS_WS_PATH, initial_job_event_replay, stream_job_events
from core.api.platform_state import bootstrap_platform_state
from core.jobs.events import JobEventBus
from core.jobs.service import JobService
from tests.unit.jobs.support import FixedClock, make_spec, make_store
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class JobWebSocketTestCase(AppReferenceApiTestSupport, unittest.IsolatedAsyncioTestCase):
    async def test_asgi_websocket_requires_authenticated_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = self._repo_root(temporary_directory)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
            host = PlatformAsgiHost(state)
            sent: list[dict] = []

            async def receive() -> dict:
                return {"type": "websocket.connect"}

            async def send(message: dict) -> None:
                sent.append(message)

            await host(
                {"type": "websocket", "path": JOB_EVENTS_WS_PATH, "headers": [], "query_string": b""},
                receive,
                send,
            )

        self.assertEqual(sent, [{"type": "websocket.close", "code": 4401}])

    async def test_stream_replays_then_emits_only_workspace_live_events(self) -> None:
        bus = JobEventBus()
        service = JobService(make_store(), clock=FixedClock(), event_bus=bus)
        service.register_input_validator("file.content.read", lambda _spec, _grant: True)
        service.submit(make_spec(idempotency_key="replayed"), job_id="job-replayed")
        received: asyncio.Queue[dict] = asyncio.Queue()
        await received.put({"type": "websocket.connect"})
        sent: list[dict] = []

        async def receive() -> dict:
            return await received.get()

        async def send(message: dict) -> None:
            sent.append(message)
            if message.get("type") == "websocket.send":
                frame = json.loads(message["text"])
                if frame.get("type") == "compute.job.event":
                    await received.put({"type": "websocket.disconnect"})

        stream = asyncio.create_task(
            stream_job_events(
                service=service,
                bus=bus,
                scope={"path": JOB_EVENTS_WS_PATH},
                receive=receive,
                send=send,
                workspace_id="workspace-a",
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        service.submit(make_spec(idempotency_key="live"), job_id="job-live")
        service.submit(
            make_spec(workspace_id="workspace-b", idempotency_key="other"),
            job_id="job-other",
        )
        await asyncio.wait_for(stream, timeout=2)

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(sent[0]["type"], "websocket.accept")
        self.assertEqual(frames[0]["type"], "compute.job.snapshot")
        self.assertEqual([item["job_id"] for item in frames[0]["events"]], ["job-replayed"])
        live = [item for item in frames if item["type"] == "compute.job.event"]
        self.assertEqual([item["event"]["job_id"] for item in live], ["job-live"])

    async def test_stream_sends_transport_heartbeat(self) -> None:
        bus = JobEventBus()
        service = JobService(make_store(), clock=FixedClock(), event_bus=bus)
        service.register_input_validator("file.content.read", lambda _spec, _grant: True)
        received: asyncio.Queue[dict] = asyncio.Queue()
        await received.put({"type": "websocket.connect"})
        sent: list[dict] = []
        receive_cancellations = 0

        async def receive() -> dict:
            nonlocal receive_cancellations
            try:
                return await received.get()
            except asyncio.CancelledError:
                receive_cancellations += 1
                raise

        async def send(message: dict) -> None:
            sent.append(message)
            if message.get("type") == "websocket.send":
                frame = json.loads(message["text"])
                if frame.get("type") == "compute.job.heartbeat":
                    await received.put({"type": "websocket.disconnect"})

        await asyncio.wait_for(
            stream_job_events(
                service=service,
                bus=bus,
                scope={"path": JOB_EVENTS_WS_PATH},
                receive=receive,
                send=send,
                workspace_id="workspace-a",
                heartbeat_interval_seconds=0.01,
            ),
            timeout=2,
        )

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertIn("compute.job.heartbeat", [item["type"] for item in frames])
        self.assertEqual(receive_cancellations, 0)

    def test_replay_is_cursor_aware_workspace_scoped_and_bounded(self) -> None:
        clock = FixedClock()
        service = JobService(make_store(), clock=clock)
        service.register_input_validator("file.content.read", lambda _spec, _grant: True)
        for index in range(3):
            service.submit(make_spec(idempotency_key=f"job-{index}"), job_id=f"job-{index}")
            clock.advance(seconds=1)
        service.submit(make_spec(workspace_id="workspace-b", idempotency_key="other"), job_id="other")
        all_events = service.list_workspace_events(workspace_id="workspace-a")

        bounded, cursor_found, truncated = initial_job_event_replay(
            service,
            workspace_id="workspace-a",
            last_event_id=None,
            limit=2,
        )
        after_cursor, after_found, after_truncated = initial_job_event_replay(
            service,
            workspace_id="workspace-a",
            last_event_id=all_events[1].event_id,
            limit=2,
        )

        self.assertEqual([item.job_id for item in bounded], ["job-1", "job-2"])
        self.assertTrue(cursor_found)
        self.assertTrue(truncated)
        self.assertEqual([item.job_id for item in after_cursor], ["job-2"])
        self.assertTrue(after_found)
        self.assertFalse(after_truncated)


if __name__ == "__main__":
    unittest.main()
