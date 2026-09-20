"""Direct OpenRouter agentic model configuration."""

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
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_DEFAULT_REASONING_EFFORT,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_MODEL_REVISION,
    OPENROUTER_AGENTIC_REASONING_EFFORTS,
    OPENROUTER_DEEPSEEK_FLASH_LATEST_DEFAULT_REASONING_EFFORT,
    OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_ID,
    OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_REVISION,
    OPENROUTER_DEEPSEEK_FLASH_LATEST_REASONING_EFFORTS,
)
from core.providers.maverick_agent_builtins import (
    OPENROUTER_CHAT_PROTOCOL_ADAPTER,
    OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG,
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
    publish_maverick_agent_profile,
    validate_maverick_runtime_adapter,
)
from core.providers.store import ProviderStore
from core.runtime.hosted_provider_model_config import (
    OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_CONFIG,
    OPENROUTER_HOSTED_MODEL_CONFIG,
)


OPENROUTER_AGENTIC_PROFILE_ID = "agentic-profile-openrouter-glm-5-3-flash-relace"
OPENROUTER_DEEPSEEK_FLASH_LATEST_PROFILE_ID = (
    "agentic-profile-openrouter-deepseek-flash-latest"
)
OPENROUTER_REASONING_EFFORTS = OPENROUTER_AGENTIC_REASONING_EFFORTS
OPENROUTER_DEFAULT_REASONING_EFFORT = OPENROUTER_AGENTIC_DEFAULT_REASONING_EFFORT


def openrouter_agentic_capabilities() -> RuntimeCapabilitySet:
    """Capabilities implemented by Maverick's OpenRouter tool loop."""
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


def openrouter_agentic_preview_policy() -> AgenticRuntimePolicy:
    """Return the Codex-equivalent real-workspace resource ceiling."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=256,
        max_tool_calls_per_turn=256,
        max_parallel_tool_calls=UNBOUNDED_PARALLEL_TOOL_CALLS,
        max_wall_time_seconds=86_400,
        max_tool_result_bytes=1_048_576,
        max_total_tool_result_bytes=16_777_216,
        max_input_tokens=1_000_000,
        max_output_tokens=128_000,
        max_estimated_cost_microusd=None,
        allowed_surface_kinds=(
            "cli",
            "mcp",
            "app-interface",
            "core-capability",
        ),
        tool_handle_mode="all_currently_authorized",
        allowed_tool_handles=(),
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


def openrouter_agentic_routing_constraint() -> RoutingConstraint:
    """Pin every OpenRouter router control used by the profile."""
    return OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.routing_constraint


def openrouter_agentic_preview_publication(
    *,
    now: datetime | None = None,
) -> MaverickAgentProfilePublication:
    """Build the immutable OpenRouter publication record used by onboarding."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=OPENROUTER_AGENTIC_PROFILE_ID,
        display_name="GLM 5.3 Flash",
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
        capabilities=openrouter_agentic_capabilities(),
        reasoning_efforts=OPENROUTER_REASONING_EFFORTS,
        default_reasoning_effort=OPENROUTER_DEFAULT_REASONING_EFFORT,
        created_at=timestamp,
        egress_policy_id=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
        context_policy=OPENROUTER_HOSTED_MODEL_CONFIG.context_policy,
    )
    return MaverickAgentProfilePublication(
        adapter=OPENROUTER_CHAT_PROTOCOL_ADAPTER,
        provider_config=OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
        model_config=OPENROUTER_HOSTED_MODEL_CONFIG,
        profile=definition,
    )


def openrouter_deepseek_flash_latest_publication(
    *,
    now: datetime | None = None,
) -> MaverickAgentProfilePublication:
    """Build the OpenRouter DeepSeek Flash Latest agent publication."""
    timestamp = now or datetime.now(tz=UTC)
    definition = AgenticProfileDefinition(
        definition_id=OPENROUTER_DEEPSEEK_FLASH_LATEST_PROFILE_ID,
        display_name="DeepSeek Flash Latest",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="openrouter",
        model_id=OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_ID,
        model_revision=OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_REVISION,
        model_revision_policy="provider_alias",
        provider_protocol="openrouter-chat-completions",
        provider_api_version="v1",
        adapter_id=OPENROUTER_CHAT_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={OPENROUTER_CHAT_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=(
            OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG.routing_constraint
        ),
        policy_ceiling=openrouter_agentic_preview_policy(),
        capabilities=openrouter_agentic_capabilities(),
        reasoning_efforts=OPENROUTER_DEEPSEEK_FLASH_LATEST_REASONING_EFFORTS,
        default_reasoning_effort=(
            OPENROUTER_DEEPSEEK_FLASH_LATEST_DEFAULT_REASONING_EFFORT
        ),
        created_at=timestamp,
        egress_policy_id=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION,
        context_policy=(
            OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_CONFIG.context_policy
        ),
    )
    return MaverickAgentProfilePublication(
        adapter=OPENROUTER_CHAT_PROTOCOL_ADAPTER,
        provider_config=OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG,
        model_config=OPENROUTER_DEEPSEEK_FLASH_LATEST_MODEL_CONFIG,
        profile=definition,
    )


def ensure_openrouter_agentic_preview_profile(
    store: ProviderStore,
    *,
    adapter: object,
    now: datetime | None = None,
) -> AgenticProfileDefinition:
    """Publish the current OpenRouter agentic model config without enabling it."""
    timestamp = now or datetime.now(tz=UTC)
    validate_maverick_runtime_adapter(OPENROUTER_CHAT_PROTOCOL_ADAPTER, adapter)
    return publish_maverick_agent_profile(
        store,
        publication=openrouter_agentic_preview_publication(now=timestamp),
        now=timestamp,
    )
