"""Plain hosted text runtime bridge for non-agentic chat sessions."""

from __future__ import annotations

import json
import os
from typing import Callable

from core.observability.service import record_platform_event
from core.providers.models import RoutingDecision
from core.providers.payloads import routing_decision_payload
from core.providers.routing import ProviderRoutingContext, primary_routing_failure_reason, select_provider_for_profile
from core.providers.service import effective_provider_registry
from core.providers.text_generation import (
    FakeHostedTextTransport,
    HostedTextGenerationError,
    TextGenerationMessage,
    TextGenerationRequest,
    execute_hosted_text_generation,
)
from core.runtime.execution import RuntimeExecutionResult
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.runtime_session import RuntimeSessionRecord


HOSTED_TEXT_RUNTIME_PROVIDER_ID = "hosted-text-runtime"


def runtime_session_is_plain_hosted_chat(session: RuntimeSessionRecord) -> bool:
    """Return whether a session should use the plain hosted text bridge."""
    return getattr(session, "runtime_mode", "agentic") == "plain_hosted_chat"


def queue_provider_id_for_session(session: RuntimeSessionRecord) -> str:
    """Return the provider id used before a concrete hosted provider is routed."""
    if runtime_session_is_plain_hosted_chat(session):
        return HOSTED_TEXT_RUNTIME_PROVIDER_ID
    return str(session.provider_id or "codex")


def assert_plain_hosted_chat_input_allowed(
    session: RuntimeSessionRecord,
    *,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> None:
    """Fail closed on agentic/operative features before prompt materialization."""
    if not runtime_session_is_plain_hosted_chat(session):
        return
    if session.skill_ids:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_skills")
    if attachments:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_attachments")
    if app_references:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_app_references")


def execute_plain_hosted_text_turn(
    state,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    event_sink: Callable[[RuntimeExecutionEvent], object] | None = None,
) -> tuple[RuntimeExecutionResult, RoutingDecision]:
    """Execute one plain hosted chat turn through a routed hosted text provider."""
    decision = select_provider_for_profile(
        "fast_model",
        ProviderRoutingContext(
            workspace_id=session.workspace_id,
            provider_store=state.provider_store,
            registry=effective_provider_registry(state.provider_store),
            secret_store=state.secret_store,
            request_id=None,
        ),
    )
    _emit_routing_decision_event(event_sink, decision)
    _record_platform_routing_decision(state, session=session, decision=decision)
    if decision.execution_path != "plain_hosted_text" or decision.selected_provider_id is None:
        reason = primary_routing_failure_reason(decision)
        raise HostedTextGenerationError(reason, reason_codes=decision.reason_codes)
    request = TextGenerationRequest(
        model_id=decision.selected_model_id_or_voice_id or "",
        system_prompt=session.system_prompt,
        messages=[TextGenerationMessage(role="user", content=input_text)],
        stream=True,
        timeout_seconds=30,
        workspace_id=session.workspace_id,
        workspace_root=session.workspace_root,
    )
    try:
        result = execute_hosted_text_generation(
            state.provider_store,
            state.secret_store,
            decision=decision,
            request=request,
            runtime_session_id=session.session_id,
            transport=_fake_transport_from_environment(),
        )
    except HostedTextGenerationError as error:
        raise HostedTextGenerationError(
            error.reason_code,
            reason_codes=[*decision.reason_codes, error.reason_code],
        ) from error
    if event_sink is not None:
        for delta in result.deltas:
            event_sink(
                RuntimeExecutionEvent(
                    event_type="runtime.output.delta",
                    payload={
                        "text": delta,
                        "provider_id": decision.selected_provider_id,
                        "model_id": decision.selected_model_id_or_voice_id,
                        "runtime_mode": "plain_hosted_chat",
                    },
                )
            )
    return RuntimeExecutionResult(output_text=result.output_text, exit_code=0), decision


def _emit_routing_decision_event(
    event_sink: Callable[[RuntimeExecutionEvent], object] | None,
    decision: RoutingDecision,
) -> None:
    if event_sink is None:
        return
    event_sink(
        RuntimeExecutionEvent(
            event_type="provider.routing.decision",
            payload=routing_decision_payload(decision),
        )
    )


def _record_platform_routing_decision(state, *, session: RuntimeSessionRecord, decision: RoutingDecision) -> None:
    observability_store = getattr(state, "observability_store", None)
    if observability_store is None:
        return
    record_platform_event(
        observability_store,
        event_type="provider.routing.decision",
        event_plane="runtime",
        source_domain="providers",
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
        provider_id=decision.selected_provider_id,
        payload=routing_decision_payload(decision),
    )


def _fake_transport_from_environment() -> FakeHostedTextTransport | None:
    response = os.environ.get("MAVERICK_HOSTED_TEXT_FAKE_RESPONSE")
    chunks = os.environ.get("MAVERICK_HOSTED_TEXT_FAKE_CHUNKS")
    if response is None and chunks is None:
        return None
    parsed_chunks = _json_string_list(chunks)
    if response is not None and not parsed_chunks:
        parsed_chunks = [response]
    return FakeHostedTextTransport(
        response_text=response or "".join(parsed_chunks) or "fake hosted response",
        chunks=parsed_chunks,
    )


def _json_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item)]
    return [str(parsed)]
