"""Periodic bounded cleanup for hidden prepared runtime sessions."""

from __future__ import annotations

import logging
import os
from threading import Event, Thread
from typing import Any

from core.api.runtime_cleanup import cleanup_runtime_session
from core.runtime.prepared_sessions import (
    PREPARED_SESSION_POOL_MAX_PER_OWNER,
    PREPARED_SESSION_TTL_SECONDS,
    prepared_session_cleanup_candidates,
)


logger = logging.getLogger(__name__)

DEFAULT_PREPARED_SESSION_CLEANUP_INTERVAL_SECONDS = 60.0
DEFAULT_PREPARED_SESSION_CLEANUP_BATCH_SIZE = 4


def start_prepared_session_cleanup_scheduler(
    state,
    *,
    interval_seconds: float | None = None,
    initial_delay_seconds: float | None = None,
    shutdown_controller=None,
) -> Thread:
    """Start one daemon that cleans only bounded hidden prepared-session batches."""
    stop = Event()
    if shutdown_controller is not None:
        shutdown_controller.register_cleanup(stop.set)
    interval = _cleanup_interval_seconds(interval_seconds)
    initial_delay = (
        interval
        if initial_delay_seconds is None
        else max(1.0, float(initial_delay_seconds))
    )
    thread = Thread(
        target=_run_prepared_session_cleanup_scheduler,
        args=(state, interval, initial_delay, stop),
        name="maverick-prepared-session-cleanup",
        daemon=True,
    )
    thread.start()
    return thread


def run_prepared_session_cleanup_tick(
    state,
    *,
    now=None,
    ttl_seconds: float = PREPARED_SESSION_TTL_SECONDS,
    max_per_owner: int = PREPARED_SESSION_POOL_MAX_PER_OWNER,
    max_cleanups: int = DEFAULT_PREPARED_SESSION_CLEANUP_BATCH_SIZE,
) -> dict[str, Any]:
    """Run a bounded cleanup tick through the canonical runtime cleanup path."""
    if max_cleanups < 1:
        raise ValueError("Prepared session cleanup batch size must be positive.")
    cleaned: list[str] = []
    skipped: list[str] = []
    failures: list[dict[str, str]] = []
    attempted: set[str] = set()
    candidates = prepared_session_cleanup_candidates(
        state,
        now=now,
        ttl_seconds=ttl_seconds,
        max_per_owner=max_per_owner,
    )

    while len(attempted) < max_cleanups:
        candidate = next(
            (item for item in candidates if item.session_id not in attempted),
            None,
        )
        if candidate is None:
            break
        attempted.add(candidate.session_id)
        try:
            location = state.runtime_store.get_session(candidate.session_id)
            with state.runtime_store.session_lifecycle_handoff(
                workspace_id=location.workspace_id,
                session_id=location.session_id,
            ):
                fresh_candidates = prepared_session_cleanup_candidates(
                    state,
                    now=now,
                    ttl_seconds=ttl_seconds,
                    max_per_owner=max_per_owner,
                )
                candidates = fresh_candidates
                fresh = next(
                    (item for item in fresh_candidates if item.session_id == candidate.session_id),
                    None,
                )
                if fresh is None:
                    skipped.append(candidate.session_id)
                    continue
                result = cleanup_runtime_session(
                    state,
                    session_id=fresh.session_id,
                    reason=fresh.reason,
                    start_path=state.repository_root,
                    publish_thread_events=False,
                    allow_hidden_prepared_chat_cleanup=True,
                    cleanup_inter_agent_runs=False,
                )
            if result.get("found"):
                cleaned.append(candidate.session_id)
            else:
                skipped.append(candidate.session_id)
        except Exception as error:  # best-effort maintenance must not stop later ticks
            failures.append(
                {
                    "session_id": candidate.session_id,
                    "error_type": type(error).__name__,
                }
            )
            logger.exception(
                "Prepared runtime session cleanup failed for %s.",
                candidate.session_id,
            )

    if attempted:
        candidates = prepared_session_cleanup_candidates(
            state,
            now=now,
            ttl_seconds=ttl_seconds,
            max_per_owner=max_per_owner,
        )
    return {
        "candidate_count": len(candidates),
        "attempted": len(attempted),
        "cleaned_session_ids": cleaned,
        "skipped_session_ids": skipped,
        "failures": failures,
        "max_cleanups": max_cleanups,
    }


def _run_prepared_session_cleanup_scheduler(
    state,
    interval_seconds: float,
    initial_delay_seconds: float,
    stop: Event,
) -> None:
    if stop.wait(initial_delay_seconds):
        return
    while True:
        try:
            result = run_prepared_session_cleanup_tick(state)
        except Exception:
            logger.exception("Prepared runtime session cleanup tick failed.")
            result = None
        if result and (result["cleaned_session_ids"] or result["failures"]):
            logger.info("Prepared runtime session cleanup tick completed: %s", result)
        if stop.wait(interval_seconds):
            return


def _cleanup_interval_seconds(interval_seconds: float | None) -> float:
    if interval_seconds is not None:
        return max(1.0, float(interval_seconds))
    raw = os.environ.get("MAVERICK_PREPARED_SESSION_CLEANUP_INTERVAL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_PREPARED_SESSION_CLEANUP_INTERVAL_SECONDS
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_PREPARED_SESSION_CLEANUP_INTERVAL_SECONDS
