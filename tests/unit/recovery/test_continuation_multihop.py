from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.certification_target import api_profile_target_digest
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
)
from core.recovery.continuation_admission import RuntimeAdmissionAssessment
from core.recovery.continuation_compatibility import prove_compatible_runtime_upgrade
from core.recovery.continuation_fork import admit_runtime_session
from core.recovery.continuation_handoff_service import (
    complete_compatible_continuation_fork,
)
from core.runtime.execution_binding import (
    build_runtime_execution_binding,
    canonical_digest,
)
from tests.support.continuation import NOW, RuntimeContinuationFixture


class RuntimeContinuationMultiHopTest(RuntimeContinuationFixture, unittest.TestCase):
    def test_obsolete_planned_target_is_stopped_before_forking_to_current(self) -> None:
        source = self._source_session("source-multi-hop")
        intermediate = self._intermediate_binding(source)
        capabilities, proof_digest = prove_compatible_runtime_upgrade(
            self.state.provider_store,
            source=source.execution_binding,
            target=intermediate,
            source_reason="adapter_artifact_mismatch",
        )
        assessment = RuntimeAdmissionAssessment(
            status="compatible_upgrade",
            session_id=source.session_id,
            reason_code="runtime_profile_upgrade_compatible",
            detail_code="adapter_artifact_mismatch",
            target_execution_binding=intermediate,
            compatible_capabilities=capabilities,
            compatibility_digest=proof_digest,
        )
        with patch(
            "core.recovery.continuation_handoff_service.ensure_successor_session",
            side_effect=RuntimeError("simulated rev8 planning crash"),
        ):
            with self.assertRaisesRegex(RuntimeError, "rev8 planning crash"):
                complete_compatible_continuation_fork(
                    self.state,
                    predecessor=source,
                    assessment=assessment,
                    now=NOW,
                )

        result = admit_runtime_session(self.state, session=source, now=NOW)

        middle = self.state.runtime_store.get_session(intermediate.session_id)
        final = result.session
        self.assertEqual(result.status, "forked")
        self.assertEqual(middle.status, "stopped")
        self.assertEqual(middle.execution_binding.profile_definition_revision, "8")
        self.assertEqual(final.status, "running")
        self.assertEqual(final.execution_binding.profile_definition_revision, self.target.profile_definition_revision)
        self.assertEqual(final.predecessor_session_id, middle.session_id)
        self.assertEqual(
            self.state.runtime_store.get_thread(source.session_id).runtime_session_id,
            final.session_id,
        )
        provider_thread_ids = {
            self.state.runtime_store.get_provider_state(session.session_id).provider_thread_id
            for session in (source, middle, final)
        }
        self.assertEqual(provider_thread_ids, {"provider-thread-source-multi-hop"})

    def _intermediate_binding(self, source):
        source_binding = source.execution_binding
        current_definition = self.state.provider_store.get_agentic_profile_definition(
            source_binding.profile_definition_id,
            self.target.profile_definition_revision,
        )
        current_workspace_binding = (
            self.state.provider_store.get_workspace_agentic_profile_binding(
                source_binding.workspace_binding_id
            )
        )
        source_certificate = self.state.provider_store.get_capability_certificate(
            source_binding.capability_certificate_id
        )
        artifact_digest = "3" * 64
        intermediate_definition = replace(
            current_definition,
            revision="8",
            capability_certificate_id="intermediate-revision-8-certificate",
        )
        evidence = build_capability_evidence(
            suite_id=source_certificate.suite_id,
            suite_version=source_certificate.suite_version,
            test_run_id="intermediate-revision-8",
            adapter_artifact_digest=artifact_digest,
            result_summary_digest=canonical_digest({"revision": "8"}),
            evidence_refs=source_certificate.evidence_refs,
            recorded_at=NOW,
            certification_target_digest=api_profile_target_digest(intermediate_definition),
            **{name: getattr(source_certificate, name) for name in (
                "tcb_manifest_id", "tcb_manifest_version", "tcb_structure_digest", "tcb_live_digest",
            )},
        )
        certificate = replace(
            source_certificate,
            certificate_id="intermediate-revision-8-certificate",
            adapter_artifact_digest=artifact_digest,
            test_run_id=evidence.test_run_id,
            evidence_digest=evidence.evidence_digest,
            certification_target_digest=evidence.certification_target_digest,
        )
        publish_capability_certificate(
            self.state.provider_store,
            certificate=certificate,
            evidence=evidence,
        )
        self.state.provider_store.save_agentic_profile_definition(
            intermediate_definition
        )
        self.state.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=intermediate_definition.definition_id,
                definition_revision="8",
                rollout_status="suspended",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        intermediate_workspace_binding = replace(
            current_workspace_binding,
            binding_id="intermediate-revision-8-binding",
            definition_revision="8",
            is_default=False,
            revision=0,
        )
        self.state.provider_store.save_workspace_agentic_profile_binding(
            intermediate_workspace_binding,
            expected_revision=None,
        )
        return build_runtime_execution_binding(
            session_id="middle-multi-hop",
            workspace_id=source_binding.workspace_id,
            profile_definition_id=source_binding.profile_definition_id,
            profile_definition_revision="8",
            workspace_binding_id=intermediate_workspace_binding.binding_id,
            workspace_binding_revision=intermediate_workspace_binding.revision,
            capability_certificate_id=certificate.certificate_id,
            runtime_engine_id=source_binding.runtime_engine_id,
            adapter_id=source_binding.adapter_id,
            adapter_version=source_binding.adapter_version,
            adapter_artifact_digest=artifact_digest,
            model_provider_id=source_binding.model_provider_id,
            model_id=source_binding.model_id,
            provider_protocol=source_binding.provider_protocol,
            provider_api_version=source_binding.provider_api_version,
            routing_constraint=source_binding.routing_constraint_snapshot,
            credential_binding_id=source_binding.credential_binding_id,
            reasoning_effort=source_binding.reasoning_effort,
            certified_reasoning_efforts=source_binding.certified_reasoning_efforts,
            default_reasoning_effort=source_binding.default_reasoning_effort,
            execution_mode=source_binding.execution_mode,
            profile_policy_ceiling=source_binding.profile_policy_ceiling_snapshot,
            workspace_policy_ceiling=source_binding.workspace_policy_ceiling_snapshot,
            egress_policy_id=source_binding.egress_policy_id,
            egress_policy_revision=source_binding.egress_policy_revision,
            certificate_evidence_digest=evidence.evidence_digest,
            created_at=NOW,
            context_policy=intermediate_definition.context_policy,
            **{name: getattr(intermediate_definition, name) for name in (
                "model_revision", "model_revision_policy", "full_workspace_contract_revision",
                "execution_family", "harness_recipe_id", "harness_recipe_revision", "harness_recipe_digest",
                "provider_capability_catalog_digest", "semantic_projection_compiler_revision",
                "tool_contract_revision", "provider_config_id", "provider_config_revision",
                "provider_config_digest", "protocol_adapter_id", "protocol_adapter_version",
            )},
        )


if __name__ == "__main__":
    unittest.main()
