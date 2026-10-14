"""Request-local receive and queue latency spans."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from core.api.platform_state import PlatformState

@dataclass
class RuntimeTurnSubmissionTiming:
    """Request-local latency spans for the HTTP receive to queue path."""

    received_perf_counter: float | None = None
    client_submission_started_at: datetime | None = None
    client_submission_metrics: dict[str, Any] = field(default_factory=dict)
    _durations_ms: dict[str, float] = field(default_factory=dict)
    _queue_recorded_perf_counter: float | None = None

    def record_duration_ms(self, name: str, started_perf_counter: float) -> None:
        if self.received_perf_counter is None:
            return
        self._durations_ms[name] = (time.perf_counter() - started_perf_counter) * 1000

    def record_queue_completed(self, started_perf_counter: float) -> None:
        if self.received_perf_counter is None:
            return
        now = time.perf_counter()
        self._durations_ms["queue_turn_ms"] = (now - started_perf_counter) * 1000
        self._queue_recorded_perf_counter = now

    def record_post_queue_response_ms(self) -> float | None:
        if self.received_perf_counter is None or self._queue_recorded_perf_counter is None:
            return None
        value = (time.perf_counter() - self._queue_recorded_perf_counter) * 1000
        self._durations_ms["post_queue_response_ms"] = value
        return value

    def payload(self, *names: str) -> dict[str, float]:
        payload: dict[str, float] = {}
        for name in names:
            value = self._durations_ms.get(name)
            if value is not None:
                payload[name] = round(value, 3)
        return payload


def runtime_turn_submission_timing(received_perf_counter: float | None) -> RuntimeTurnSubmissionTiming | None:
    if received_perf_counter is None:
        return None
    return RuntimeTurnSubmissionTiming(received_perf_counter=received_perf_counter)
