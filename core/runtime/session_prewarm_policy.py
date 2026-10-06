"""Readiness records and bounded retry policy for automatic session prewarm."""

from dataclasses import dataclass
from threading import Event

from core.runtime.runtime_session import RuntimeSessionRecord


@dataclass
class SessionPrewarmState:
    completion: Event
    started_perf_counter: float
    status: str = "pending"
    provider_id: str | None = None
    provider_thread_id: str | None = None
    elapsed_ms: float | None = None
    runtime_ready: bool = False


@dataclass(frozen=True)
class RuntimeSessionPrewarmResult:
    """Redaction-safe readiness state for one runtime session prewarm."""

    status: str
    prewarm_completed: bool
    provider_thread_ready: bool
    runtime_ready: bool = False
    provider_id: str | None = None
    provider_thread_id: str | None = None
    prewarm_total_ms: float | None = None


def native_session_connected(session: RuntimeSessionRecord) -> bool:
    binding = getattr(session, "device_use_binding", None)
    if binding is None:
        return True
    from core.device_use.runtime_registry import device_use_service_for_session
    service = device_use_service_for_session(session.session_id)
    return service is not None and service.binding_connected(binding, session.session_id)


def failure_cooling_down(state: SessionPrewarmState, now: float) -> bool:
    return state.status == "failed" and now - state.started_perf_counter < 60
