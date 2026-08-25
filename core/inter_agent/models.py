"""Inter-agent domain records and specification validation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Literal

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.events import InterAgentVisibilityPlane, validate_visibility_plane
from core.runtime.runtime_session import (
    RuntimeThreadVisibility,
    coerce_skill_activation_mode,
    normalize_runtime_session_visibility,
)
from core.skills.service import SkillInvocationError, normalize_invoked_skill_ids


InterAgentRunMode = Literal[
    "single_agent",
    "manager_tools",
    "sequential",
    "concurrent",
    "handoff",
    "group_chat",
    "magentic_like",
    "orchestrated",
]
InterAgentRunStatus = Literal[
    "created",
    "planning",
    "running",
    "paused",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "recovering",
]
InterAgentParticipantKind = Literal["orchestrator", "agent", "tool", "human", "system"]
InterAgentParticipantExecutionMode = Literal[
    "root_orchestrator",
    "child_runtime_session",
    "embedded_executor",
    "human_gate",
    "tool_proxy",
]
InterAgentParticipantStatus = Literal[
    "idle",
    "planning",
    "running",
    "waiting",
    "blocked",
    "reviewing",
    "completed",
    "failed",
    "cancelled",
]
InterAgentEdgeKind = Literal[
    "delegated",
    "handed_off",
    "reviewed_by",
    "produced",
    "depends_on",
    "requested_approval",
]
InterAgentApprovalStatus = Literal["pending", "approved", "rejected", "expired", "cancelled"]
InterAgentRiskLevel = Literal["low", "medium", "high", "critical"]
BudgetReservationStatus = Literal["reserved", "released"]


RUN_MODES: set[str] = {
    "single_agent",
    "manager_tools",
    "sequential",
    "concurrent",
    "handoff",
    "group_chat",
    "magentic_like",
    "orchestrated",
}
PARTICIPANT_KINDS: set[str] = {"orchestrator", "agent", "tool", "human", "system"}
PARTICIPANT_EXECUTION_MODES: set[str] = {
    "root_orchestrator",
    "child_runtime_session",
    "embedded_executor",
    "human_gate",
    "tool_proxy",
}
EDGE_KINDS: set[str] = {
    "delegated",
    "handed_off",
    "reviewed_by",
    "produced",
    "depends_on",
    "requested_approval",
}

PARTICIPANT_EXECUTION_BY_KIND: dict[str, set[str]] = {
    "orchestrator": {"root_orchestrator", "child_runtime_session", "embedded_executor"},
    "agent": {"child_runtime_session", "embedded_executor"},
    "tool": {"tool_proxy"},
    "human": {"human_gate"},
    "system": {"embedded_executor"},
}


@dataclass(frozen=True)
class AgentParticipantSnapshot:
    """Immutable prompt and skill materialization supplied by an app such as Agents."""

    agent_type_id: str
    label: str
    system_prompt: str
    skill_ids: list[str]
    skill_catalog_app_id: str
    skill_activation_mode: str = "implicit"
    provider_id: str | None = None
    revision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        """Return a stable digest for replay and recovery."""
        payload = {
            "agent_type_id": self.agent_type_id,
            "label": self.label,
            "system_prompt": self.system_prompt,
            "skill_ids": sorted(self.skill_ids),
            "skill_catalog_app_id": self.skill_catalog_app_id,
            "skill_activation_mode": self.skill_activation_mode,
            "provider_id": self.provider_id,
            "revision_id": self.revision_id,
            "metadata": self.metadata,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParticipantSpec:
    """Validated input contract for one participant before executor materialization."""

    kind: InterAgentParticipantKind
    execution_mode: InterAgentParticipantExecutionMode
    label: str
    participant_id: str | None = None
    agent_type_id: str | None = None
    agent_snapshot: AgentParticipantSnapshot | None = None
    prompt_snapshot_ref: str | None = None
    skill_ids: list[str] = field(default_factory=list)
    invoked_skill_ids: list[str] = field(default_factory=list)
    provider_id: str | None = None
    authority_grant_ids: list[str] = field(default_factory=list)
    thread_visibility: RuntimeThreadVisibility | None = None


@dataclass(frozen=True)
class EdgeSpec:
    """Validated input contract for one graph edge."""

    source_id: str
    target_id: str
    kind: InterAgentEdgeKind
    label: str = ""


@dataclass(frozen=True)
class BudgetPolicySpec:
    """Budget limits supplied before creating a run policy record."""

    max_participants: int = 1
    max_concurrent_participants: int = 1
    max_handoffs: int = 0
    max_rounds: int = 1
    max_total_turns: int = 1
    max_turns_per_participant: int = 1
    max_tool_calls: int = 0
    max_estimated_tokens: int = 0
    max_estimated_cost: Decimal | float | int = Decimal("0")
    max_idle_seconds: int = 300
    max_stall_seconds: int = 300
    approval_required_above_cost: Decimal | float | int = Decimal("0")


@dataclass(frozen=True)
class InterAgentRunSpec:
    """Validated input contract for creating an inter-agent run without an executor."""

    workspace_id: str
    thread_id: str
    root_runtime_session_id: str
    source_app_id: str
    mode: InterAgentRunMode
    created_by_user_id: str
    participants: list[ParticipantSpec]
    budget: BudgetPolicySpec = field(default_factory=BudgetPolicySpec)
    edges: list[EdgeSpec] = field(default_factory=list)
    run_id: str | None = None
    orchestrator_participant_id: str | None = None
    aggregator_participant_id: str | None = None
    merge_policy: str | None = None
    visibility_level: InterAgentVisibilityPlane = "summary"
    idempotency_key: str | None = None
    source_runtime_turn_id: str | None = None
    orchestration_policy: str | None = None


@dataclass(frozen=True)
class InterAgentRunRecord:
    """Persisted lifecycle record for one inter-agent run."""

    run_id: str
    workspace_id: str
    thread_id: str
    root_runtime_session_id: str
    source_app_id: str
    mode: InterAgentRunMode
    status: InterAgentRunStatus
    created_by_user_id: str
    orchestrator_participant_id: str
    budget_policy_id: str
    budget_ledger_id: str
    visibility_level: InterAgentVisibilityPlane
    retention_policy_id: str
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    recovery_generation: int
    idempotency_key: str | None = None
    spec_fingerprint: str | None = None
    aggregator_participant_id: str | None = None
    merge_policy: str | None = None
    source_runtime_turn_id: str | None = None
    orchestration_policy: str | None = None


@dataclass(frozen=True)
class InterAgentParticipantRecord:
    """Persisted participant state for one run."""

    participant_id: str
    workspace_id: str
    run_id: str
    kind: InterAgentParticipantKind
    execution_mode: InterAgentParticipantExecutionMode
    agent_type_id: str | None
    agent_snapshot_digest: str | None
    agent_snapshot: dict[str, Any] | None
    prompt_snapshot_ref: str | None
    label: str
    runtime_session_id: str | None
    status: InterAgentParticipantStatus
    current_task_id: str | None
    skill_ids: list[str]
    invoked_skill_ids: list[str]
    provider_id: str | None
    authority_grant_ids: list[str]
    thread_visibility: RuntimeThreadVisibility
    created_at: datetime
    updated_at: datetime
    sequence_index: int = 0


@dataclass(frozen=True)
class InterAgentEdgeRecord:
    """Persisted graph edge between participants or graph objects."""

    edge_id: str
    workspace_id: str
    run_id: str
    source_id: str
    target_id: str
    kind: InterAgentEdgeKind
    label: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ApprovalRequestRecord:
    """Persisted human approval gate for inter-agent operations."""

    approval_id: str
    workspace_id: str
    run_id: str
    participant_id: str
    requested_by_participant_id: str
    operation_kind: str
    resource_refs: list[dict[str, Any]]
    summary: str
    risk_level: InterAgentRiskLevel
    status: InterAgentApprovalStatus
    eligible_approver_user_ids: list[str]
    eligible_approver_roles: list[str]
    expires_at: datetime
    resolved_by_user_id: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None


@dataclass(frozen=True)
class BudgetPolicyRecord:
    """Persisted budget limits for one run."""

    budget_policy_id: str
    workspace_id: str
    max_participants: int
    max_concurrent_participants: int
    max_handoffs: int
    max_rounds: int
    max_total_turns: int
    max_turns_per_participant: int
    max_tool_calls: int
    max_estimated_tokens: int
    max_estimated_cost: Decimal
    max_idle_seconds: int
    max_stall_seconds: int
    approval_required_above_cost: Decimal
    created_at: datetime


@dataclass(frozen=True)
class BudgetReservation:
    """One idempotent budget reservation inside a ledger."""

    reservation_id: str
    participant_id: str | None
    participant_slots: int
    running_participants: int
    turns: int
    tool_calls: int
    handoffs: int
    estimated_tokens: int
    estimated_cost: Decimal
    status: BudgetReservationStatus
    created_at: datetime
    fingerprint: str | None = None
    released_at: datetime | None = None


@dataclass(frozen=True)
class BudgetLedgerRecord:
    """Persisted budget usage and active reservations for one run."""

    budget_ledger_id: str
    workspace_id: str
    run_id: str
    reserved_participants: int
    running_participants: int
    turns_used: int
    tool_calls_used: int
    handoffs_used: int
    estimated_tokens_used: int
    estimated_cost_used: Decimal
    operation_reservations: dict[str, dict[str, Any]]
    updated_at: datetime


def validate_run_spec(spec: InterAgentRunSpec) -> InterAgentRunSpec:
    """Validate a run spec without creating runtime sessions or executor work."""
    _require_non_empty(spec.workspace_id, "workspace_id")
    _require_non_empty(spec.thread_id, "thread_id")
    _require_non_empty(spec.root_runtime_session_id, "root_runtime_session_id")
    _require_non_empty(spec.source_app_id, "source_app_id")
    _require_non_empty(spec.created_by_user_id, "created_by_user_id")
    if spec.mode not in RUN_MODES:
        raise InterAgentValidationError(f"Unsupported inter-agent run mode `{spec.mode}`.")
    validate_visibility_plane(spec.visibility_level)
    if not spec.participants:
        raise InterAgentValidationError("Inter-agent run specs require at least one participant.")
    _validate_budget_policy_spec(spec.budget)
    normalized_participants = [validate_participant_spec(participant) for participant in spec.participants]
    participant_ids = [participant.participant_id for participant in normalized_participants if participant.participant_id]
    if len(set(participant_ids)) != len(participant_ids):
        raise InterAgentValidationError("Participant ids must be unique within an inter-agent run spec.")
    if len(normalized_participants) > spec.budget.max_participants:
        raise InterAgentValidationError("Inter-agent run spec exceeds max_participants.")
    orchestrators = [participant for participant in normalized_participants if participant.kind == "orchestrator"]
    if len(orchestrators) != 1:
        raise InterAgentValidationError("Inter-agent run specs require exactly one orchestrator participant.")
    if spec.mode == "orchestrated":
        if len(normalized_participants) != 1:
            raise InterAgentValidationError("Orchestrated runs must start with only the orchestrator participant.")
        if orchestrators[0].execution_mode != "child_runtime_session":
            raise InterAgentValidationError("Orchestrated runs require a hidden child runtime orchestrator.")
        if not _clean_optional(spec.source_runtime_turn_id):
            raise InterAgentValidationError("Orchestrated runs require source_runtime_turn_id.")
        if spec.edges:
            raise InterAgentValidationError("Orchestrated runs must start without static edges.")
    elif orchestrators[0].execution_mode != "root_orchestrator":
        raise InterAgentValidationError("Static inter-agent runs require a root orchestrator participant.")
    if spec.orchestrator_participant_id and spec.orchestrator_participant_id not in set(participant_ids):
        raise InterAgentValidationError("orchestrator_participant_id must reference an existing participant.")
    if spec.mode != "single_agent":
        if spec.budget.max_participants < 2:
            raise InterAgentValidationError("Multi-agent run specs require max_participants >= 2.")
        if spec.budget.max_concurrent_participants < 1:
            raise InterAgentValidationError("Multi-agent run specs require max_concurrent_participants >= 1.")
    if spec.mode == "concurrent":
        if not str(spec.merge_policy or "").strip():
            raise InterAgentValidationError("Concurrent inter-agent run specs require a merge_policy.")
        if not str(spec.aggregator_participant_id or "").strip():
            raise InterAgentValidationError("Concurrent inter-agent run specs require an aggregator_participant_id.")
        if spec.aggregator_participant_id not in set(participant_ids):
            raise InterAgentValidationError("aggregator_participant_id must reference an existing participant.")
    if spec.mode == "group_chat":
        if not str(spec.aggregator_participant_id or "").strip():
            raise InterAgentValidationError("Group chat inter-agent run specs require an aggregator_participant_id.")
        root_orchestrator_id = spec.orchestrator_participant_id or orchestrators[0].participant_id
        if spec.aggregator_participant_id == root_orchestrator_id:
            raise InterAgentValidationError("Group chat aggregator_participant_id must reference a non-orchestrator participant.")
        if spec.aggregator_participant_id not in set(participant_ids):
            raise InterAgentValidationError("aggregator_participant_id must reference an existing participant.")
    _validate_edge_specs(spec.edges, known_participant_ids=set(participant_ids))
    return replace(spec, participants=normalized_participants)


def validate_participant_spec(spec: ParticipantSpec) -> ParticipantSpec:
    """Validate a participant spec and normalize its thread visibility."""
    if spec.kind not in PARTICIPANT_KINDS:
        raise InterAgentValidationError(f"Unsupported participant kind `{spec.kind}`.")
    if spec.execution_mode not in PARTICIPANT_EXECUTION_MODES:
        raise InterAgentValidationError(f"Unsupported participant execution mode `{spec.execution_mode}`.")
    if spec.execution_mode not in PARTICIPANT_EXECUTION_BY_KIND[spec.kind]:
        raise InterAgentValidationError(f"Participant kind `{spec.kind}` cannot use `{spec.execution_mode}`.")
    label = str(spec.label or "").strip()
    if not label:
        raise InterAgentValidationError("Participant specs require a non-empty label.")
    if len(label) > 160:
        raise InterAgentValidationError("Participant labels must be 160 characters or fewer.")
    if spec.execution_mode == "child_runtime_session":
        try:
            _kind, visibility = normalize_runtime_session_visibility(
                "inter_agent_participant",
                spec.thread_visibility,
            )
        except ValueError as exc:
            raise InterAgentValidationError(str(exc)) from exc
    elif spec.execution_mode == "root_orchestrator":
        try:
            _kind, visibility = normalize_runtime_session_visibility("chat_root", spec.thread_visibility)
        except ValueError as exc:
            raise InterAgentValidationError(str(exc)) from exc
        if visibility != "user":
            raise InterAgentValidationError("Root orchestrator participants must use user thread visibility.")
    else:
        visibility = spec.thread_visibility or "hidden"
        if visibility not in {"user", "hidden"}:
            raise InterAgentValidationError(f"Unsupported participant thread visibility `{visibility}`.")
    if spec.agent_snapshot is not None:
        validate_agent_snapshot(spec.agent_snapshot)
    skill_ids = _clean_string_list(spec.skill_ids)
    try:
        invoked_skill_ids = normalize_invoked_skill_ids(spec.invoked_skill_ids)
    except SkillInvocationError as error:
        raise InterAgentValidationError(str(error)) from error
    assigned_skill_ids = spec.agent_snapshot.skill_ids if spec.agent_snapshot is not None else skill_ids
    denied_skill_ids = [
        skill_id
        for skill_id in invoked_skill_ids
        if assigned_skill_ids and skill_id not in assigned_skill_ids
    ]
    if denied_skill_ids:
        raise InterAgentValidationError(
            "Participant skill invocation is outside its assigned allowlist: "
            + ", ".join(denied_skill_ids)
        )
    return replace(
        spec,
        label=label,
        thread_visibility=visibility,
        skill_ids=skill_ids,
        invoked_skill_ids=invoked_skill_ids,
        authority_grant_ids=_clean_string_list(spec.authority_grant_ids),
        agent_type_id=_clean_optional(spec.agent_type_id),
        prompt_snapshot_ref=_clean_optional(spec.prompt_snapshot_ref),
        provider_id=_clean_optional(spec.provider_id),
        participant_id=_clean_optional(spec.participant_id),
    )


def validate_agent_snapshot(snapshot: AgentParticipantSnapshot) -> AgentParticipantSnapshot:
    """Validate a materialized Agents snapshot before storing its digest."""
    _require_non_empty(snapshot.agent_type_id, "agent_snapshot.agent_type_id")
    _require_non_empty(snapshot.label, "agent_snapshot.label")
    _require_non_empty(snapshot.skill_catalog_app_id, "agent_snapshot.skill_catalog_app_id")
    if not all(str(skill_id).strip() for skill_id in snapshot.skill_ids):
        raise InterAgentValidationError("agent_snapshot.skill_ids cannot contain empty values.")
    try:
        coerce_skill_activation_mode(snapshot.skill_activation_mode)
    except ValueError as error:
        raise InterAgentValidationError(str(error)) from error
    snapshot.digest()
    return snapshot


def budget_policy_from_spec(
    spec: BudgetPolicySpec,
    *,
    budget_policy_id: str,
    workspace_id: str,
    created_at: datetime,
) -> BudgetPolicyRecord:
    """Materialize a validated budget policy spec."""
    _validate_budget_policy_spec(spec)
    return BudgetPolicyRecord(
        budget_policy_id=budget_policy_id,
        workspace_id=workspace_id,
        max_participants=spec.max_participants,
        max_concurrent_participants=spec.max_concurrent_participants,
        max_handoffs=spec.max_handoffs,
        max_rounds=spec.max_rounds,
        max_total_turns=spec.max_total_turns,
        max_turns_per_participant=spec.max_turns_per_participant,
        max_tool_calls=spec.max_tool_calls,
        max_estimated_tokens=spec.max_estimated_tokens,
        max_estimated_cost=_to_decimal(spec.max_estimated_cost),
        max_idle_seconds=spec.max_idle_seconds,
        max_stall_seconds=spec.max_stall_seconds,
        approval_required_above_cost=_to_decimal(spec.approval_required_above_cost),
        created_at=created_at,
    )


def empty_budget_ledger(
    *,
    budget_ledger_id: str,
    workspace_id: str,
    run_id: str,
    updated_at: datetime,
) -> BudgetLedgerRecord:
    """Return a new zero-use budget ledger."""
    return BudgetLedgerRecord(
        budget_ledger_id=budget_ledger_id,
        workspace_id=workspace_id,
        run_id=run_id,
        reserved_participants=0,
        running_participants=0,
        turns_used=0,
        tool_calls_used=0,
        handoffs_used=0,
        estimated_tokens_used=0,
        estimated_cost_used=Decimal("0"),
        operation_reservations={},
        updated_at=updated_at,
    )


def budget_reservation_to_document(reservation: BudgetReservation) -> dict[str, Any]:
    """Serialize one budget reservation for storage inside a ledger."""
    return {
        "reservation_id": reservation.reservation_id,
        "participant_id": reservation.participant_id,
        "participant_slots": reservation.participant_slots,
        "running_participants": reservation.running_participants,
        "turns": reservation.turns,
        "tool_calls": reservation.tool_calls,
        "handoffs": reservation.handoffs,
        "estimated_tokens": reservation.estimated_tokens,
        "estimated_cost": reservation.estimated_cost,
        "status": reservation.status,
        "created_at": reservation.created_at,
        "fingerprint": reservation.fingerprint,
        "released_at": reservation.released_at,
    }


def budget_reservation_from_document(document: dict[str, Any]) -> BudgetReservation:
    """Hydrate one budget reservation from a ledger document."""
    return BudgetReservation(
        reservation_id=str(document["reservation_id"]),
        participant_id=_clean_optional(document.get("participant_id")),
        participant_slots=int(document.get("participant_slots") or 0),
        running_participants=int(document.get("running_participants") or 0),
        turns=int(document.get("turns") or 0),
        tool_calls=int(document.get("tool_calls") or 0),
        handoffs=int(document.get("handoffs") or 0),
        estimated_tokens=int(document.get("estimated_tokens") or 0),
        estimated_cost=_to_decimal(document.get("estimated_cost") or 0),
        status=str(document.get("status") or "reserved"),  # type: ignore[arg-type]
        created_at=document["created_at"],
        fingerprint=document.get("fingerprint"),
        released_at=document.get("released_at"),
    )


def _validate_edge_specs(specs: list[EdgeSpec], *, known_participant_ids: set[str]) -> None:
    for edge in specs:
        if edge.kind not in EDGE_KINDS:
            raise InterAgentValidationError(f"Unsupported inter-agent edge kind `{edge.kind}`.")
        if edge.source_id not in known_participant_ids:
            raise InterAgentValidationError("Inter-agent edges must reference an existing source participant.")
        if edge.target_id not in known_participant_ids:
            raise InterAgentValidationError("Inter-agent edges must reference an existing target participant.")


def _validate_budget_policy_spec(spec: BudgetPolicySpec) -> None:
    positive_fields = {
        "max_participants": spec.max_participants,
        "max_concurrent_participants": spec.max_concurrent_participants,
        "max_rounds": spec.max_rounds,
        "max_total_turns": spec.max_total_turns,
        "max_turns_per_participant": spec.max_turns_per_participant,
        "max_idle_seconds": spec.max_idle_seconds,
        "max_stall_seconds": spec.max_stall_seconds,
    }
    for field_name, value in positive_fields.items():
        if int(value) < 1:
            raise InterAgentValidationError(f"Budget policy `{field_name}` must be positive.")
    non_negative_fields = {
        "max_handoffs": spec.max_handoffs,
        "max_tool_calls": spec.max_tool_calls,
        "max_estimated_tokens": spec.max_estimated_tokens,
    }
    for field_name, value in non_negative_fields.items():
        if int(value) < 0:
            raise InterAgentValidationError(f"Budget policy `{field_name}` cannot be negative.")
    if _to_decimal(spec.max_estimated_cost) < 0:
        raise InterAgentValidationError("Budget policy `max_estimated_cost` cannot be negative.")
    if _to_decimal(spec.approval_required_above_cost) < 0:
        raise InterAgentValidationError("Budget policy `approval_required_above_cost` cannot be negative.")
    if spec.max_concurrent_participants > spec.max_participants:
        raise InterAgentValidationError("max_concurrent_participants cannot exceed max_participants.")


def _require_non_empty(value: str | None, field_name: str) -> None:
    if not str(value or "").strip():
        raise InterAgentValidationError(f"`{field_name}` is required.")


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _clean_string_list(values: list[str]) -> list[str]:
    return [cleaned for value in values if (cleaned := str(value).strip())]


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
