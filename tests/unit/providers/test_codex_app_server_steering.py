from __future__ import annotations

import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_runtime_process as runtime_process
from core.providers import codex_app_server_runtime_steering as runtime_steering
from core.providers.codex_app_server_runtime_errors import (
    CodexAppServerDeliveryUncertainError,
    CodexAppServerRequestError,
)
from core.providers.codex_app_server_runtime_transport import _send_request
from core.skills.models import SkillDefinition


class CodexAppServerSteeringTestCase(unittest.TestCase):
    def test_steer_sends_the_same_structured_skill_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self._runtime("session-steer", provider_turn_id="provider-turn-1")
            runtime.runtime_root = str(Path(temp_dir) / "runtime")
            skill_file = Path(runtime.runtime_root) / "codex-home" / "skills" / "storage-ops" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("# Storage Ops\n", encoding="utf-8")
            invoked_skill = SkillDefinition(
                skill_id="storage-ops",
                local_skill_id="storage-ops",
                name="Storage Ops",
                description="Operate Storage.",
                source_root="/catalog/storage-ops",
                owner_kind="workspace",
                owner_id="default",
                workspace_id="default",
                status="available",
            )

            with patch.object(runtime_steering, "_send_request", return_value={"turnId": "provider-turn-1"}) as send_request:
                result = runtime_process.steer_codex_app_server_turn(
                    runtime.session_id,
                    input_text="$storage-ops continue",
                    expected_provider_turn_id="provider-turn-1",
                    invoked_skills=[invoked_skill],
                )

        self.assertEqual(result.status, "steered")
        self.assertEqual(
            send_request.call_args.args[2]["input"],
            [
                {"type": "text", "text": "$storage-ops continue"},
                {"type": "skill", "name": "storage-ops", "path": str(skill_file.resolve())},
            ],
        )

    def tearDown(self) -> None:
        for session_id in (
            "session-steer",
            "session-steer-race",
            "session-steer-timeout",
            "session-steer-overload",
            "session-steer-mismatch",
        ):
            runtime_process._RUNTIMES.pop(session_id, None)

    def test_steer_admits_input_into_the_expected_active_turn(self) -> None:
        runtime = self._runtime("session-steer", provider_turn_id="provider-turn-1")

        with patch.object(
            runtime_steering,
            "_send_request",
            return_value={"turnId": "provider-turn-1"},
        ) as send_request:
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="new direction",
                client_message_id="client-message-1",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "steered")
        send_request.assert_called_once_with(
            runtime,
            "turn/steer",
            {
                "threadId": "provider-thread-1",
                "expectedTurnId": "provider-turn-1",
                "input": [{"type": "text", "text": "new direction"}],
                "clientUserMessageId": "client-message-1",
            },
            timeout=5.0,
        )

    def test_steer_refuses_a_provider_turn_that_changed_before_dispatch(self) -> None:
        runtime = self._runtime("session-steer-race", provider_turn_id="provider-turn-2")

        with patch.object(runtime_steering, "_send_request") as send_request:
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="stale direction",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "not_active")
        self.assertEqual(result.reason, "provider_turn_changed")
        send_request.assert_not_called()

    def test_steer_marks_timeout_delivery_uncertain_instead_of_retrying(self) -> None:
        runtime = self._runtime("session-steer-timeout", provider_turn_id="provider-turn-1")

        with patch.object(
            runtime_steering,
            "_send_request",
            side_effect=CodexAppServerDeliveryUncertainError("timeout"),
        ) as send_request:
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="maybe delivered",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "delivery_uncertain")
        send_request.assert_called_once()

    def test_steer_retries_only_explicit_backpressure_with_a_bound(self) -> None:
        runtime = self._runtime("session-steer-overload", provider_turn_id="provider-turn-1")
        rejection = CodexAppServerRequestError(
            "turn/steer",
            code=-32001,
            message="server overloaded",
        )

        with patch.object(runtime_steering, "_send_request", side_effect=rejection) as send_request, patch.object(
            runtime_steering.time,
            "sleep",
        ) as sleep, patch.object(runtime_steering.random, "uniform", return_value=1.0):
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="try with backpressure",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "overloaded")
        self.assertEqual(send_request.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1, 0.2])

    def test_steer_does_not_follow_a_provider_reported_turn_mismatch(self) -> None:
        runtime = self._runtime("session-steer-mismatch", provider_turn_id="provider-turn-1")
        rejection = CodexAppServerRequestError(
            "turn/steer",
            code=-32602,
            message="expected turn does not match active turn",
            data={"actualTurnId": "provider-turn-2"},
        )

        with patch.object(runtime_steering, "_send_request", side_effect=rejection) as send_request:
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="do not cross turns",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "not_active")
        self.assertEqual(result.provider_turn_id, "provider-turn-2")
        send_request.assert_called_once()

    def test_steer_recognizes_the_codex_expected_turn_mismatch_message(self) -> None:
        runtime = self._runtime("session-steer-mismatch", provider_turn_id="provider-turn-1")
        rejection = CodexAppServerRequestError(
            "turn/steer",
            code=-32600,
            message="expected active turn id `provider-turn-1` but found `provider-turn-2`",
        )

        with patch.object(runtime_steering, "_send_request", side_effect=rejection):
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="do not cross turns",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "not_active")
        self.assertEqual(result.reason, "provider_turn_changed")

    def test_steer_recognizes_structured_non_steerable_turn_rejection(self) -> None:
        runtime = self._runtime("session-steer", provider_turn_id="provider-turn-1")
        rejection = CodexAppServerRequestError(
            "turn/steer",
            code=-32600,
            message="input rejected",
            data={"codexErrorInfo": {"activeTurnNotSteerable": {"turnKind": "review"}}},
        )

        with patch.object(runtime_steering, "_send_request", side_effect=rejection):
            result = runtime_process.steer_codex_app_server_turn(
                runtime.session_id,
                input_text="cannot steer review",
                expected_provider_turn_id="provider-turn-1",
            )

        self.assertEqual(result.status, "not_supported")

    def test_transport_disconnect_is_not_mistaken_for_an_explicit_rejection(self) -> None:
        runtime = self._runtime("session-steer", provider_turn_id="provider-turn-1")

        class DisconnectingStdin:
            request_id = 0

            def write(self, value: str) -> None:
                self.request_id = int(json.loads(value)["id"])

            def flush(self) -> None:
                runtime.response_waiters[self.request_id].put({"_transport_error": "stream ended"})

        runtime.process.stdin = DisconnectingStdin()

        with self.assertRaises(CodexAppServerDeliveryUncertainError):
            _send_request(runtime, "turn/steer", {}, timeout=0.1)

    def test_transport_preserves_json_rpc_error_code_and_data(self) -> None:
        runtime = self._runtime("session-steer", provider_turn_id="provider-turn-1")

        class RejectingStdin:
            request_id = 0

            def write(self, value: str) -> None:
                self.request_id = int(json.loads(value)["id"])

            def flush(self) -> None:
                runtime.response_waiters[self.request_id].put(
                    {
                        "error": {
                            "code": -32602,
                            "message": "turn mismatch",
                            "data": {"actualTurnId": "provider-turn-2"},
                        }
                    }
                )

        runtime.process.stdin = RejectingStdin()

        with self.assertRaises(CodexAppServerRequestError) as raised:
            _send_request(runtime, "turn/steer", {}, timeout=0.1)

        self.assertEqual(raised.exception.code, -32602)
        self.assertEqual(raised.exception.data, {"actualTurnId": "provider-turn-2"})

    @staticmethod
    def _runtime(session_id: str, *, provider_turn_id: str):
        runtime = runtime_process._CodexAppServerRuntime(
            session_id=session_id,
            workspace_id="default",
            runtime_root=f"/tmp/{session_id}",
            process=SimpleNamespace(pid=123, poll=lambda: None),
            provider_thread_id="provider-thread-1",
            current_provider_turn_id=provider_turn_id,
        )
        runtime_process._RUNTIMES[session_id] = runtime
        return runtime


if __name__ == "__main__":
    unittest.main()
