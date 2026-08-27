"""Encode and validate opaque Google Interactions continuation state."""

from __future__ import annotations

import json

from core.providers.agentic_protocol import AgenticProviderPrivateState
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
    GoogleInteractionState,
    GoogleInteractionStateMode,
    GoogleInteractionsProtocolError,
    GooglePendingFunctionCall,
)
from core.runtime.hosted_agentic_models import HostedProviderStateInspection


def initial_google_interaction_state(mode: GoogleInteractionStateMode) -> GoogleInteractionState:
    if mode not in {"stateful", "stateless"}:
        raise GoogleInteractionsProtocolError("provider_private_state_invalid")
    return GoogleInteractionState(
        schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
        mode=mode,
        previous_interaction_id=None,
        history=(),
        pending_function_calls=(),
        consumed_function_call_ids=(),
    )


def decode_google_interaction_state(
    private_state: AgenticProviderPrivateState | None,
    *,
    default_mode: GoogleInteractionStateMode,
) -> GoogleInteractionState:
    if private_state is None:
        return initial_google_interaction_state(default_mode)
    identity = (
        private_state.codec_id,
        private_state.codec_version,
        private_state.schema_version,
        private_state.content_type,
    )
    if identity != (
        GOOGLE_INTERACTIONS_CODEC_ID,
        GOOGLE_INTERACTIONS_CODEC_VERSION,
        GOOGLE_INTERACTIONS_SCHEMA_VERSION,
        GOOGLE_INTERACTIONS_CONTENT_TYPE,
    ):
        raise GoogleInteractionsProtocolError("provider_private_state_invalid")
    try:
        payload = json.loads(private_state.content)
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "mode",
            "previous_interaction_id",
            "history",
            "pending_function_calls",
            "consumed_function_call_ids",
        }:
            raise ValueError
        mode = payload["mode"]
        history = payload["history"]
        pending = payload["pending_function_calls"]
        consumed = payload["consumed_function_call_ids"]
        previous = payload["previous_interaction_id"]
        if (
            payload["schema_version"] != GOOGLE_INTERACTIONS_SCHEMA_VERSION
            or mode not in {"stateful", "stateless"}
            or mode != default_mode
            or not isinstance(history, list)
            or not all(isinstance(step, dict) for step in history)
            or not isinstance(pending, list)
            or not isinstance(consumed, list)
            or not all(isinstance(item, str) and item for item in consumed)
            or len(set(consumed)) != len(consumed)
            or previous is not None and not isinstance(previous, str)
        ):
            raise ValueError
        calls = tuple(_pending_call(item) for item in pending)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GoogleInteractionsProtocolError("provider_private_state_invalid") from error
    if mode == "stateful" and history:
        raise GoogleInteractionsProtocolError("provider_private_state_invalid")
    if mode == "stateless" and previous is not None:
        raise GoogleInteractionsProtocolError("provider_private_state_invalid")
    if (
        len({item.call_id for item in calls}) != len(calls)
        or {item.call_id for item in calls}.intersection(consumed)
    ):
        raise GoogleInteractionsProtocolError("provider_private_state_invalid")
    return GoogleInteractionState(
        schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
        mode=mode,
        previous_interaction_id=previous,
        history=tuple(dict(step) for step in history),
        pending_function_calls=calls,
        consumed_function_call_ids=tuple(consumed),
    )


def encode_google_interaction_state(state: GoogleInteractionState) -> AgenticProviderPrivateState:
    payload = {
        "schema_version": state.schema_version,
        "mode": state.mode,
        "previous_interaction_id": state.previous_interaction_id,
        "history": state.history,
        "pending_function_calls": [
            {"call_id": item.call_id, "name": item.name}
            for item in state.pending_function_calls
        ],
        "consumed_function_call_ids": state.consumed_function_call_ids,
    }
    return AgenticProviderPrivateState(
        codec_id=GOOGLE_INTERACTIONS_CODEC_ID,
        codec_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
        schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
        content_type=GOOGLE_INTERACTIONS_CONTENT_TYPE,
        content=json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    )


def inspect_google_interaction_state(
    content: bytes,
    *,
    mode: GoogleInteractionStateMode,
) -> HostedProviderStateInspection:
    """Decode recovery facts through the exact current Google codec identity."""
    state = decode_google_interaction_state(
        AgenticProviderPrivateState(
            codec_id=GOOGLE_INTERACTIONS_CODEC_ID,
            codec_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
            schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
            content_type=GOOGLE_INTERACTIONS_CONTENT_TYPE,
            content=content,
        ),
        default_mode=mode,
    )
    return HostedProviderStateInspection(
        pending_tool_calls=tuple(
            (item.call_id, item.name) for item in state.pending_function_calls
        ),
        consumed_tool_call_ids=state.consumed_function_call_ids,
    )


def _pending_call(value: object) -> GooglePendingFunctionCall:
    if not isinstance(value, dict) or set(value) != {"call_id", "name"}:
        raise ValueError
    call_id = value.get("call_id")
    name = value.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ValueError
    return GooglePendingFunctionCall(call_id=call_id, name=name)
