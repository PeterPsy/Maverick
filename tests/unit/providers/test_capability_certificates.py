from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest
import tempfile
from pathlib import Path

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_service import (
    revoke_capability_certificate,
    runtime_adapter_artifact_digest,
    validate_certificate_for_binding,
)
from core.providers.errors import CapabilityCertificateConflictError, CapabilityCertificateError
from core.providers.evidence_store import CapabilityEvidenceBlobStore
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import build_runtime_execution_binding, canonical_digest
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class CapabilityCertificateTest(unittest.TestCase):
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
            reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=updates.pop("profile_policy", codex_runtime_policy()),
            workspace_policy_ceiling=updates.pop("workspace_policy", codex_runtime_policy()),
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            certificate_evidence_digest=self.evidence.evidence_digest,
            created_at=NOW,
            **updates,
        )

    def test_exact_certificate_grants_only_policy_intersection(self) -> None:
        live = self.store.get_workspace_agentic_profile_binding(self.binding.workspace_binding_id)
        narrowed_policy = replace(
            live.workspace_policy_ceiling,
            allowed_surface_kinds=("mcp",),
            allow_filesystem_write=False,
            allow_shell=False,
        )
        self.store.save_workspace_agentic_profile_binding(
            replace(live, workspace_policy_ceiling=narrowed_policy, revision=1, updated_at=NOW),
            expected_revision=0,
        )

        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-certified",
            currently_authorized_tool_handles=("mcp:read", "cli:write"),
            now=NOW,
        )

        self.assertTrue(authority.allowed_capabilities.mcp)
        self.assertFalse(authority.allowed_capabilities.cli)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)
        self.assertEqual(authority.authority_digest, canonical_digest(authority))

    def test_revoked_or_expired_certificate_cannot_execute(self) -> None:
        revoked = revoke_capability_certificate(
            self.store,
            certificate_id=self.binding.capability_certificate_id,
            expected_revision=0,
            reason="test_revocation",
            now=NOW,
        )
        self.assertEqual(revoked.revision, 1)
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_revoked"):
            validate_certificate_for_binding(
                self.store, binding=self.binding, adapter=self.adapter, now=NOW
            )
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_status_revision_conflict"):
            revoke_capability_certificate(
                self.store,
                certificate_id=self.binding.capability_certificate_id,
                expected_revision=0,
                reason="stale_revoke",
                now=NOW,
            )

        fresh_store = certified_test_provider_store(
            self.binding, self.adapter, evidence=self.evidence, now=NOW
        )
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_expired"):
            validate_certificate_for_binding(
                fresh_store,
                binding=self.binding,
                adapter=self.adapter,
                now=NOW + timedelta(days=2),
            )

    def test_certificate_identity_is_immutable(self) -> None:
        certificate = self.store.get_capability_certificate(self.binding.capability_certificate_id)
        with self.assertRaisesRegex(CapabilityCertificateConflictError, "certificate_immutable_conflict"):
            self.store.save_capability_certificate(replace(certificate, model_id="other-model"))

    def test_adapter_artifact_and_version_are_verified_live(self) -> None:
        changed_adapter = FakeHostedAgenticAdapter()
        changed_adapter.adapter_version = "2"
        with self.assertRaisesRegex(CapabilityCertificateError, "adapter_version_mismatch"):
            validate_certificate_for_binding(
                self.store,
                binding=self.binding,
                adapter=changed_adapter,
                now=NOW,
            )

        tampered = replace(self.binding, adapter_artifact_digest="0" * 64, binding_digest="")
        tampered = replace(tampered, binding_digest=canonical_digest(tampered))
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_adapter_artifact_digest_mismatch"):
            validate_certificate_for_binding(
                self.store,
                binding=tampered,
                adapter=self.adapter,
                now=NOW,
            )

    def test_effective_upstream_must_be_certified(self) -> None:
        routing = replace(
            codex_routing_constraint(),
            endpoint_id="fake-router",
            allowed_upstream_ids=("upstream-a",),
            data_collection_policy="deny",
        )
        binding = self._binding(routing_constraint=routing)
        store = certified_test_provider_store(
            binding, self.adapter, evidence=self.evidence, now=NOW
        )

        validate_certificate_for_binding(
            store,
            binding=binding,
            adapter=self.adapter,
            observed_upstream_id="upstream-a",
            now=NOW,
        )
        with self.assertRaisesRegex(CapabilityCertificateError, "provider_upstream_not_certified"):
            validate_certificate_for_binding(
                store,
                binding=binding,
                adapter=self.adapter,
                observed_upstream_id="upstream-b",
                now=NOW,
            )

    def test_missing_certificate_and_unavailable_health_fail_closed(self) -> None:
        missing = replace(self.binding, capability_certificate_id="missing", binding_digest="")
        missing = replace(missing, binding_digest=canonical_digest(missing))
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_missing"):
            validate_certificate_for_binding(
                self.store, binding=missing, adapter=self.adapter, now=NOW
            )
        with self.assertRaisesRegex(CapabilityCertificateError, "runtime_health_unavailable"):
            resolve_effective_runtime_authority(
                self.store,
                binding=self.binding,
                adapter=self.adapter,
                turn_id="turn-unhealthy",
                health_status="unavailable",
                now=NOW,
            )

    def test_evidence_blob_store_is_content_addressed_and_integrity_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapabilityEvidenceBlobStore(Path(temp_dir))
            evidence_ref = store.put(b"certification evidence")
            self.assertEqual(store.get(evidence_ref), b"certification evidence")
            digest = evidence_ref.rsplit(":", 1)[-1]
            (Path(temp_dir) / digest[:2] / digest).write_bytes(b"tampered")
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_evidence_blob_corrupt"):
                store.get(evidence_ref)


if __name__ == "__main__":
    unittest.main()
