"""Shared fixtures for Maverick Agent onboarding contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.google_agentic_profile import google_agentic_preview_policy
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    MAVERICK_AGENT_EXECUTION_FAMILY,
)
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE
from tests.support.collections import FakeCollection


NOW = datetime(2026, 9, 4, tzinfo=UTC)


def provider_store() -> ProviderDocumentStore:
    return ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            agentic_migrations=FakeCollection(),
        )
    )


def google_publication(
    *,
    model_id: str = "gemini-3.6-flash",
    profile_revision: str = "test-1",
) -> MaverickAgentProfilePublication:
    recipe = replace(
        GOOGLE_GOVERNED_WORKSPACE_RECIPE,
        recipe_id=f"test-google-recipe-{model_id}",
        revision=profile_revision,
        model_id=model_id,
        model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
    )
    profile = AgenticProfileDefinition(
        definition_id=f"test-profile-{model_id}",
        revision=profile_revision,
        display_name=f"Test {model_id}",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id=model_id,
        model_revision=recipe.model_revision,
        model_revision_policy=recipe.model_revision_policy,
        provider_protocol=recipe.provider_protocol,
        provider_api_version=recipe.provider_api_version,
        adapter_id=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.routing_constraint,
        policy_ceiling=google_agentic_preview_policy(),
        capability_certificate_id=f"certificate:{model_id}:{profile_revision}",
        created_at=NOW,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=MAVERICK_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.recipe_digest,
        provider_capability_catalog_digest=recipe.capability_catalog_digest,
        semantic_projection_compiler_revision=(
            recipe.semantic_projection_compiler_revision
        ),
        tool_contract_revision=recipe.tool_contract_revision,
        context_policy=recipe.context_policy,
        provider_config_id=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.config_id,
        provider_config_revision=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.revision,
        provider_config_digest=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.digest,
        protocol_adapter_id=(
            GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.protocol_adapter_id
        ),
        protocol_adapter_version=(
            GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.protocol_adapter_version
        ),
    )
    return MaverickAgentProfilePublication(
        adapter=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
        provider_config=GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
        recipe=recipe,
        profile=profile,
        rollout_status="preview",
    )


class RuntimeClient:
    """Minimal introspectable protocol client for composition tests."""

    def __init__(self, config, recipe) -> None:
        self.model_id = recipe.model_id
        self.endpoint_url = config.endpoint_url
        self.routing_constraint = config.routing_constraint
        self.allowed_upstream_ids = config.routing_constraint.allowed_upstream_ids
        self.upstream_provider_names = config.upstream_provider_names
        self.resolved_model_ids = config.resolved_model_ids
        self.token_cost_policy = config.token_cost_policy

    async def create_response(self, request, *, credential):
        from core.providers.agentic_protocol import AgenticModelEvent

        yield AgenticModelEvent(event_type="completed", request_id=request.request_id, ordinal=1)


__all__ = ["NOW", "RuntimeClient", "google_publication", "provider_store"]
