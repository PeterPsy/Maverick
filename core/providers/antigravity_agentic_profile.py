"""Immutable Full Workspace projections for a certified Antigravity connection."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib

from core.providers.agentic_models import (
    AgenticContextPolicy,
    AgenticProfileDefinition,
    AgenticProfileDefinitionStatus,
    AgenticRuntimePolicy,
    RoutingConstraint,
)
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.errors import AgenticProfileError, ProviderNotFoundError
from core.providers.execution_families import NATIVE_AGENT_EXECUTION_FAMILY
from core.providers.native_agent_catalog import NativeAgentCatalogModel
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
)


ANTIGRAVITY_PROFILE_REVISION = "3"
ANTIGRAVITY_CONTEXT_POLICY = AgenticContextPolicy(
    revision="antigravity-native-context-v1",
    max_request_input_tokens=262_144,
    context_reserve_tokens=16_384,
    compaction_mode="provider_history",
    compaction_trigger_tokens=196_608,
    max_compacted_state_bytes=1_048_576,
    summary_max_bytes=65_536,
    tool_result_inline_bytes=65_536,
    tool_result_summary_bytes=16_384,
    attachment_projection_mode="native_or_reference",
    steering_delivery_mode="safe_next_turn",
    max_same_turn_steering_messages=0,
)
ANTIGRAVITY_CAPABILITY_CATALOG_DIGEST = canonical_digest(
    {
        "revision": "antigravity-native-full-workspace-v1",
        "tool_handles": FULL_WORKSPACE_CORE_TOOL_HANDLES,
        "native_effects": (
            "workspace-readonly-native-shell",
            "maverick-runtime-cli",
            "maverick-runtime-mcp",
            "maverick-confirmed-workspace-mutations",
        ),
    }
)
ANTIGRAVITY_SEMANTIC_PROJECTION_REVISION = "antigravity-native-projection-v1"


def antigravity_native_policy() -> AgenticRuntimePolicy:
    """Bound the remote native runtime to the common Full Workspace surface."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=64,
        max_tool_calls_per_turn=48,
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


def antigravity_native_routing_constraint() -> RoutingConstraint:
    return RoutingConstraint(
        endpoint_id="antigravity-oauth-google",
        allowed_upstream_ids=("google",),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="provider_contract",
        require_zdr=False,
        allowed_quantizations=(),
    )


def antigravity_native_capabilities() -> RuntimeCapabilitySet:
    return RuntimeCapabilitySet(
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
        same_turn_steering=False,
        recovery=True,
        confirmation_resume=True,
        provider_private_state=True,
        attachment_modalities=("file",),
        app_references=True,
        confirmations=True,
    )


def antigravity_agentic_profile_definition(
    *,
    installation,
    model: NativeAgentCatalogModel,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Build a model pin that inherits one connection-scoped certificate."""
    if (
        installation.manifest.runtime_engine_id != "antigravity-cli"
        or model.model_provider_id != "google"
        or not model.model_id
    ):
        raise AgenticProfileError("antigravity_profile_identity_invalid")
    timestamp = now or datetime.now(tz=UTC)
    identity = hashlib.sha256(
        f"antigravity-cli\0google\0{model.model_id}".encode()
    ).hexdigest()[:20]
    definition_id = f"agentic-profile-antigravity-{identity}"
    revision = f"{ANTIGRAVITY_PROFILE_REVISION}.{model.digest}"
    manifest = installation.manifest
    recipe = installation.recipe
    return AgenticProfileDefinition(
        definition_id=definition_id,
        revision=revision,
        display_name=f"Antigravity · {model.model_id}",
        runtime_engine_id=manifest.runtime_engine_id,
        model_provider_id=model.model_provider_id,
        model_id=model.model_id,
        model_revision=model.model_revision,
        model_revision_policy=model.revision_policy,
        provider_protocol=manifest.protocol_id,
        provider_api_version=manifest.protocol_version,
        adapter_id=manifest.adapter_id,
        adapter_version_constraint=f"=={manifest.adapter_version}",
        routing_constraint=antigravity_native_routing_constraint(),
        policy_ceiling=antigravity_native_policy(),
        capability_certificate_id=(
            f"capability-certificate:{definition_id}:{revision}"
        ),
        created_at=timestamp,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=NATIVE_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.digest,
        provider_capability_catalog_digest=(
            ANTIGRAVITY_CAPABILITY_CATALOG_DIGEST
        ),
        semantic_projection_compiler_revision=(
            ANTIGRAVITY_SEMANTIC_PROJECTION_REVISION
        ),
        tool_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        context_policy=ANTIGRAVITY_CONTEXT_POLICY,
        native_model_catalog_digest=model.digest,
    )


def publish_antigravity_agentic_profile(
    store,
    *,
    installation,
    model: NativeAgentCatalogModel,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish one immutable preview projection without creating a binding."""
    timestamp = now or datetime.now(tz=UTC)
    profile = antigravity_agentic_profile_definition(
        installation=installation,
        model=model,
        now=timestamp,
    )
    try:
        stored = store.get_agentic_profile_definition(
            profile.definition_id,
            profile.revision,
        )
    except ProviderNotFoundError:
        store.save_agentic_profile_definition(profile)
        stored = profile
    if stored != replace(profile, created_at=stored.created_at):
        raise AgenticProfileError("agentic_profile_definition_conflict")
    status = store.get_agentic_profile_definition_status(
        profile.definition_id,
        profile.revision,
    )
    if status is None:
        store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=profile.definition_id,
                definition_revision=profile.revision,
                rollout_status="preview",
                revision=0,
                updated_at=timestamp,
            ),
            expected_revision=None,
        )
    return stored


__all__ = [
    "ANTIGRAVITY_CAPABILITY_CATALOG_DIGEST",
    "ANTIGRAVITY_CONTEXT_POLICY",
    "ANTIGRAVITY_PROFILE_REVISION",
    "ANTIGRAVITY_SEMANTIC_PROJECTION_REVISION",
    "antigravity_agentic_profile_definition",
    "antigravity_native_capabilities",
    "antigravity_native_policy",
    "antigravity_native_routing_constraint",
    "publish_antigravity_agentic_profile",
]
