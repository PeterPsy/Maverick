"""Hourly and daily usage rollups for Settings charts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from typing import Iterable

from core.usage.models import UsageBucketRecord, UsageResolution, UsageSampleRecord
from core.usage.store import UsageDocumentStore


MAX_HOURLY_PERIODS = 24 * 31
MAX_DAILY_PERIODS = 366


def reconcile_sample_buckets(store: UsageDocumentStore, sample: UsageSampleRecord) -> None:
    """Rebuild the two small provider/model buckets touched by a new sample."""
    workspace_samples = store.list_samples(workspace_id=sample.workspace_id)
    for resolution in ("hour", "day"):
        bucket_start = usage_bucket_start(sample.observed_at, resolution)
        matching = [
            candidate
            for candidate in workspace_samples
            if candidate.provider_id == sample.provider_id
            and candidate.model_id == sample.model_id
            and usage_bucket_start(candidate.observed_at, resolution) == bucket_start
        ]
        store.save_bucket(_bucket_record(matching, resolution=resolution, bucket_start=bucket_start))


def usage_timeseries_payload(
    store: UsageDocumentStore,
    *,
    workspace_id: str,
    resolution: UsageResolution,
    periods: int,
    provider_id: str | None = None,
    model_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return a gap-filled UTC token series and reconcile its persisted buckets."""
    maximum = MAX_HOURLY_PERIODS if resolution == "hour" else MAX_DAILY_PERIODS
    bounded_periods = max(1, min(int(periods), maximum))
    generated_at = now or datetime.now(tz=UTC)
    current_start = usage_bucket_start(generated_at, resolution)
    step = timedelta(hours=1) if resolution == "hour" else timedelta(days=1)
    range_start = current_start - step * (bounded_periods - 1)
    range_end = current_start + step
    matching = [
        sample
        for sample in store.list_samples(workspace_id=workspace_id)
        if range_start <= sample.observed_at < range_end
        and (provider_id is None or sample.provider_id == provider_id)
        and (model_id is None or sample.model_id == model_id)
    ]
    grouped: dict[tuple[datetime, str, str | None], list[UsageSampleRecord]] = {}
    for sample in matching:
        key = (usage_bucket_start(sample.observed_at, resolution), sample.provider_id, sample.model_id)
        grouped.setdefault(key, []).append(sample)
    for (bucket_start, _provider, _model), samples in grouped.items():
        store.save_bucket(_bucket_record(samples, resolution=resolution, bucket_start=bucket_start))

    items = []
    for index in range(bounded_periods):
        bucket_start = range_start + step * index
        bucket_samples = [
            sample
            for sample in matching
            if usage_bucket_start(sample.observed_at, resolution) == bucket_start
        ]
        items.append(_series_item(bucket_samples, bucket_start=bucket_start, bucket_end=bucket_start + step))
    return {
        "workspace_id": workspace_id,
        "resolution": resolution,
        "periods": bounded_periods,
        "provider_id": provider_id,
        "model_id": model_id,
        "timezone": "UTC",
        "range_start": range_start,
        "range_end": range_end,
        "coverage_since": min((sample.observed_at for sample in matching), default=None),
        "generated_at": generated_at,
        "items": items,
        "totals": _token_totals(matching),
    }


def usage_bucket_start(value: datetime, resolution: UsageResolution) -> datetime:
    normalized = value.astimezone(UTC)
    if resolution == "hour":
        return normalized.replace(minute=0, second=0, microsecond=0)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_record(
    samples: list[UsageSampleRecord],
    *,
    resolution: UsageResolution,
    bucket_start: datetime,
) -> UsageBucketRecord:
    if not samples:
        raise ValueError("Usage buckets require at least one sample.")
    step = timedelta(hours=1) if resolution == "hour" else timedelta(days=1)
    first = samples[0]
    totals = _token_totals(samples)
    identity = f"{first.workspace_id}:{resolution}:{bucket_start.isoformat()}:{first.provider_id}:{first.model_id or ''}"
    return UsageBucketRecord(
        bucket_id="usage-bucket-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        workspace_id=first.workspace_id,
        resolution=resolution,
        bucket_start=bucket_start,
        bucket_end=bucket_start + step,
        provider_id=first.provider_id,
        model_id=first.model_id,
        input_tokens=totals["input_tokens"],
        cached_input_tokens=totals["cached_input_tokens"],
        cache_write_input_tokens=totals["cache_write_input_tokens"],
        output_tokens=totals["output_tokens"],
        reasoning_output_tokens=totals["reasoning_output_tokens"],
        total_tokens=totals["total_tokens"],
        estimated_cost_microusd=totals["estimated_cost_microusd"],
        sample_count=len(samples),
        updated_at=max(sample.observed_at for sample in samples),
    )


def _series_item(
    samples: list[UsageSampleRecord],
    *,
    bucket_start: datetime,
    bucket_end: datetime,
) -> dict[str, object]:
    return {
        "bucket_start": bucket_start,
        "bucket_end": bucket_end,
        **_token_totals(samples),
        "sample_count": len(samples),
    }


def _token_totals(samples: Iterable[UsageSampleRecord]) -> dict[str, int | None]:
    records = list(samples)
    costs = [sample.estimated_cost_microusd for sample in records if sample.estimated_cost_microusd is not None]
    return {
        "input_tokens": sum(sample.input_tokens for sample in records),
        "cached_input_tokens": sum(sample.cached_input_tokens for sample in records),
        "cache_write_input_tokens": sum(sample.cache_write_input_tokens for sample in records),
        "output_tokens": sum(sample.output_tokens for sample in records),
        "reasoning_output_tokens": sum(sample.reasoning_output_tokens for sample in records),
        "total_tokens": sum(sample.total_tokens for sample in records),
        "estimated_cost_microusd": sum(costs) if costs else None,
    }
