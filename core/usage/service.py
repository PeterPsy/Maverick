"""Runtime-facing usage ingestion and chat summary services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.runtime.continuation_lineage import (
    resolve_latest_runtime_session,
    runtime_session_lineage,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.usage.models import ChatUsageSummary, TokenUsageBreakdown, UsageAccuracy, UsageSampleRecord
from core.usage.normalization import normalized_usage_sample
from core.usage.store import UsageDocumentStore
from core.usage.timeseries import reconcile_sample_buckets


@dataclass(frozen=True)
class UsageIngestResult:
    """Result of one idempotent runtime usage observation."""

    sample: UsageSampleRecord
    inserted: bool
    summary: ChatUsageSummary
    notification_session_id: str


def ingest_runtime_usage(
    state: Any,
    *,
    session_id: str,
    turn_id: str | None,
    payload: dict[str, Any],
    observed_at: datetime | None = None,
) -> UsageIngestResult | None:
    """Persist one provider report and return the root-chat authoritative summary."""
    store = getattr(state, "usage_store", None)
    if not isinstance(store, UsageDocumentStore):
        return None
    session = state.runtime_store.get_session(session_id)
    root_session_id = resolve_root_session_id(state.runtime_store, session)
    sample = normalized_usage_sample(
        state,
        store,
        session=session,
        root_session_id=root_session_id,
        turn_id=turn_id,
        payload=payload,
        observed_at=observed_at or datetime.now(tz=UTC),
    )
    if sample is None:
        return None
    persisted, inserted = store.save_sample_if_absent(sample)
    if inserted:
        reconcile_sample_buckets(store, persisted)
    return UsageIngestResult(
        sample=persisted,
        inserted=inserted,
        summary=build_runtime_chat_usage_summary(
            store,
            runtime_store=state.runtime_store,
            session=session,
        ),
        notification_session_id=resolve_current_root_session_id(
            state.runtime_store,
            session,
        ),
    )


def resolve_root_session_id(runtime_store: Any, session: RuntimeSessionRecord) -> str:
    """Follow continuation and creator links to the logical root session."""
    current = session
    visited = {current.session_id}
    while getattr(current, "predecessor_session_id", None) or getattr(
        current,
        "creator_runtime_session_id",
        None,
    ):
        parent_id = getattr(current, "predecessor_session_id", None) or getattr(
            current,
            "creator_runtime_session_id",
            None,
        )
        if parent_id in visited:
            break
        visited.add(parent_id)
        try:
            parent = runtime_store.get_session(parent_id)
        except Exception:
            break
        if parent.workspace_id != session.workspace_id:
            break
        current = parent
    return current.session_id


def resolve_current_root_session_id(
    runtime_store: Any,
    session: RuntimeSessionRecord,
) -> str:
    """Return the current executable session for one logical root chat."""
    root_session_id = resolve_root_session_id(runtime_store, session)
    try:
        root = runtime_store.get_session(root_session_id)
        return resolve_latest_runtime_session(runtime_store, root).session_id
    except Exception:
        return root_session_id


def build_runtime_chat_usage_summary(
    store: UsageDocumentStore,
    *,
    runtime_store: Any,
    session: RuntimeSessionRecord,
) -> ChatUsageSummary:
    """Aggregate usage with every continuation of the root counted as direct."""
    root_session_id = resolve_root_session_id(runtime_store, session)
    direct_session_ids = {root_session_id}
    try:
        root = runtime_store.get_session(root_session_id)
        current = resolve_latest_runtime_session(runtime_store, root)
        direct_session_ids = {
            item.session_id for item in runtime_session_lineage(runtime_store, current)
        }
    except Exception:
        pass
    return build_chat_usage_summary(
        store,
        workspace_id=session.workspace_id,
        root_session_id=root_session_id,
        direct_session_ids=direct_session_ids,
    )


def build_chat_usage_summary(
    store: UsageDocumentStore,
    *,
    workspace_id: str,
    root_session_id: str,
    direct_session_ids: set[str] | None = None,
) -> ChatUsageSummary:
    """Aggregate all direct and delegated samples for one root chat."""
    samples = store.list_samples(workspace_id=workspace_id, root_session_id=root_session_id)
    direct_ids = direct_session_ids or {root_session_id}
    direct = [sample for sample in samples if sample.session_id in direct_ids]
    delegated = [sample for sample in samples if sample.session_id not in direct_ids]
    root_context_samples = [sample for sample in direct if sample.context_tokens is not None]
    latest_context = root_context_samples[-1] if root_context_samples else None
    context_tokens = latest_context.context_tokens if latest_context else None
    context_window_tokens = latest_context.context_window_tokens if latest_context else None
    context_used_percent = (
        round(min(100.0, max(0.0, context_tokens / context_window_tokens * 100.0)), 1)
        if context_tokens is not None and context_window_tokens
        else None
    )
    costs = [sample.estimated_cost_microusd for sample in samples if sample.estimated_cost_microusd is not None]
    return ChatUsageSummary(
        workspace_id=workspace_id,
        root_session_id=root_session_id,
        tokens=_breakdown(samples),
        direct_tokens=_breakdown(direct),
        delegated_tokens=_breakdown(delegated),
        context_tokens=context_tokens,
        context_window_tokens=context_window_tokens,
        context_used_percent=context_used_percent,
        token_accuracy=_combined_accuracy([sample.token_accuracy for sample in samples]),
        context_accuracy=latest_context.context_accuracy if latest_context else "unavailable",
        provider_ids=tuple(sorted({sample.provider_id for sample in samples})),
        model_ids=tuple(sorted({sample.model_id for sample in samples if sample.model_id})),
        estimated_cost_microusd=sum(costs) if costs else None,
        sample_count=len(samples),
        coverage_since=samples[0].observed_at if samples else None,
        updated_at=samples[-1].observed_at if samples else None,
    )


def _breakdown(samples: list[UsageSampleRecord]) -> TokenUsageBreakdown:
    return TokenUsageBreakdown(
        input_tokens=sum(sample.input_tokens for sample in samples),
        cached_input_tokens=sum(sample.cached_input_tokens for sample in samples),
        cache_write_input_tokens=sum(sample.cache_write_input_tokens for sample in samples),
        output_tokens=sum(sample.output_tokens for sample in samples),
        reasoning_output_tokens=sum(sample.reasoning_output_tokens for sample in samples),
        total_tokens=sum(sample.total_tokens for sample in samples),
    )


def _combined_accuracy(values: list[UsageAccuracy]) -> UsageAccuracy:
    if not values:
        return "unavailable"
    if "estimated" in values:
        return "estimated"
    if "unavailable" in values:
        return "unavailable"
    return "exact"
