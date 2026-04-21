"""Backend downtime watchdog state and escalation decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class BackendWatchdogState:
    """Persisted downtime state for the main backend health probe."""

    first_unhealthy_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_healthy_at: datetime | None = None
    last_rescue_started_at: datetime | None = None
    last_status: str = "unknown"
    last_error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackendWatchdogState":
        return cls(
            first_unhealthy_at=_parse_datetime(payload.get("first_unhealthy_at")),
            last_checked_at=_parse_datetime(payload.get("last_checked_at")),
            last_healthy_at=_parse_datetime(payload.get("last_healthy_at")),
            last_rescue_started_at=_parse_datetime(payload.get("last_rescue_started_at")),
            last_status=str(payload.get("last_status") or "unknown"),
            last_error=payload.get("last_error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_unhealthy_at": _format_datetime(self.first_unhealthy_at),
            "last_checked_at": _format_datetime(self.last_checked_at),
            "last_healthy_at": _format_datetime(self.last_healthy_at),
            "last_rescue_started_at": _format_datetime(self.last_rescue_started_at),
            "last_status": self.last_status,
            "last_error": self.last_error,
        }


def record_backend_probe(
    state: BackendWatchdogState,
    *,
    healthy: bool,
    detail: str | None = None,
    now: datetime | None = None,
) -> BackendWatchdogState:
    """Return updated watchdog state after one health probe."""
    checked_at = now or _now()
    if healthy:
        return replace(
            state,
            first_unhealthy_at=None,
            last_checked_at=checked_at,
            last_healthy_at=checked_at,
            last_status="healthy",
            last_error=None,
        )
    return replace(
        state,
        first_unhealthy_at=state.first_unhealthy_at or checked_at,
        last_checked_at=checked_at,
        last_status="unhealthy",
        last_error=detail or "backend health probe failed",
    )


def backend_downtime_seconds(state: BackendWatchdogState, *, now: datetime | None = None) -> float:
    """Return continuous backend downtime in seconds."""
    if state.first_unhealthy_at is None:
        return 0.0
    return max(0.0, ((now or _now()) - state.first_unhealthy_at).total_seconds())


def should_start_rescue_agent(
    state: BackendWatchdogState,
    *,
    threshold_seconds: int = 300,
    cooldown_seconds: int = 1800,
    now: datetime | None = None,
) -> bool:
    """Decide whether downtime has crossed the escalation threshold."""
    current_time = now or _now()
    if backend_downtime_seconds(state, now=current_time) < threshold_seconds:
        return False
    if state.last_rescue_started_at is None:
        return True
    elapsed = (current_time - state.last_rescue_started_at).total_seconds()
    return elapsed >= cooldown_seconds


def mark_rescue_agent_started(state: BackendWatchdogState, *, now: datetime | None = None) -> BackendWatchdogState:
    """Record that an autonomous rescue attempt was started."""
    return replace(state, last_rescue_started_at=now or _now())
