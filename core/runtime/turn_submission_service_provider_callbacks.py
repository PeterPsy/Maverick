"""Provider-start callback metrics for synchronous runtime turns."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING

from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.turn_submission_service_output import (
    _record_provider_accepted,
    _record_provider_turn_start_sent,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


@dataclass
class ProviderStartupCallbacks:
    """Collect provider startup timing and persist acceptance milestones."""

    state: PlatformState
    session: RuntimeSessionRecord
    turn: RuntimeTurnRecord
    provider_id: str
    events: list[RuntimeEventRecord]
    dispatch_started_at: float = field(default_factory=time.perf_counter)
    turn_start_sent_at: float | None = None
    metrics: dict[str, object] = field(default_factory=dict)
    phase_started_at: dict[str, float] = field(default_factory=dict)

    def record_startup_event(self, phase: str, metadata: dict[str, object]) -> None:
        if phase.endswith("_started"):
            self.phase_started_at[phase.removesuffix("_started")] = time.perf_counter()
        if phase.endswith("_completed"):
            base_phase = phase.removesuffix("_completed")
            started_at = self.phase_started_at.get(base_phase)
            metric_name = {
                "ensure_runtime": "ensure_runtime_ms",
                "remove_generated_skills": "remove_generated_skills_ms",
                "ensure_thread": "ensure_provider_thread_ms",
                "event_sink_reset": "event_sink_reset_ms",
            }.get(base_phase)
            if metric_name and metric_name not in metadata and started_at is not None:
                self.metrics[metric_name] = (time.perf_counter() - started_at) * 1000
        if phase == "turn_start_write_started":
            self.phase_started_at["turn_start_write"] = time.perf_counter()
        if phase == "turn_start_write_sent":
            started_at = self.phase_started_at.get("turn_start_write")
            if "turn_start_write_ms" not in metadata and started_at is not None:
                self.metrics["turn_start_write_ms"] = (time.perf_counter() - started_at) * 1000
        for key, value in metadata.items():
            if key.endswith("_ms") and isinstance(value, int | float):
                self.metrics[key] = float(value)
            elif key in {"provider_thread_id", "source"} and value is not None and value != "":
                self.metrics[key] = value

    def record_turn_start_sent(self, metadata: dict[str, object]) -> None:
        self.turn_start_sent_at = time.perf_counter()
        sent = _record_provider_turn_start_sent(
            self.state,
            session_id=self.session.session_id,
            turn_id=self.turn.turn_id,
            provider_id=self.provider_id,
            runtime_mode=self.session.runtime_mode,
            metadata={**self.metrics, **metadata},
        )
        self.events.append(sent)

    def record_accepted(self, metadata: dict[str, object]) -> None:
        started_at = self.turn_start_sent_at if self.turn_start_sent_at is not None else self.dispatch_started_at
        accepted = _record_provider_accepted(
            self.state,
            session_id=self.session.session_id,
            turn_id=self.turn.turn_id,
            provider_id=self.provider_id,
            runtime_mode=self.session.runtime_mode,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            metadata={**self.metrics, **metadata},
        )
        self.events.append(accepted)
