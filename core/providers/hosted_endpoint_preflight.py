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
    *,
    upstream_provider_names: tuple[str, ...] = (),
) -> HostedEndpointRequestSnapshot:
    """Verify exact wire controls; empty catalogs and explicit-none are omitted."""
    if credential is None:
        raise OpenRouterAgenticProtocolError("provider_authentication_failed")
    state = decode_openrouter_chat_state(request.provider_private_state)
    payload, _new_messages = openrouter_chat_payload(request, state)
    omitted = not request.tool_definitions
    if (
        payload.get("stream") is not True
        or payload.get("stream_options") != {"include_usage": True}
        or (omitted and ("tools" in payload or "tool_choice" in payload))
        or (not omitted and (
            payload.get("tool_choice") != "auto"
            or not isinstance(payload.get("tools"), list)
            or len(payload["tools"]) != len(request.tool_definitions)
        ))
    ):
        raise OpenRouterAgenticProtocolError("provider_endpoint_parameters_unsupported")
    catalog = preflight_openrouter_agentic_catalog(
        request,
        credential=credential,
        upstream_provider_names=upstream_provider_names,
    )
    projection = {
        "model_id": request.model_id,
        "request_phase": request.request_phase,
        "streaming": True,
        "usage_accounting": True,
        "tool_calling": True,
        "tool_catalog_mode": "omitted" if omitted else "declared",
        "tool_choice_mode": "provider-default" if omitted else "auto",
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


@dataclass(frozen=True)
class OpenRouterCompletionRequestPreflight:
    """Bind configured router provider identities into live preflight."""

    upstream_provider_names: tuple[str, ...]

    def __call__(
        self,
        request: AgenticModelRequest,
        credential: EphemeralCredential | None,
    ) -> HostedEndpointRequestSnapshot:
        return preflight_openrouter_completion_request(
            request,
            credential,
            upstream_provider_names=self.upstream_provider_names,
        )


__all__ = [
    "HostedEndpointRequestSnapshot",
    "OpenRouterCompletionRequestPreflight",
    "preflight_google_interactions_request",
    "preflight_openrouter_completion_request",
]
