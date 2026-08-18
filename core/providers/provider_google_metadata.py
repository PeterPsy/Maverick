"""Google AI Studio provider and current Gemini model catalog metadata."""

from __future__ import annotations

from datetime import datetime

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderCredentialRequirement,
    ProviderDefinition,
    ProviderExecutionContract,
    ProviderModelOption,
    ProviderNetworkRequirement,
    ProviderReasoningOption,
)


def build_google_ai_studio_definition(timestamp: datetime) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id="google-ai-studio",
        label="Google AI Studio",
        description="Hosted Gemini text and certified agentic Interactions provider metadata.",
        kind="hosted_api",
        provider_role="model_provider",
        status="disabled",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=False,
            supports_streaming=True,
            supports_tools=True,
            supports_mcp=False,
            supports_skills=False,
            supports_filesystem_access=False,
            supports_remote_execution=True,
            supports_api_key_auth=True,
            supports_local_binary=False,
            input_modalities=["text"],
            output_modalities=["text"],
            supports_streaming_output=True,
            supports_tool_calling=True,
            supports_structured_output=True,
            latency_class="low",
        ),
        default_model_family="gemini-3.6-flash",
        requires_credentials=True,
        supported_execution_modes=[],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            _model(
                "gemini-3.6-flash",
                "Gemini 3.6 Flash",
                "Stable Gemini 3.6 Flash model certified for preview agentic Interactions.",
                reasoning="high",
                endpoint="https://generativelanguage.googleapis.com/v1/interactions",
                protocol="google-interactions",
            ),
            _model(
                "gemini-3.5-flash",
                "Gemini 3.5 Flash",
                "Stable Gemini Flash model retained for compatible hosted text routing.",
                endpoint=(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    "gemini-3.5-flash:generateContent"
                ),
            ),
            _model(
                "gemini-3.5-flash-lite",
                "Gemini 3.5 Flash-Lite",
                "Stable low-cost Gemini Flash-Lite model for high-throughput agentic work.",
                reasoning="high",
                endpoint="https://generativelanguage.googleapis.com/v1/interactions",
                protocol="google-interactions",
            ),
            _model(
                "gemini-3.1-flash-lite",
                "Gemini 3.1 Flash-Lite",
                "Stable legacy Flash-Lite model retained for pinned workspace compatibility.",
                endpoint=(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    "gemini-3.1-flash-lite:generateContent"
                ),
            ),
        ],
        credential_requirements=[
            ProviderCredentialRequirement(
                secret_alias_or_logical_name="google_ai_studio_api_key",
                secret_kind="api_key",
                required_for_modes=["plain_hosted_chat", "agentic_runtime"],
                secret_binding_scope="provider",
            )
        ],
        network_requirements=[
            ProviderNetworkRequirement(
                outbound_required=True,
                allowed_hosts=["generativelanguage.googleapis.com"],
                transport="https",
            )
        ],
        execution_contract=ProviderExecutionContract(
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
            secret_alias_or_logical_name="google_ai_studio_api_key",
            transport_test_mode="fake_supported",
        ),
        latency_metadata={"latency_class": "low"},
    )


def _model(
    model_id: str,
    label: str,
    description: str,
    *,
    endpoint: str,
    reasoning: str | None = None,
    protocol: str | None = None,
) -> ProviderModelOption:
    metadata: dict[str, object] = {
        "endpoint": endpoint,
        "context_length": 1_048_576,
        "max_output_tokens": 65_536,
    }
    if protocol:
        metadata.update(api_version="v1", protocol=protocol, lifecycle="stable")
    return ProviderModelOption(
        model_id=model_id,
        label=label,
        description=description,
        default_reasoning_effort=reasoning,
        supported_reasoning_efforts=(
            [
                ProviderReasoningOption(effort="minimal", label="Minimal", description="Fastest responses"),
                ProviderReasoningOption(effort="low", label="Low", description="Light reasoning"),
                ProviderReasoningOption(effort="medium", label="Medium", description="Balanced reasoning"),
                ProviderReasoningOption(effort="high", label="High", description="Deep reasoning"),
            ]
            if reasoning is not None
            else []
        ),
        input_modalities=["text", "image", "audio", "video", "pdf"],
        output_modalities=["text"],
        metadata=metadata,
    )
