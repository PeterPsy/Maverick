"""Trusted protocol and provider-config records for builtin API agents."""

from __future__ import annotations

from datetime import datetime

from core.providers.agentic_models import RoutingConstraint
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_ENDPOINT,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
    MaverickProtocolAdapterManifest,
)
from core.providers.maverick_agent_provider_config import (
    MaverickProviderConfig,
    MaverickTokenCostPolicy,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_ENDPOINT,
    OPENROUTER_AGENTIC_ENDPOINT_ID,
    OPENROUTER_AGENTIC_PROVIDER_NAME,
    OPENROUTER_AGENTIC_RESOLVED_MODEL_ID,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
    OPENROUTER_DEEPSEEK_FLASH_LATEST_RESOLVED_MODEL_IDS,
)
from core.providers.store import ProviderStore


HOSTED_TOOL_LOOP_ADAPTER_ID = "maverick-hosted-tool-loop"
HOSTED_TOOL_LOOP_ADAPTER_VERSION = "59"
RETIRED_MAVERICK_AGENT_PROFILE_IDS = (
    "agentic-profile-google-gemini-3-6-flash",
)

GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER = MaverickProtocolAdapterManifest(
    protocol_adapter_id="google-interactions-protocol",
    protocol_adapter_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
    runtime_adapter_id=HOSTED_TOOL_LOOP_ADAPTER_ID,
    runtime_adapter_version=HOSTED_TOOL_LOOP_ADAPTER_VERSION,
    provider_protocol="google-interactions",
    provider_api_version="v1",
    transport_id="google-interactions-sse",
    request_codec_id=f"{GOOGLE_INTERACTIONS_CODEC_ID}@{GOOGLE_INTERACTIONS_CODEC_VERSION}",
    response_codec_id=f"{GOOGLE_INTERACTIONS_CODEC_ID}@{GOOGLE_INTERACTIONS_CODEC_VERSION}",
    private_state_codec_id=f"{GOOGLE_INTERACTIONS_CODEC_ID}@{GOOGLE_INTERACTIONS_CODEC_VERSION}",
    usage_accounting_id="google-interactions-usage-v1",
    cancellation_id="cooperative-stream-cancel-v1",
    recovery_id="core-stateless-history-v1",
    trusted_distribution="maverick_builtin",
)

OPENROUTER_CHAT_PROTOCOL_ADAPTER = MaverickProtocolAdapterManifest(
    protocol_adapter_id="openrouter-chat-completions-protocol",
    protocol_adapter_version=OPENROUTER_AGENTIC_CODEC_VERSION,
    runtime_adapter_id=HOSTED_TOOL_LOOP_ADAPTER_ID,
    runtime_adapter_version=HOSTED_TOOL_LOOP_ADAPTER_VERSION,
    provider_protocol="openrouter-chat-completions",
    provider_api_version="v1",
    transport_id="openrouter-chat-sse",
    request_codec_id=f"{OPENROUTER_AGENTIC_CODEC_ID}@{OPENROUTER_AGENTIC_CODEC_VERSION}",
    response_codec_id=f"{OPENROUTER_AGENTIC_CODEC_ID}@{OPENROUTER_AGENTIC_CODEC_VERSION}",
    private_state_codec_id=f"{OPENROUTER_AGENTIC_CODEC_ID}@{OPENROUTER_AGENTIC_CODEC_VERSION}",
    usage_accounting_id="openrouter-chat-usage-v1",
    cancellation_id="cooperative-stream-cancel-v1",
    recovery_id="core-chat-history-v1",
    trusted_distribution="maverick_builtin",
)

GOOGLE_INTERACTIONS_PROVIDER_CONFIG = MaverickProviderConfig(
    config_id="google-ai-studio-interactions",
    model_provider_id="google-ai-studio",
    provider_protocol="google-interactions",
    provider_api_version="v1",
    routing_constraint=RoutingConstraint(
        endpoint_id="google-generativelanguage-v1-interactions",
        allowed_upstream_ids=(),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="provider_contract",
        require_zdr=False,
        allowed_quantizations=(),
    ),
    endpoint_url=GOOGLE_INTERACTIONS_ENDPOINT,
    credential_logical_name="google_ai_studio_api_key",
    data_destination="Google AI Studio API",
    retention_policy="provider_contract",
    token_cost_policy=MaverickTokenCostPolicy(
        policy_id="google-gemini-3.6-flash-public-list-price",
        input_microusd_per_million_tokens=1_500_000,
        output_microusd_per_million_tokens=7_500_000,
    ),
)

