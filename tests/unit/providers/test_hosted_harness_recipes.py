from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch
import unittest

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    EphemeralCredential,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.google_agentic_profile import (
    google_agentic_preview_policy,
    google_interactions_routing_constraint,
)
from core.providers.google_interactions_catalog import (
    GoogleInteractionsCatalogSnapshot,
)
from core.providers.hosted_endpoint_preflight import (
    preflight_google_interactions_request,
    preflight_openrouter_completion_request,
)
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
    OPENROUTER_CHAT_PROTOCOL_ADAPTER,
    OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
)
from core.providers.openrouter_agentic_catalog import (
    OpenRouterAgenticCatalogSnapshot,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_preview_policy,
    openrouter_agentic_routing_constraint,
)
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CONTRACT_REVISION
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_context_management import (
    HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
)
from core.runtime.hosted_harness_recipes import (
    GOOGLE_GOVERNED_WORKSPACE_RECIPE,
    OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
)
from core.runtime.hosted_runtime_registry_builder import (
    build_hosted_provider_runtime_registry,
)


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedHarnessRecipeTest(unittest.TestCase):
    def test_review_closure_publishes_new_immutable_recipe_identities(self) -> None:
        for recipe in (
            GOOGLE_GOVERNED_WORKSPACE_RECIPE,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
        ):
            with self.subTest(recipe_id=recipe.recipe_id):
                self.assertEqual(
                    recipe.revision, "24" if recipe.model_provider_id == "google-ai-studio" else "25",
                )
                self.assertEqual(
                    recipe.semantic_projection_compiler_revision,
                    "10",
                )
                self.assertEqual(
                    recipe.tool_contract_revision,
                    FULL_WORKSPACE_CONTRACT_REVISION,
                )
                self.assertEqual(recipe.context_policy.revision, "p4-context-v4")
        self.assertEqual(HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION, "3")

    def test_registry_resolves_only_the_exact_recipe_and_catalog_identity(self) -> None:
        registry = build_hosted_provider_runtime_registry()
        binding = _binding(GOOGLE_GOVERNED_WORKSPACE_RECIPE)

        with patch(
            "core.runtime.hosted_provider_runtime.require_remote_agentic_dispatch"
        ):
            runtime = registry.resolve(binding)

        self.assertEqual(runtime.recipe, GOOGLE_GOVERNED_WORKSPACE_RECIPE)
        self.assertEqual(runtime.client.model_id, GOOGLE_GOVERNED_WORKSPACE_RECIPE.model_id)
        self.assertEqual(runtime.client.state_mode, "stateless")
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "provider_capability_catalog_mismatch",
        ), patch(
            "core.runtime.hosted_provider_runtime.require_remote_agentic_dispatch"
        ):
            registry.resolve(replace(binding, provider_capability_catalog_digest="f" * 64))
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "harness_recipe_mismatch",
        ), patch(
            "core.runtime.hosted_provider_runtime.require_remote_agentic_dispatch"
        ):
            registry.resolve(replace(binding, context_policy_snapshot=None))
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "provider_config_identity_mismatch",
        ), patch(
            "core.runtime.hosted_provider_runtime.require_remote_agentic_dispatch"
        ):
            registry.resolve(replace(binding, provider_config_digest="f" * 64))

    def test_catalog_digest_covers_fine_grained_endpoint_flags(self) -> None:
        changed = replace(
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
            support_flags=replace(
                OPENROUTER_GOVERNED_WORKSPACE_RECIPE.support_flags,
                supports_tool_choice_none=True,
            ),
        )

        self.assertNotEqual(
            changed.capability_catalog_digest,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.capability_catalog_digest,
        )
        self.assertNotEqual(
            changed.recipe_digest,
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.recipe_digest,
        )

    def test_google_final_preflight_omits_tools(self) -> None:
        catalog = GoogleInteractionsCatalogSnapshot(
            api_version="v1",
            operation_id="CreateInteraction",
            model_name="models/gemini-3.6-flash",
            model_version="stable-2026-07",
            input_token_limit=1_048_576,
            output_token_limit=65_536,
            streaming=True,
            usage_accounting=True,
            tool_calling=True,
            endpoint_schema_digest="a" * 64,
            model_record_digest="b" * 64,
            catalog_snapshot_digest="c" * 64,
        )
        with patch(
            "core.providers.hosted_endpoint_preflight."
            "preflight_google_interactions_catalog",
            return_value=catalog,
        ):
            exploration = preflight_google_interactions_request(
                _request(GOOGLE_GOVERNED_WORKSPACE_RECIPE, final=False),
                EphemeralCredential("synthetic-google-key"),
            )
            final = preflight_google_interactions_request(
                _request(GOOGLE_GOVERNED_WORKSPACE_RECIPE, final=True),
                EphemeralCredential("synthetic-google-key"),
            )

        self.assertEqual(exploration.tool_catalog_mode, "declared")
        self.assertTrue(exploration.tool_calling)
        self.assertEqual(final.tool_catalog_mode, "omitted")
        self.assertEqual(final.tool_choice_mode, "provider-default")
        self.assertNotEqual(exploration.snapshot_digest, final.snapshot_digest)

    def test_openrouter_final_preflight_requires_omission_without_explicit_none_support(self) -> None:
        catalog = OpenRouterAgenticCatalogSnapshot(
            upstream_id="deepinfra/fp8",
            supported_parameters=(
                "max_tokens",
                "reasoning",
                "reasoning_effort",
                "tool_choice",
                "tools",
            ),
            model_catalog_record_digest="a" * 64,
            zdr_catalog_record_digest="b" * 64,
            supports_tool_choice_none=False,
            context_length=1_048_576,
            max_completion_tokens=65_536,
            catalog_snapshot_digest="c" * 64,
        )
        with patch(
            "core.providers.hosted_endpoint_preflight."
            "preflight_openrouter_agentic_catalog",
            return_value=catalog,
        ):
            exploration = preflight_openrouter_completion_request(
                _request(OPENROUTER_GOVERNED_WORKSPACE_RECIPE, final=False),
                EphemeralCredential("synthetic-openrouter-key"),
            )
            final = preflight_openrouter_completion_request(
                _request(OPENROUTER_GOVERNED_WORKSPACE_RECIPE, final=True),
                EphemeralCredential("synthetic-openrouter-key"),
            )

        self.assertEqual(exploration.tool_choice_mode, "auto")
        self.assertEqual(exploration.tool_catalog_mode, "declared")
        self.assertEqual(final.tool_choice_mode, "provider-default")
        self.assertEqual(final.tool_catalog_mode, "omitted")
        self.assertNotEqual(exploration.snapshot_digest, final.snapshot_digest)


