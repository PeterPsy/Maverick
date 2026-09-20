"""Normalize heterogeneous provider token reports into durable samples."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
from typing import Any

from core.runtime.runtime_session import RuntimeSessionRecord
from core.usage.models import UsageAccuracy, UsageSampleRecord, UsageSemantics
from core.usage.store import UsageHistory


def normalized_usage_sample(
    state: Any,
    store: UsageHistory,
    *,
    session: RuntimeSessionRecord,
    root_session_id: str,
    turn_id: str | None,
    payload: dict[str, Any],
    observed_at: datetime,
) -> UsageSampleRecord | None:
    """Build one sample, deriving deltas for cumulative provider snapshots."""
    semantics = _semantics(payload.get("semantics"))
    binding = session.execution_binding
    provider_id = _text(payload.get("provider_id")) or (
        binding.model_provider_id if binding is not None else ""
    ) or _text(session.hosted_provider_id) or _text(session.provider_id) or "unknown"
    model_id = _text(payload.get("model_id")) or (
        binding.model_id if binding is not None else ""
    ) or _text(session.hosted_model_id) or None
    source = _text(payload.get("source")) or "runtime_provider"
    reported = _reported_breakdown(payload)
    latest = _latest_breakdown(payload)
    context_tokens = _optional_nonnegative_int(payload.get("context_tokens"))
    if context_tokens is None and semantics == "incremental" and reported["total_tokens"] > 0:
        context_tokens = reported["total_tokens"]
    context_window_tokens = _optional_nonnegative_int(payload.get("context_window_tokens"))
    if context_window_tokens is None:
        context_window_tokens = _model_context_window(state, provider_id=provider_id, model_id=model_id)
    if not any(reported.values()) and context_tokens is None:
        return None

    sample_identity = {
        "session_id": session.session_id,
        "turn_id": turn_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "source": source,
        "usage_id": _text(payload.get("usage_id")),
        "reported": reported,
        "latest": latest,
        "context_tokens": context_tokens,
        "context_window_tokens": context_window_tokens,
    }
    sample_id = _sample_id(sample_identity)
    previous = store.previous_cumulative_sample(
        workspace_id=session.workspace_id, session_id=session.session_id, provider_id=provider_id, model_id=model_id,
        source=source, before=observed_at, sample_id=sample_id,
    ) if semantics == "cumulative" else None
    tokens = normalized_token_delta(reported, previous=previous, latest=latest, semantics=semantics)
    return UsageSampleRecord(
        sample_id=sample_id,
        workspace_id=session.workspace_id,
        root_session_id=root_session_id,
        session_id=session.session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        model_id=model_id,
        source=source,
        semantics=semantics,
        token_accuracy=_accuracy(payload.get("token_accuracy") or payload.get("accuracy"), "exact"),
        context_accuracy=_accuracy(
            payload.get("context_accuracy"),
            "exact" if semantics == "cumulative" else "estimated",
        ),
        **tokens,
        reported_input_tokens=reported["input_tokens"],
        reported_cached_input_tokens=reported["cached_input_tokens"],
        reported_cache_write_input_tokens=reported["cache_write_input_tokens"],
        reported_output_tokens=reported["output_tokens"],
        reported_reasoning_output_tokens=reported["reasoning_output_tokens"],
        reported_total_tokens=reported["total_tokens"],
        context_tokens=context_tokens,
        context_window_tokens=context_window_tokens,
        estimated_cost_microusd=_optional_nonnegative_int(payload.get("estimated_cost_microusd")),
        observed_at=observed_at,
    )


def _reported_breakdown(payload: dict[str, Any]) -> dict[str, int]:
    input_tokens = _nonnegative_int(payload.get("input_tokens"))
    cached_input_tokens = min(input_tokens, _nonnegative_int(payload.get("cached_input_tokens")))
    cache_write_input_tokens = min(
        max(0, input_tokens - cached_input_tokens),
        _nonnegative_int(payload.get("cache_write_input_tokens")),
    )
    output_tokens = _nonnegative_int(payload.get("output_tokens"))
    reasoning_output_tokens = min(
        output_tokens,
        _nonnegative_int(payload.get("reasoning_output_tokens")),
    )
    total_tokens = _nonnegative_int(payload.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": cache_write_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
    }


def _latest_breakdown(payload: dict[str, Any]) -> dict[str, int] | None:
    keys = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    if not any(f"latest_{key}" in payload for key in keys):
        return None
    return _reported_breakdown({key: payload.get(f"latest_{key}") for key in keys})


def normalized_token_delta(reported: dict[str, int], *, previous: UsageSampleRecord | None,
                           latest: dict[str, int] | None, semantics: UsageSemantics) -> dict[str, int]:
    if semantics == "cumulative" and previous is None and latest is not None:
        raw_delta = latest
    else:
        raw_delta = {
            key: _cumulative_delta(value, getattr(previous, f"reported_{key}") if previous else None)
            if semantics == "cumulative" else value for key, value in reported.items()
        }
    cached = raw_delta["cached_input_tokens"]
    cache_write = raw_delta["cache_write_input_tokens"]
    reasoning = raw_delta["reasoning_output_tokens"]
    input_tokens = max(0, raw_delta["input_tokens"] - cached - cache_write)
    output_tokens = max(0, raw_delta["output_tokens"] - reasoning)
    return {
        "input_tokens": input_tokens, "cached_input_tokens": cached, "cache_write_input_tokens": cache_write,
        "output_tokens": output_tokens, "reasoning_output_tokens": reasoning,
        "total_tokens": raw_delta["total_tokens"] or (input_tokens + cached + cache_write + output_tokens + reasoning),
    }


def cumulative_sample_with_previous(sample: UsageSampleRecord, previous: UsageSampleRecord | None,
                                     payload: dict | None) -> UsageSampleRecord:
    """Recompute only the affected stream neighbor for a late cumulative observation."""
    from core.usage.canonical import _zero_legacy_codex_baseline
    if sample.semantics != "cumulative":
        return sample
    if previous is None and payload is None:
        return _zero_legacy_codex_baseline(sample)
    reported = {key: getattr(sample, f"reported_{key}") for key in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
        "reasoning_output_tokens", "total_tokens")}
    result = replace(sample, **normalized_token_delta(reported, previous=previous,
        latest=_latest_breakdown(payload or {}), semantics="cumulative"))
    if payload is not None:
        result = replace(result, estimated_cost_microusd=_optional_nonnegative_int(payload.get('estimated_cost_microusd')))
    return _zero_legacy_codex_baseline(result) if previous is None else result


def stored_usage_observation(payload: dict) -> dict:
    """Persist only the additional numeric counters required for late compensation."""
    latest = _latest_breakdown(payload)
    return {**({f'latest_{key}': value for key, value in latest.items()} if latest else {}),
        'estimated_cost_microusd': _optional_nonnegative_int(payload.get('estimated_cost_microusd'))}


def _cumulative_delta(current: int, previous: int | None) -> int:
    if previous is None:
        return current
    if current >= previous:
        return current - previous
    return current


def _model_context_window(state: Any, *, provider_id: str, model_id: str | None) -> int | None:
    if not model_id:
        return None
    registry = getattr(state, "provider_registry", None)
    try:
        definition = registry.get_provider_definition(provider_id) if registry is not None else None
    except Exception:
        definition = None
    if definition is None:
        return None
    option = next((item for item in definition.model_options if item.model_id == model_id), None)
    if option is None:
        return None
    candidates: list[int] = []
    metadata_window = _optional_nonnegative_int(option.metadata.get("context_length"))
    if metadata_window:
        candidates.append(metadata_window)
    for upstream in option.upstream_provider_options:
        value = _optional_nonnegative_int(upstream.get("context_length"))
        if value:
            candidates.append(value)
    return min(candidates) if candidates else None


def _sample_id(identity: dict[str, Any]) -> str:
    explicit = _text(identity.get("usage_id"))
    if explicit:
        prefix = f"{identity['session_id']}:{explicit}"
        return "usage-" + hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "usage-" + hashlib.sha256(encoded).hexdigest()


def _semantics(value: object) -> UsageSemantics:
    return "cumulative" if _text(value) == "cumulative" else "incremental"


def _accuracy(value: object, fallback: UsageAccuracy) -> UsageAccuracy:
    normalized = _text(value)
    return normalized if normalized in {"exact", "estimated", "unavailable"} else fallback  # type: ignore[return-value]


def _nonnegative_int(value: object) -> int:
    return _optional_nonnegative_int(value) or 0


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
