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
from core.providers.store import ProviderStore


GOOGLE_AGENTIC_PROFILE_ID = "agentic-profile-google-gemini-3-6-flash"
GOOGLE_AGENTIC_PROFILE_REVISION = "4"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION = "3"
GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISIONS = ("1", "2", "3")
GOOGLE_AGENTIC_CERTIFICATE_ID = (
    f"capability-certificate:{GOOGLE_AGENTIC_PROFILE_ID}:{GOOGLE_AGENTIC_PROFILE_REVISION}"
)


def google_agentic_preview_policy() -> AgenticRuntimePolicy:
    """Allow only bounded reads over public or explicitly synthetic data."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=8,
        max_tool_calls_per_turn=4,
        max_parallel_tool_calls=0,
        max_wall_time_seconds=120,
        max_tool_result_bytes=262_144,
        max_total_tool_result_bytes=524_288,
        max_input_tokens=262_144,
        max_output_tokens=16_384,
        max_estimated_cost_microusd=250_000,
        allowed_surface_kinds=("core-capability",),
        tool_handle_mode="exact",
        allowed_tool_handles=("core-capability:filesystem.read",),
        allow_filesystem_read=True,
        allow_filesystem_write=False,
        allow_shell=False,
        require_confirmation_for_mutating=True,
        require_confirmation_for_destructive=True,
        allowed_remote_data_classes=("public", "workspace_internal_fake"),
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
        display_name="Google Gemini 3.6 Flash · fake-data preview",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id="gemini-3.6-flash",
        provider_protocol="google-interactions",
        provider_api_version="v1",
        adapter_id="maverick-hosted-tool-loop",
        adapter_version_constraint="==3",
        routing_constraint=google_interactions_routing_constraint(),
        policy_ceiling=google_agentic_preview_policy(),
        capability_certificate_id=GOOGLE_AGENTIC_CERTIFICATE_ID,
        created_at=timestamp,
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
