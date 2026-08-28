"""Immutable contained preview for certified OpenRouter agentic execution."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.providers.agentic_models import (
    AgenticProfileDefinition,
    AgenticProfileDefinitionStatus,
    AgenticRuntimePolicy,
    RoutingConstraint,
)
from core.providers.errors import ProviderNotFoundError
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_ENDPOINT_ID,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
)
from core.providers.store import ProviderStore
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)
from core.runtime.hosted_harness_recipes import OPENROUTER_FULL_WORKSPACE_RECIPE


OPENROUTER_AGENTIC_PROFILE_ID = "agentic-profile-openrouter-deepseek-v4-flash-deepinfra-fp8"
OPENROUTER_AGENTIC_PROFILE_REVISION = "21"
OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
)
OPENROUTER_CERTIFIED_REASONING_EFFORTS = ("minimal", "low", "medium", "high")
OPENROUTER_DEFAULT_REASONING_EFFORT = "high"
OPENROUTER_AGENTIC_CERTIFICATE_ID = (
    f"capability-certificate:{OPENROUTER_AGENTIC_PROFILE_ID}:{OPENROUTER_AGENTIC_PROFILE_REVISION}"
)


def openrouter_agentic_preview_policy() -> AgenticRuntimePolicy:
    """Return the contained full-workspace candidate resource ceiling."""
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
        allowed_surface_kinds=("core-capability",),
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
    return RoutingConstraint(
        endpoint_id=OPENROUTER_AGENTIC_ENDPOINT_ID,
        allowed_upstream_ids=(OPENROUTER_AGENTIC_UPSTREAM_ID,),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="deny",
        require_zdr=True,
        allowed_quantizations=("fp8",),
    )


def ensure_openrouter_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish uncertified candidate metadata without enabling a binding."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=OPENROUTER_AGENTIC_PROFILE_ID,
        revision=OPENROUTER_AGENTIC_PROFILE_REVISION,
        display_name="OpenRouter DeepSeek V4 Flash · DeepInfra FP8 · full-workspace candidate",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="openrouter",
        model_id=OPENROUTER_AGENTIC_MODEL_ID,
        provider_protocol="openrouter-chat-completions",
        provider_api_version="v1",
        adapter_id="maverick-hosted-tool-loop",
        adapter_version_constraint="==14",
        routing_constraint=openrouter_agentic_routing_constraint(),
        policy_ceiling=openrouter_agentic_preview_policy(),
        capability_certificate_id=OPENROUTER_AGENTIC_CERTIFICATE_ID,
        created_at=timestamp,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family="maverick_agent",
        harness_recipe_id=OPENROUTER_FULL_WORKSPACE_RECIPE.recipe_id,
        harness_recipe_revision=OPENROUTER_FULL_WORKSPACE_RECIPE.revision,
        harness_recipe_digest=OPENROUTER_FULL_WORKSPACE_RECIPE.recipe_digest,
        provider_capability_catalog_digest=(
            OPENROUTER_FULL_WORKSPACE_RECIPE.capability_catalog_digest
        ),
        semantic_projection_compiler_revision=(
            OPENROUTER_FULL_WORKSPACE_RECIPE.semantic_projection_compiler_revision
        ),
        tool_contract_revision=(
            OPENROUTER_FULL_WORKSPACE_RECIPE.tool_contract_revision
        ),
        context_policy=OPENROUTER_FULL_WORKSPACE_RECIPE.context_policy,
    )
    try:
        stored = store.get_agentic_profile_definition(
            definition.definition_id,
            definition.revision,
        )
    except ProviderNotFoundError:
        stored = store.save_agentic_profile_definition(definition)
    if store.get_agentic_profile_definition_status(stored.definition_id, stored.revision) is None:
        store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=stored.definition_id,
                definition_revision=stored.revision,
                rollout_status="preview",
                revision=0,
                updated_at=timestamp,
            ),
            expected_revision=None,
        )
    _suspend_previous_revisions(store, now=timestamp)
    return stored


def _suspend_previous_revisions(store: ProviderStore, *, now: datetime) -> None:
    """Suspend preview definitions certified against earlier adapter bytes."""
    for revision in OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS:
        status = store.get_agentic_profile_definition_status(
            OPENROUTER_AGENTIC_PROFILE_ID,
            revision,
        )
        if status is None or status.rollout_status in {"disabled", "suspended"}:
            continue
        store.save_agentic_profile_definition_status(
            replace(
                status,
                rollout_status="suspended",
                revision=status.revision + 1,
                updated_at=now,
            ),
            expected_revision=status.revision,
        )
