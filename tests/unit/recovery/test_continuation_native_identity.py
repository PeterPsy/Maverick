"""Native connection authority must fail before generic continuation upgrade."""

import unittest

from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import admit_runtime_session
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from tests.support.continuation import NOW, RuntimeContinuationFixture


class NativeContinuationIdentityTest(RuntimeContinuationFixture, unittest.TestCase):
    def test_changed_codex_artifact_cannot_borrow_current_connection_authority(self):
        store = self.state.provider_store
        codex = next(
            binding for binding in store.list_workspace_agentic_profile_bindings("default")
            if binding.enabled and store.get_agentic_profile_definition(
                binding.definition_id, binding.definition_revision,
            ).runtime_engine_id == "codex"
        )
        definition = store.get_agentic_profile_definition(codex.definition_id, codex.definition_revision)
        certificate = store.get_capability_certificate(definition.capability_certificate_id)
        evidence = store.get_capability_evidence(certificate.evidence_digest)
        for label, options in (("artifact", {}), ("model", {"source_model_id": "different-model"}),
                               ("routing", {"routing_mismatch": True})):
            with self.subTest(label=label):
                source = self._source_session(
                    f"native-source-{label}", target_workspace_binding_id=codex.binding_id, **options,
                )
                provider_state = self.state.runtime_store.get_provider_state(source.session_id)
                assessment = assess_runtime_session_admission(
                    store, self.state.runtime_store, self.state.provider_registry,
                    session=source, target_session_id=f"native-target-{label}", now=NOW,
                )
                self.assertEqual(assessment.status, "upgrade_required")
                self.assertEqual(assessment.detail_code, "native_agent_connection_identity_mismatch")
                with self.assertRaises(RuntimeProfileUpgradeRequiredError):
                    admit_runtime_session(self.state, session=source, now=NOW)
                self.assertEqual(self.state.runtime_store.get_session(source.session_id), source)
                self.assertEqual(self.state.runtime_store.get_provider_state(source.session_id), provider_state)
                self.assertIsNone(self.state.runtime_store.get_continuation_handoff_by_predecessor(
                    workspace_id="default", predecessor_session_id=source.session_id,
                ))
        self.assertEqual(store.get_workspace_agentic_profile_binding(codex.binding_id), codex)
        self.assertEqual(store.get_capability_certificate(certificate.certificate_id), certificate)
        self.assertEqual(store.get_capability_evidence(evidence.evidence_digest), evidence)


if __name__ == "__main__":
    unittest.main()
