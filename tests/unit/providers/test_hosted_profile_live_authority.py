from __future__ import annotations

from datetime import UTC, datetime
import os
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
    GOOGLE_CERTIFIED_REASONING_EFFORTS,
    GOOGLE_DEFAULT_REASONING_EFFORT,
)
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
    OPENROUTER_CERTIFIED_REASONING_EFFORTS,
    OPENROUTER_DEFAULT_REASONING_EFFORT,
)
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CORE_TOOL_HANDLES
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 9, 3, 20, 0, tzinfo=UTC)


class HostedProfileLiveAuthorityTest(unittest.TestCase):
    def test_exact_google_and_openrouter_profiles_resolve_full_live_authority(self) -> None:
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
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            "maverick-tool-loop"
        )
        profiles = (
            (
                state.provider_store.get_agentic_profile_definition(
                    GOOGLE_AGENTIC_PROFILE_ID,
                    GOOGLE_AGENTIC_PROFILE_REVISION,
                ),
                GOOGLE_CERTIFIED_REASONING_EFFORTS,
                GOOGLE_DEFAULT_REASONING_EFFORT,
            ),
            (
                state.provider_store.get_agentic_profile_definition(
                    OPENROUTER_AGENTIC_PROFILE_ID,
                    OPENROUTER_AGENTIC_PROFILE_REVISION,
                ),
                OPENROUTER_CERTIFIED_REASONING_EFFORTS,
                OPENROUTER_DEFAULT_REASONING_EFFORT,
            ),
        )
        capabilities = RuntimeCapabilitySet(
            streaming=True,
            tool_orchestration=True,
            cli=True,
            mcp=True,
            skill_catalog=True,
            filesystem_list=True,
            filesystem_read=True,
            filesystem_write=True,
            shell=True,
            interrupt=True,
            same_turn_steering=True,
            recovery=True,
            confirmation_resume=True,
            provider_private_state=True,
            attachment_modalities=("file",),
            app_references=True,
            confirmations=True,
        )
        for profile, reasoning_efforts, default_effort in profiles:
            with self.subTest(profile=profile.definition_id):
                evidence = fake_capability_evidence(adapter, now=NOW, definition=profile)
                binding = build_runtime_execution_binding(
                    session_id=f"session:{profile.definition_id}",
                    workspace_id="default",
                    profile_definition_id=profile.definition_id,
                    profile_definition_revision=profile.revision,
                    workspace_binding_id=f"binding:{profile.definition_id}",
                    workspace_binding_revision=0,
                    capability_certificate_id=profile.capability_certificate_id,
                    certificate_evidence_digest=evidence.evidence_digest,
                    runtime_engine_id=profile.runtime_engine_id,
                    adapter_id=profile.adapter_id,
                    adapter_version=str(getattr(adapter, "adapter_version")),
                    adapter_artifact_digest=runtime_adapter_artifact_digest(adapter),
                    model_provider_id=profile.model_provider_id,
                    model_id=profile.model_id,
                    model_revision=profile.model_revision,
                    model_revision_policy=profile.model_revision_policy,
                    provider_protocol=profile.provider_protocol,
                    provider_api_version=profile.provider_api_version,
                    routing_constraint=profile.routing_constraint,
                    credential_binding_id=None,
                    reasoning_effort=default_effort,
                    certified_reasoning_efforts=reasoning_efforts,
                    default_reasoning_effort=default_effort,
                    execution_mode="full-access",
                    profile_policy_ceiling=profile.policy_ceiling,
                    workspace_policy_ceiling=profile.policy_ceiling,
                    egress_policy_id=profile.egress_policy_id,
                    egress_policy_revision=profile.egress_policy_revision,
                    created_at=NOW,
                    tcb_manifest_id=evidence.tcb_manifest_id,
                    tcb_manifest_version=evidence.tcb_manifest_version,
                    tcb_structure_digest=evidence.tcb_structure_digest,
                    tcb_live_digest=evidence.tcb_live_digest,
                    full_workspace_contract_revision=(
                        profile.full_workspace_contract_revision
                    ),
                    execution_family=profile.execution_family,
                    harness_recipe_id=profile.harness_recipe_id,
                    harness_recipe_revision=profile.harness_recipe_revision,
                    harness_recipe_digest=profile.harness_recipe_digest,
                    provider_capability_catalog_digest=(
                        profile.provider_capability_catalog_digest
                    ),
                    semantic_projection_compiler_revision=(
                        profile.semantic_projection_compiler_revision
                    ),
                    tool_contract_revision=profile.tool_contract_revision,
                    context_policy=profile.context_policy,
                    provider_config_id=profile.provider_config_id,
                    provider_config_revision=profile.provider_config_revision,
                    provider_config_digest=profile.provider_config_digest,
                    protocol_adapter_id=profile.protocol_adapter_id,
                    protocol_adapter_version=profile.protocol_adapter_version,
                )
                store = certified_test_provider_store(
                    binding,
                    adapter,
                    evidence=evidence,
                    now=NOW,
                    certified_capabilities=capabilities,
                    definition=profile,
                )
                with mock.patch(
                    "core.runtime.authority.feature_enabled",
                    return_value=True,
                ):
                    authority = resolve_effective_runtime_authority(
                        store,
                        binding=binding,
                        adapter=adapter,
                        turn_id=f"turn:{profile.definition_id}",
                        currently_authorized_tool_handles=(
                            FULL_WORKSPACE_CORE_TOOL_HANDLES
                        ),
                        now=NOW,
                    )

                self.assertTrue(authority.allowed_capabilities.cli)
                self.assertTrue(authority.allowed_capabilities.mcp)
                self.assertTrue(authority.allowed_capabilities.app_references)
                self.assertEqual(
                    authority.allowed_tool_handles,
                    FULL_WORKSPACE_CORE_TOOL_HANDLES,
                )


if __name__ == "__main__":
    unittest.main()
