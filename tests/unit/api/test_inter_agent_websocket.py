from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
import json
import tempfile
import unittest

from core.api.inter_agent_websocket import _events_after_cursor, stream_inter_agent_run_events
from core.api.platform_host import PlatformHost
from core.inter_agent.models import ApprovalRequestRecord
from core.inter_agent.service import InterAgentService
from tests.unit.api.inter_agent_websocket_test_support import (
    InterAgentWebSocketApiTestSupport,
    _run_spec,
    _wait_for_frame,
    _wait_for_live_event,
)


class InterAgentWebSocketTestCase(InterAgentWebSocketApiTestSupport):

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

    async def test_inter_agent_websocket_returns_empty_history_page_for_missing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            _service, run = self._create_run(state, repo_root, run_id="run-ws-missing-history")
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
                        "query_string": b"visibility_plane=detail&initial_event_limit=50",
                        "headers": [(b"cookie", cookie.encode("latin1"))],
                    },
                    receive=receive,
                    send=send,
                    heartbeat_interval_seconds=10,
                    poll_interval_seconds=0.1,
                )
            )
            await _wait_for_frame(sent, "inter_agent.snapshot")
            await incoming.put(
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {
                            "type": "inter_agent.history.before",
                            "before_event_id": "missing-event",
                            "limit": 50,
                        }
                    ),
                }
            )
            history_frame = await _wait_for_frame(sent, "inter_agent.history.page")
            await incoming.put({"type": "websocket.disconnect"})
            await task

        self.assertEqual(history_frame["events"], [])
        self.assertEqual(history_frame["before_event_id"], "missing-event")
        self.assertFalse(history_frame["has_more_before"])
        self.assertFalse(history_frame["cursor_found"])

    async def test_inter_agent_websocket_ignores_ack_for_undelivered_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            service, run = self._create_run(state, repo_root, run_id="run-ws-ack")
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
            first_live = service.record_event(
                run,
                event_type="inter_agent.summary.updated",
                participant_id="orchestrator",
                visibility_plane="summary",
                payload={"summary": "First undelivered live update"},
                now=datetime(2026, 6, 18, 10, 4, tzinfo=UTC),
            )
            service.record_event(
                run,
                event_type="inter_agent.summary.updated",
                participant_id="orchestrator",
                visibility_plane="summary",
                payload={"summary": "Second live update"},
                now=datetime(2026, 6, 18, 10, 5, tzinfo=UTC),
            )
            await incoming.put(
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "inter_agent.ack", "last_event_id": first_live.event_id}),
                }
            )
            await _wait_for_live_event(sent, first_live.event_id)
            await incoming.put({"type": "websocket.disconnect"})
            await task

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        live_event_ids = [frame["event"]["event_id"] for frame in frames if frame["type"] == "inter_agent.event"]
        self.assertIn(first_live.event_id, live_event_ids)

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

    async def test_inter_agent_artifacts_http_route_pages_artifact_events_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            service, run = self._create_run(state, repo_root, run_id="run-artifacts-tail")
            for index in range(60):
                service.record_event(
                    run,
                    event_type="inter_agent.summary.updated",
                    participant_id="orchestrator",
                    visibility_plane="summary",
                    payload={"summary": f"Later summary {index}"},
                    now=datetime(2026, 6, 18, 10, 4, tzinfo=UTC) + timedelta(minutes=index),
                )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/inter-agent/runs/{run.run_id}/artifacts?visibility_plane=detail&limit=50",
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["label"], "Research report")
        self.assertFalse(payload["has_more_before"])

    async def test_inter_agent_artifacts_http_route_accepts_visible_non_artifact_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            service, run = self._create_run(state, repo_root, run_id="run-artifacts-cursor")
            summary_marker = service.record_event(
                run,
                event_type="inter_agent.summary.updated",
                participant_id="orchestrator",
                visibility_plane="summary",
                payload={"summary": "Cursor marker"},
                now=datetime(2026, 6, 18, 10, 4, tzinfo=UTC),
            )
            service.record_event(
                run,
                event_type="inter_agent.artifact.created",
                participant_id="researcher",
                visibility_plane="detail",
                payload={
                    "artifact_refs": [
                        {
                            "workspace_relative_path": "storage/generated/reports/final.md",
                            "label": "Final report",
                        }
                    ],
                    "status": "created",
                },
                now=datetime(2026, 6, 18, 10, 5, tzinfo=UTC),
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            after_status, after_payload, _headers = self._invoke(
                app,
                path=(
                    f"/api/inter-agent/runs/{run.run_id}/artifacts"
                    f"?visibility_plane=detail&after_event_id={summary_marker.event_id}&limit=50"
                ),
                cookie=cookie,
            )
            before_status, before_payload, _headers = self._invoke(
                app,
                path=(
                    f"/api/inter-agent/runs/{run.run_id}/artifacts"
                    f"?visibility_plane=detail&before_event_id={summary_marker.event_id}&limit=50"
                ),
                cookie=cookie,
            )

        self.assertEqual(after_status, 200)
        self.assertEqual([item["label"] for item in after_payload["items"]], ["Final report"])
        self.assertEqual(before_status, 200)
        self.assertEqual([item["label"] for item in before_payload["items"]], ["Research report"])

    async def test_inter_agent_artifacts_http_route_returns_404_for_missing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            _service, run = self._create_run(state, repo_root, run_id="run-artifacts-missing-cursor")
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/inter-agent/runs/{run.run_id}/artifacts?visibility_plane=detail&after_event_id=missing-event&limit=50",
                cookie=cookie,
            )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "inter_agent_event_not_found")

    async def test_inter_agent_websocket_snapshot_expires_pending_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            _service, run = self._create_run(state, repo_root, run_id="run-ws-expired-approval")
            state.inter_agent_store.save_approval(
                ApprovalRequestRecord(
                    approval_id="approval-expired-ws",
                    workspace_id="default",
                    run_id=run.run_id,
                    participant_id="researcher",
                    requested_by_participant_id="orchestrator",
                    operation_kind="storage.write",
                    resource_refs=[],
                    summary="Write a generated file.",
                    risk_level="medium",
                    status="pending",
                    eligible_approver_user_ids=["user:admin"],
                    eligible_approver_roles=[],
                    expires_at=datetime(2026, 6, 18, 9, 0, tzinfo=UTC),
                )
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            sent = await self._collect_snapshot(
                state,
                run_id=run.run_id,
                cookie=cookie,
                query_string=b"visibility_plane=detail&initial_event_limit=50",
            )
            stored = state.inter_agent_store.get_approval("approval-expired-ws", workspace_id="default")

        frames = [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]
        snapshot = frames[0]
        self.assertEqual(snapshot["type"], "inter_agent.snapshot")
        self.assertEqual(snapshot["approvals"][0]["status"], "expired")
        self.assertEqual(stored.status, "expired")


if __name__ == "__main__":
    unittest.main()
