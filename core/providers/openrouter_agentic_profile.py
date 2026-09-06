"""Immutable contained preview for certified OpenRouter agentic execution."""

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
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_MODEL_REVISION,
)
from core.providers.maverick_agent_builtins import (
    OPENROUTER_CHAT_PROTOCOL_ADAPTER,
    OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
    publish_maverick_agent_profile,
    validate_maverick_runtime_adapter,
)
from core.providers.store import ProviderStore
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)
from core.runtime.hosted_harness_recipes import OPENROUTER_GOVERNED_WORKSPACE_RECIPE


OPENROUTER_AGENTIC_PROFILE_ID = "agentic-profile-openrouter-deepseek-v4-flash-deepinfra-fp8"
OPENROUTER_AGENTIC_PROFILE_REVISION = "46"
OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11",
    "12", "13", "14", "15", "16", "17", "18", "19", "20", "21",
    "22", "23", "24", "25", "26", "27", "28", "29", "30", "31",
    "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
)
OPENROUTER_CERTIFIED_REASONING_EFFORTS = ("minimal", "low", "medium", "high")
OPENROUTER_DEFAULT_REASONING_EFFORT = "high"
OPENROUTER_AGENTIC_CERTIFICATE_ID = (
    f"capability-certificate:{OPENROUTER_AGENTIC_PROFILE_ID}:{OPENROUTER_AGENTIC_PROFILE_REVISION}"
)


def openrouter_agentic_preview_policy() -> AgenticRuntimePolicy:
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
        max_estimated_cost_microusd=250_000,
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


def openrouter_agentic_routing_constraint() -> RoutingConstraint:
    """Pin every OpenRouter router control used by the certified profile."""
    return OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.routing_constraint


def openrouter_agentic_preview_publication(
    *,
    now: datetime | None = None,
) -> MaverickAgentProfilePublication:
    """Build the immutable OpenRouter publication record used by onboarding."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=OPENROUTER_AGENTIC_PROFILE_ID,
        revision=OPENROUTER_AGENTIC_PROFILE_REVISION,
        display_name="OpenRouter DeepSeek V4 Flash · DeepInfra FP8 · Full Workspace preview",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="openrouter",
        model_id=OPENROUTER_AGENTIC_MODEL_ID,
        model_revision=OPENROUTER_AGENTIC_MODEL_REVISION,
        model_revision_policy="provider_alias",
        provider_protocol="openrouter-chat-completions",
        provider_api_version="v1",
        adapter_id=OPENROUTER_CHAT_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={OPENROUTER_CHAT_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=openrouter_agentic_routing_constraint(),
        policy_ceiling=openrouter_agentic_preview_policy(),
        capability_certificate_id=OPENROUTER_AGENTIC_CERTIFICATE_ID,
        created_at=timestamp,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=MAVERICK_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.recipe_id,
        harness_recipe_revision=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.revision,
        harness_recipe_digest=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.recipe_digest,
        provider_capability_catalog_digest=(
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.capability_catalog_digest
        ),
        semantic_projection_compiler_revision=(
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.semantic_projection_compiler_revision
        ),
        tool_contract_revision=(
            OPENROUTER_GOVERNED_WORKSPACE_RECIPE.tool_contract_revision
        ),
        context_policy=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.context_policy,
        provider_config_id=OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.config_id,
        provider_config_revision=OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.revision,
        provider_config_digest=OPENROUTER_DEEPINFRA_PROVIDER_CONFIG.digest,
        protocol_adapter_id=OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_id,
        protocol_adapter_version=(
            OPENROUTER_CHAT_PROTOCOL_ADAPTER.protocol_adapter_version
        ),
    )
    return MaverickAgentProfilePublication(
        adapter=OPENROUTER_CHAT_PROTOCOL_ADAPTER,
        provider_config=OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
        recipe=OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
        profile=definition,
        rollout_status="preview",
        superseded_profile_revisions=OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
    )


def ensure_openrouter_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish an uncertified Full Workspace preview without enabling a binding."""
    timestamp = now or datetime.now(tz=UTC)
    validate_maverick_runtime_adapter(OPENROUTER_CHAT_PROTOCOL_ADAPTER, adapter)
    return publish_maverick_agent_profile(
        store,
        publication=openrouter_agentic_preview_publication(now=timestamp),
        now=timestamp,
    )
