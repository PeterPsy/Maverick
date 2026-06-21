from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
import json
import unittest
from unittest.mock import patch

from core.api.inter_agent_websocket import stream_inter_agent_run_events
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


class InterAgentWebSocketApiTestSupport(AppReferenceApiTestSupport, unittest.IsolatedAsyncioTestCase):
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


async def _wait_for_live_event(sent: list[dict], event_id: str) -> dict:
    deadline = datetime.now(tz=UTC) + timedelta(seconds=3)
    while datetime.now(tz=UTC) < deadline:
        for message in sent:
            if message.get("type") != "websocket.send":
                continue
            frame = json.loads(message["text"])
            if frame.get("type") == "inter_agent.event" and frame.get("event", {}).get("event_id") == event_id:
                return frame
        await asyncio.sleep(0.02)
    raise AssertionError(f"Timed out waiting for live event {event_id}")
