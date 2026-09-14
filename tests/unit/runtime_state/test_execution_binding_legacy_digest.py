from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.providers.agentic_models import (
    codex_routing_constraint,
    codex_runtime_capabilities,
    codex_runtime_policy,
)
from core.runtime.execution_binding import (
    RuntimeExecutionBinding,
    build_runtime_execution_binding,
    canonical_digest,
    execution_binding_from_document,
)


class ExecutionBindingLegacyDigestTestCase(unittest.TestCase):
    def test_current_binding_round_trip_preserves_immutable_snapshot(self) -> None:
        binding = _execution_binding()

        self.assertEqual(execution_binding_from_document(asdict(binding)), binding)

    def test_retired_adapter_digest_is_renamed_after_validation(self) -> None:
        binding = _execution_binding()
        serialized = asdict(binding)
        serialized["adapter_artifact_digest"] = serialized.pop("adapter_identity_digest")
        serialized["binding_digest"] = canonical_digest(serialized)

        self.assertEqual(execution_binding_from_document(serialized), binding)
        self.assertIn("adapter_artifact_digest", serialized)
        self.assertNotIn("adapter_identity_digest", serialized)

    def test_tampered_retired_adapter_digest_is_rejected(self) -> None:
        serialized = asdict(_execution_binding())
        serialized["adapter_artifact_digest"] = serialized.pop("adapter_identity_digest")
        serialized["binding_digest"] = canonical_digest(serialized)
        serialized["adapter_artifact_digest"] = "c" * 64

        with self.assertRaisesRegex(ValueError, "digest does not match"):
            execution_binding_from_document(serialized)

    def test_legacy_digest_validation_is_bounded_by_schema_groups(self) -> None:
        serialized = asdict(_execution_binding())
        serialized["adapter_artifact_digest"] = serialized.pop("adapter_identity_digest")
        serialized["certified_reasoning_efforts"] = serialized.pop(
            "reasoning_efforts"
        )
        serialized.pop("capabilities_snapshot")
        serialized["capability_certificate_id"] = "legacy-certificate"
        serialized["certificate_evidence_digest"] = "a" * 64
        serialized["tcb_manifest_id"] = "legacy-tcb"
        serialized["tcb_manifest_version"] = "1"
        serialized["tcb_structure_digest"] = "b" * 64
        serialized["tcb_live_digest"] = "c" * 64
        for field_name in (
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        ):
            serialized[field_name].pop("allow_filesystem_list")
        serialized["tool_authority_ceiling_digest"] = canonical_digest(
            serialized["workspace_policy_ceiling_snapshot"]
        )
        serialized["binding_digest"] = canonical_digest(serialized)

        with patch(
            "core.runtime.execution_binding.canonical_digest",
            wraps=canonical_digest,
        ) as digest:
            rehydrated = execution_binding_from_document(serialized)

        self.assertNotEqual(rehydrated.binding_digest, serialized["binding_digest"])
        self.assertEqual(rehydrated.adapter_identity_digest, serialized["adapter_artifact_digest"])
        self.assertNotIn("adapter_artifact_digest", asdict(rehydrated))
        self.assertTrue(rehydrated.capabilities_snapshot.tool_orchestration)
        self.assertFalse(rehydrated.capabilities_snapshot.confirmations)
        self.assertLessEqual(digest.call_count, 8)


def _execution_binding() -> RuntimeExecutionBinding:
    return build_runtime_execution_binding(
        session_id="session-legacy",
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
