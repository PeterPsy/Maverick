from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_projection import certificate_profile_status
from core.providers.certificate_service import runtime_adapter_artifact_digest, validate_certificate_for_binding
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import build_runtime_execution_binding, canonical_digest
from tests.support.agentic_certification import certified_test_provider_store, fake_capability_evidence
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class CertificateTcbEnforcementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeHostedAgenticAdapter()
        self.evidence = fake_capability_evidence(self.adapter, now=NOW)
        self.binding = build_runtime_execution_binding(
            session_id="session-certified-tcb",
            workspace_id="default",
            profile_definition_id="profile-certified-tcb",
            profile_definition_revision="1",
            workspace_binding_id="workspace-certified-tcb",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-certified-tcb",
            runtime_engine_id=self.adapter.runtime_engine_id,
            adapter_id=self.adapter.adapter_id,
            adapter_version=self.adapter.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(self.adapter),
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            certificate_evidence_digest=self.evidence.evidence_digest,
            created_at=NOW,
        )
        self.store = certified_test_provider_store(
            self.binding, self.adapter, evidence=self.evidence, now=NOW
        )

    def test_tcb_drift_blocks_publication_binding_and_live_status(self) -> None:
        certificate = self.store.get_capability_certificate(
            self.binding.capability_certificate_id
        )
        status = self.store.get_capability_certificate_status(certificate.certificate_id)
        definition = SimpleNamespace(
            capability_certificate_id=certificate.certificate_id,
            runtime_engine_id=certificate.runtime_engine_id,
            adapter_id=certificate.adapter_id,
            model_provider_id=certificate.model_provider_id,
            model_id=certificate.model_id,
            provider_protocol=certificate.provider_protocol,
            provider_api_version=certificate.provider_api_version,
            routing_constraint=self.binding.routing_constraint_snapshot,
            adapter_version_constraint=f"=={certificate.adapter_version}",
        )
        mismatched_binding = replace(
            self.binding,
            tcb_live_digest="e" * 64,
            binding_digest="",
        )
        mismatched_binding = replace(
            mismatched_binding,
            binding_digest=canonical_digest(mismatched_binding),
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certificate_tcb_binding_mismatch",
        ):
            validate_certificate_for_binding(
                self.store,
                binding=mismatched_binding,
                adapter=self.adapter,
                now=NOW,
            )

        with patch(
            "core.providers.certified_execution_tcb.compute_certified_tcb_digest",
            return_value="f" * 64,
        ):
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_tcb_drift"):
                certified_test_provider_store(
                    self.binding,
                    self.adapter,
                    evidence=self.evidence,
                    now=NOW,
                )
            self.assertEqual(
                certificate_profile_status(
                    certificate,
                    status,
                    definition=definition,
                    adapter=self.adapter,
                    now=NOW,
                ),
                "tcb_drift",
            )


if __name__ == "__main__":
    unittest.main()
