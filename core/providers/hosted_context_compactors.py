"""Exact provider-state compactors for profile-pinned hosted recipes."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from core.providers.agentic_models import AgenticContextPolicy
from core.providers.agentic_protocol import AgenticProviderPrivateState
from core.providers.google_interactions_models import GoogleInteractionState
from core.providers.google_interactions_state import (
    decode_google_interaction_state,
    encode_google_interaction_state,
)
from core.providers.openrouter_agentic_models import OpenRouterChatState
from core.providers.openrouter_agentic_state import (
    decode_openrouter_chat_state,
    encode_openrouter_chat_state,
)
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_context_management import (
    HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
    HostedContextCompactionEvidence,
    HostedContextCompactionResult,
    bounded_semantic_context_summary,
    canonical_context_digest,
)


def compact_openrouter_history(
    private_state: AgenticProviderPrivateState,
    policy: AgenticContextPolicy,
    summary_base: dict[str, object],
) -> HostedContextCompactionResult:
    """Replace old chat history with a semantic summary plus an active suffix."""
    try:
        state = decode_openrouter_chat_state(private_state)
    except Exception as error:
        raise HostedAgenticLoopError("context_compaction_invalid") from error
    system = tuple(item for item in state.history if item.get("role") == "system")
    active_result_ids = _active_tool_result_ids(summary_base)
    retained = _openrouter_pairing_history(
        state,
        active_tool_result_ids=active_result_ids,
    )
    retained_consumed_ids = tuple(
        str(item.get("tool_call_id") or "")
        for item in retained
        if item.get("role") == "tool"
    )
    omitted = max(0, len(state.history) - len(system) - len(retained))
    summary_payload = {
        **_provider_summary_base(summary_base),
        "provider": "openrouter",
        "omitted_history_items": omitted,
        "retained_history_items": len(system) + len(retained),
        "active_pending_call_ids_digest": canonical_context_digest(
            tuple(item.call_id for item in state.pending_tool_calls)
        ),
    }
    summary = bounded_semantic_context_summary(
        summary_payload,
        _openrouter_semantic_history(state.history),
        max_bytes=policy.summary_max_bytes,
    )
    history = (
        *system,
        {"role": "user", "content": summary},
        *retained,
    )
    compacted = encode_openrouter_chat_state(
        OpenRouterChatState(
            schema_version=state.schema_version,
            history=history,
            pending_tool_calls=state.pending_tool_calls,
            consumed_tool_call_ids=retained_consumed_ids,
        )
    )
    compacted = _preserve_private_metadata(compacted, private_state)
    return HostedContextCompactionResult(
        state=compacted,
        evidence=_evidence(
            private_state,
            compacted,
            policy=policy,
            summary=summary,
            summary_base=summary_base,
            omitted_items=omitted,
            retained_items=len(system) + len(retained),
        ),
    )


def compact_google_stateless_history(
    private_state: AgenticProviderPrivateState,
    policy: AgenticContextPolicy,
    summary_base: dict[str, object],
) -> HostedContextCompactionResult:
    """Compact Core-managed Google stateless history without breaking pairing."""
    try:
        state = decode_google_interaction_state(
            private_state,
            default_mode="stateless",
        )
    except Exception as error:
        raise HostedAgenticLoopError("context_compaction_invalid") from error
    pending_ids = tuple(item.call_id for item in state.pending_function_calls)
    active_result_ids = _active_tool_result_ids(summary_base)
    retained = _google_pairing_steps(
        state.history,
        tuple(dict.fromkeys((*active_result_ids, *pending_ids))),
    )
    if pending_ids and not retained:
        raise HostedAgenticLoopError("context_compaction_pairing_unsafe")
    retained_consumed_ids = tuple(
        call_id
        for call_id in state.consumed_function_call_ids
        if call_id in active_result_ids
    )
    omitted = max(0, len(state.history) - len(retained))
    summary_payload = {
        **_provider_summary_base(summary_base),
        "provider": "google-ai-studio",
        "omitted_history_items": omitted,
        "retained_history_items": len(retained),
        "active_pending_call_ids_digest": canonical_context_digest(pending_ids),
    }
    summary = bounded_semantic_context_summary(
        summary_payload,
        _google_semantic_history(state.history),
        max_bytes=policy.summary_max_bytes,
    )
    summary_step = {
        "type": "user_input",
        "content": [{"type": "text", "text": summary}],
    }
    compacted = encode_google_interaction_state(
        GoogleInteractionState(
            schema_version=state.schema_version,
            mode="stateless",
            previous_interaction_id=None,
            history=(summary_step, *retained),
            pending_function_calls=state.pending_function_calls,
            consumed_function_call_ids=retained_consumed_ids,
        )
    )
    compacted = _preserve_private_metadata(compacted, private_state)
    return HostedContextCompactionResult(
        state=compacted,
        evidence=_evidence(
            private_state,
            compacted,
            policy=policy,
            summary=summary,
            summary_base=summary_base,
            omitted_items=omitted,
            retained_items=len(retained),
        ),
    )


def _openrouter_pairing_history(
    state: OpenRouterChatState,
    *,
    active_tool_result_ids: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    relevant_ids = set(active_tool_result_ids)
    relevant_ids.update(item.call_id for item in state.pending_tool_calls)
    if not relevant_ids:
        return ()
    retained: list[dict[str, object]] = []
    retained_call_ids: list[str] = []
    retained_tool_ids: list[str] = []
    for item in state.history:
        role = item.get("role")
        if role == "assistant" and item.get("tool_calls"):
            call_ids = tuple(
                str(call.get("id") or "")
                for call in item["tool_calls"]
                if isinstance(call, dict)
            )
            if relevant_ids.intersection(call_ids):
                retained.append(dict(item))
                retained_call_ids.extend(call_ids)
                relevant_ids.update(call_ids)
        elif role == "tool" and str(item.get("tool_call_id") or "") in relevant_ids:
            retained.append(dict(item))
            retained_tool_ids.append(str(item["tool_call_id"]))
    pending_ids = tuple(item.call_id for item in state.pending_tool_calls)
    reconstructed_pending = tuple(
        call_id for call_id in retained_call_ids if call_id not in retained_tool_ids
    )
    if (
        reconstructed_pending != pending_ids
        or any(call_id not in retained_call_ids for call_id in retained_tool_ids)
    ):
        raise HostedAgenticLoopError("context_compaction_pairing_unsafe")
    return tuple(retained)


def _google_pairing_steps(
    history: tuple[dict[str, object], ...],
    pending_ids: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    if not pending_ids:
        return ()
    identifiers = set(pending_ids)
    retained = []
    for step in history:
        if _contains_exact_identifier(step, identifiers):
            retained.append(dict(step))
    return tuple(retained)


def _contains_exact_identifier(value: object, identifiers: set[str]) -> bool:
    if isinstance(value, str):
        return value in identifiers
    if isinstance(value, dict):
        return any(
            _contains_exact_identifier(item, identifiers)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_exact_identifier(item, identifiers) for item in value)
    return False


def _openrouter_semantic_history(
    history: tuple[dict[str, object], ...],
) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    for message in history:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role in {"user", "assistant", "tool"} and isinstance(content, str) and content.strip():
            values.append({"role": role, "text": content})
        if role == "assistant" and isinstance(message.get("tool_calls"), list):
            for call in message["tool_calls"]:
                function = call.get("function") if isinstance(call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = (
                    function.get("arguments") if isinstance(function, dict) else None
                )
                if isinstance(name, str) and name:
                    values.append(
                        {
                            "role": "assistant_action",
                            "text": (
                                f"Called tool {name} with arguments: "
                                f"{_canonical_tool_arguments(arguments)}"
                            ),
                        }
                    )
    return tuple(values)


def _google_semantic_history(
    history: tuple[dict[str, object], ...],
) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    for step in history:
        step_type = str(step.get("type") or "")
        if step_type in {"user_input", "model_output"}:
            role = "user" if step_type == "user_input" else "assistant"
            values.extend(
                {"role": role, "text": text}
                for text in _google_text_values(step.get("content"))
            )
        elif step_type == "function_result":
            values.extend(
                {"role": "tool", "text": text}
                for text in _google_text_values(step.get("result"))
            )
        elif step_type == "function_call":
            name = step.get("name")
            arguments = step.get("arguments")
            values.append(
                {
                    "role": "assistant_action",
                    "text": (
                        f"Called tool {name} with arguments: "
                        f"{_canonical_tool_arguments(arguments)}"
                        if isinstance(name, str) and name
                        else "Called a tool with arguments: "
                        f"{_canonical_tool_arguments(arguments)}"
                    ),
                }
            )
    return tuple(values)


def _google_text_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        str(item["text"])
        for item in value
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
        and str(item["text"]).strip()
    )


def _canonical_tool_arguments(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(
            value if value is not None else {},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return "<unprojectable>"


def _active_tool_result_ids(summary_base: dict[str, object]) -> tuple[str, ...]:
    value = summary_base.get("_active_tool_result_ids", ())
    if (
        not isinstance(value, tuple)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise HostedAgenticLoopError("context_compaction_pairing_unsafe")
    return value


def _provider_summary_base(summary_base: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in summary_base.items()
        if not key.startswith("_")
    }


def _preserve_private_metadata(
    compacted: AgenticProviderPrivateState,
    source: AgenticProviderPrivateState,
) -> AgenticProviderPrivateState:
    return replace(
        compacted,
        source_metadata=source.source_metadata,
        effective_data_class=source.effective_data_class,
        effective_trust_level=source.effective_trust_level,
        provider_request_id=source.provider_request_id,
        turn_generation=source.turn_generation,
    )


def _evidence(
    source: AgenticProviderPrivateState,
    compacted: AgenticProviderPrivateState,
    *,
    policy: AgenticContextPolicy,
    summary: str,
    summary_base: dict[str, object],
    omitted_items: int,
    retained_items: int,
) -> HostedContextCompactionEvidence:
    return HostedContextCompactionEvidence(
        schema_version=HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
        policy_revision=policy.revision,
        applied=True,
        source_state_digest=hashlib.sha256(source.content).hexdigest(),
        compacted_state_digest=hashlib.sha256(compacted.content).hexdigest(),
        source_bytes=len(source.content),
        compacted_bytes=len(compacted.content),
        omitted_items=omitted_items,
        retained_items=retained_items,
        authority_digest=str(summary_base["authority_digest"]),
        provenance_digest=str(summary_base["provenance_digest"]),
        summary_digest=hashlib.sha256(summary.encode("ascii")).hexdigest(),
    )


__all__ = [
    "compact_google_stateless_history",
    "compact_openrouter_history",
]
