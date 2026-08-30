"""Provider-neutral runtime cancellation and idle resource cleanup."""

from __future__ import annotations

from contextlib import suppress
from threading import Lock, Timer
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.provider_registry import ProviderRegistry
from core.providers.service import resolve_runtime_engine_for_session
from core.runtime.agentic_runtime_service import cancel_agentic_runtime, close_agentic_runtime
from core.runtime.plain_hosted_cancellation import interrupt_plain_hosted_requests
from core.runtime.plain_hosted_text import runtime_session_is_plain_hosted_chat
from core.runtime.process_control import (
    terminate_orphaned_runtime_processes_for_session,
    terminate_runtime_processes,
)
from core.runtime.resolved_runtime_engine import ResolvedRuntimeEngine
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.service import record_runtime_event
from core.runtime.turn_submission_launch_cache import clear_cached_runtime_launch_context

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


ACTIVE_TURN_STATUSES = frozenset({"queued", "active", "waiting_for_tool_confirmation"})
IDLE_RUNTIME_REAP_TTL_SECONDS = 180.0
_IDLE_REAP_TIMERS: dict[str, Timer] = {}
_IDLE_REAP_TIMERS_LOCK = Lock()


def release_idle_runtime_processes(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str,
    reason: str,
    idle_ttl_seconds: float | None = IDLE_RUNTIME_REAP_TTL_SECONDS,
) -> int:
    """Close engine resources after an idle TTL when a session has no pending work."""
    if any(turn.status in ACTIVE_TURN_STATUSES for turn in state.runtime_store.list_turns(session_id)):
        return 0
    ttl_seconds = IDLE_RUNTIME_REAP_TTL_SECONDS if idle_ttl_seconds is None else idle_ttl_seconds
    if ttl_seconds > 0:
        return _schedule_idle_runtime_process_reap(
            state,
            session_id=session_id,
            provider_id=provider_id,
            reason=reason,
            idle_ttl_seconds=ttl_seconds,
        )
    _cancel_scheduled_idle_runtime_process_reap(session_id)
    clear_cached_runtime_launch_context(session_id)
    terminated = 0
    with suppress(Exception):
        session = state.runtime_store.get_session(session_id)
        engine = ResolvedRuntimeEngine(
            *resolve_runtime_engine_for_session(
                state.provider_store,
                session=session,
                registry=getattr(state, "provider_registry", None),
            )
        )
        if session.execution_binding is not None:
            terminated += close_agentic_runtime(
                state.runtime_store,
                session_id=session_id,
                adapter=engine.agentic_adapter,
            ).terminated_processes
        elif engine.legacy_adapter is not None:
            closed = engine.legacy_adapter.close_runtime(session_id)
            if isinstance(closed, int):
                terminated += closed
    terminated += terminate_runtime_processes(session_id)
    terminated += terminate_orphaned_runtime_processes_for_session(session_id)
    if terminated:
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            plane="process",
            event_type="runtime.process.idle_reaped",
            payload={"provider_id": provider_id, "terminated_processes": terminated, "reason": reason},
            event_bus=state.runtime_event_bus,
        )
    return terminated


def _schedule_idle_runtime_process_reap(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str,
    reason: str,
    idle_ttl_seconds: float,
) -> int:
    def run_reap() -> None:
        with _IDLE_REAP_TIMERS_LOCK:
            if _IDLE_REAP_TIMERS.get(session_id) is not timer:
                return
            _IDLE_REAP_TIMERS.pop(session_id, None)
        release_idle_runtime_processes(
            state,
            session_id=session_id,
            provider_id=provider_id,
            reason=reason,
            idle_ttl_seconds=0,
        )

    timer = Timer(idle_ttl_seconds, run_reap)
    timer.daemon = True
    with _IDLE_REAP_TIMERS_LOCK:
        previous = _IDLE_REAP_TIMERS.get(session_id)
        _IDLE_REAP_TIMERS[session_id] = timer
    if previous is not None:
        previous.cancel()
    timer.start()
    return 0


def _cancel_scheduled_idle_runtime_process_reap(session_id: str) -> None:
    with _IDLE_REAP_TIMERS_LOCK:
        timer = _IDLE_REAP_TIMERS.pop(session_id, None)
    if timer is not None:
        timer.cancel()


def interrupt_runtime_provider_turn(
    state: PlatformState,
    session: RuntimeSessionRecord,
    *,
    turn_id: str | None = None,
    registry: ProviderRegistry | None = None,
    wait_for_termination: bool = False,
) -> bool:
    """Ask the selected runtime engine to cancel its active request."""
    if runtime_session_is_plain_hosted_chat(session):
        return interrupt_plain_hosted_requests(
            session.session_id,
            turn_id=turn_id,
            store=state.runtime_store,
            wait_for_termination=wait_for_termination,
        )
    with suppress(Exception):
        engine = ResolvedRuntimeEngine(
            *resolve_runtime_engine_for_session(
                state.provider_store,
                session=session,
                registry=registry or getattr(state, "provider_registry", None),
            )
        )
        if session.execution_binding is not None:
            return cancel_agentic_runtime(
                state.runtime_store,
                session_id=session.session_id,
                correlation_id=turn_id or session.session_id,
                adapter=engine.agentic_adapter,
            ).cancelled
        return bool(
            engine.legacy_adapter
            and engine.legacy_adapter.interrupt_turn(session.session_id)
        )
    return False
