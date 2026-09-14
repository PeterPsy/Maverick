from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import unittest

from core.providers.agentic_models import (
    codex_routing_constraint,
    codex_runtime_capabilities,
    codex_runtime_policy,
)
from core.runtime.continuation_handoff import (
    RuntimeContinuationHandoff,
    runtime_continuation_handoff_from_document,
)
from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    build_runtime_execution_binding,
    execution_binding_from_document,
)


class ExecutionBindingDigestTestCase(unittest.TestCase):
    def test_current_binding_round_trip_preserves_immutable_snapshot(self) -> None:
        binding = _execution_binding()

        self.assertEqual(execution_binding_from_document(asdict(binding)), binding)

    def test_tampered_adapter_identity_is_rejected(self) -> None:
        serialized = asdict(_execution_binding())
        serialized["adapter_identity_digest"] = "c" * 64

        with self.assertRaisesRegex(ValueError, "digest does not match"):
            execution_binding_from_document(serialized)


class ContinuationHandoffDigestTestCase(unittest.TestCase):
    def test_current_handoff_round_trip_preserves_snapshot(self) -> None:
        handoff = _continuation_handoff()

        self.assertEqual(
            runtime_continuation_handoff_from_document(asdict(handoff)),
            handoff,
        )

    def test_handoff_rejects_inconsistent_target_digest(self) -> None:
        serialized = asdict(_continuation_handoff())
        serialized["target_binding_digest"] = "e" * 64

        with self.assertRaisesRegex(ValueError, "target binding digest is inconsistent"):
            runtime_continuation_handoff_from_document(serialized)

    def test_handoff_rejects_tampered_embedded_binding(self) -> None:
        serialized = asdict(_continuation_handoff())
        serialized["target_execution_binding"]["adapter_identity_digest"] = "c" * 64

        with self.assertRaisesRegex(ValueError, "digest does not match"):
            runtime_continuation_handoff_from_document(serialized)


def _continuation_handoff() -> RuntimeContinuationHandoff:
    binding = _execution_binding()
    return RuntimeContinuationHandoff(
        handoff_id="handoff-direct",
        workspace_id=binding.workspace_id,
        predecessor_session_id="session-predecessor",
        successor_session_id=binding.session_id,
        reason_code="adapter_profile_upgrade",
        source_detail_code="runtime_profile_upgrade_required",
        source_binding_digest="a" * 64,
        target_binding_digest=binding.binding_digest,
        source_provider_state_revision=0,
        source_provider_state_digest="c" * 64,
        compatible_capabilities=("streaming",),
        compatibility_digest="d" * 64,
        target_execution_binding=binding,
        phase="completed",
        revision=5,
        created_at=binding.created_at,
        updated_at=binding.created_at,
        completed_at=binding.created_at,
    )


def _execution_binding() -> RuntimeExecutionBinding:
    return build_runtime_execution_binding(
        session_id="session-direct",
        workspace_id="default",
        profile_definition_id="profile-codex",
        profile_definition_revision="1",
        workspace_binding_id="workspace-codex",
        workspace_binding_revision=0,
        runtime_engine_id="codex",
        adapter_id="codex-app-server",
        adapter_version="test",
        adapter_identity_digest="b" * 64,
        model_provider_id="codex",
        model_id="gpt-test",
        provider_protocol="codex-app-server-stdio",
        provider_api_version=None,
        routing_constraint=codex_routing_constraint(),
        credential_binding_id=None,
        reasoning_effort=None,
        reasoning_efforts=(),
        default_reasoning_effort=None,
        capabilities=codex_runtime_capabilities(),
        execution_mode="full-access",
        profile_policy_ceiling=codex_runtime_policy(),
        workspace_policy_ceiling=codex_runtime_policy(),
        egress_policy_id="egress-codex",
        egress_policy_revision="1",
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
