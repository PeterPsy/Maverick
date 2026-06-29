"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from dataclasses import replace
import os
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.service import build_runtime_backend_launch_spec
from core.providers.service import prepare_runtime_skills
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
    turn = state.runtime_store.get_turn(turn_id)
    set_thread_availability(
        state,
        workspace_id=turn.workspace_id,
        runtime_session_id=session_id,
        availability="active",
        now=event.created_at,
    )
    return event


def _record_turn_worker_started(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.worker_started",
        payload={"provider_id": provider_id},
        event_bus=state.runtime_event_bus,
    )


def _record_provider_dispatching(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    runtime_mode: str,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.provider.dispatching",
        payload={"provider_id": provider_id, "runtime_mode": runtime_mode},
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
        if key in {"provider_thread_id", "provider_turn_id", "model_id", "source", "request_id"} and value is not None and value != "":
            payload[key] = value
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
        if key in {"provider_thread_id", "provider_turn_id", "model_id", "status_code", "source"} and value is not None and value != "":
            payload[key] = value
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



def _build_launch_spec_for_execution(state: PlatformState, *, session: RuntimeSessionRecord, provider_id: str):
    if os.environ.get("MAVERICK_RUNTIME_FAKE_RESPONSE") is not None:
        return None
    spec = build_runtime_backend_launch_spec(
        state.provider_store,
        session=session,
        secret_store=state.secret_store,
        observability_store=state.observability_store,
    )
    skills = (
        resolve_runtime_skills(session, start_path=state.repository_root)
        if session.skill_ids
        else list_available_workspace_skills(
            workspace_id=session.workspace_id,
            start_path=state.repository_root,
            app_id=session.skill_catalog_app_id or DEFAULT_SKILL_CATALOG_APP_ID,
        )
    )
    if skills:
        prepare_runtime_skills(state.provider_store, session=session, skills=skills)
    token = spec.env_overrides.get("MAVERICK_RUNTIME_API_TOKEN")
    if token:
        register_workspace_api_token(state.runtime_store, token)
    return spec
