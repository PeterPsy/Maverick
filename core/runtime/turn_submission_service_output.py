"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from dataclasses import replace
import os
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.service import build_resolved_runtime_backend_launch_spec, build_runtime_backend_launch_spec
from core.providers.service import prepare_runtime_skills
from core.runtime.turn_submission_launch_cache import (
    build_runtime_launch_context_fingerprint,
    cache_runtime_launch_context,
    get_cached_runtime_launch_context,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.service import record_runtime_event
from core.runtime.thread_catalog_events import set_thread_availability
from core.runtime.workspace_api_token import register_workspace_api_token
from core.skills.catalog import DEFAULT_SKILL_CATALOG_APP_ID
from core.skills.service import list_available_workspace_skills, resolve_runtime_skills

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


def _record_turn_started(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    started_at = time.perf_counter()
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )
    _record_turn_marker(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        event_type="runtime.turn.turn_started_recorded",
        payload={
            "recorded_event_id": event.event_id,
            "turn_started_record_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
    )
    return event


def _record_turn_thread_availability_active(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    now=None,
) -> list[RuntimeEventRecord]:
    turn = state.runtime_store.get_turn(turn_id)
    availability_started_at = time.perf_counter()
    started = _record_thread_availability_started(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        availability="active",
    )
    set_thread_availability(
        state,
        workspace_id=turn.workspace_id,
        runtime_session_id=session_id,
        availability="active",
        now=now,
    )
    completed = _record_thread_availability_completed(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        availability="active",
        elapsed_ms=(time.perf_counter() - availability_started_at) * 1000,
    )
    return [started, completed]


def _record_turn_worker_started(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    started_at = time.perf_counter()
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.worker_started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )
    _record_turn_marker(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        event_type="runtime.turn.worker_started_recorded",
        payload={
            "recorded_event_id": event.event_id,
            "worker_started_record_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
    )
    return event


def _record_turn_worker_entered(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.worker_entered",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )


def _record_worker_turn_lookup_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    phase: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return _record_turn_marker(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        event_type="runtime.turn.worker_turn_lookup_completed",
        payload={"phase": phase, "worker_turn_lookup_ms": round(elapsed_ms, 3)},
    )


def _record_worker_session_lookup_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    phase: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return _record_turn_marker(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        event_type="runtime.turn.worker_session_lookup_completed",
        payload={"phase": phase, "worker_session_lookup_ms": round(elapsed_ms, 3)},
    )


def _record_turn_marker(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> RuntimeEventRecord:
    marker_payload: dict[str, object] = {"provider_id": provider_id}
    if payload:
        marker_payload.update(payload)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type=event_type,
        payload=marker_payload,
        event_bus=state.runtime_event_bus,
    )


def _record_debug_log_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    phase: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return _record_turn_marker(
        state,
        session_id=session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        event_type="runtime.turn.debug_log_completed",
        payload={
            "phase": phase,
            "debug_log_runtime_turn_ms": round(elapsed_ms, 3),
        },
    )


def _record_source_app_queued_dispatch_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.source_app_queued_dispatch_started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )


def _record_source_app_queued_dispatch_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.source_app_queued_dispatch_completed",
        payload={"provider_id": provider_id, "source_app_queued_dispatch_ms": round(elapsed_ms, 3)},
        event_bus=state.runtime_event_bus,
    )


def _record_thread_availability_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    availability: str,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.thread_availability_started",
        payload={"provider_id": provider_id, "availability": availability},
        event_bus=state.runtime_event_bus,
    )


def _record_thread_availability_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    availability: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.thread_availability_completed",
        payload={
            "provider_id": provider_id,
            "availability": availability,
            "thread_availability_update_ms": round(elapsed_ms, 3),
        },
        event_bus=state.runtime_event_bus,
    )


def _record_turn_activation_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    status: str,
    elapsed_ms: float | None = None,
    transition_timings: dict[str, float] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {"provider_id": provider_id, "status": status}
    if elapsed_ms is not None:
        payload["transition_active_ms"] = round(elapsed_ms, 3)
    for key, value in (transition_timings or {}).items():
        payload[key] = round(value, 3)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.turn_activation_completed",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _record_session_lock_wait_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.session_lock_wait_started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )


def _record_session_lock_acquired(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    elapsed_ms: float,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.session_lock_acquired",
        payload={"provider_id": provider_id, "session_lock_wait_ms": round(elapsed_ms, 3)},
        event_bus=state.runtime_event_bus,
    )


