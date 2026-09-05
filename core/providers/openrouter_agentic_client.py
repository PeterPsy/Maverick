"""Certified OpenRouter agentic provider client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import core.providers.openrouter_agentic_models as openrouter_agentic_models_module
import core.providers.openrouter_agentic_request as openrouter_agentic_request_module
import core.providers.openrouter_agentic_state as openrouter_agentic_state_module
import core.providers.openrouter_agentic_stream as openrouter_agentic_stream_module
import core.providers.openrouter_agentic_stream_fields as openrouter_agentic_stream_fields_module
import core.providers.openrouter_agentic_transport as openrouter_agentic_transport_module
from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    EphemeralCredential,
)
from core.providers.agentic_models import RoutingConstraint
from core.providers.maverick_agent_provider_config import MaverickTokenCostPolicy
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OpenRouterAgenticProtocolError,
)
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.providers.openrouter_agentic_stream import OpenRouterChatStreamDecoder
from core.providers.openrouter_agentic_transport import (
    OpenRouterAgenticHttpTransport,
    OpenRouterAgenticTransport,
)


class OpenRouterAgenticClient:
    """Run one exact model/upstream protocol and expose normalized events."""

    def __init__(
        self,
        *,
        model_id: str = OPENROUTER_AGENTIC_MODEL_ID,
        transport: OpenRouterAgenticTransport | None = None,
        token_cost_policy: MaverickTokenCostPolicy | None = None,
        routing_constraint: RoutingConstraint | None = None,
        allowed_upstream_ids: tuple[str, ...] | None = None,
        upstream_provider_names: tuple[str, ...] | None = None,
        resolved_model_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.model_id = str(model_id or "").strip()
        if not self.model_id:
            raise ValueError("OpenRouter agentic model id is required.")
        builtin_config = None
        if self.model_id == OPENROUTER_AGENTIC_MODEL_ID and (
            token_cost_policy is None
            or routing_constraint is None
            or allowed_upstream_ids is None
            or upstream_provider_names is None
            or resolved_model_ids is None
        ):
            from core.providers.maverick_agent_builtins import (
                OPENROUTER_DEEPINFRA_PROVIDER_CONFIG,
            )

            builtin_config = OPENROUTER_DEEPINFRA_PROVIDER_CONFIG
        self.transport = transport or OpenRouterAgenticHttpTransport()
        self.token_cost_policy = token_cost_policy or (
            None if builtin_config is None else builtin_config.token_cost_policy
        )
        self.routing_constraint = routing_constraint or (
            None if builtin_config is None else builtin_config.routing_constraint
        )
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
            or len(self.allowed_upstream_ids) != 1
            or len(self.upstream_provider_names) != 1
            or not self.resolved_model_ids
            or routing.allow_fallbacks
            or not routing.require_parameters
            or routing.data_collection_policy != "deny"
            or not routing.require_zdr
            or not routing.allowed_quantizations
        ):
            raise ValueError("OpenRouter agentic runtime routing config is unsupported.")

    @property
    def artifact_components(self) -> tuple[object, ...]:
        return (
            openrouter_agentic_models_module,
            openrouter_agentic_request_module,
            openrouter_agentic_state_module,
            openrouter_agentic_stream_module,
            openrouter_agentic_stream_fields_module,
            openrouter_agentic_transport_module,
        )

    async def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]:
        decoder = None
        failure: OpenRouterAgenticProtocolError | None = None
        try:
            if request.model_id != self.model_id:
                raise OpenRouterAgenticProtocolError("provider_request_rejected")
            if (
                self.routing_constraint is not None
                and request.routing_constraint != self.routing_constraint
            ):
                raise OpenRouterAgenticProtocolError(
                    "provider_routing_not_certified"
                )
            if credential is None:
                raise OpenRouterAgenticProtocolError("provider_authentication_failed")
            state = decode_openrouter_chat_state(request.provider_private_state)
            payload, new_messages = openrouter_chat_payload(request, state)
            decoder = OpenRouterChatStreamDecoder(
                request=request,
                state=state,
                new_messages=new_messages,
                usage_cost=self._usage_cost,
                upstream_provider_names=self.upstream_provider_names,
                resolved_model_ids=self.resolved_model_ids,
            )
            async for raw_event in self.transport.stream(payload=payload, credential=credential):
                if failure is not None:
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
                try:
                    events = decoder.feed(raw_event)
                except OpenRouterAgenticProtocolError as error:
                    failure = error
                    for event in decoder.failure_observed_tool_events():
                        yield event
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
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
            if failure is not None:
                yield AgenticModelEvent(
                    event_type="error",
                    request_id=request.request_id,
                    ordinal=decoder.ordinal + 1,
                    error_code=failure.reason_code,
                )
                return
            decoder.finish()
        except OpenRouterAgenticProtocolError as cause:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=cause.reason_code,
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
