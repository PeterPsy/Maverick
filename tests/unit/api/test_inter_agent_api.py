from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.inter_agent.errors import InterAgentRunNotFoundError
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


def _run_payload(*, run_id: str = "run-api-1") -> dict:
    return {
        "run_id": run_id,
        "thread_id": "root-session",
        "root_runtime_session_id": "root-session",
        "source_app_id": "chat",
        "mode": "manager_tools",
        "idempotency_key": run_id,
        "participants": [
            {
                "participant_id": "orchestrator",
                "kind": "orchestrator",
                "execution_mode": "root_orchestrator",
                "label": "Orchestrator",
            },
            {
                "participant_id": "researcher",
                "kind": "agent",
                "execution_mode": "child_runtime_session",
                "label": "Researcher",
                "agent_type_id": "research-agent",
                "agent_snapshot": {
                    "agent_type_id": "research-agent",
                    "label": "Researcher",
                    "system_prompt": "Research only.",
                    "skill_ids": ["storage"],
                    "skill_catalog_app_id": "skills",
                },
            },
        ],
        "budget": {
            "max_participants": 3,
            "max_concurrent_participants": 2,
            "max_total_turns": 4,
            "max_turns_per_participant": 2,
        },
    }


def _run_payload_without_snapshot(*, run_id: str = "run-api-1") -> dict:
    payload = _run_payload(run_id=run_id)
    payload["participants"][1].pop("agent_snapshot", None)
    return payload


class InterAgentApiSupport(AppReferenceApiTestSupport, unittest.TestCase):
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
            system_prompt="Parent prompt must not leak.",
            skill_ids=["parent-skill"],
            owner_user_id="parent-owner",
            grants=[
                RuntimeSessionGrantRecord(
                    operation="cleanup",
                    grantee_kind="user",
                    grantee_id="parent-owner",
                    issued_by_user_id="parent-owner",
                )
            ],
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )


class InterAgentApiTestCase(InterAgentApiSupport):
    def test_inter_agent_http_spawn_send_wait_and_close_hidden_child_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(),
                cookie=cookie,
            )
            spawn_status, spawn_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-1/participants",
                method="POST",
                body={
                    "participant_id": "researcher",
                    "child_session_id": "child-api-1",
                    "system_prompt": "payload prompt must not apply",
                    "skill_ids": ["storage"],
                    "skill_catalog_app_id": "skills",
                    "source_app_id": "spoofed-app",
                    "grants": [
                        {
                            "source": "platform",
                            "operation": "cleanup",
                            "grantee_kind": "user",
                            "grantee_id": "attacker",
                        }
                    ],
                },
                cookie=cookie,
            )
            runtime_list_status, runtime_list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                cookie=cookie,
            )
            child_route_status, child_route_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/child-api-1",
                cookie=cookie,
            )
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
            turn = RuntimeTurnRecord(
                turn_id="turn-api-1",
                session_id="child-api-1",
                workspace_id="default",
                status="completed",
                input_text="hello child",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
                failure_reason=None,
            )
            event = RuntimeEventRecord(
                event_id="event-api-1",
                workspace_id="default",
                session_id="child-api-1",
                plane="turn",
                event_type="runtime.turn.completed",
                turn_id="turn-api-1",
                process_id=None,
                payload={},
                created_at=now,
            )
            with patch("core.inter_agent.service.submit_runtime_turn", return_value=(turn, [event])):
                send_status, send_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-api-1/messages",
                    method="POST",
                    body={"participant_id": "researcher", "input_text": "hello child"},
                    cookie=cookie,
                )
            wait_status, wait_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-1/wait",
                method="POST",
                body={"timeout_seconds": 0},
                cookie=cookie,
            )
            close_status, close_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-1/close",
                method="POST",
                body={"reason": "test-close"},
                cookie=cookie,
            )
            root_session_id = state.runtime_store.get_session("root-session").session_id
            child_deleted = False
            try:
                state.runtime_store.get_session("child-api-1")
            except RuntimeSessionNotFoundError:
                child_deleted = True

        child_session = spawn_payload["runtime_session"]
        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["run_id"], "run-api-1")
        self.assertEqual(spawn_status, 201)
        self.assertEqual(child_session["session_kind"], "inter_agent_participant")
        self.assertEqual(child_session["thread_visibility"], "hidden")
        self.assertEqual(child_session["system_prompt"], None)
        self.assertEqual(child_session["skill_ids"], [])
        self.assertEqual(child_session["skill_catalog_app_id"], None)
        self.assertEqual(child_session["source_app_id"], "chat")
        self.assertEqual(child_session["owner_user_id"], None)
        self.assertEqual(child_session["grants"], [])
        self.assertEqual(runtime_list_status, 200)
        self.assertEqual([item["session_id"] for item in runtime_list_payload["items"]], ["root-session"])
        self.assertEqual(child_route_status, 409)
        self.assertEqual(child_route_payload["error"], "runtime_session_hidden")
        self.assertEqual(send_status, 201)
        self.assertEqual(send_payload["turn"]["turn_id"], "turn-api-1")
        self.assertEqual(wait_status, 200)
        self.assertEqual(wait_payload["run"]["run_id"], "run-api-1")
        self.assertEqual(close_status, 200)
        self.assertEqual(close_payload["run"].get("status"), "cancelled")
        self.assertEqual(close_payload["participant_cleanups"][0]["participant_id"], "researcher")
        self.assertEqual(close_payload["participant_cleanups"][0]["session_id"], "child-api-1")
        self.assertEqual(root_session_id, "root-session")
        self.assertTrue(child_deleted)

    def test_inter_agent_http_execute_runtime_run_keeps_root_transcript_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            def fake_submit(_state, *, session, input_text, client_message_id=None, async_requested=False):
                turn = RuntimeTurnRecord(
                    turn_id="turn-execute-1",
                    session_id=session.session_id,
                    workspace_id="default",
                    status="completed",
                    input_text=input_text,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    completed_at=now,
                    failure_reason=None,
                )
                event = RuntimeEventRecord(
                    event_id="event-execute-final",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.final",
                    turn_id=turn.turn_id,
                    process_id=None,
                    payload={"text": "Rollout is ready."},
                    created_at=now,
                )
                return turn, [event]

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-api-execute"),
                cookie=cookie,
            )
            with patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit):
                execute_status, execute_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-api-execute/execute",
                    method="POST",
                    body={"input_text": "Research the rollout."},
                    cookie=cookie,
                )
            events_status, events_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-execute/events",
                cookie=cookie,
            )
            root_events = state.runtime_store.list_events("root-session")

        event_types = [event["event_type"] for event in events_payload["items"]]
        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["run_id"], "run-api-execute")
        self.assertEqual(execute_status, 200)
        self.assertEqual(execute_payload["run"]["status"], "completed")
        self.assertEqual(execute_payload["final_answer"], "Rollout is ready.")
        self.assertEqual(execute_payload["participant_results"][0]["summary"], "Rollout is ready.")
        self.assertEqual(events_status, 200)
        self.assertIn("inter_agent.plan.summary_created", event_types)
        self.assertIn("inter_agent.run.completed", event_types)
        self.assertEqual(root_events, [])

    def test_inter_agent_http_events_route_returns_404_for_missing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-api-missing-event-cursor"),
                cookie=cookie,
            )
            events_status, events_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-missing-event-cursor/events?after_event_id=missing-event",
                cookie=cookie,
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(events_status, 404)
        self.assertEqual(events_payload["error"], "inter_agent_event_not_found")

    def test_inter_agent_http_execute_rejects_controlled_participants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-api-controlled-forbidden"),
                cookie=cookie,
            )
            execute_status, execute_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-controlled-forbidden/execute",
                method="POST",
                body={"controlled_participants": {"researcher": {"output_text": "synthetic"}}},
                cookie=cookie,
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(execute_status, 403)
        self.assertEqual(execute_payload["error"], "inter_agent_controlled_participants_forbidden")

    def test_inter_agent_http_spawn_rejects_unsafe_child_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="unsafe-child-run"),
                cookie=cookie,
            )
            spawn_status, spawn_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/unsafe-child-run/participants",
                method="POST",
                body={"participant_id": "researcher", "child_session_id": "../escape"},
                cookie=cookie,
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(spawn_status, 400)
        self.assertEqual(spawn_payload["error"], "inter_agent_validation_failed")
        self.assertIn("runtime_session_id_unsafe", spawn_payload["detail"])

    def test_inter_agent_http_rejects_hidden_root_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            create_runtime_session(
                state.runtime_store,
                session_id="root-session",
                workspace_id="default",
                agent_id="hidden-root",
                source_app_id="chat",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
                governance=state.workspace_store.get_governance("default"),
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="hidden-root-run"),
                cookie=cookie,
            )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "root_runtime_session_hidden")

    def test_root_runtime_cleanup_cascades_to_child_session_and_run_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="cleanup-run"),
                cookie=cookie,
            )
            spawn_status, _spawn_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/cleanup-run/participants",
                method="POST",
                body={"participant_id": "researcher", "child_session_id": "cleanup-child"},
                cookie=cookie,
            )
            cleanup_status, cleanup_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/root-session/cleanup",
                method="POST",
                body={"reason": "root-cleanup"},
                cookie=cookie,
            )
            root_deleted = False
            child_deleted = False
            run_deleted = False
            try:
                state.runtime_store.get_session("root-session")
            except RuntimeSessionNotFoundError:
                root_deleted = True
            try:
                state.runtime_store.get_session("cleanup-child")
            except RuntimeSessionNotFoundError:
                child_deleted = True
            try:
                state.inter_agent_store.get_run("cleanup-run", workspace_id="default")
            except InterAgentRunNotFoundError:
                run_deleted = True

        self.assertEqual(create_status, 201)
        self.assertEqual(spawn_status, 201)
        self.assertEqual(cleanup_status, 200)
        self.assertEqual(cleanup_payload["inter_agent_cleanup"][0]["run_id"], "cleanup-run")
        self.assertTrue(root_deleted)
        self.assertTrue(child_deleted)
        self.assertTrue(run_deleted)

if __name__ == "__main__":
    unittest.main()