def _binding(recipe):
    policy = (
        google_agentic_preview_policy()
        if recipe.model_provider_id == "google-ai-studio"
        else openrouter_agentic_preview_policy()
    )
    routing = (
        google_interactions_routing_constraint()
        if recipe.model_provider_id == "google-ai-studio"
        else openrouter_agentic_routing_constraint()
    )
    config, protocol_adapter = (
        (
            GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
            GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
        )
        if recipe.model_provider_id == "google-ai-studio"
        else (
            OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
            OPENROUTER_CHAT_PROTOCOL_ADAPTER,
        )
    )
    return build_runtime_execution_binding(
        session_id="session-recipe",
        workspace_id="default",
        profile_definition_id="profile-recipe",
        profile_definition_revision="1",
        workspace_binding_id="binding-recipe",
        workspace_binding_revision=1,
        capability_certificate_id="certificate-recipe",
        certificate_evidence_digest="a" * 64,
        runtime_engine_id="maverick-tool-loop",
        adapter_id="maverick-hosted-tool-loop",
        adapter_version=protocol_adapter.runtime_adapter_version,
        adapter_artifact_digest="b" * 64,
        model_provider_id=recipe.model_provider_id,
        model_id=recipe.model_id,
        model_revision=recipe.model_revision,
        model_revision_policy=recipe.model_revision_policy,
        provider_protocol=recipe.provider_protocol,
        provider_api_version=recipe.provider_api_version,
        routing_constraint=routing,
        credential_binding_id="credential-recipe",
        reasoning_effort=recipe.support_flags.reasoning_efforts[-1],
        certified_reasoning_efforts=recipe.support_flags.reasoning_efforts,
        default_reasoning_effort=recipe.support_flags.reasoning_efforts[-1],
        execution_mode="full-access",
        profile_policy_ceiling=policy,
        workspace_policy_ceiling=policy,
        egress_policy_id="remote-agentic-contained",
        egress_policy_revision="2",
        created_at=NOW,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family="maverick_agent",
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.recipe_digest,
        provider_capability_catalog_digest=recipe.capability_catalog_digest,
        semantic_projection_compiler_revision=(
            recipe.semantic_projection_compiler_revision
        ),
        tool_contract_revision=recipe.tool_contract_revision,
        context_policy=recipe.context_policy,
        provider_config_id=config.config_id,
        provider_config_revision=config.revision,
        provider_config_digest=config.digest,
        protocol_adapter_id=protocol_adapter.protocol_adapter_id,
        protocol_adapter_version=protocol_adapter.protocol_adapter_version,
    )


def _request(recipe, *, final: bool) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=f"recipe-request-{'final' if final else 'explore'}",
        correlation_id="recipe-turn",
        model_id=recipe.model_id,
        model_revision=recipe.model_revision,
        model_revision_policy=recipe.model_revision_policy,
        reasoning_effort=recipe.support_flags.reasoning_efforts[-1],
        content_blocks=(
            AgenticRequestContentBlock(
                content_block_id="recipe-user",
                role="user",
                data_class="public",
                provenance="user_input",
                trust_level="trusted_actor",
                content_type="text/plain",
                content=b"synthetic request",
            ),
            *(
                (
                    AgenticRequestContentBlock(
                        content_block_id="recipe-finalization",
                        role="system",
                        data_class="public",
                        provenance="finalization_instruction",
                        trust_level="trusted_platform",
                        content_type="text/plain",
                        content=HOSTED_FINALIZATION_INSTRUCTION.encode(),
                    ),
                )
                if final
                else ()
            ),
        ),
        tool_definitions=(
            ()
            if final
            else (
                AgenticToolDefinition(
                    "fixture_tool",
                    "Synthetic fixture tool.",
                    {"type": "object", "additionalProperties": False},
                ),
            )
        ),
        tool_results=(),
        provider_private_state=None,
        routing_constraint=(
            google_interactions_routing_constraint()
            if recipe.model_provider_id == "google-ai-studio"
            else openrouter_agentic_routing_constraint()
        ),
        max_output_tokens=1_024,
        request_phase="finalization" if final else "exploration",
    )


if __name__ == "__main__":
    unittest.main()