def _record_app_references_materialize_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    app_reference_count: int,
    storage_reference_count: int,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.app_references_materialize_started",
        payload={
            "provider_id": provider_id,
            "app_reference_count": app_reference_count,
            "storage_reference_count": storage_reference_count,
        },
        event_bus=state.runtime_event_bus,
    )


def _record_app_references_materialize_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    elapsed_ms: float,
    app_reference_count: int,
    storage_reference_count: int,
    materialized_reference_count: int,
    reference_cache_hit: bool,
    reference_action_timings: list[dict[str, object]] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {
        "provider_id": provider_id,
        "app_reference_materialize_ms": round(elapsed_ms, 3),
        "app_reference_count": app_reference_count,
        "storage_reference_count": storage_reference_count,
        "materialized_reference_count": materialized_reference_count,
        "reference_cache_hit": reference_cache_hit,
    }
    if reference_action_timings:
        payload["reference_action_timings"] = reference_action_timings
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.app_references_materialize_completed",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _record_app_references_materialize_failed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    elapsed_ms: float,
    app_reference_count: int,
    storage_reference_count: int,
    error: Exception,
    reference_action_timings: list[dict[str, object]] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {
        "provider_id": provider_id,
        "app_reference_materialize_ms": round(elapsed_ms, 3),
        "app_reference_count": app_reference_count,
        "storage_reference_count": storage_reference_count,
        "error_type": error.__class__.__name__,
    }
    if reference_action_timings:
        payload["reference_action_timings"] = reference_action_timings
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.app_references_materialize_failed",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _record_provider_input_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    app_reference_count: int,
    storage_reference_count: int,
    materialized_reference_count: int,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.provider_input_started",
        payload={
            "provider_id": provider_id,
            "app_reference_count": app_reference_count,
            "storage_reference_count": storage_reference_count,
            "materialized_reference_count": materialized_reference_count,
        },
        event_bus=state.runtime_event_bus,
    )


def _record_provider_input_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    elapsed_ms: float,
    app_reference_count: int,
    storage_reference_count: int,
    materialized_reference_count: int,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.provider_input_completed",
        payload={
            "provider_id": provider_id,
            "provider_input_build_ms": round(elapsed_ms, 3),
            "app_reference_count": app_reference_count,
            "storage_reference_count": storage_reference_count,
            "materialized_reference_count": materialized_reference_count,
        },
        event_bus=state.runtime_event_bus,
    )