OPENROUTER_RELACE_GLM_PROVIDER_CONFIG = MaverickProviderConfig(
    config_id="openrouter-relace-glm-5-3-flash",
    model_provider_id="openrouter",
    provider_protocol="openrouter-chat-completions",
    provider_api_version="v1",
    routing_constraint=RoutingConstraint(
        endpoint_id=OPENROUTER_AGENTIC_ENDPOINT_ID,
        allowed_upstream_ids=(OPENROUTER_AGENTIC_UPSTREAM_ID,),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="deny",
        require_zdr=True,
        allowed_quantizations=("unknown",),
    ),
    endpoint_url=OPENROUTER_AGENTIC_ENDPOINT,
    credential_logical_name="openrouter_api_key",
    data_destination="OpenRouter via Relace",
    retention_policy="zdr_required",
    token_cost_policy=MaverickTokenCostPolicy(
        policy_id="openrouter-relace-glm-5-3-flash-public-list-price",
        input_microusd_per_million_tokens=90_000,
        output_microusd_per_million_tokens=300_000,
    ),
    upstream_provider_names=(OPENROUTER_AGENTIC_PROVIDER_NAME,),
    resolved_model_ids=(OPENROUTER_AGENTIC_RESOLVED_MODEL_ID,),
)


OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG = MaverickProviderConfig(
    config_id="openrouter-relace-deepseek-flash-latest",
    model_provider_id="openrouter",
    provider_protocol="openrouter-chat-completions",
    provider_api_version="v1",
    routing_constraint=RoutingConstraint(
        endpoint_id=OPENROUTER_AGENTIC_ENDPOINT_ID,
        allowed_upstream_ids=(OPENROUTER_AGENTIC_UPSTREAM_ID,),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="deny",
        require_zdr=True,
        allowed_quantizations=("fp4",),
    ),
    endpoint_url=OPENROUTER_AGENTIC_ENDPOINT,
    credential_logical_name="openrouter_api_key",
    data_destination="OpenRouter API",
    retention_policy="zdr_required",
    token_cost_policy=MaverickTokenCostPolicy(
        policy_id="openrouter-relace-deepseek-flash-latest-public-list-price",
        input_microusd_per_million_tokens=130_000,
        output_microusd_per_million_tokens=520_000,
    ),
    upstream_provider_names=(OPENROUTER_AGENTIC_PROVIDER_NAME,),
    resolved_model_ids=OPENROUTER_DEEPSEEK_FLASH_LATEST_RESOLVED_MODEL_IDS,
)


def builtin_maverick_protocol_adapters() -> tuple[
    MaverickProtocolAdapterManifest,
    ...,
]:
    """Return trusted protocol records without model-specific branching."""
    return (
        OPENROUTER_CHAT_PROTOCOL_ADAPTER,
    )


def builtin_maverick_provider_configs() -> tuple[MaverickProviderConfig, ...]:
    """Return provider endpoint/policy records in deterministic order."""
    return (
        OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
        OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG,
    )


def builtin_maverick_agent_publications(
    *,
    now: datetime | None = None,
) -> tuple[MaverickAgentProfilePublication, ...]:
    """Return model publications consumed by production onboarding."""
    from core.providers.openrouter_agentic_profile import (
        openrouter_deepseek_flash_latest_publication,
        openrouter_agentic_preview_publication,
    )

    return (
        openrouter_agentic_preview_publication(now=now),
        openrouter_deepseek_flash_latest_publication(now=now),
    )


def retire_builtin_maverick_agent_profiles(store: ProviderStore) -> None:
    """Remove API-agent profiles that are no longer product choices."""
    for definition_id in RETIRED_MAVERICK_AGENT_PROFILE_IDS:
        store.delete_workspace_agentic_profile_bindings_for_definition(definition_id)
        store.delete_agentic_profile_definition(definition_id)


__all__ = [
    "GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER",
    "GOOGLE_INTERACTIONS_PROVIDER_CONFIG",
    "HOSTED_TOOL_LOOP_ADAPTER_ID",
    "HOSTED_TOOL_LOOP_ADAPTER_VERSION",
    "OPENROUTER_CHAT_PROTOCOL_ADAPTER",
    "OPENROUTER_RELACE_GLM_PROVIDER_CONFIG",
    "OPENROUTER_RELACE_DEEPSEEK_FLASH_LATEST_PROVIDER_CONFIG",
    "RETIRED_MAVERICK_AGENT_PROFILE_IDS",
    "builtin_maverick_agent_publications",
    "builtin_maverick_protocol_adapters",
    "builtin_maverick_provider_configs",
    "retire_builtin_maverick_agent_profiles",
]
