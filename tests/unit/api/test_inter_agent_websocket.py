from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from core.api.inter_agent_websocket import _events_after_cursor, stream_inter_agent_run_events
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.inter_agent.models import BudgetPolicySpec, InterAgentRunSpec, ParticipantSpec
from core.inter_agent.service import InterAgentService
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


def _run_spec(*, run_id: str = "run-ws-1") -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="manager_tools",
        created_by_user_id="admin",
        run_id=run_id,
        visibility_level="debug",
        participants=[
            ParticipantSpec(
                participant_id="orchestrator",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Orchestrator",
            ),
            ParticipantSpec(
                participant_id="researcher",
                kind="agent",
                execution_mode="embedded_executor",
                label="Researcher",
            ),
        ],
        budget=BudgetPolicySpec(
            max_participants=3,
            max_concurrent_participants=2,
            max_total_turns=4,
            max_turns_per_participant=2,
        ),
        idempotency_key=run_id,
    )


class InterAgentWebSocketTestCase(AppReferenceApiTestSupport, unittest.IsolatedAsyncioTestCase):
    def _bootstrap_state(self, repo_root):
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            return bootstrap_platform_state(start_path=repo_root)

    def _create_root_session(self, state, repo_root) -> None:
        create_runtime_session(
            state.runtime_store,
            session_id="root-session",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )

    def _create_run(self, state, repo_root, *, run_id: str = "run-ws-1"):
        self._create_root_session(state, repo_root)
        service = InterAgentService(state.inter_agent_store)
        run = service.create_run(_run_spec(run_id=run_id), now=datetime(2026, 6, 18, 10, 0, tzinfo=UTC))
        service.record_event(
            run,
            event_type="inter_agent.summary.updated",
            participant_id="orchestrator",
            visibility_plane="summary",
            payload={"summary": "Plan created"},
            now=datetime(2026, 6, 18, 10, 1, tzinfo=UTC),
        )
        service.record_event(
            run,
            event_type="inter_agent.artifact.created",
            participant_id="researcher",
            visibility_plane="detail",
            payload={
                "artifact_refs": [
                    {
                        "workspace_relative_path": "storage/generated/reports/research.md",
                        "label": "Research report",
                    }
                ],
                "partial_output": "Draft report",
                "status": "partial",
            },
            now=datetime(2026, 6, 18, 10, 2, tzinfo=UTC),
        )
        service.record_event(
            run,
            event_type="inter_agent.summary.updated",
            participant_id="orchestrator",
            visibility_plane="debug",
            payload={"summary": "Debug trace"},
            now=datetime(2026, 6, 18, 10, 3, tzinfo=UTC),
        )
        return service, run

    async def _collect_snapshot(self, state, *, run_id: str, cookie: str, query_string: bytes = b"") -> list[dict]:
        sent: list[dict] = []
        received = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_inter_agent_run_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/inter-agent/runs/{run_id}",
                "query_string": query_string,
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )
        return sent

    async def test_inter_agent_websocket_snapshot_filters_visibility_and_projects_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            _service, run = self._create_run(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            sent = await self._collect_snapshot(
                state,
                run_id=run.run_id,
                cookie=cookie,
                query_string=b"visibility_plane=detail&initial_event_limit=50",
            )

        self.assertEqual(sent[0]["type"], "websocket.accept")
        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual(frames[0]["type"], "inter_agent.snapshot")
        self.assertEqual(frames[0]["visibility_plane"], "detail")
        self.assertIn("Plan created", json.dumps(frames[0]["events"]))
        self.assertIn("Research report", json.dumps(frames[0]["artifacts"]))
        self.assertNotIn("Debug trace", json.dumps(frames[0]["events"]))
        self.assertEqual(frames[0]["artifacts"][0]["workspace_relative_path"], "storage/generated/reports/research.md")

    async def test_inter_agent_websocket_streams_events_written_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            service, run = self._create_run(state, repo_root, run_id="run-ws-live")
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            sent: list[dict] = []
            incoming: asyncio.Queue[dict] = asyncio.Queue()
            await incoming.put({"type": "websocket.connect"})

            async def receive() -> dict:
                return await incoming.get()

            async def send(message: dict) -> None:
                sent.append(message)

            task = asyncio.create_task(
                stream_inter_agent_run_events(
                    state=state,
                    scope={
                        "type": "websocket",
                        "path": f"/ws/inter-agent/runs/{run.run_id}",
                        "query_string": b"visibility_plane=summary&initial_event_limit=50",
                        "headers": [(b"cookie", cookie.encode("latin1"))],
                    },
                    receive=receive,
                    send=send,
                    heartbeat_interval_seconds=10,
                    poll_interval_seconds=0.1,
                )
            )
            await _wait_for_frame(sent, "inter_agent.snapshot")
            service.record_event(
                run,
                event_type="inter_agent.summary.updated",
                participant_id="orchestrator",
                visibility_plane="summary",
                payload={"summary": "Live update"},
                now=datetime(2026, 6, 18, 10, 4, tzinfo=UTC),
            )
            await _wait_for_frame(sent, "inter_agent.event")
            await incoming.put({"type": "websocket.disconnect"})
            await task

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        live_frames = [frame for frame in frames if frame["type"] == "inter_agent.event"]
        self.assertTrue(any(frame["event"]["payload"].get("summary") == "Live update" for frame in live_frames))

    def test_inter_agent_event_polling_without_cursor_returns_bounded_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            service = InterAgentService(state.inter_agent_store)
            run = service.create_run(_run_spec(run_id="run-ws-empty"), now=datetime(2026, 6, 18, 10, 0, tzinfo=UTC))
            service.record_event(
                run,
                event_type="inter_agent.summary.updated",
                participant_id="orchestrator",
                visibility_plane="summary",
                payload={"summary": "First live update"},
                now=datetime(2026, 6, 18, 10, 1, tzinfo=UTC),
            )
            events = _events_after_cursor(
                state,
                run,
                visibility_plane="summary",
                last_event_id=None,
                limit=50,
            )

        self.assertTrue(any(event.payload.get("summary") == "First live update" for event in events))

    async def test_inter_agent_artifacts_http_route_uses_event_visibility_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            _service, run = self._create_run(state, repo_root, run_id="run-artifacts")
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/inter-agent/runs/{run.run_id}/artifacts?visibility_plane=detail&limit=50",
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["label"], "Research report")
        self.assertEqual(payload["items"][0]["status"], "partial")


async def _wait_for_frame(sent: list[dict], frame_type: str) -> dict:
    deadline = datetime.now(tz=UTC) + timedelta(seconds=3)
    while datetime.now(tz=UTC) < deadline:
        for message in sent:
            if message.get("type") != "websocket.send":
                continue
            frame = json.loads(message["text"])
            if frame.get("type") == frame_type:
                return frame
        await asyncio.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {frame_type}")


if __name__ == "__main__":
    unittest.main()
