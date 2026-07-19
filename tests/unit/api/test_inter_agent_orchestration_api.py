from __future__ import annotations

from datetime import UTC, datetime
import tempfile
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.test_inter_agent_api import InterAgentApiSupport


class InterAgentOrchestrationApiTest(InterAgentApiSupport):
    def test_chat_intent_creates_only_hidden_orchestrator_and_accepts_steering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
            state.runtime_store.save_turn(
                RuntimeTurnRecord(
                    turn_id="generalist-turn-1",
                    session_id="root-session",
                    workspace_id="default",
                    status="queued",
                    input_text="Implement the redesign.",
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                )
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            request_body = {
                "root_runtime_session_id": "root-session",
                "source_runtime_turn_id": "generalist-turn-1",
                "policy": "multi",
                "idempotency_key": "chat-orchestration-1",
            }
            with patch("core.api.inter_agent_api._start_orchestrated_execution_worker") as start_worker:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/orchestrations",
                    method="POST",
                    body=request_body,
                    cookie=cookie,
                )
                retry_status, retry_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/orchestrations",
                    method="POST",
                    body=request_body,
                    cookie=cookie,
                )

            run_id = payload["run"]["run_id"]
            directive_status, directive_payload, _headers = self._invoke(
                app,
                path=f"/api/inter-agent/runs/{run_id}/directives",
                method="POST",
                body={"text": "Prioritize regression coverage.", "idempotency_key": "steer-1"},
                cookie=cookie,
            )

            self.assertEqual(status, 202)
            self.assertEqual(retry_status, 200)
            self.assertEqual(retry_payload["run"]["run_id"], run_id)
            self.assertEqual(payload["run"]["mode"], "orchestrated")
            self.assertEqual(payload["run"]["source_runtime_turn_id"], "generalist-turn-1")
            self.assertEqual([item["participant_id"] for item in payload["participants"]], ["orchestrator"])
            self.assertEqual(payload["participants"][0]["execution_mode"], "child_runtime_session")
            self.assertEqual(payload["participants"][0]["thread_visibility"], "hidden")
            self.assertEqual(payload["edges"], [])
            start_worker.assert_called_once()
            self.assertEqual(directive_status, 201)
            self.assertEqual(directive_payload["directive"]["payload"]["source_kind"], "user")

    def test_chat_intent_rejects_client_owned_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/orchestrations",
                method="POST",
                body={
                    "root_runtime_session_id": "root-session",
                    "source_runtime_turn_id": "generalist-turn-1",
                    "participants": [],
                },
                cookie=cookie,
            )

            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "inter_agent_validation_failed")

    def test_group_policy_requires_the_server_product_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
            state.runtime_store.save_turn(
                RuntimeTurnRecord(
                    turn_id="generalist-group-turn",
                    session_id="root-session",
                    workspace_id="default",
                    status="completed",
                    input_text="Compare the options.",
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    completed_at=now,
                    failure_reason=None,
                )
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            body = {
                "root_runtime_session_id": "root-session",
                "source_runtime_turn_id": "generalist-group-turn",
                "policy": "group_chat",
                "idempotency_key": "group-orchestration-1",
            }

            disabled_status, disabled_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/orchestrations",
                method="POST",
                body=body,
                cookie=cookie,
            )
            with (
                patch.dict("os.environ", {"MAVERICK_FEATURE_GROUP_CHAT": "1"}),
                patch("core.api.inter_agent_api._start_orchestrated_execution_worker"),
            ):
                enabled_status, enabled_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/orchestrations",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )

            self.assertEqual(disabled_status, 400)
            self.assertIn("MAVERICK_FEATURE_GROUP_CHAT=1", disabled_payload["detail"])
            self.assertEqual(enabled_status, 202)
            self.assertEqual(enabled_payload["run"]["orchestration_policy"], "group_chat")
