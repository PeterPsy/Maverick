from __future__ import annotations

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_runtime_protocol as protocol
from core.providers import codex_app_server_runtime_process as process
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.models import RuntimeBackendLaunchSpec


class CodexAgentMessagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events = []
        self.runtime = _CodexAppServerRuntime(
            session_id="session-test", workspace_id="default", runtime_root="/tmp/runtime-test",
            process=SimpleNamespace(pid=1, poll=lambda: None),
            current_event_sink=self.events.append,
        )
        self.debug = patch.object(protocol, "_debug_log")
        self.debug.start()
        self.addCleanup(self.debug.stop)

    def notify(self, method: str, **params) -> None:
        protocol._handle_notification(self.runtime, {"method": method, "params": params})

    def test_completed_content_snapshot_is_not_emitted_again(self) -> None:
        self.notify("item/agentMessage/delta", itemId="question", delta="Which calendar?")
        self.notify("item/completed", item={
            "id": "question", "type": "AgentMessage", "phase": "final_answer", "delivery": "async",
            "content": [{"type": "Text", "text": "Which calendar?"}], "questions": [{}],
        })
        deltas = [e for e in self.events if e.event_type == "runtime.output.delta"]
        self.assertEqual([e.payload["text"] for e in deltas], ["Which calendar?"])
        self.assertEqual(deltas[0].payload["message_id"], "question")
        self.assertIsNone(self.runtime.current_final_answer)
        self.assertEqual(self.events[-1].event_type, "runtime.output.message.completed")
        self.assertEqual(self.events[-1].payload["phase"], "commentary")

    def test_final_answer_is_separate_from_commentary(self) -> None:
        for item_id, phase, text in (("progress", "commentary", "Checking."), ("answer", "final_answer", "Done.\n\n- Passed.")):
            item = {"id": item_id, "type": "agentMessage", "phase": phase, "text": text}
            self.notify("item/started", item=item)
            self.notify("item/agentMessage/delta", itemId=item_id, delta=text)
            self.notify("item/completed", item=item)
        self.assertEqual(self.runtime.current_final_answer, "Done.\n\n- Passed.")
        self.assertEqual([e.payload.get("phase") for e in self.events if e.event_type == "runtime.output.delta"], ["commentary", "final"])

    def test_completed_content_without_deltas_preserves_markdown(self) -> None:
        text = "Paragraph.\n\n- First\n- Second\n"
        self.notify("item/completed", item={
            "id": "answer", "type": "AgentMessage", "phase": "final_answer",
            "content": [{"type": "Text", "text": text}],
        })
        self.assertEqual(self.runtime.current_final_answer, text)
        self.assertEqual(self.events[0].payload["text"], text)

    def test_turn_result_returns_the_final_message_and_clears_its_state(self) -> None:
        session = SimpleNamespace(session_id="session-test", workspace_id="default", runtime_root="/tmp/runtime-test")
        spec = RuntimeBackendLaunchSpec(
            provider_id="codex", command=["codex", "app-server"], env_overrides={},
            credential_binding_id=None, resolved_secret_refs=[], working_directory="/tmp",
            execution_mode="sandbox", readable_roots=[], writable_roots=[],
        )

        def send_request(runtime, method, params, **kwargs):
            self.notify("item/completed", item={"id": "progress", "type": "agentMessage", "text": "Checking.", "phase": "commentary"})
            self.notify("item/completed", item={"id": "final", "type": "agentMessage", "text": "Done.\n\n- Passed.", "phase": "final_answer"})
            runtime.completion_queue.put({"status": "completed"})
            return {"turn": {"id": "provider-turn"}}

        with patch.object(process, "_ensure_runtime", return_value=self.runtime), patch.object(
            process, "_ensure_provider_thread", return_value="provider-thread"
        ), patch.object(process, "_remove_generated_system_skills_if_needed"), patch.object(
            process, "_send_request", side_effect=send_request
        ), patch.object(process, "_debug_log"):
            result = process.execute_codex_app_server_turn(
                session=session, launch_spec=spec, input_text="Check", event_sink=self.events.append, timeout_seconds=1,
            )
        self.assertEqual(result.output_text, "Done.\n\n- Passed.")
        self.assertIsNone(self.runtime.current_final_answer)
        self.assertEqual(self.runtime.agent_message_phases, {})


if __name__ == "__main__":
    unittest.main()
