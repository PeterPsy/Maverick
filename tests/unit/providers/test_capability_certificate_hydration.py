from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import unittest

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_service import (
    runtime_adapter_artifact_digest,
    validate_certificate_for_binding,
)
from core.runtime.execution_binding import build_runtime_execution_binding, canonical_digest
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class CapabilityCertificateHydrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeHostedAgenticAdapter()
        self.evidence = fake_capability_evidence(self.adapter, now=NOW)
        self.binding = self._binding()
        self.store = certified_test_provider_store(
            self.binding,
            self.adapter,
            evidence=self.evidence,
            now=NOW,
        )

    def _binding(self, **updates):
        routing = updates.pop("routing_constraint", codex_routing_constraint())
        return build_runtime_execution_binding(
            session_id="session-certified",
            workspace_id="default",
            profile_definition_id="profile-certified",
            profile_definition_revision="1",
            workspace_binding_id="workspace-certified",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-certified",
            runtime_engine_id=self.adapter.runtime_engine_id,
            adapter_id=self.adapter.adapter_id,
            adapter_version=self.adapter.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(self.adapter),
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=routing,
            credential_binding_id=None,
            reasoning_effort=updates.pop("reasoning_effort", None),
            certified_reasoning_efforts=updates.pop("certified_reasoning_efforts", ()),
            default_reasoning_effort=updates.pop("default_reasoning_effort", None),
            execution_mode="full-access",
            profile_policy_ceiling=updates.pop("profile_policy", codex_runtime_policy()),
            workspace_policy_ceiling=updates.pop("workspace_policy", codex_runtime_policy()),
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            certificate_evidence_digest=self.evidence.evidence_digest,
            created_at=NOW,
            **updates,
        )

    def test_rehydrated_execution_binding_validates_without_upstream_type_mismatch(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        serialized["routing_constraint_snapshot"]["allowed_upstream_ids"] = list(
            self.binding.routing_constraint_snapshot.allowed_upstream_ids
        )
        self.assertIsInstance(serialized["routing_constraint_snapshot"]["allowed_upstream_ids"], list)

        rehydrated = execution_binding_from_document(serialized)
        self.assertIsInstance(rehydrated.routing_constraint_snapshot.allowed_upstream_ids, tuple)

        validated = validate_certificate_for_binding(
            self.store,
            binding=rehydrated,
            adapter=self.adapter,
            now=NOW,
        )
        self.assertEqual(validated.certificate_id, self.binding.capability_certificate_id)

    def test_rehydrated_legacy_binding_defaults_new_list_capability_fail_closed(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        for field_name in (
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        ):
            serialized[field_name].pop("allow_filesystem_list")
        serialized["tool_authority_ceiling_digest"] = canonical_digest(
            serialized["workspace_policy_ceiling_snapshot"]
        )
        serialized["binding_digest"] = canonical_digest(serialized)

        rehydrated = execution_binding_from_document(serialized)

        self.assertFalse(
            rehydrated.profile_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertFalse(
            rehydrated.workspace_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertEqual(rehydrated.binding_digest, serialized["binding_digest"])

        reserialized = asdict(rehydrated)
        round_tripped = execution_binding_from_document(reserialized)
        self.assertFalse(
            round_tripped.profile_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertEqual(round_tripped.binding_digest, serialized["binding_digest"])

        reserialized["workspace_policy_ceiling_snapshot"][
            "allow_filesystem_list"
        ] = True
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)

        serialized["model_id"] = "tampered-model"
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(serialized)

    def test_rehydrated_legacy_binding_round_trips_reasoning_defaults_fail_closed(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        serialized.pop("certified_reasoning_efforts")
        serialized.pop("default_reasoning_effort")
        serialized["binding_digest"] = canonical_digest(serialized)

        rehydrated = execution_binding_from_document(serialized)
        self.assertEqual(rehydrated.certified_reasoning_efforts, ())
        self.assertIsNone(rehydrated.default_reasoning_effort)

        reserialized = asdict(rehydrated)
        round_tripped = execution_binding_from_document(reserialized)
        self.assertEqual(round_tripped.binding_digest, serialized["binding_digest"])

        reserialized["certified_reasoning_efforts"] = ["high"]
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)
        reserialized["certified_reasoning_efforts"] = []
        reserialized["default_reasoning_effort"] = "high"
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)

    def test_legacy_binding_uses_explicit_provider_alias_revision_policy(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        serialized.pop("model_revision")
        serialized.pop("model_revision_policy")
        serialized["binding_digest"] = canonical_digest(serialized)

        rehydrated = execution_binding_from_document(serialized)

        self.assertIsNone(rehydrated.model_revision)
        self.assertEqual(rehydrated.model_revision_policy, "provider_alias")
        self.assertEqual(rehydrated.binding_digest, serialized["binding_digest"])


if __name__ == "__main__":
    unittest.main()
