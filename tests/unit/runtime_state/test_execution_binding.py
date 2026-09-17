from dataclasses import asdict, fields
from datetime import UTC, datetime
import unittest

from core.providers.agentic_models import (
    codex_routing_constraint,
    codex_runtime_capabilities,
    codex_runtime_policy,
)
from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    build_runtime_execution_binding,
    copy_runtime_execution_binding_for_child,
    execution_binding_from_document,
)


NOW = datetime(2026, 9, 17, tzinfo=UTC)


def binding():
    return build_runtime_execution_binding(
        session_id="session-direct",
        workspace_id="default",
        workspace_binding_id="workspace-codex",
        runtime_engine_id="codex",
        adapter_id="codex-app-server",
        adapter_version="2",
        model_provider_id="codex",
        model_id="gpt-5.6-sol",
        provider_protocol="codex-app-server-stdio",
        provider_api_version=None,
        routing_constraint=codex_routing_constraint(),
        credential_binding_id=None,
        reasoning_effort="high",
        reasoning_efforts=("high", "xhigh"),
        capabilities=codex_runtime_capabilities(),
        execution_mode="full-access",
        runtime_policy=codex_runtime_policy(),
        egress_policy_id="local-runtime-no-remote-egress",
        egress_policy_revision="1",
        created_at=NOW,
    )


class ExecutionBindingTest(unittest.TestCase):
    def test_current_binding_round_trips_without_identity_metadata(self) -> None:
        current = binding()
        hydrated = execution_binding_from_document(asdict(current))

        self.assertEqual(hydrated, current)
        self.assertNotIn("binding_digest", {field.name for field in fields(RuntimeExecutionBinding)})
        self.assertNotIn("profile_definition_revision", asdict(current))

    def test_child_copy_only_changes_session_identity_and_time(self) -> None:
        current = binding()
        later = datetime(2026, 9, 18, tzinfo=UTC)
        forked = copy_runtime_execution_binding_for_child(
            current,
            session_id="child",
            created_at=later,
        )

        self.assertEqual(forked.session_id, "child")
        self.assertEqual(forked.created_at, later)
        self.assertNotEqual(forked.execution_binding_id, current.execution_binding_id)
        comparable = asdict(current)
        comparable.update(
            execution_binding_id=forked.execution_binding_id,
            session_id="child",
            created_at=later,
        )
        self.assertEqual(asdict(forked), comparable)


if __name__ == "__main__":
    unittest.main()
