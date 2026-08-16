"""Static metadata for hosted model and remote speech providers."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.provider_agentic_runtime_metadata import (
    build_hosted_agentic_runtime_definition,
)
from core.providers.provider_google_metadata import build_google_ai_studio_definition
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
        build_hosted_agentic_runtime_definition(timestamp),
        build_google_ai_studio_definition(timestamp),
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


def _openrouter_upstream(
    provider_id: str,
    label: str,
    *,
    quantization: str,
    context_length: int,
    max_completion_tokens: int | None = None,
    tag: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider_id": provider_id,
        "label": label,
        "tag": tag or provider_id,
        "quantization": quantization,
        "context_length": context_length,
    }
    if max_completion_tokens is not None:
        payload["max_completion_tokens"] = max_completion_tokens
    return payload


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
                description="OpenRouter hosted multimodal model candidate for fast_model routing.",
                default_reasoning_effort=None,
                input_modalities=["text", "image", "video", "pdf"],
                output_modalities=["text"],
                upstream_provider_options=[
                    _openrouter_upstream(
                        "google-ai-studio",
                        "Google AI Studio",
                        quantization="unknown",
                        context_length=262144,
                        max_completion_tokens=32768,
                    ),
                    _openrouter_upstream(
                        "open-inference",
                        "OpenInference",
                        quantization="bf16",
                        context_length=262144,
                        max_completion_tokens=8192,
                        tag="open-inference/bf16",
                    ),
                ],
            ),
            ProviderModelOption(
                model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
                label="Nemotron 3 Ultra (free)",
                description="OpenRouter hosted text model candidate for fast_model routing.",
                default_reasoning_effort=None,
                input_modalities=["text", "pdf"],
                output_modalities=["text"],
                upstream_provider_options=[
                    _openrouter_upstream(
                        "nvidia",
                        "Nvidia",
                        quantization="unknown",
                        context_length=1000000,
                        max_completion_tokens=65536,
                    )
                ],
            ),
            ProviderModelOption(
                model_id="deepseek/deepseek-v4-flash",
                label="DeepSeek V4 Flash",
                description="OpenRouter paid text model candidate for high-throughput fast_model routing.",
                default_reasoning_effort=None,
                input_modalities=["text", "pdf"],
                output_modalities=["text"],
                upstream_provider_options=[
                    _openrouter_upstream(
                        "wafer/fp4",
                        "Wafer",
                        quantization="fp4",
                        context_length=1000000,
                        max_completion_tokens=32000,
                    ),
                    _openrouter_upstream("gmicloud/fp8", "GMICloud", quantization="fp8", context_length=1048575),
                    _openrouter_upstream(
                        "deepinfra/fp4",
                        "DeepInfra",
                        quantization="fp4",
                        context_length=1048576,
                        max_completion_tokens=163840,
                    ),
                    _openrouter_upstream(
                        "deepseek",
                        "DeepSeek",
                        quantization="unknown",
                        context_length=1048576,
                        max_completion_tokens=163840,
                    ),
                    _openrouter_upstream(
                        "venice",
                        "Venice",
                        quantization="unknown",
                        context_length=1000000,
                        max_completion_tokens=163840,
                    ),
                ],
            ),
            ProviderModelOption(
                model_id="hexgrad/kokoro-82m",
                label="Kokoro 82M",
                description="OpenRouter paid text-to-speech model for speech synthesis workflows.",
                default_reasoning_effort=None,
                input_modalities=["text"],
                output_modalities=["speech"],
                upstream_provider_options=[
                    _openrouter_upstream(
                        "deepinfra",
                        "DeepInfra",
                        quantization="unknown",
                        context_length=4096,
                    )
                ],
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
        description="Remote speech-to-text provider metadata with separate transcription and conversation profiles.",
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
        default_model_family="nova-3",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            ProviderModelOption(
                model_id="nova-3",
                label="Nova-3",
                description=(
                    "Default Deepgram speech-to-text model for prerecorded audio, file transcription, "
                    "and one-shot microphone dictation."
                ),
                default_reasoning_effort=None,
                input_modalities=["audio"],
                output_modalities=["text", "events"],
                metadata={
                    "purpose": "prerecorded_transcription",
                    "endpoint": "https://api.deepgram.com/v1/listen?model=nova-3",
                },
            ),
            ProviderModelOption(
                model_id="nova-3-general",
                label="Nova-3 General",
                description="Deepgram Nova-3 general transcription profile for prerecorded audio.",
                default_reasoning_effort=None,
                input_modalities=["audio"],
                output_modalities=["text", "events"],
                metadata={
                    "purpose": "prerecorded_transcription",
                    "endpoint": "https://api.deepgram.com/v1/listen?model=nova-3-general",
                },
            ),
            ProviderModelOption(
                model_id="nova-3-medical",
                label="Nova-3 Medical",
                description="Deepgram Nova-3 medical transcription profile for prerecorded clinical audio.",
                default_reasoning_effort=None,
                input_modalities=["audio"],
                output_modalities=["text", "events"],
                metadata={
                    "purpose": "prerecorded_transcription",
                    "endpoint": "https://api.deepgram.com/v1/listen?model=nova-3-medical",
                },
            ),
            ProviderModelOption(
                model_id="flux-general-multi",
                label="Flux General Multilingual",
                description="Deepgram Flux realtime conversation model with multilingual turn detection.",
                default_reasoning_effort=None,
                input_modalities=["audio"],
                output_modalities=["text", "events"],
                metadata={
                    "purpose": "conversational_streaming",
                    "endpoint": "wss://api.deepgram.com/v2/listen?model=flux-general-multi",
                },
            ),
            ProviderModelOption(
                model_id="flux-general-en",
                label="Flux General English",
                description="Deepgram Flux realtime conversation model for English turn-taking.",
                default_reasoning_effort=None,
                input_modalities=["audio"],
                output_modalities=["text", "events"],
                metadata={
                    "purpose": "conversational_streaming",
                    "endpoint": "wss://api.deepgram.com/v2/listen?model=flux-general-en",
                },
            ),
        ],
        credential_requirements=[_credential("deepgram_api_key", modes=["speech_stt"])],
        network_requirements=[
            _network("api.deepgram.com", transport="https"),
            _network("api.deepgram.com", transport="websocket"),
        ],
        latency_metadata={
            "speech_profile": "stt_realtime_deferred",
            "default_audio_transcription_model_id": "nova-3",
            "default_conversation_model_id": "flux-general-multi",
            "prerecorded_endpoint": "https://api.deepgram.com/v1/listen?model=nova-3",
            "conversation_endpoint": "wss://api.deepgram.com/v2/listen?model=flux-general-multi",
        },
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
