"""Public redaction-safe payloads for usage APIs and runtime events."""

from __future__ import annotations

from dataclasses import asdict

from core.usage.models import ChatUsageSummary


def chat_usage_summary_payload(summary: ChatUsageSummary) -> dict[str, object]:
    """Serialize one authoritative chat usage summary."""
    return {
        "workspace_id": summary.workspace_id,
        "root_session_id": summary.root_session_id,
        "tokens": asdict(summary.tokens),
        "direct_tokens": asdict(summary.direct_tokens),
        "delegated_tokens": asdict(summary.delegated_tokens),
        "context_tokens": summary.context_tokens,
        "context_window_tokens": summary.context_window_tokens,
        "context_used_percent": summary.context_used_percent,
        "token_accuracy": summary.token_accuracy,
        "context_accuracy": summary.context_accuracy,
        "provider_ids": list(summary.provider_ids),
        "model_ids": list(summary.model_ids),
        "estimated_cost_microusd": summary.estimated_cost_microusd,
        "sample_count": summary.sample_count,
        "coverage_since": summary.coverage_since,
        "updated_at": summary.updated_at,
    }


def runtime_usage_diagnostic_payload(summary: ChatUsageSummary) -> dict[str, object]:
    """Numeric usage projection safe for generic CLI credential redaction."""
    def counts(value):
        return {"uncached_input": value.input_tokens, "cached_input": value.cached_input_tokens,
                "cache_write_input": value.cache_write_input_tokens, "output": value.output_tokens,
                "reasoning_output": value.reasoning_output_tokens, "processed": value.total_tokens,
                "non_cached": value.total_tokens - value.cached_input_tokens}
    return {"unit": "tokens", "source": "core_usage", "accuracy": summary.token_accuracy,
            "counts": counts(summary.tokens), "direct": counts(summary.direct_tokens),
            "delegated": counts(summary.delegated_tokens),
            "active_context": {"used": summary.context_tokens, "window": summary.context_window_tokens,
                               "used_percent": summary.context_used_percent, "accuracy": summary.context_accuracy},
            "provider_ids": list(summary.provider_ids), "model_ids": list(summary.model_ids),
            "estimated_cost_microusd": summary.estimated_cost_microusd, "sample_count": summary.sample_count,
            "coverage_since": summary.coverage_since, "updated_at": summary.updated_at}
