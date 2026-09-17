"""Direct Google Gemini agentic model configuration."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.agentic_models import (
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
from core.runtime.hosted_agentic_policy import HOSTED_CORE_TOOL_HANDLES
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE


GOOGLE_AGENTIC_PROFILE_ID = "agentic-profile-google-gemini-3-6-flash"
GOOGLE_REASONING_EFFORTS = ("high",)
GOOGLE_DEFAULT_REASONING_EFFORT = "high"


def google_agentic_capabilities() -> RuntimeCapabilitySet:
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


def google_agentic_preview_policy() -> AgenticRuntimePolicy:
    """Return the full-access governed-workspace preview resource ceiling."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=32,
        max_tool_calls_per_turn=24,
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
        require_confirmation_for_mutating=False,
        require_confirmation_for_destructive=False,
        allowed_remote_data_classes=(
            "public",
            "workspace_internal",
            "personal_data",
            "regulated_or_customer_data",
        ),
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
        capabilities=google_agentic_capabilities(),
        reasoning_efforts=GOOGLE_REASONING_EFFORTS,
        default_reasoning_effort=GOOGLE_DEFAULT_REASONING_EFFORT,
        created_at=timestamp,
        egress_policy_id=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
        context_policy=GOOGLE_GOVERNED_WORKSPACE_RECIPE.context_policy,
    )
    return MaverickAgentProfilePublication(
        adapter=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
        provider_config=GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
        recipe=GOOGLE_GOVERNED_WORKSPACE_RECIPE,
        profile=definition,
    )


def ensure_google_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish a Full Workspace profile without enabling a binding."""
    timestamp = now or datetime.now(tz=UTC)
    validate_maverick_runtime_adapter(GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER, adapter)
    return publish_maverick_agent_profile(
        store,
        publication=google_agentic_preview_publication(now=timestamp),
        now=timestamp,
    )
