"""Usage-domain records shared by runtime and administrative surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


UsageAccuracy = Literal["exact", "estimated", "unavailable"]
UsageSemantics = Literal["incremental", "cumulative"]
UsageResolution = Literal["hour", "day"]


@dataclass(frozen=True)
class UsageSampleRecord:
    """One idempotent provider usage observation normalized into token deltas."""

    sample_id: str
    workspace_id: str
    root_session_id: str
    session_id: str
    turn_id: str | None
    provider_id: str
    model_id: str | None
    source: str
    semantics: UsageSemantics
    token_accuracy: UsageAccuracy
    context_accuracy: UsageAccuracy
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    reported_input_tokens: int
    reported_cached_input_tokens: int
    reported_cache_write_input_tokens: int
    reported_output_tokens: int
    reported_reasoning_output_tokens: int
    reported_total_tokens: int
    context_tokens: int | None
    context_window_tokens: int | None
    estimated_cost_microusd: int | None
    observed_at: datetime


@dataclass(frozen=True)
class UsageBucketRecord:
    """One provider/model rollup used by hourly and daily charts."""

    bucket_id: str
    workspace_id: str
    resolution: UsageResolution
    bucket_start: datetime
    bucket_end: datetime
    provider_id: str
    model_id: str | None
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int | None
    sample_count: int
    updated_at: datetime


@dataclass(frozen=True)
class ProviderQuotaSnapshotRecord:
    """One redaction-safe provider quota window observation."""

    snapshot_id: str
    workspace_id: str
    provider_id: str
    plan_type: str | None
    limit_id: str
    limit_label: str
    window_kind: str
    used_percent: float
    limit_window_seconds: int | None
    reset_at_epoch_seconds: int | None
    limit_reached: bool
    observed_at: datetime


@dataclass(frozen=True)
class TokenUsageBreakdown:
    """Additive normalized token categories."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ChatUsageSummary:
    """Authoritative root-chat usage snapshot sent to Chat clients."""

    workspace_id: str
    root_session_id: str
    tokens: TokenUsageBreakdown
    direct_tokens: TokenUsageBreakdown
    delegated_tokens: TokenUsageBreakdown
    context_tokens: int | None
    context_window_tokens: int | None
    context_used_percent: float | None
    token_accuracy: UsageAccuracy
    context_accuracy: UsageAccuracy
    provider_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    estimated_cost_microusd: int | None
    sample_count: int
    coverage_since: datetime | None
    updated_at: datetime | None
