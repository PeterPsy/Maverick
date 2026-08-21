"""Read-time repair for usage samples written before newer normalization rules."""

from __future__ import annotations

from dataclasses import replace

from core.usage.models import UsageSampleRecord


def canonical_usage_samples(samples: list[UsageSampleRecord]) -> list[UsageSampleRecord]:
    """Return samples with legacy Codex history snapshots converted to baselines."""
    first_cumulative_streams: set[tuple[str, str, str, str | None, str]] = set()
    canonical: list[UsageSampleRecord] = []
    for sample in samples:
        if sample.semantics != "cumulative":
            canonical.append(sample)
            continue
        stream_key = (
            sample.workspace_id,
            sample.session_id,
            sample.provider_id,
            sample.model_id,
            sample.source,
        )
        is_first = stream_key not in first_cumulative_streams
        first_cumulative_streams.add(stream_key)
        canonical.append(_zero_legacy_codex_baseline(sample) if is_first else sample)
    return canonical


def _zero_legacy_codex_baseline(sample: UsageSampleRecord) -> UsageSampleRecord:
    """Exclude a pre-metering Codex lifetime total while preserving reported counters."""
    context_tokens = sample.context_tokens or 0
    context_window_tokens = sample.context_window_tokens or 0
    historical_floor = max(context_tokens * 2, context_window_tokens)
    is_legacy_full_snapshot = (
        sample.source == "codex_app_server"
        and context_tokens > 0
        and sample.total_tokens == sample.reported_total_tokens
        and sample.reported_total_tokens > historical_floor
    )
    if not is_legacy_full_snapshot:
        return sample
    return replace(
        sample,
        input_tokens=0,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=0,
        estimated_cost_microusd=None,
    )
