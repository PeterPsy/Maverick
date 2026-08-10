"""Runtime turn records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.runtime.runtime_session import RuntimeMode


RuntimeTurnStatus = Literal["queued", "active", "completed", "failed", "cancelled", "timed-out"]


@dataclass(frozen=True)
class RuntimeTurnRecord:
    """One execution turn inside a runtime session."""

    turn_id: str
    session_id: str
    workspace_id: str
    status: RuntimeTurnStatus
    input_text: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    runtime_mode: RuntimeMode = "agentic"
    client_message_id: str | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_reason: str | None = None
    provider_request_started_at: datetime | None = None
    provider_request_finished_at: datetime | None = None
    provider_request_owner_id: str | None = None
    provider_request_generation: str | None = None
    provider_request_owner_kind: str | None = None
    provider_request_owner_host_id: str | None = None
    provider_request_owner_pid: int | None = None
    provider_request_owner_process_start: str | None = None
    provider_request_cancellation_acknowledged_at: datetime | None = None
    terminalization_event_id: str | None = None
    terminalization_event_type: str | None = None
    terminalization_event_payload: dict[str, object] | None = None
    terminalization_claimed_at: datetime | None = None
    terminalization_event_persisted_at: datetime | None = None
    terminalization_thread_released_at: datetime | None = None
    terminalization_callback_delivered_at: datetime | None = None
