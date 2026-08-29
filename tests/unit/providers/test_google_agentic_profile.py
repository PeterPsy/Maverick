from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_pipeline import (
    SignedCertificationRun,
    execute_certification_suite,
    sign_certification_run,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.google_agentic_certification import (
    GOOGLE_CERTIFICATION_MATRIX_REVISION,
    GOOGLE_CERTIFICATION_SUITE_ID,
    GOOGLE_CERTIFICATION_SUITE_VERSION,
    publish_google_preview_certificate,
)
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
    GOOGLE_AGENTIC_PROFILE_REVISION,
    ensure_google_agentic_preview_profile,
)
from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)
from core.runtime.hosted_harness_recipes import GOOGLE_FULL_WORKSPACE_RECIPE
from core.runtime.hosted_agentic_factory import classify_hosted_content_fail_closed
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class GoogleAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_unbound_full_workspace_candidate(self) -> None:
        root = make_temp_repo_root(self)
        with mock.patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )

        profile = state.provider_store.get_agentic_profile_definition(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        status = state.provider_store.get_agentic_profile_definition_status(
            profile.definition_id,
            profile.revision,
        )
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            profile.runtime_engine_id
        )

        production_classification = adapter.loop.request_builder.classifier(
            SimpleNamespace(
                session=SimpleNamespace(session_id="production-session"),
                correlation_id="production-turn",
            ),
            "user_input",
            "ordinary production prompt",
        )

        self.assertEqual(status.rollout_status, "preview")
        self.assertEqual(profile.revision, "27")
        self.assertEqual(profile.adapter_version_constraint, "==19")
        self.assertEqual(profile.model_id, "gemini-3.6-flash")
        self.assertEqual(profile.provider_api_version, "v1")
        self.assertEqual(profile.policy_ceiling.allowed_remote_data_classes, ("public",))
        self.assertEqual(production_classification.data_class, "unclassified")
        self.assertIsNone(production_classification.classification_revision)
        for resource_provenance in (
            "attachment",
            "skill",
            "workspace_instruction",
            "provider_state",
            "tool_schema",
        ):
            with self.subTest(resource_provenance=resource_provenance):
                self.assertEqual(
                    adapter.loop.request_builder.classifier(
                        SimpleNamespace(
                            session=SimpleNamespace(
                                session_id="production-session"
                            ),
                            correlation_id="production-turn",
                        ),
                        resource_provenance,
                        {"unclassified": True},
                    ).data_class,
                    "unclassified",
                )
        self.assertEqual(profile.egress_policy_id, "remote-agentic-contained")
        self.assertEqual(profile.egress_policy_revision, "2")
        self.assertEqual(
            profile.full_workspace_contract_revision,
            FULL_WORKSPACE_CONTRACT_REVISION,
        )
        self.assertEqual(profile.execution_family, "maverick_agent")
        self.assertEqual(profile.harness_recipe_id, GOOGLE_FULL_WORKSPACE_RECIPE.recipe_id)
        self.assertEqual(profile.harness_recipe_digest, GOOGLE_FULL_WORKSPACE_RECIPE.recipe_digest)
        self.assertEqual(profile.context_policy, GOOGLE_FULL_WORKSPACE_RECIPE.context_policy)
        self.assertEqual(
            profile.policy_ceiling.allowed_tool_handles,
            FULL_WORKSPACE_CORE_TOOL_HANDLES,
        )
        with self.assertRaises(ProviderNotFoundError):
            state.provider_store.get_capability_certificate(profile.capability_certificate_id)

        private_key = Ed25519PrivateKey.generate()
        repository_root = Path(__file__).resolve().parents[3]
        completed = mock.Mock(returncode=0, stdout=b"passed", stderr=b"")
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch("core.providers.certification_pipeline.subprocess.run", return_value=completed):
            fixture_run = execute_certification_suite(
                cwd=repository_root,
                suite_id=GOOGLE_CERTIFICATION_SUITE_ID,
                suite_version=GOOGLE_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
                evidence_refs=("platform-evidence:test-run:google-fixture",),
                started_at=NOW,
                step_kinds=("fixture_contract",),
            )
            run = execute_certification_suite(
                cwd=repository_root,
                suite_id=GOOGLE_CERTIFICATION_SUITE_ID,
                suite_version=GOOGLE_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
                evidence_refs=("platform-evidence:test-run:google",),
                started_at=NOW,
            )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_required_steps_missing",
        ):
            publish_google_preview_certificate(
                state.provider_store,
                definition=profile,
                adapter=adapter,
                signed_run=SignedCertificationRun(
                    run=fixture_run,
                    signer_key_id="test-ci",
                    signature="fixture-only-is-not-certificate-evidence",
                ),
                trusted_keys={"test-ci": private_key.public_key()},
            )
        with self.assertRaises(ProviderNotFoundError):
            state.provider_store.get_capability_certificate(
                profile.capability_certificate_id
            )
        signed = sign_certification_run(
            run,
            signer_key_id="test-ci",
            private_key=private_key,
        )
        with mock.patch("core.providers.certification_pipeline._git_commit", return_value="a" * 40):
            certificate = publish_google_preview_certificate(
                state.provider_store,
                definition=profile,
                adapter=adapter,
                signed_run=signed,
                trusted_keys={"test-ci": private_key.public_key()},
            )
        evidence = state.provider_store.get_capability_evidence(certificate.evidence_digest)
        self.assertEqual(certificate.test_run_id, run.test_run_id)
        self.assertEqual(evidence.source_commit, run.source_commit)
        self.assertEqual(evidence.artifact_bundle_digest, run.artifact_bundle_digest)
        self.assertEqual(evidence.matrix_revision, GOOGLE_CERTIFICATION_MATRIX_REVISION)
        self.assertEqual(evidence.certification_outcome, "passed")
        self.assertTrue(certificate.certified_capabilities.filesystem_list)
        self.assertTrue(certificate.certified_capabilities.filesystem_write)
        self.assertTrue(certificate.certified_capabilities.shell)
        self.assertTrue(certificate.certified_capabilities.recovery)
        self.assertEqual(certificate.harness_recipe_digest, profile.harness_recipe_digest)
        self.assertEqual(
            certificate.context_policy_revision,
            profile.context_policy.revision,
        )
        self.assertEqual(
            certificate.certified_reasoning_efforts,
            ("high",),
        )
        self.assertEqual(certificate.default_reasoning_effort, "high")
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings("default")
            )
        )

        google = state.provider_registry.get_provider_definition("google-ai-studio")
        model = next(option for option in google.model_options if option.model_id == profile.model_id)
        self.assertEqual(model.metadata["lifecycle"], "stable")
        self.assertEqual(model.metadata["protocol"], "google-interactions")

        state.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=GOOGLE_AGENTIC_PROFILE_ID,
                definition_revision=GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
                rollout_status="preview",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        ensure_google_agentic_preview_profile(
            state.provider_store,
            adapter=adapter,
            now=NOW + timedelta(seconds=1),
        )
        previous = state.provider_store.get_agentic_profile_definition_status(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
        )
        self.assertEqual(previous.rollout_status, "suspended")
        self.assertEqual(previous.revision, 1)

    def test_explicit_fail_closed_classifier_never_assumes_data_is_fake(self) -> None:
        self.assertEqual(
            classify_hosted_content_fail_closed(None, "user_input", "synthetic-looking text").data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(None, "tool_result", {"value": 4}).data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(None, "tool_schema", {}).data_class,
            "unclassified",
        )

    def test_classifier_ignores_persisted_legacy_declaration(self) -> None:
        context = SimpleNamespace(
            session=SimpleNamespace(declared_remote_data_class="legacy-non-authoritative")
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(context, "user_input", "fixture").data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(context, "tool_result", {"fixture": True}).data_class,
            "unclassified",
        )


if __name__ == "__main__":
    unittest.main()
