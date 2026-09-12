from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from pathlib import Path
from unittest import mock
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certificate_projection import certificate_profile_status
from core.providers.certification_target import api_profile_target_digest
from core.providers.certification_pipeline import (
    SignedCertificationRun,
    execute_certification_suite,
    sign_certification_run,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.openrouter_agentic_certification import (
    OPENROUTER_CERTIFICATION_MATRIX_REVISION,
    OPENROUTER_CERTIFICATION_SUITE_ID,
    OPENROUTER_CERTIFICATION_SUITE_VERSION,
    publish_openrouter_preview_certificate,
)
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
)
from core.providers.openrouter_agentic_models import OPENROUTER_AGENTIC_MODEL_REVISION
from core.providers.maverick_agent_builtins import (
    OPENROUTER_CHAT_PROTOCOL_ADAPTER,
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
)
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    MAVERICK_AGENT_EXECUTION_FAMILY,
)
from core.runtime.hosted_harness_recipes import OPENROUTER_GOVERNED_WORKSPACE_RECIPE
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 17, tzinfo=UTC)


from tests.support.certification_evidence import fixture_step_process, with_fixture_behavior

class OpenRouterAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_exact_expiring_unbound_full_workspace_profile(self) -> None:
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
            OPENROUTER_AGENTIC_PROFILE_ID,
            OPENROUTER_AGENTIC_PROFILE_REVISION,
        )
        status = state.provider_store.get_agentic_profile_definition_status(
            profile.definition_id,
            profile.revision,
        )
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            profile.runtime_engine_id
        )

        self.assertEqual(status.rollout_status, "available")
        self.assertEqual(profile.revision, "6")
        self.assertEqual(profile.adapter_version_constraint, "==59")
        self.assertEqual(
            profile.policy_ceiling.allowed_surface_kinds,
            ("cli", "mcp", "app-interface", "core-capability"),
        )
        self.assertEqual(profile.model_provider_id, "openrouter")
        self.assertEqual(profile.model_id, "z-ai/glm-5.3-flash")
        self.assertEqual(profile.model_revision, OPENROUTER_AGENTIC_MODEL_REVISION)
        self.assertEqual(profile.model_revision_policy, "provider_alias")
        self.assertEqual(profile.provider_protocol, "openrouter-chat-completions")
        self.assertEqual(
            (
                profile.provider_config_id,
                profile.provider_config_revision,
                profile.provider_config_digest,
            ),
            (
                OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.config_id,
                OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.revision,
                OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.digest,
            ),
        )
        self.assertEqual(
            (
                profile.protocol_adapter_id,
                profile.protocol_adapter_version,
            ),
            (
                OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_id,
                OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_version,
            ),
        )
        self.assertEqual(
            OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.token_cost_policy.input_microusd_per_million_tokens,
            90_000,
        )
        self.assertEqual(
            OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.token_cost_policy.output_microusd_per_million_tokens,
            300_000,
        )
        routing = profile.routing_constraint
        self.assertEqual(routing.allowed_upstream_ids, ("relace",))
        self.assertFalse(routing.allow_fallbacks)
        self.assertTrue(routing.require_parameters)
        self.assertEqual(routing.data_collection_policy, "deny")
        self.assertTrue(routing.require_zdr)
        self.assertEqual(routing.allowed_quantizations, ("unknown",))
        self.assertEqual(
            profile.policy_ceiling.allowed_remote_data_classes,
            (
                "public",
                "workspace_internal",
                "personal_data",
                "regulated_or_customer_data",
            ),
        )
        self.assertEqual(
            profile.egress_policy_id,
            "remote-agentic-full-workspace",
        )
        self.assertEqual(profile.egress_policy_revision, "1")
        self.assertEqual(
            profile.full_workspace_contract_revision,
            FULL_WORKSPACE_CONTRACT_REVISION,
        )
        self.assertEqual(
            profile.execution_family,
            MAVERICK_AGENT_EXECUTION_FAMILY,
        )
        self.assertEqual(
            profile.harness_recipe_id,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.recipe_id,
        )
        self.assertEqual(
            profile.harness_recipe_digest,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.recipe_digest,
        )
        self.assertEqual(
            profile.context_policy,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.context_policy,
        )
        with self.assertRaises(ProviderNotFoundError):
            state.provider_store.get_capability_certificate(profile.capability_certificate_id)
        self.assertEqual(
            profile.policy_ceiling.tool_handle_mode,
            "all_currently_authorized",
        )
        self.assertEqual(profile.policy_ceiling.allowed_tool_handles, ())
        self.assertEqual(profile.policy_ceiling.max_steps_per_turn, 256)
        self.assertEqual(profile.policy_ceiling.max_tool_calls_per_turn, 256)
        self.assertEqual(profile.policy_ceiling.max_wall_time_seconds, 86_400)
        self.assertEqual(profile.policy_ceiling.max_input_tokens, 1_000_000)
        self.assertEqual(profile.policy_ceiling.max_output_tokens, 128_000)
        self.assertIsNone(profile.policy_ceiling.max_estimated_cost_microusd)
        self.assertFalse(
            profile.policy_ceiling.require_confirmation_for_mutating
        )
        self.assertFalse(
            profile.policy_ceiling.require_confirmation_for_destructive
        )
        self.assertEqual(
            profile.context_policy.max_request_input_tokens,
            1_000_000,
        )
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings("default")
            )
        )

        private_key = Ed25519PrivateKey.generate()
        repository_root = Path(__file__).resolve().parents[3]
        with mock.patch(
            "core.providers.certification_pipeline._require_clean_checkout"
        ), mock.patch(
            "core.providers.certification_pipeline._git_commit",
            return_value="a" * 40,
        ), mock.patch(
            "core.providers.certification_pipeline.subprocess.run",
            side_effect=fixture_step_process,
        ):
            fixture_run = execute_certification_suite(
                cwd=repository_root,
                suite_id=OPENROUTER_CERTIFICATION_SUITE_ID,
                suite_version=OPENROUTER_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
                evidence_refs=("platform-evidence:test-run:openrouter-fixture",),
                started_at=NOW,
                step_kinds=("fixture_contract",),
            )
            run = execute_certification_suite(
                cwd=repository_root,
                suite_id=OPENROUTER_CERTIFICATION_SUITE_ID,
                suite_version=OPENROUTER_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
                evidence_refs=("platform-evidence:test-run:openrouter",),
                started_at=NOW,
            )
        run = with_fixture_behavior(run)
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_required_steps_missing",
        ):
            publish_openrouter_preview_certificate(
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
        with mock.patch(
            "core.providers.certification_pipeline._git_commit",
            return_value="a" * 40,
        ):
            certificate = publish_openrouter_preview_certificate(
                state.provider_store,
                definition=profile,
                adapter=adapter,
                signed_run=signed,
                trusted_keys={"test-ci": private_key.public_key()},
            )
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_target_mismatch"):
            publish_openrouter_preview_certificate(
                state.provider_store, definition=replace(profile, model_id="unproven-model"),
                adapter=adapter, signed_run=signed, trusted_keys={"test-ci": private_key.public_key()},
            )
        evidence = state.provider_store.get_capability_evidence(
            certificate.evidence_digest
        )
        self.assertEqual(certificate.certification_target_digest, run.target_digest)
        self.assertEqual(evidence.certification_target_digest, run.target_digest)
        revised = replace(
            profile, revision=f"{profile.revision}-uncertified",
            policy_ceiling=replace(
                profile.policy_ceiling,
                max_steps_per_turn=profile.policy_ceiling.max_steps_per_turn * 2,
                max_tool_calls_per_turn=profile.policy_ceiling.max_tool_calls_per_turn * 2,
            ),
        )
        state.provider_store.save_agentic_profile_definition(revised)
        self.assertNotEqual(api_profile_target_digest(revised), run.target_digest)
        for definition, expected_status in (
            (profile, "active"), (revised, "certificate_target_mismatch"),
        ):
            self.assertEqual(certificate_profile_status(
                certificate,
                state.provider_store.get_capability_certificate_status(certificate.certificate_id),
                definition=definition, adapter=adapter, now=NOW,
                store=state.provider_store,
            ), expected_status)
        self.assertTrue(certificate.certified_capabilities.filesystem_list)
        self.assertTrue(certificate.certified_capabilities.filesystem_write)
        self.assertTrue(certificate.certified_capabilities.shell)
        self.assertTrue(certificate.certified_capabilities.recovery)
        self.assertEqual(
            certificate.full_workspace_contract_revision,
            FULL_WORKSPACE_CONTRACT_REVISION,
        )
        self.assertEqual(
            certificate.execution_family,
            MAVERICK_AGENT_EXECUTION_FAMILY,
        )
        self.assertEqual(certificate.harness_recipe_digest, profile.harness_recipe_digest)
        self.assertEqual(
            (
                certificate.provider_config_id,
                certificate.provider_config_revision,
                certificate.provider_config_digest,
                certificate.protocol_adapter_id,
                certificate.protocol_adapter_version,
            ),
            (
                profile.provider_config_id,
                profile.provider_config_revision,
                profile.provider_config_digest,
                profile.protocol_adapter_id,
                profile.protocol_adapter_version,
            ),
        )
        self.assertEqual(
            certificate.context_policy_revision,
            profile.context_policy.revision,
        )
        self.assertEqual(
            certificate.certified_reasoning_efforts,
            ("max", "high", "low"),
        )
        self.assertEqual(certificate.default_reasoning_effort, "max")
        self.assertEqual(evidence.matrix_revision, OPENROUTER_CERTIFICATION_MATRIX_REVISION)

        self.assertEqual(
            OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
            ("1", "2", "3", "4", "5"),
        )


if __name__ == "__main__":
    unittest.main()
