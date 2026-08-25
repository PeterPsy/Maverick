"""Exact Codex usage normalization and prompt-budget enrichment."""

from __future__ import annotations

from typing import Any

from core.providers.codex_prompt_budget import add_first_turn_prompt_budget
from core.runtime.execution_events import RuntimeExecutionEvent


def codex_usage_event(
    runtime: Any,
    params: dict[str, Any],
    *,
    final_snapshot: bool = False,
) -> RuntimeExecutionEvent | None:
    """Normalize one exact Codex cumulative token snapshot before noise filtering."""
    usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
    total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
    last = usage.get("last") if isinstance(usage.get("last"), dict) else {}
    if not total and not last:
        return None
    provider_thread_id = str(params.get("threadId") or runtime.provider_thread_id or "").strip()
    provider_turn_id = str(params.get("turnId") or runtime.current_provider_turn_id or "").strip()
    context_tokens = _nonnegative_usage_int(last.get("totalTokens"))
    context_window_tokens = _optional_nonnegative_usage_int(usage.get("modelContextWindow"))
    cumulative_total = _nonnegative_usage_int(total.get("totalTokens"))
    latest_input_tokens = _nonnegative_usage_int(last.get("inputTokens"))
    latest_cached_input_tokens = _nonnegative_usage_int(last.get("cachedInputTokens"))
    payload = {
        "usage_id": ":".join(
            [
                "codex",
                provider_thread_id,
                provider_turn_id,
                str(cumulative_total),
                str(context_tokens),
            ]
        ),
        "provider_id": "codex",
        "source": "codex_app_server",
        "semantics": "cumulative",
        "token_accuracy": "exact",
        "context_accuracy": "exact",
        "input_tokens": _nonnegative_usage_int(total.get("inputTokens")),
        "cached_input_tokens": _nonnegative_usage_int(total.get("cachedInputTokens")),
        "cache_write_input_tokens": _nonnegative_usage_int(total.get("cacheWriteInputTokens")),
        "output_tokens": _nonnegative_usage_int(total.get("outputTokens")),
        "reasoning_output_tokens": _nonnegative_usage_int(total.get("reasoningOutputTokens")),
        "total_tokens": cumulative_total,
        "latest_input_tokens": latest_input_tokens,
        "latest_cached_input_tokens": latest_cached_input_tokens,
        "latest_cache_write_input_tokens": _nonnegative_usage_int(last.get("cacheWriteInputTokens")),
        "latest_output_tokens": _nonnegative_usage_int(last.get("outputTokens")),
        "latest_reasoning_output_tokens": _nonnegative_usage_int(last.get("reasoningOutputTokens")),
        "latest_total_tokens": context_tokens,
        "context_tokens": context_tokens,
        "context_window_tokens": context_window_tokens,
        "provider_thread_id": provider_thread_id or None,
        "provider_turn_id": provider_turn_id or None,
    }
    add_first_turn_prompt_budget(
        runtime,
        payload,
        provider_turn_id=provider_turn_id,
        latest_input_tokens=latest_input_tokens,
        latest_cached_input_tokens=latest_cached_input_tokens,
        final_snapshot=final_snapshot,
    )
    return RuntimeExecutionEvent(event_type="runtime.usage.reported", payload=payload)


def _nonnegative_usage_int(value: object) -> int:
    return _optional_nonnegative_usage_int(value) or 0


def _optional_nonnegative_usage_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None
