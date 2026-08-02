"""Inter-agent event contracts and visibility helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from core.inter_agent.errors import InterAgentValidationError


InterAgentVisibilityPlane = Literal["summary", "detail", "debug"]
InterAgentEventType = Literal[
    "inter_agent.run.started",
    "inter_agent.mode.selected",
    "inter_agent.plan.summary_created",
    "inter_agent.participant.added",
    "inter_agent.participant.started",
    "inter_agent.participant.status_changed",
    "inter_agent.graph.edge_added",
    "inter_agent.directive.received",
    "inter_agent.directive.delivered",
    "inter_agent.generalist.handoff_prepared",
    "inter_agent.message.sent",
    "inter_agent.task.created",
    "inter_agent.task.started",
    "inter_agent.task.completed",
    "inter_agent.handoff.requested",
    "inter_agent.handoff.accepted",
    "inter_agent.handoff.completed",
    "inter_agent.tool_call.observed",
    "inter_agent.approval.requested",
    "inter_agent.approval.resolved",
    "inter_agent.artifact.created",
    "inter_agent.budget.reserved",
    "inter_agent.budget.released",
    "inter_agent.budget.exceeded",
    "inter_agent.summary.updated",
    "inter_agent.quality.assessed",
    "inter_agent.completion.decided",
    "inter_agent.run.paused",
    "inter_agent.run.resumed",
    "inter_agent.run.completed",
    "inter_agent.run.failed",
    "inter_agent.run.cancelled",
    "inter_agent.run.recovered",
]


VISIBILITY_PLANES: set[str] = {"summary", "detail", "debug"}
VISIBILITY_ORDER: tuple[InterAgentVisibilityPlane, ...] = ("summary", "detail", "debug")

INTER_AGENT_EVENT_TYPES: set[str] = {
    "inter_agent.run.started",
    "inter_agent.mode.selected",
    "inter_agent.plan.summary_created",
    "inter_agent.participant.added",
    "inter_agent.participant.started",
    "inter_agent.participant.status_changed",
    "inter_agent.graph.edge_added",
    "inter_agent.directive.received",
    "inter_agent.directive.delivered",
    "inter_agent.generalist.handoff_prepared",
    "inter_agent.message.sent",
    "inter_agent.task.created",
    "inter_agent.task.started",
    "inter_agent.task.completed",
    "inter_agent.handoff.requested",
    "inter_agent.handoff.accepted",
    "inter_agent.handoff.completed",
    "inter_agent.tool_call.observed",
    "inter_agent.approval.requested",
    "inter_agent.approval.resolved",
    "inter_agent.artifact.created",
    "inter_agent.budget.reserved",
    "inter_agent.budget.released",
    "inter_agent.budget.exceeded",
    "inter_agent.summary.updated",
    "inter_agent.quality.assessed",
    "inter_agent.completion.decided",
    "inter_agent.run.paused",
    "inter_agent.run.resumed",
    "inter_agent.run.completed",
    "inter_agent.run.failed",
    "inter_agent.run.cancelled",
    "inter_agent.run.recovered",
}

CHAIN_OF_THOUGHT_PAYLOAD_KEYS = {
    "chain_of_thought",
    "chainOfThought",
    "cot",
    "raw_cot",
    "raw_reasoning",
    "reasoning_trace",
    "reasoningTrace",
}


@dataclass(frozen=True)
class EventRetentionPolicyRecord:
    """Bound inter-agent event history independently by visibility plane."""

    retention_policy_id: str
    workspace_id: str
    summary_max_events: int
    detail_max_events: int
    debug_max_events: int
    created_at: datetime

    def max_events_for(self, visibility_plane: InterAgentVisibilityPlane) -> int:
        """Return the event cap for one visibility plane."""
        if visibility_plane == "summary":
            return self.summary_max_events
        if visibility_plane == "detail":
            return self.detail_max_events
        return self.debug_max_events


@dataclass(frozen=True)
class InterAgentEventRecord:
    """Normalized inter-agent event projected for graph replay and audit."""

    event_id: str
    workspace_id: str
    run_id: str
    thread_id: str
    root_runtime_session_id: str
    participant_id: str | None
    runtime_session_id: str | None
    runtime_turn_id: str | None
    runtime_event_id: str | None
    event_type: InterAgentEventType
    visibility_plane: InterAgentVisibilityPlane
    sequence: int
    correlation_id: str
    idempotency_key: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    idempotency_fingerprint: str | None = None


@dataclass(frozen=True)
class InterAgentEventPage:
    """One bounded page of ordered inter-agent events."""

    events: list[InterAgentEventRecord]
    visibility_plane: InterAgentVisibilityPlane
    limit: int
    after_event_id: str | None = None
    before_event_id: str | None = None
    has_more_before: bool = False
    has_more_after: bool = False
    oldest_event_id: str | None = None
    newest_event_id: str | None = None


def validate_event_type(event_type: str) -> InterAgentEventType:
    """Return a supported inter-agent event type."""
    normalized = str(event_type).strip()
    if normalized not in INTER_AGENT_EVENT_TYPES:
        raise InterAgentValidationError(f"Unsupported inter-agent event type `{normalized}`.")
    return normalized  # type: ignore[return-value]


def validate_visibility_plane(visibility_plane: str) -> InterAgentVisibilityPlane:
    """Return a supported event visibility plane."""
    normalized = str(visibility_plane).strip()
    if normalized not in VISIBILITY_PLANES:
        raise InterAgentValidationError(f"Unsupported inter-agent event visibility `{normalized}`.")
    return normalized  # type: ignore[return-value]


def visible_planes_for(
    visibility_plane: InterAgentVisibilityPlane,
) -> set[InterAgentVisibilityPlane]:
    """Return planes visible when a caller is authorized up to the requested level."""
    normalized = validate_visibility_plane(visibility_plane)
    index = VISIBILITY_ORDER.index(normalized)
    return set(VISIBILITY_ORDER[: index + 1])


def assert_payload_is_user_safe(payload: Any, *, path: str = "payload") -> None:
    """Reject event payloads that attempt to persist raw chain-of-thought."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in CHAIN_OF_THOUGHT_PAYLOAD_KEYS:
                raise InterAgentValidationError(f"Inter-agent event `{path}.{key}` cannot contain raw reasoning.")
            assert_payload_is_user_safe(value, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_payload_is_user_safe(item, path=f"{path}[{index}]")


def validate_event_record(record: InterAgentEventRecord) -> InterAgentEventRecord:
    """Validate one event record before it reaches the event store."""
    if not record.event_id.strip():
        raise InterAgentValidationError("Inter-agent events require a non-empty event_id.")
    if not record.workspace_id.strip():
        raise InterAgentValidationError("Inter-agent events require a workspace_id.")
    if not record.run_id.strip():
        raise InterAgentValidationError("Inter-agent events require a run_id.")
    if not record.thread_id.strip():
        raise InterAgentValidationError("Inter-agent events require a thread_id.")
    if not record.root_runtime_session_id.strip():
        raise InterAgentValidationError("Inter-agent events require a root_runtime_session_id.")
    if not record.correlation_id.strip():
        raise InterAgentValidationError("Inter-agent events require a correlation_id.")
    validate_event_type(record.event_type)
    validate_visibility_plane(record.visibility_plane)
    assert_payload_is_user_safe(record.payload)
    return record
