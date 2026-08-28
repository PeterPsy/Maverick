"""Exact request/catalog checks run before hosted completion transport."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.agentic_protocol import AgenticModelRequest, EphemeralCredential
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.providers.google_interactions_catalog import (
    preflight_google_interactions_catalog,
)
from core.providers.google_interactions_request import google_interaction_payload
from core.providers.google_interactions_state import decode_google_interaction_state
from core.providers.openrouter_agentic_catalog import (
    OpenRouterAgenticCatalogSnapshot,
    preflight_openrouter_agentic_catalog,
)
from core.providers.openrouter_agentic_models import OpenRouterAgenticProtocolError
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class HostedEndpointRequestSnapshot:
    """Redaction-safe exact wire behavior proven immediately before dispatch."""

    model_id: str
    request_phase: str
    streaming: bool
    usage_accounting: bool
    tool_calling: bool
    tool_catalog_mode: str
    tool_choice_mode: str
    reasoning_mode: str
    max_output_tokens: int
    snapshot_digest: str


def preflight_google_interactions_request(
    request: AgenticModelRequest,
    credential: EphemeralCredential | None,
) -> HostedEndpointRequestSnapshot:
    """Prove Google final requests omit tools and all requests use exact controls."""
    if credential is None:
        raise GoogleInteractionsProtocolError("provider_authentication_failed")
    state = decode_google_interaction_state(
        request.provider_private_state,
        default_mode="stateless",
    )
    payload, _new_input = google_interaction_payload(request, state)
    final = request.request_phase != "exploration"
    if (
        payload.get("stream") is not True
        or not isinstance(payload.get("generation_config"), dict)
        or (final and "tools" in payload)
        or (not final and bool(request.tool_definitions) != ("tools" in payload))
    ):
        raise GoogleInteractionsProtocolError("provider_endpoint_parameters_unsupported")
    catalog = preflight_google_interactions_catalog(
        request,
        credential=credential,
    )
    projection = {
        "model_id": request.model_id,
        "request_phase": request.request_phase,
        "streaming": catalog.streaming,
        "usage_accounting": catalog.usage_accounting,
        "tool_calling": catalog.tool_calling,
        "tool_catalog_mode": "omitted" if final else "declared",
        "tool_choice_mode": "provider-default",
        "reasoning_mode": str(request.reasoning_effort or "default"),
        "max_output_tokens": request.max_output_tokens,
        "live_catalog_snapshot_digest": catalog.catalog_snapshot_digest,
    }
    return HostedEndpointRequestSnapshot(
        **{
            key: value
            for key, value in projection.items()
            if key != "live_catalog_snapshot_digest"
        },
        snapshot_digest=canonical_digest(projection),
    )


def preflight_openrouter_completion_request(
    request: AgenticModelRequest,
    credential: EphemeralCredential | None,
) -> HostedEndpointRequestSnapshot:
    """Require live catalog support, including the exact `tool_choice: none`."""
    if credential is None:
        raise OpenRouterAgenticProtocolError("provider_authentication_failed")
    state = decode_openrouter_chat_state(request.provider_private_state)
    payload, _new_messages = openrouter_chat_payload(request, state)
    final = request.request_phase != "exploration"
    expected_choice = "none" if final else "auto"
    if (
        payload.get("stream") is not True
        or payload.get("stream_options") != {"include_usage": True}
        or payload.get("tool_choice") != expected_choice
        or not isinstance(payload.get("tools"), list)
        or (final and payload["tools"] != [])
    ):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    catalog = preflight_openrouter_agentic_catalog(
        request,
        credential=credential,
    )
    _require_openrouter_none_support(catalog, required=final)
    projection = {
        "model_id": request.model_id,
        "request_phase": request.request_phase,
        "streaming": True,
        "usage_accounting": True,
        "tool_calling": True,
        "tool_catalog_mode": "empty" if final else "declared",
        "tool_choice_mode": expected_choice,
        "reasoning_mode": str(request.reasoning_effort or "default"),
        "max_output_tokens": request.max_output_tokens,
        "live_catalog_snapshot_digest": catalog.catalog_snapshot_digest,
    }
    return HostedEndpointRequestSnapshot(
        **{
            key: value
            for key, value in projection.items()
            if key != "live_catalog_snapshot_digest"
        },
        snapshot_digest=canonical_digest(projection),
    )


def _require_openrouter_none_support(
    catalog: OpenRouterAgenticCatalogSnapshot,
    *,
    required: bool,
) -> None:
    if required and not catalog.supports_tool_choice_none:
        raise OpenRouterAgenticProtocolError(
            "provider_endpoint_parameters_unsupported"
        )


__all__ = [
    "HostedEndpointRequestSnapshot",
    "preflight_google_interactions_request",
    "preflight_openrouter_completion_request",
]
