"""Immutable preview profile for certified Google Gemini Interactions."""

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
from core.providers.store import ProviderStore
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)
from core.runtime.hosted_harness_recipes import GOOGLE_FULL_WORKSPACE_RECIPE


GOOGLE_AGENTIC_PROFILE_ID = "agentic-profile-google-gemini-3-6-flash"
GOOGLE_AGENTIC_PROFILE_REVISION = "26"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION = "25"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISIONS = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25",
)
GOOGLE_CERTIFIED_REASONING_EFFORTS = ("high",)
GOOGLE_DEFAULT_REASONING_EFFORT = "high"
GOOGLE_AGENTIC_CERTIFICATE_ID = (
    f"capability-certificate:{GOOGLE_AGENTIC_PROFILE_ID}:{GOOGLE_AGENTIC_PROFILE_REVISION}"
)


def google_agentic_preview_policy() -> AgenticRuntimePolicy:
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
        max_estimated_cost_microusd=3_500_000,
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


def google_interactions_routing_constraint() -> RoutingConstraint:
    return RoutingConstraint(
        endpoint_id="google-generativelanguage-v1-interactions",
        allowed_upstream_ids=(),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="provider_contract",
        require_zdr=False,
        allowed_quantizations=(),
    )


def ensure_google_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish uncertified candidate metadata without enabling a workspace binding."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=GOOGLE_AGENTIC_PROFILE_ID,
        revision=GOOGLE_AGENTIC_PROFILE_REVISION,
        display_name="Google Gemini 3.6 Flash · full-workspace candidate",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id="gemini-3.6-flash",
        provider_protocol="google-interactions",
        provider_api_version="v1",
        adapter_id="maverick-hosted-tool-loop",
        adapter_version_constraint="==18",
        routing_constraint=google_interactions_routing_constraint(),
        policy_ceiling=google_agentic_preview_policy(),
        capability_certificate_id=GOOGLE_AGENTIC_CERTIFICATE_ID,
        created_at=timestamp,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family="maverick_agent",
        harness_recipe_id=GOOGLE_FULL_WORKSPACE_RECIPE.recipe_id,
        harness_recipe_revision=GOOGLE_FULL_WORKSPACE_RECIPE.revision,
        harness_recipe_digest=GOOGLE_FULL_WORKSPACE_RECIPE.recipe_digest,
        provider_capability_catalog_digest=(
            GOOGLE_FULL_WORKSPACE_RECIPE.capability_catalog_digest
        ),
        semantic_projection_compiler_revision=(
            GOOGLE_FULL_WORKSPACE_RECIPE.semantic_projection_compiler_revision
        ),
        tool_contract_revision=GOOGLE_FULL_WORKSPACE_RECIPE.tool_contract_revision,
        context_policy=GOOGLE_FULL_WORKSPACE_RECIPE.context_policy,
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
    """Prevent selection of revisions certified against earlier adapter bytes."""
    for revision in GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISIONS:
        status = store.get_agentic_profile_definition_status(
            GOOGLE_AGENTIC_PROFILE_ID,
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
