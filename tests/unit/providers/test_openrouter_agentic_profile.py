from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
    OPENROUTER_AGENTIC_SUPERSEDED_PROFILE_DEFINITIONS,
    OPENROUTER_DEFAULT_REASONING_EFFORT,
    OPENROUTER_REASONING_EFFORTS,
    ensure_openrouter_agentic_preview_profile,
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


class OpenRouterAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_direct_unbound_full_workspace_profile(self) -> None:
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
        self.assertEqual(profile.definition_id, OPENROUTER_AGENTIC_PROFILE_ID)
        self.assertEqual(profile.revision, OPENROUTER_AGENTIC_PROFILE_REVISION)
        self.assertEqual(profile.adapter_version_constraint, "==59")
        self.assertEqual(profile.model_provider_id, "openrouter")
        self.assertEqual(profile.model_id, "z-ai/glm-5.3-flash")
        self.assertEqual(profile.model_revision, OPENROUTER_AGENTIC_MODEL_REVISION)
        self.assertEqual(profile.model_revision_policy, "provider_alias")
        self.assertEqual(profile.provider_protocol, "openrouter-chat-completions")
        self.assertEqual(profile.reasoning_efforts, OPENROUTER_REASONING_EFFORTS)
        self.assertEqual(
            profile.default_reasoning_effort,
            OPENROUTER_DEFAULT_REASONING_EFFORT,
        )
        self.assertTrue(profile.capabilities.streaming)
        self.assertTrue(profile.capabilities.tool_orchestration)
        self.assertTrue(profile.capabilities.cli)
        self.assertTrue(profile.capabilities.mcp)
        self.assertTrue(profile.capabilities.filesystem_read)
        self.assertTrue(profile.capabilities.filesystem_write)
        self.assertTrue(profile.capabilities.shell)
        self.assertTrue(profile.capabilities.recovery)
        self.assertEqual(profile.capabilities.attachment_modalities, ("file",))
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
            (profile.protocol_adapter_id, profile.protocol_adapter_version),
            (
                OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_id,
                OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_version,
            ),
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
        self.assertEqual(profile.egress_policy_id, "remote-agentic-full-workspace")
        self.assertEqual(profile.egress_policy_revision, "1")
        self.assertEqual(
            profile.full_workspace_contract_revision,
            FULL_WORKSPACE_CONTRACT_REVISION,
        )
        self.assertEqual(profile.execution_family, MAVERICK_AGENT_EXECUTION_FAMILY)
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
        self.assertEqual(profile.policy_ceiling.tool_handle_mode, "all_currently_authorized")
        self.assertEqual(profile.policy_ceiling.allowed_tool_handles, ())
        self.assertEqual(profile.policy_ceiling.max_steps_per_turn, 256)
        self.assertEqual(profile.policy_ceiling.max_tool_calls_per_turn, 256)
        self.assertEqual(profile.policy_ceiling.max_wall_time_seconds, 86_400)
        self.assertEqual(profile.policy_ceiling.max_input_tokens, 1_000_000)
        self.assertEqual(profile.policy_ceiling.max_output_tokens, 128_000)
        self.assertIsNone(profile.policy_ceiling.max_estimated_cost_microusd)
        self.assertFalse(profile.policy_ceiling.require_confirmation_for_mutating)
        self.assertFalse(profile.policy_ceiling.require_confirmation_for_destructive)
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings(
                    "default"
                )
            )
        )

        legacy_id, legacy_revision = OPENROUTER_AGENTIC_SUPERSEDED_PROFILE_DEFINITIONS[-1]
        state.provider_store.save_agentic_profile_definition(
            replace(profile, definition_id=legacy_id, revision=legacy_revision)
        )
        state.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=legacy_id,
                definition_revision=legacy_revision,
                rollout_status="available",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        ensure_openrouter_agentic_preview_profile(
            state.provider_store,
            adapter=adapter,
            now=NOW,
        )
        self.assertEqual(
            state.provider_store.get_agentic_profile_definition_status(
                legacy_id,
                legacy_revision,
            ).rollout_status,
            "suspended",
        )
        self.assertEqual(
            OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
            ("1", "2", "3"),
        )


if __name__ == "__main__":
    unittest.main()
