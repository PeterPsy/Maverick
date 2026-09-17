from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.runtime.prepared_session_config import prepared_session_fingerprint


def _binding(*, model_id: str = "gpt-5.6-sol"):
    return SimpleNamespace(
        workspace_binding_id="workspace-agentic-default",
        runtime_engine_id="codex",
        model_provider_id="codex",
        model_id=model_id,
        reasoning_effort="max",
        execution_mode="full-access",
    )


class PreparedSessionConfigTestCase(unittest.TestCase):
    def test_resolved_default_and_explicit_reasoning_share_one_fingerprint(self) -> None:
        base = {
            "source_app_id": "chat",
            "workspace_profile_binding_id": "workspace-agentic-default",
        }
        implicit_default = prepared_session_fingerprint(
            base,
            agent_id="chat",
            execution_binding=_binding(),
        )
        explicit_default = prepared_session_fingerprint(
            {**base, "reasoning_effort": "max"},
            agent_id="chat",
            execution_binding=_binding(),
        )

        self.assertEqual(implicit_default, explicit_default)

    def test_resolved_model_change_fences_prepared_session_reuse(self) -> None:
        body = {"source_app_id": "chat"}

        first = prepared_session_fingerprint(
            body,
            agent_id="chat",
            execution_binding=_binding(model_id="gpt-5.6-sol"),
        )
        revised = prepared_session_fingerprint(
            body,
            agent_id="chat",
            execution_binding=_binding(model_id="gpt-6-astra"),
        )

        self.assertNotEqual(first, revised)


if __name__ == "__main__":
    unittest.main()
