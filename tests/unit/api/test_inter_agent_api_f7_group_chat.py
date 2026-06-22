from __future__ import annotations

from datetime import UTC, datetime
import tempfile
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.test_inter_agent_api import InterAgentApiSupport, _run_payload_without_snapshot


class InterAgentApiF7GroupChatTest(InterAgentApiSupport):
    def test_inter_agent_http_group_chat_requires_feature_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            payload = _group_chat_payload(run_id="run-api-group-chat-disabled")

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=payload,
                cookie=cookie,
            )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "inter_agent_validation_failed")
        self.assertIn("MAVERICK_FEATURE_GROUP_CHAT=1", create_payload["detail"])

    def test_inter_agent_http_group_chat_requires_aggregator_when_flag_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            payload = _run_payload_without_snapshot(run_id="run-api-group-chat-no-aggregator")
            payload["mode"] = "group_chat"
            payload["participants"][1]["execution_mode"] = "embedded_executor"

            with patch.dict("os.environ", {"MAVERICK_FEATURE_GROUP_CHAT": "1"}):
                create_status, create_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs",
                    method="POST",
                    body=payload,
                    cookie=cookie,
                )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "inter_agent_validation_failed")
        self.assertIn("aggregator_participant_id", create_payload["detail"])

    def test_inter_agent_http_group_chat_create_and_execute_when_feature_flag_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            payload = _group_chat_payload(run_id="run-api-group-chat-enabled")
            now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
            submitted: list[tuple[str, str]] = []

            def fake_submit(_state, *, session, input_text, client_message_id=None, async_requested=False):
                submitted.append((session.agent_id, input_text))
                output_by_agent_id = {
                    "research-agent": "Research says option A is fast.",
                    "review-agent": "Review says option B is safer.",
                    "synthesis-agent": "Choose option B with a staged rollout.",
                }
                output = output_by_agent_id[session.agent_id]
                turn = RuntimeTurnRecord(
                    turn_id=f"turn-{session.agent_id}",
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
                    event_id=f"event-{session.agent_id}",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.final",
                    turn_id=turn.turn_id,
                    process_id=None,
                    payload={"text": output},
                    created_at=now,
                )
                return turn, [event]

            with patch.dict("os.environ", {"MAVERICK_FEATURE_GROUP_CHAT": "1"}):
                create_status, create_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs",
                    method="POST",
                    body=payload,
                    cookie=cookie,
                )
                with patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit):
                    execute_status, execute_payload, _headers = self._invoke(
                        app,
                        path="/api/inter-agent/runs/run-api-group-chat-enabled/execute",
                        method="POST",
                        body={
                            "input_text": "Compare the rollout options.",
                            "participant_inputs": {
                                "researcher": "Research the rollout options.",
                                "reviewer": "Review the rollout risk.",
                                "synthesizer": "Synthesize the final answer.",
                            },
                        },
                        cookie=cookie,
                    )

        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["mode"], "group_chat")
        self.assertEqual(create_payload["run"]["aggregator_participant_id"], "synthesizer")
        self.assertEqual(execute_status, 200)
        self.assertEqual(execute_payload["run"]["status"], "completed")
        self.assertEqual(execute_payload["final_answer"], "Choose option B with a staged rollout.")
        self.assertEqual(
            [agent_id for agent_id, _input in submitted],
            ["research-agent", "review-agent", "synthesis-agent"],
        )
        self.assertEqual(
            [result["participant_id"] for result in execute_payload["participant_results"]],
            ["researcher", "reviewer", "synthesizer"],
        )
        self.assertTrue(all(result["runtime_session_id"] for result in execute_payload["participant_results"]))
        self.assertEqual([result["synthetic"] for result in execute_payload["participant_results"]], [False, False, False])
        self.assertIn("Researcher: Research says option A is fast.", submitted[2][1])
        self.assertIn("Reviewer: Review says option B is safer.", submitted[2][1])

    def test_inter_agent_http_handoff_and_magentic_are_not_product_facing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            statuses = []
            for mode in ("handoff", "magentic_like"):
                payload = _run_payload_without_snapshot(run_id=f"run-api-{mode}")
                payload["mode"] = mode
                create_status, create_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs",
                    method="POST",
                    body=payload,
                    cookie=cookie,
                )
                statuses.append((create_status, create_payload))

        self.assertEqual([status for status, _payload in statuses], [400, 400])
        for _status, payload in statuses:
            self.assertEqual(payload["error"], "inter_agent_validation_failed")
            self.assertIn("not product-facing", payload["detail"])


def _group_chat_payload(*, run_id: str) -> dict:
    payload = _run_payload_without_snapshot(run_id=run_id)
    payload["mode"] = "group_chat"
    payload["aggregator_participant_id"] = "synthesizer"
    payload["participants"] = [
        payload["participants"][0],
        _group_chat_participant("synthesizer", "Synthesizer", "synthesis-agent"),
        _group_chat_participant("researcher", "Researcher", "research-agent"),
        _group_chat_participant("reviewer", "Reviewer", "review-agent"),
    ]
    payload["budget"] = {
        "max_participants": 4,
        "max_concurrent_participants": 1,
        "max_rounds": 1,
        "max_total_turns": 3,
        "max_turns_per_participant": 1,
    }
    return payload


def _group_chat_participant(participant_id: str, label: str, agent_type_id: str) -> dict:
    return {
        "participant_id": participant_id,
        "kind": "agent",
        "execution_mode": "child_runtime_session",
        "label": label,
        "agent_type_id": agent_type_id,
    }
