"""Agentic provider client for Google Gemini Interactions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import core.providers.google_interactions_models as google_interactions_models_module
import core.providers.google_interactions_request as google_interactions_request_module
import core.providers.google_interactions_state as google_interactions_state_module
import core.providers.google_interactions_stream as google_interactions_stream_module
import core.providers.google_interactions_transport as google_interactions_transport_module
from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    EphemeralCredential,
)
from core.providers.agentic_models import RoutingConstraint
from core.providers.google_interactions_models import (
    GoogleInteractionStateMode,
    GoogleInteractionsProtocolError,
)
from core.providers.google_interactions_request import google_interaction_payload
from core.providers.google_interactions_state import decode_google_interaction_state
from core.providers.google_interactions_stream import GoogleInteractionStreamDecoder
from core.providers.google_interactions_transport import (
    GoogleInteractionsHttpTransport,
    GoogleInteractionsTransport,
)
from core.providers.maverick_agent_provider_config import MaverickTokenCostPolicy


GOOGLE_AGENTIC_MODEL_ID = "gemini-3.6-flash"
GOOGLE_AGENTIC_MODEL_REVISION = "stable-2026-07"


class GoogleInteractionsAgenticClient:
    """Preserve Google continuation privately while exposing normalized events."""

    def __init__(
        self,
        *,
        model_id: str = GOOGLE_AGENTIC_MODEL_ID,
        state_mode: GoogleInteractionStateMode = "stateful",
        transport: GoogleInteractionsTransport | None = None,
        token_cost_policy: MaverickTokenCostPolicy | None = None,
        routing_constraint: RoutingConstraint | None = None,
        allowed_upstream_ids: tuple[str, ...] | None = None,
        upstream_provider_names: tuple[str, ...] | None = None,
        resolved_model_ids: tuple[str, ...] | None = None,
    ) -> None:
        if state_mode not in {"stateful", "stateless"}:
            raise ValueError("Unsupported Google Interactions state mode.")
        self.state_mode = state_mode
        self.model_id = str(model_id or "").strip()
        if not self.model_id:
            raise ValueError("Google Interactions model id is required.")
        builtin_config = None
        if self.model_id == GOOGLE_AGENTIC_MODEL_ID and (
            token_cost_policy is None
            or allowed_upstream_ids is None
            or upstream_provider_names is None
            or resolved_model_ids is None
        ):
            from core.providers.maverick_agent_builtins import (
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
            )

            builtin_config = GOOGLE_INTERACTIONS_PROVIDER_CONFIG
        self.transport = transport or GoogleInteractionsHttpTransport()
        self.token_cost_policy = token_cost_policy or (
            None if builtin_config is None else builtin_config.token_cost_policy
        )
        self.routing_constraint = routing_constraint
        self.allowed_upstream_ids = tuple(
            allowed_upstream_ids
            if allowed_upstream_ids is not None
            else (
                ()
                if builtin_config is None
                else builtin_config.routing_constraint.allowed_upstream_ids
            )
        )
        self.upstream_provider_names = tuple(
            upstream_provider_names
            if upstream_provider_names is not None
            else (
                ()
                if builtin_config is None
                else builtin_config.upstream_provider_names
            )
        )
        self.resolved_model_ids = tuple(
            resolved_model_ids
            if resolved_model_ids is not None
            else (
                () if builtin_config is None else builtin_config.resolved_model_ids
            )
        )
        self._validate_runtime_config()

    @property
    def endpoint_url(self) -> str:
        return str(getattr(self.transport, "endpoint", "") or "")

    def _validate_runtime_config(self) -> None:
        routing = self.routing_constraint
        if routing is None:
            return
        if (
            self.allowed_upstream_ids != tuple(routing.allowed_upstream_ids)
            or self.allowed_upstream_ids
            or self.upstream_provider_names
            or self.resolved_model_ids
            or routing.allow_fallbacks
            or routing.allowed_quantizations
        ):
            raise ValueError(
                "Google Interactions runtime routing config is unsupported."
            )

    @property
    def artifact_components(self) -> tuple[object, ...]:
        """Expose codec and transport modules included in capability evidence."""
        return (
            google_interactions_models_module,
            google_interactions_request_module,
            google_interactions_state_module,
            google_interactions_stream_module,
            google_interactions_transport_module,
        )

    async def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]:
        decoder = None
        failure: GoogleInteractionsProtocolError | None = None
        try:
            if request.model_id != self.model_id:
                raise GoogleInteractionsProtocolError("provider_request_rejected")
            if (
                self.routing_constraint is not None
                and request.routing_constraint != self.routing_constraint
            ):
                raise GoogleInteractionsProtocolError("provider_routing_not_certified")
            if credential is None:
                raise GoogleInteractionsProtocolError("provider_authentication_failed")
            state = decode_google_interaction_state(
                request.provider_private_state,
                default_mode=self.state_mode,
            )
            payload, new_input = google_interaction_payload(request, state)
            decoder = GoogleInteractionStreamDecoder(
                request=request,
                state=state,
                new_input=new_input,
                usage_cost=self._usage_cost,
            )
            async for raw_event in self.transport.stream(payload=payload, credential=credential):
                if failure is not None:
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
                try:
                    events = decoder.feed(raw_event)
                except GoogleInteractionsProtocolError as error:
                    failure = error
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
                terminal_error = False
                for event in events:
                    if event.provider_private_state is not None:
                        event = replace(
                            event,
                            provider_private_state=replace(
                                event.provider_private_state,
                                provider_request_id=request.request_id,
                                turn_generation=request.correlation_id,
                            ),
                        )
                    yield event
                    terminal_error = terminal_error or event.event_type == "error"
                if terminal_error:
                    return
            if failure is not None:
                yield AgenticModelEvent(
                    event_type="error",
                    request_id=request.request_id,
                    ordinal=decoder.ordinal + 1,
                    error_code=failure.reason_code,
                )
                return
            decoder.finish()
        except GoogleInteractionsProtocolError as error:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=error.reason_code,
            )
        except Exception:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=(
                    failure.reason_code
                    if failure is not None
                    else "provider_unavailable"
                ),
            )

    def _usage_cost(self, input_tokens: int, output_tokens: int) -> int | None:
        estimator = getattr(self.token_cost_policy, "usage_cost_microusd", None)
        if not callable(estimator):
            return None
        return estimator(input_tokens, output_tokens)
