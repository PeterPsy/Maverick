"""Static metadata for hosted model and remote speech providers."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderCredentialRequirement,
    ProviderDefinition,
    ProviderExecutionContract,
    ProviderModelOption,
    ProviderNetworkRequirement,
)


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def build_hosted_provider_definitions(now: datetime | None = None) -> list[ProviderDefinition]:
    """Return built-in hosted provider metadata without executable runtime adapters."""
    timestamp = now or utcnow()
    return [
        _groq_definition(timestamp),
        _deepseek_definition(timestamp),
        _openrouter_definition(timestamp),
        _deepgram_definition(timestamp),
        _cartesia_definition(timestamp),
        _kokoro_hosted_definition(timestamp),
    ]


def _hosted_text_capabilities(*, latency_class: str) -> ProviderCapabilitySet:
    return ProviderCapabilitySet(
        supports_interactive_runtime=False,
        supports_streaming=True,
        supports_tools=False,
        supports_mcp=False,
        supports_skills=False,
        supports_filesystem_access=False,
        supports_remote_execution=True,
        supports_api_key_auth=True,
        supports_local_binary=False,
        input_modalities=["text"],
        output_modalities=["text"],
        supports_streaming_output=True,
        supports_tool_calling=False,
        supports_structured_output=False,
        latency_class=latency_class,
    )


def _hosted_text_contract(secret_name: str) -> ProviderExecutionContract:
    return ProviderExecutionContract(
        adapter_type="hosted_text_generation",
        request_shape="chat_messages",
        streaming_supported=True,
        non_streaming_supported=True,
        timeout_policy="short_interactive",
        error_mapping={
            "401": "provider_credential_rejected",
            "403": "provider_credential_rejected",
            "429": "provider_rate_limited",
            "timeout": "provider_timeout",
            "invalid_payload": "provider_response_invalid",
        },
        secret_alias_or_logical_name=secret_name,
        transport_test_mode="fake_supported",
    )


def _credential(secret_name: str, *, modes: list[str]) -> ProviderCredentialRequirement:
    return ProviderCredentialRequirement(
        secret_alias_or_logical_name=secret_name,
        secret_kind="api_key",
        required_for_modes=modes,
        secret_binding_scope="provider",
    )


def _network(host: str, *, transport: str = "https") -> ProviderNetworkRequirement:
    return ProviderNetworkRequirement(
        outbound_required=True,
        allowed_hosts=[host],
        transport=transport,
    )


def _groq_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="groq",
        label="Groq",
        description="Hosted low-latency text generation provider metadata.",
        kind="hosted_api",
        provider_role="model_provider",
        status="disabled",
        capabilities=_hosted_text_capabilities(latency_class="low"),
        default_model_family="llama-3.3-70b-versatile",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            ProviderModelOption(
                model_id="llama-3.3-70b-versatile",
                label="Llama 3.3 70B Versatile",
                description="Hosted text model candidate for fast_model routing.",
                default_reasoning_effort=None,
            )
        ],
        credential_requirements=[_credential("groq_api_key", modes=["plain_hosted_chat"])],
        network_requirements=[_network("api.groq.com")],
        execution_contract=_hosted_text_contract("groq_api_key"),
        latency_metadata={"latency_class": "low"},
    )


def _deepseek_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="deepseek",
        label="DeepSeek",
        description="Hosted text generation provider metadata.",
        kind="hosted_api",
        provider_role="model_provider",
        status="disabled",
        capabilities=_hosted_text_capabilities(latency_class="standard"),
        default_model_family="deepseek-chat",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            ProviderModelOption(
                model_id="deepseek-chat",
                label="DeepSeek Chat",
                description="Hosted text model candidate for plain hosted chat.",
                default_reasoning_effort=None,
            )
        ],
        credential_requirements=[_credential("deepseek_api_key", modes=["plain_hosted_chat"])],
        network_requirements=[_network("api.deepseek.com")],
        execution_contract=_hosted_text_contract("deepseek_api_key"),
        latency_metadata={"latency_class": "standard"},
    )


def _openrouter_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="openrouter",
        label="OpenRouter",
        description="Hosted OpenAI-compatible text generation provider metadata.",
        kind="hosted_api",
        provider_role="model_provider",
        status="disabled",
        capabilities=_hosted_text_capabilities(latency_class="low"),
        default_model_family="google/gemma-4-31b-it:free",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            ProviderModelOption(
                model_id="google/gemma-4-31b-it:free",
                label="Gemma 4 31B (free)",
                description="OpenRouter hosted text model candidate for fast_model routing.",
                default_reasoning_effort=None,
            ),
            ProviderModelOption(
                model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
                label="Nemotron 3 Ultra (free)",
                description="OpenRouter hosted text model candidate for fast_model routing.",
                default_reasoning_effort=None,
            ),
        ],
        credential_requirements=[_credential("openrouter_api_key", modes=["plain_hosted_chat", "fast_model"])],
        network_requirements=[_network("openrouter.ai")],
        execution_contract=_hosted_text_contract("openrouter_api_key"),
        latency_metadata={"latency_class": "low", "router": "openrouter"},
    )


def _deepgram_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="deepgram",
        label="Deepgram",
        description="Remote speech-to-text provider metadata for future speech routing.",
        kind="hosted_api",
        provider_role="speech_provider",
        status="disabled",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=False,
            supports_streaming=True,
            supports_tools=False,
            supports_mcp=False,
            supports_skills=False,
            supports_filesystem_access=False,
            supports_remote_execution=True,
            supports_api_key_auth=True,
            supports_local_binary=False,
            input_modalities=["audio"],
            output_modalities=["text", "events"],
            supports_streaming_input=True,
            supports_streaming_output=True,
            supports_realtime=True,
            supports_turn_detection=True,
        ),
        default_model_family="speech-to-text",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        credential_requirements=[_credential("deepgram_api_key", modes=["speech_stt"])],
        network_requirements=[_network("api.deepgram.com", transport="websocket")],
        latency_metadata={"speech_profile": "stt_realtime_deferred"},
    )


def _cartesia_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="cartesia",
        label="Cartesia",
        description="Remote text-to-speech provider metadata for future speech routing.",
        kind="hosted_api",
        provider_role="speech_provider",
        status="disabled",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=False,
            supports_streaming=True,
            supports_tools=False,
            supports_mcp=False,
            supports_skills=False,
            supports_filesystem_access=False,
            supports_remote_execution=True,
            supports_api_key_auth=True,
            supports_local_binary=False,
            input_modalities=["text"],
            output_modalities=["audio"],
            supports_streaming_output=True,
            supports_realtime=True,
        ),
        default_model_family="text-to-speech",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        credential_requirements=[_credential("cartesia_api_key", modes=["speech_tts"])],
        network_requirements=[_network("api.cartesia.ai", transport="websocket")],
        latency_metadata={"speech_profile": "tts_realtime_deferred"},
    )


def _kokoro_hosted_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="kokoro-hosted",
        label="Kokoro Hosted",
        description="Metadata placeholder for an externally hosted Kokoro text-to-speech provider.",
        kind="hosted_api",
        provider_role="speech_provider",
        status="disabled",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=False,
            supports_streaming=False,
            supports_tools=False,
            supports_mcp=False,
            supports_skills=False,
            supports_filesystem_access=False,
            supports_remote_execution=True,
            supports_api_key_auth=True,
            supports_local_binary=False,
            input_modalities=["text"],
            output_modalities=["audio"],
        ),
        default_model_family="kokoro-hosted",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        credential_requirements=[_credential("kokoro_hosted_api_key", modes=["speech_tts"])],
        network_requirements=[
            ProviderNetworkRequirement(
                outbound_required=True,
                allowed_hosts=[],
                transport="provider_declared",
                description="Host is selected when an external Kokoro provider is approved.",
            )
        ],
        latency_metadata={"speech_profile": "tts_hosted_deferred"},
    )
