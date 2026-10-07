"""Readiness records and bounded retry policy for automatic session prewarm."""

from dataclasses import dataclass
from threading import Event


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


def failure_cooling_down(state: SessionPrewarmState, now: float) -> bool:
    return state.status == "failed" and now - state.started_perf_counter < 60
