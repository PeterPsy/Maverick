"""Immutable preview profile for certified Google Gemini Interactions."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.agentic_models import (
    AgenticProfileDefinition,
    AgenticRuntimePolicy,
    RoutingConstraint,
)
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.execution_families import MAVERICK_AGENT_EXECUTION_FAMILY
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
    publish_maverick_agent_profile,
    validate_maverick_runtime_adapter,
)
from core.providers.store import ProviderStore
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE


GOOGLE_AGENTIC_PROFILE_ID = "agentic-profile-google-gemini-3-6-flash"
GOOGLE_AGENTIC_PROFILE_REVISION = "49"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION = "48"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISIONS = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
    "12", "13", "14", "15", "16", "17", "18", "19", "20", "21",
    "22", "23", "24", "25", "26", "27", "28", "29", "30", "31",
    "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48",
)
GOOGLE_CERTIFIED_REASONING_EFFORTS = ("high",)
GOOGLE_DEFAULT_REASONING_EFFORT = "high"
GOOGLE_AGENTIC_CERTIFICATE_ID = (
    f"capability-certificate:{GOOGLE_AGENTIC_PROFILE_ID}:{GOOGLE_AGENTIC_PROFILE_REVISION}"
)


def google_agentic_preview_policy() -> AgenticRuntimePolicy:
    """Return the contained governed-workspace preview resource ceiling."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=32,
        max_tool_calls_per_turn=24,
        max_parallel_tool_calls=0,
        max_wall_time_seconds=900,
        max_tool_result_bytes=1_500_000,
        max_total_tool_result_bytes=8_000_000,
        max_input_tokens=262_144,
        max_output_tokens=16_384,
        max_estimated_cost_microusd=3_500_000,
        allowed_surface_kinds=(
            "cli",
            "mcp",
            "app-interface",
            "core-capability",
        ),
        tool_handle_mode="exact",
        allowed_tool_handles=FULL_WORKSPACE_CORE_TOOL_HANDLES,
        allow_filesystem_list=True,
        allow_filesystem_read=True,
        allow_filesystem_write=True,
        allow_shell=True,
        require_confirmation_for_mutating=True,
        require_confirmation_for_destructive=True,
        allowed_remote_data_classes=("public",),
    )


def google_interactions_routing_constraint() -> RoutingConstraint:
    return GOOGLE_INTERACTIONS_PROVIDER_CONFIG.routing_constraint


def google_agentic_preview_publication(
    *,
    now: datetime | None = None,
) -> MaverickAgentProfilePublication:
    """Build the immutable Google publication record used by onboarding."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=GOOGLE_AGENTIC_PROFILE_ID,
        revision=GOOGLE_AGENTIC_PROFILE_REVISION,
        display_name="Google Gemini 3.6 Flash · Full Workspace preview",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id="gemini-3.6-flash",
        model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
        model_revision_policy="exact",
        provider_protocol="google-interactions",
        provider_api_version="v1",
        adapter_id=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=google_interactions_routing_constraint(),
        policy_ceiling=google_agentic_preview_policy(),
        capability_certificate_id=GOOGLE_AGENTIC_CERTIFICATE_ID,
        created_at=timestamp,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=MAVERICK_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=GOOGLE_GOVERNED_WORKSPACE_RECIPE.recipe_id,
        harness_recipe_revision=GOOGLE_GOVERNED_WORKSPACE_RECIPE.revision,
        harness_recipe_digest=GOOGLE_GOVERNED_WORKSPACE_RECIPE.recipe_digest,
        provider_capability_catalog_digest=(
            GOOGLE_GOVERNED_WORKSPACE_RECIPE.capability_catalog_digest
        ),
        semantic_projection_compiler_revision=(
            GOOGLE_GOVERNED_WORKSPACE_RECIPE.semantic_projection_compiler_revision
        ),
        tool_contract_revision=GOOGLE_GOVERNED_WORKSPACE_RECIPE.tool_contract_revision,
        context_policy=GOOGLE_GOVERNED_WORKSPACE_RECIPE.context_policy,
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
        recipe=GOOGLE_GOVERNED_WORKSPACE_RECIPE,
        profile=definition,
        rollout_status="preview",
        superseded_profile_revisions=GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
    )


def ensure_google_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish an uncertified Full Workspace preview without enabling a binding."""
    timestamp = now or datetime.now(tz=UTC)
    validate_maverick_runtime_adapter(GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER, adapter)
    return publish_maverick_agent_profile(
        store,
        publication=google_agentic_preview_publication(now=timestamp),
        now=timestamp,
    )
