"""Profile-pinned context admission and governed provider-history compaction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Callable

from core.providers.agentic_models import AgenticContextPolicy
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticProviderPrivateState,
)
from core.runtime.hosted_agentic_budget import estimate_hosted_request_tokens
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.tool_result_artifacts import MIN_TOOL_RESULT_SUMMARY_BYTES


HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION = "2"


@dataclass(frozen=True)
class HostedContextCompactionEvidence:
    """Redaction-safe evidence for one deterministic history projection."""

    schema_version: str
    policy_revision: str
    applied: bool
    source_state_digest: str
    compacted_state_digest: str
    source_bytes: int
    compacted_bytes: int
    omitted_items: int
    retained_items: int
    authority_digest: str
    provenance_digest: str
    summary_digest: str

    @property
    def evidence_digest(self) -> str:
        return canonical_context_digest(self.__dict__)

    def public_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_revision": self.policy_revision,
            "applied": self.applied,
            "source_bytes": self.source_bytes,
            "compacted_bytes": self.compacted_bytes,
            "omitted_items": self.omitted_items,
            "retained_items": self.retained_items,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class HostedContextCompactionResult:
    state: AgenticProviderPrivateState
    evidence: HostedContextCompactionEvidence


HostedProviderStateCompactor = Callable[
    [AgenticProviderPrivateState, AgenticContextPolicy, dict[str, object]],
    HostedContextCompactionResult,
]


def manage_hosted_provider_context(
    state: AgenticProviderPrivateState | None,
    *,
    context,
    context_policy: AgenticContextPolicy | None,
    compactor: HostedProviderStateCompactor | None,
    active_tool_result_ids: tuple[str, ...] = (),
) -> tuple[AgenticProviderPrivateState | None, HostedContextCompactionEvidence | None]:
    """Compact provider history at a deterministic pre-dispatch boundary."""
    if context_policy is None:
        return state, None
    validate_agentic_context_policy(context_policy)
    if state is None:
        return None, None
    authority = getattr(context, "effective_authority", None)
    authority_digest = str(getattr(authority, "authority_digest", "") or "")
    if not authority_digest:
        raise HostedAgenticLoopError("runtime_authority_unavailable")
    source_digest = hashlib.sha256(state.content).hexdigest()
    source_bytes = len(state.content)
    estimated_tokens = max(1, math.ceil(source_bytes / 4))
    provenance_digest = canonical_context_digest(
        [
            {
                "source_block_digest": item.source_block_digest,
                "source_data_class": item.source_data_class,
                "source_trust_level": item.source_trust_level,
                "provenance": item.provenance,
                "semantic_block_id": item.semantic_block_id,
            }
            for item in state.source_metadata
        ]
    )
    if estimated_tokens < context_policy.compaction_trigger_tokens:
        return state, HostedContextCompactionEvidence(
            schema_version=HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
            policy_revision=context_policy.revision,
            applied=False,
            source_state_digest=source_digest,
            compacted_state_digest=source_digest,
            source_bytes=source_bytes,
            compacted_bytes=source_bytes,
            omitted_items=0,
            retained_items=0,
            authority_digest=authority_digest,
            provenance_digest=provenance_digest,
            summary_digest="",
        )
    if context_policy.compaction_mode != "provider_history" or compactor is None:
        raise HostedAgenticLoopError("context_compaction_unavailable")
    summary_base = {
        "schema_version": HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION,
        "policy_revision": context_policy.revision,
        "source_state_digest": source_digest,
        "authority_digest": authority_digest,
        "provenance_digest": provenance_digest,
        "source_count": len(state.source_metadata),
        "active_tool_result_ids_digest": canonical_context_digest(
            active_tool_result_ids
        ),
        # Pairing identifiers are needed by the private codec compactor but are
        # deliberately excluded from the provider-visible summary.
        "_active_tool_result_ids": active_tool_result_ids,
        "notice": (
            "Older provider history was compacted by Maverick. Current platform, "
            "workspace, agent, skill, authority, and user blocks are reinjected "
            "separately and remain authoritative."
        ),
    }
    result = compactor(state, context_policy, summary_base)
    compacted = result.state
    evidence = result.evidence
    if (
        compacted.codec_id != state.codec_id
        or compacted.codec_version != state.codec_version
        or compacted.schema_version != state.schema_version
        or compacted.content_type != state.content_type
        or compacted.provider_request_id != state.provider_request_id
        or compacted.turn_generation != state.turn_generation
        or compacted.effective_data_class != state.effective_data_class
        or compacted.effective_trust_level != state.effective_trust_level
        or compacted.source_metadata != state.source_metadata
        or not evidence.applied
        or evidence.schema_version
        != HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION
        or evidence.policy_revision != context_policy.revision
        or evidence.source_state_digest != source_digest
        or evidence.authority_digest != authority_digest
        or evidence.provenance_digest != provenance_digest
        or evidence.compacted_state_digest
        != hashlib.sha256(compacted.content).hexdigest()
        or evidence.source_bytes != source_bytes
        or evidence.compacted_bytes != len(compacted.content)
        or evidence.compacted_bytes > context_policy.max_compacted_state_bytes
        or evidence.compacted_bytes >= evidence.source_bytes
        or not isinstance(evidence.omitted_items, int)
        or isinstance(evidence.omitted_items, bool)
        or evidence.omitted_items < 1
        or not isinstance(evidence.retained_items, int)
        or isinstance(evidence.retained_items, bool)
        or evidence.retained_items < 0
        or not _is_sha256(evidence.summary_digest)
    ):
        raise HostedAgenticLoopError("context_compaction_invalid")
    return compacted, evidence


def validate_hosted_request_context(
    request: AgenticModelRequest,
    *,
    context_policy: AgenticContextPolicy | None,
    endpoint_input_token_limit: int,
) -> int:
    """Enforce an independent request-window reserve before any transport."""
    estimated_tokens = estimate_hosted_request_tokens(request)
    if context_policy is None:
        return estimated_tokens
    validate_agentic_context_policy(context_policy)
    usable_profile_tokens = (
        context_policy.max_request_input_tokens
        - context_policy.context_reserve_tokens
    )
    usable_endpoint_tokens = (
        endpoint_input_token_limit - context_policy.context_reserve_tokens
    )
    if (
        usable_profile_tokens <= 0
        or usable_endpoint_tokens <= 0
        or estimated_tokens > min(usable_profile_tokens, usable_endpoint_tokens)
    ):
        raise HostedAgenticLoopError("context_window_reserve_unavailable")
    return estimated_tokens


def validate_agentic_context_policy(policy: AgenticContextPolicy) -> None:
    integer_fields = (
        policy.max_request_input_tokens,
        policy.context_reserve_tokens,
        policy.compaction_trigger_tokens,
        policy.max_compacted_state_bytes,
        policy.summary_max_bytes,
        policy.tool_result_inline_bytes,
        policy.tool_result_summary_bytes,
        policy.max_same_turn_steering_messages,
    )
    if (
        not str(policy.revision or "").strip()
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in integer_fields
        )
        or policy.max_request_input_tokens <= 0
        or policy.context_reserve_tokens <= 0
        or policy.context_reserve_tokens >= policy.max_request_input_tokens
        or policy.compaction_trigger_tokens <= 0
        or policy.compaction_trigger_tokens
        > policy.max_request_input_tokens - policy.context_reserve_tokens
        or policy.max_compacted_state_bytes <= 0
        or policy.summary_max_bytes <= 0
        or policy.tool_result_inline_bytes <= 0
        or policy.tool_result_summary_bytes < MIN_TOOL_RESULT_SUMMARY_BYTES
        or policy.compaction_mode not in {"disabled", "provider_history"}
        or policy.attachment_projection_mode
        not in {"workspace_reference", "native_or_reference"}
        or policy.steering_delivery_mode
        not in {"provider_native", "safe_next_turn"}
        or (
            policy.steering_delivery_mode == "safe_next_turn"
            and policy.max_same_turn_steering_messages != 0
        )
        or (
            policy.steering_delivery_mode == "provider_native"
            and policy.max_same_turn_steering_messages < 1
        )
    ):
        raise HostedAgenticLoopError("context_policy_invalid")


def bounded_context_summary(
    payload: dict[str, object],
    *,
    max_bytes: int,
) -> str:
    """Encode one bounded summary payload without silently dropping fields."""
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise HostedAgenticLoopError("context_compaction_invalid") from error
    if len(encoded) > max_bytes:
        raise HostedAgenticLoopError("context_summary_too_large")
    return encoded.decode("ascii")


def bounded_semantic_context_summary(
    payload: dict[str, object],
    semantic_history: tuple[dict[str, str], ...],
    *,
    max_bytes: int,
) -> str:
    """Encode a bounded extractive history summary without private reasoning."""
    # Keep both the initial contract and the most recent dialogue when a long
    # history exceeds the extractive-summary entry ceiling.  Taking only the
    # first entries would reproduce the original loss of recent decisions and
    # tool outcomes.
    selected_history = (
        semantic_history
        if len(semantic_history) <= 64
        else (*semantic_history[:32], *semantic_history[-32:])
    )
    normalized: list[dict[str, str]] = []
    for item in selected_history:
        role = str(item.get("role") or "").strip()[:64]
        text = str(item.get("text") or "").strip()
        if role and text:
            normalized.append({"role": role, "text": _clip_summary_text(text, 2_048)})
    candidate = {**payload, "semantic_history": normalized}
    while True:
        try:
            return bounded_context_summary(candidate, max_bytes=max_bytes)
        except HostedAgenticLoopError as error:
            if str(error) != "context_summary_too_large":
                raise
        sizeable = [
            (index, len(item["text"].encode("utf-8")))
            for index, item in enumerate(normalized)
            if len(item["text"].encode("utf-8")) > 96
        ]
        if sizeable:
            index, size = max(sizeable, key=lambda value: value[1])
            normalized[index]["text"] = _clip_summary_text(
                normalized[index]["text"],
                max(64, size // 2),
            )
            continue
        if len(normalized) > 2:
            # Preserve the earliest constraint and most recent outcome while
            # removing low-information middle history deterministically.
            del normalized[1]
            continue
        raise HostedAgenticLoopError("context_summary_too_large")


def _clip_summary_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "…"
    budget = max(1, max_bytes - len(suffix.encode("utf-8")))
    clipped = encoded[:budget]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix


def canonical_context_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "HOSTED_CONTEXT_COMPACTION_SCHEMA_VERSION",
    "HostedContextCompactionEvidence",
    "HostedContextCompactionResult",
    "HostedProviderStateCompactor",
    "bounded_context_summary",
    "bounded_semantic_context_summary",
    "canonical_context_digest",
    "manage_hosted_provider_context",
    "validate_agentic_context_policy",
    "validate_hosted_request_context",
]
