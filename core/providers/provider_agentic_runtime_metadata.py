"""Static metadata for the Core-owned hosted agentic runtime engine."""

from __future__ import annotations

from datetime import datetime

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderExecutionContract,
)


def build_hosted_agentic_runtime_definition(timestamp: datetime) -> ProviderDefinition:
    """Return the process-independent runtime engine definition."""
    return ProviderDefinition(
        provider_id="maverick-tool-loop",
        label="Maverick Hosted Tool Loop",
        description="Core-owned agentic runtime engine for certified hosted model APIs.",
        kind="runtime_backend",
        provider_role="runtime_engine",
        status="active",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=True,
            supports_streaming=True,
            supports_tools=True,
            supports_mcp=True,
            supports_skills=True,
            supports_filesystem_access=True,
            supports_remote_execution=True,
            supports_api_key_auth=False,
            supports_local_binary=False,
            input_modalities=["text"],
            output_modalities=["text", "events"],
            supports_streaming_output=True,
            supports_tool_calling=True,
            supports_structured_output=True,
            latency_class="network_bound",
        ),
        default_model_family=None,
        requires_credentials=False,
        supported_execution_modes=["sandbox", "full-access"],
        created_at=timestamp,
        updated_at=timestamp,
        execution_contract=ProviderExecutionContract(
            adapter_type="agentic_runtime_engine",
            request_shape="provider_neutral_agentic_request",
            streaming_supported=True,
            timeout_policy="agentic_budget",
            error_mapping={"invalid_payload": "provider_response_invalid"},
            transport_test_mode="fake_required",
        ),
        latency_metadata={"latency_class": "network_bound"},
    )
