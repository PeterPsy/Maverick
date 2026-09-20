"""Direct Antigravity native model configurations."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from core.providers.agentic_models import (
    AgenticContextPolicy,
    AgenticProfileDefinition,
    AgenticRuntimePolicy,
    RoutingConstraint,
    RuntimeCapabilitySet,
    UNBOUNDED_PARALLEL_TOOL_CALLS,
)
from core.providers.agentic_data_policies import (
    REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
    REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
)
from core.providers.errors import AgenticProfileError
from core.providers.native_agent_catalog import NativeAgentCatalogModel
from core.runtime.hosted_agentic_policy import HOSTED_CORE_TOOL_HANDLES


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


def antigravity_native_policy() -> AgenticRuntimePolicy:
    """Bound the remote native runtime to the configured workspace tools."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=64,
        max_tool_calls_per_turn=48,
        max_parallel_tool_calls=UNBOUNDED_PARALLEL_TOOL_CALLS,
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
        allowed_tool_handles=HOSTED_CORE_TOOL_HANDLES,
        allow_filesystem_list=True,
        allow_filesystem_read=True,
        allow_filesystem_write=True,
        allow_shell=True,
        require_confirmation_for_mutating=True,
        require_confirmation_for_destructive=True,
        allowed_remote_data_classes=(
            "public",
            "workspace_internal",
            "personal_data",
            "regulated_or_customer_data",
        ),
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
    """Build a model pin for one connection-scoped runtime."""
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
    manifest = installation.manifest
    return AgenticProfileDefinition(
        definition_id=definition_id,
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
        capabilities=antigravity_native_capabilities(),
        reasoning_efforts=model.reasoning_efforts,
        default_reasoning_effort=model.default_reasoning_effort,
        created_at=timestamp,
        egress_policy_id=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
        context_policy=ANTIGRAVITY_CONTEXT_POLICY,
    )


def publish_antigravity_agentic_profile(
    store,
    *,
    installation,
    model: NativeAgentCatalogModel,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Upsert one current model config without creating a workspace choice."""
    profile = antigravity_agentic_profile_definition(
        installation=installation,
        model=model,
        now=now,
    )
    return store.save_agentic_profile_definition(profile)


__all__ = [
    "ANTIGRAVITY_CONTEXT_POLICY",
    "antigravity_agentic_profile_definition",
    "antigravity_native_capabilities",
    "antigravity_native_policy",
    "antigravity_native_routing_constraint",
    "publish_antigravity_agentic_profile",
]
