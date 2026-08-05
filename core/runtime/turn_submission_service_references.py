"""App-reference materialization for runtime provider input."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from core.runtime.turn_submission_service_output import (
    _record_app_references_materialize_completed,
    _record_app_references_materialize_failed,
    _record_app_references_materialize_started,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def _materialize_app_references_for_execution(
    *,
    app_references: list[dict[str, object]] | None,
    app_reference_materializer: Callable[[list[dict[str, object]]], object] | None,
    state: PlatformState | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    provider_id: str | None = None,
) -> list[dict[str, object]] | None:
    references = [item for item in app_references or [] if isinstance(item, dict)]
    if not references or app_reference_materializer is None:
        return references
    app_reference_count, storage_reference_count = _runtime_app_reference_counts(references)
    can_record = state is not None and session_id is not None and turn_id is not None and provider_id is not None
    if can_record:
        _record_app_references_materialize_started(
            state,
            session_id=session_id,
            turn_id=turn_id,
            provider_id=provider_id,
            app_reference_count=app_reference_count,
            storage_reference_count=storage_reference_count,
        )
    started_at = time.perf_counter()
    try:
        raw_materialized = app_reference_materializer(references)
        materialized, reference_action_timings, reference_cache_hit = _coerce_materialized_reference_result(raw_materialized)
    except Exception as error:
        reference_action_timings = _materializer_reference_action_timings(locals().get("raw_materialized"))
        if can_record:
            _record_app_references_materialize_failed(
                state,
                session_id=session_id,
                turn_id=turn_id,
                provider_id=provider_id,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                app_reference_count=app_reference_count,
                storage_reference_count=storage_reference_count,
                error=error,
                reference_action_timings=reference_action_timings,
            )
        raise
    materialized_references = [item for item in materialized or [] if isinstance(item, dict)]
    if can_record:
        _record_app_references_materialize_completed(
            state,
            session_id=session_id,
            turn_id=turn_id,
            provider_id=provider_id,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            app_reference_count=app_reference_count,
            storage_reference_count=storage_reference_count,
            materialized_reference_count=len(materialized_references),
            reference_cache_hit=reference_cache_hit,
            reference_action_timings=reference_action_timings,
        )
    return materialized_references


def _coerce_materialized_reference_result(
    raw_result: object,
) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
    references = getattr(raw_result, "references", raw_result)
    timings = _materializer_reference_action_timings(raw_result)
    cache_hit = bool(getattr(raw_result, "reference_cache_hit", False))
    if not isinstance(references, list):
        return [], timings, cache_hit
    return [item for item in references if isinstance(item, dict)], timings, cache_hit


def _materializer_reference_action_timings(raw_result: object) -> list[dict[str, object]]:
    timings = getattr(raw_result, "reference_action_timings", None)
    if not isinstance(timings, list):
        return []
    return [item for item in timings if isinstance(item, dict)]


def _runtime_app_reference_counts(
    references: list[dict[str, object]] | None,
) -> tuple[int, int]:
    items = [item for item in references or [] if isinstance(item, dict)]
    storage_count = sum(1 for item in items if str(item.get("app_id") or "").strip().lower() == "storage")
    return len(items), storage_count