def _record_provider_dispatching(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    runtime_mode: str,
    metadata: dict[str, object] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    for key, value in (metadata or {}).items():
        if key.endswith("_ms") and isinstance(value, int | float):
            payload[key] = round(float(value), 3)
        elif key in {
            "skill_count",
            "provider_id_resolved",
            "launch_cache_hit",
            "launch_cache_fingerprint_prefix",
        } and value is not None:
            payload[key] = value
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.provider.dispatching",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


_PROVIDER_STARTUP_PHASES = {
    "ensure_runtime_started",
    "ensure_runtime_completed",
    "remove_generated_skills_started",
    "remove_generated_skills_completed",
    "ensure_thread_started",
    "ensure_thread_completed",
    "event_sink_reset_started",
    "event_sink_reset_completed",
    "turn_start_write_started",
    "turn_start_write_sent",
}


def _record_provider_startup_event(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    runtime_mode: str,
    phase: str,
    metadata: dict[str, object] | None = None,
) -> RuntimeEventRecord:
    if phase not in _PROVIDER_STARTUP_PHASES:
        raise ValueError(f"Unsupported provider startup phase `{phase}`.")
    payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    for key, value in (metadata or {}).items():
        if key in {"provider_thread_id", "source"} and value is not None and value != "":
            payload[key] = value
        elif key.endswith("_ms") and isinstance(value, int | float):
            payload[key] = round(float(value), 3)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type=f"runtime.provider.{phase}",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _record_provider_turn_start_sent(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    runtime_mode: str,
    metadata: dict[str, object] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    for key, value in (metadata or {}).items():
        if key in {"provider_thread_id", "provider_turn_id", "model_id", "source", "request_id", "acceptance_slo_scope"} and value is not None and value != "":
            payload[key] = value
        elif key.endswith("_ms") and isinstance(value, int | float):
            payload[key] = round(float(value), 3)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.provider.turn_start_sent",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )


def _record_provider_accepted(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    runtime_mode: str,
    elapsed_ms: float | None = None,
    metadata: dict[str, object] | None = None,
) -> RuntimeEventRecord:
    payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    if elapsed_ms is not None:
        payload["elapsed_ms"] = round(elapsed_ms, 3)
        payload["turn_start_to_ack_ms"] = round(elapsed_ms, 3)
        payload["elapsed_from"] = "provider_turn_start_sent"
    for key, value in (metadata or {}).items():
        if key in {"provider_thread_id", "provider_turn_id", "model_id", "status_code", "source", "acceptance_slo_scope"} and value is not None and value != "":
            payload[key] = value
        elif key.endswith("_ms") and isinstance(value, int | float):
            payload[key] = round(float(value), 3)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.provider.accepted",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )



def _record_provider_thread_id(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    provider_thread_id: str,
) -> RuntimeEventRecord:
    updated = replace(session, provider_id=provider_id, provider_thread_id=provider_thread_id)
    state.runtime_store.save_session(updated)
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        plane="runtime",
        event_type="runtime.provider_thread.bound",
        payload={"provider_id": provider_id, "provider_thread_id": provider_thread_id},
        event_bus=state.runtime_event_bus,
    )



def _build_launch_spec_for_execution(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    provider_definition=None,
    provider_selection=None,
    runtime_adapter=None,
):
    if os.environ.get("MAVERICK_RUNTIME_FAKE_RESPONSE") is not None:
        return None, {}
    cache_fingerprint_started_at = time.perf_counter()
    cache_fingerprint = (
        build_runtime_launch_context_fingerprint(
            state,
            session=session,
            provider_id=provider_id,
            provider_definition=provider_definition,
            provider_selection=provider_selection,
        )
        if provider_definition is not None and runtime_adapter is not None
        else None
    )
    cache_fingerprint_ms = (time.perf_counter() - cache_fingerprint_started_at) * 1000
    if cache_fingerprint is not None:
        cache_fingerprint_prefix = cache_fingerprint[:12]
        cached = get_cached_runtime_launch_context(
            session_id=session.session_id,
            fingerprint=cache_fingerprint,
        )
        if cached is not None and cached.fingerprint == cache_fingerprint:
            return cached.launch_spec, {
                **cached.metadata,
                "launch_spec_ms": 0.0,
                "skill_resolve_ms": 0.0,
                "skill_prepare_ms": 0.0,
                "launch_cache_hit": True,
                "launch_cache_fingerprint_ms": cache_fingerprint_ms,
                "launch_cache_fingerprint_prefix": cache_fingerprint_prefix,
            }
    started_at = time.perf_counter()
    if provider_definition is not None and runtime_adapter is not None:
        spec = build_resolved_runtime_backend_launch_spec(
            state.provider_store,
            session=session,
            definition=provider_definition,
            selection=provider_selection,
            runtime_adapter=runtime_adapter,
            secret_store=state.secret_store,
            observability_store=state.observability_store,
        )
    else:
        spec = build_runtime_backend_launch_spec(
            state.provider_store,
            session=session,
            secret_store=state.secret_store,
            observability_store=state.observability_store,
        )
    launch_spec_ms = (time.perf_counter() - started_at) * 1000
    skill_resolve_started_at = time.perf_counter()
    skills = (
        resolve_runtime_skills(session, start_path=state.repository_root)
        if session.skill_ids
        else list_available_workspace_skills(
            workspace_id=session.workspace_id,
            start_path=state.repository_root,
            app_id=session.skill_catalog_app_id or DEFAULT_SKILL_CATALOG_APP_ID,
        )
    )
    skill_resolve_ms = (time.perf_counter() - skill_resolve_started_at) * 1000
    skill_prepare_ms = 0.0
    if skills or provider_id == "codex":
        skill_prepare_started_at = time.perf_counter()
        prepare_runtime_skills(state.provider_store, session=session, skills=skills, runtime_adapter=runtime_adapter)
        skill_prepare_ms = (time.perf_counter() - skill_prepare_started_at) * 1000
    token = spec.env_overrides.get("MAVERICK_RUNTIME_API_TOKEN")
    if token:
        register_workspace_api_token(state.runtime_store, token)
    metadata = {
        "launch_spec_ms": launch_spec_ms,
        "skill_resolve_ms": skill_resolve_ms,
        "skill_prepare_ms": skill_prepare_ms,
        "skill_count": len(skills),
        "provider_id_resolved": provider_id,
        "launch_cache_hit": False,
        "launch_cache_fingerprint_ms": cache_fingerprint_ms,
    }
    if cache_fingerprint is not None:
        metadata["launch_cache_fingerprint_prefix"] = cache_fingerprint[:12]
        cache_runtime_launch_context(
            session_id=session.session_id,
            fingerprint=cache_fingerprint,
            launch_spec=spec,
            metadata=metadata,
        )
    return spec, metadata
