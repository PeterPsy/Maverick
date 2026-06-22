from __future__ import annotations

import tempfile
from unittest.mock import patch

from core.api.platform_host import PlatformHost
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

            with patch.dict("os.environ", {"MAVERICK_FEATURE_GROUP_CHAT": "1"}):
                create_status, create_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs",
                    method="POST",
                    body=payload,
                    cookie=cookie,
                )
                execute_status, execute_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-api-group-chat-enabled/execute",
                    method="POST",
                    body={"input_text": "Compare the rollout options."},
                    cookie=cookie,
                )

        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["mode"], "group_chat")
        self.assertEqual(create_payload["run"]["aggregator_participant_id"], "researcher")
        self.assertEqual(execute_status, 409)
        self.assertEqual(execute_payload["error"], "inter_agent_operation_failed")
        self.assertIn("Synthetic inter-agent participant execution requires", execute_payload["detail"])

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
    payload["aggregator_participant_id"] = "researcher"
    payload["participants"][1]["execution_mode"] = "embedded_executor"
    payload["budget"] = {
        "max_participants": 3,
        "max_concurrent_participants": 1,
        "max_rounds": 1,
        "max_total_turns": 1,
        "max_turns_per_participant": 1,
    }
    return payload
