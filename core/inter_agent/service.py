"""Inter-agent service facade for schema-only F1 operations."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
import uuid

from core.inter_agent.events import (
    EventRetentionPolicyRecord,
    InterAgentEventRecord,
    InterAgentEventType,
    InterAgentVisibilityPlane,
)
from core.inter_agent.models import (
    ApprovalRequestRecord,
    EdgeSpec,
    InterAgentEdgeRecord,
    InterAgentParticipantRecord,
    InterAgentRunRecord,
    InterAgentRunSpec,
    ParticipantSpec,
    budget_policy_from_spec,
    empty_budget_ledger,
    validate_run_spec,
)
from core.inter_agent.store import InterAgentRunCreateBundle, InterAgentStore


DEFAULT_SUMMARY_EVENT_LIMIT = 1000
DEFAULT_DETAIL_EVENT_LIMIT = 500
DEFAULT_DEBUG_EVENT_LIMIT = 100


class InterAgentService:
    """Coordinate inter-agent records without spawning runtimes or LLM work."""

    def __init__(self, store: InterAgentStore) -> None:
        self.store = store

    def create_run(self, spec: InterAgentRunSpec, *, now: datetime | None = None) -> InterAgentRunRecord:
        """Create a schema-only run and its participant records idempotently."""
        requested_at = now or datetime.now(tz=UTC)
        validated = validate_run_spec(spec)
        idempotency_key = _clean_optional(validated.idempotency_key)
        spec_fingerprint = _run_spec_fingerprint(validated)
        run_id = _materialized_run_id(validated, idempotency_key=idempotency_key)
        participant_ids = _materialized_participant_ids(validated.participants, run_id=run_id)
        orchestrator_participant_id = (
            _clean_optional(validated.orchestrator_participant_id)
            or _first_root_orchestrator_id(validated.participants, participant_ids)
        )
        budget_policy_id = _stable_id("iabp", run_id, "budget_policy")
        budget_ledger_id = _stable_id("iabl", run_id, "budget_ledger")
        retention_policy_id = _stable_id("iarp", run_id, "retention_policy")
        budget_policy = budget_policy_from_spec(
            validated.budget,
            budget_policy_id=budget_policy_id,
            workspace_id=validated.workspace_id,
            created_at=requested_at,
        )
        retention_policy = default_event_retention_policy(
            retention_policy_id=retention_policy_id,
            workspace_id=validated.workspace_id,
            created_at=requested_at,
        )
        run = InterAgentRunRecord(
            run_id=run_id,
            workspace_id=validated.workspace_id,
            thread_id=validated.thread_id,
            root_runtime_session_id=validated.root_runtime_session_id,
            source_app_id=validated.source_app_id,
            mode=validated.mode,
            status="created",
            created_by_user_id=validated.created_by_user_id,
            orchestrator_participant_id=orchestrator_participant_id,
            budget_policy_id=budget_policy_id,
            budget_ledger_id=budget_ledger_id,
            visibility_level=validated.visibility_level,
            retention_policy_id=retention_policy_id,
            created_at=requested_at,
            updated_at=requested_at,
            ended_at=None,
            recovery_generation=0,
            idempotency_key=idempotency_key,
            spec_fingerprint=spec_fingerprint,
        )
        budget_ledger = empty_budget_ledger(
            budget_ledger_id=budget_ledger_id,
            workspace_id=validated.workspace_id,
            run_id=run_id,
            updated_at=requested_at,
        )
        participants = _participant_records_from_specs(
            validated.participants,
            participant_ids=participant_ids,
            run=run,
            created_at=requested_at,
        )
        edges = _edge_records_from_specs(validated.edges, run=run, created_at=requested_at)
        initial_events = [
            _event_record(
                run,
                event_type="inter_agent.run.started",
                participant_id=orchestrator_participant_id,
                visibility_plane="summary",
                idempotency_key=f"{run.run_id}:run.started",
                correlation_id=run.run_id,
                payload={"mode": run.mode, "status": run.status},
                created_at=requested_at,
            ),
            _event_record(
                run,
                event_type="inter_agent.mode.selected",
                participant_id=orchestrator_participant_id,
                visibility_plane="summary",
                idempotency_key=f"{run.run_id}:mode.selected",
                correlation_id=run.run_id,
                payload={"mode": run.mode},
                created_at=requested_at,
            ),
        ]
        for participant in participants:
            initial_events.append(
                _event_record(
                    run,
                    event_type="inter_agent.participant.added",
                    participant_id=participant.participant_id,
                    visibility_plane="detail",
                    idempotency_key=f"{run.run_id}:participant.added:{participant.participant_id}",
                    correlation_id=run.run_id,
                    payload={
                        "participant_id": participant.participant_id,
                        "kind": participant.kind,
                        "label": participant.label,
                    },
                    created_at=requested_at,
                )
            )
        return self.store.create_run(
            InterAgentRunCreateBundle(
                run=run,
                budget_policy=budget_policy,
                budget_ledger=budget_ledger,
                retention_policy=retention_policy,
                participants=participants,
                edges=edges,
                initial_events=initial_events,
            )
        )

    def record_event(
        self,
        run: InterAgentRunRecord,
        *,
        event_type: InterAgentEventType,
        participant_id: str | None = None,
        visibility_plane: InterAgentVisibilityPlane = "summary",
        payload: dict[str, Any] | None = None,
        runtime_session_id: str | None = None,
        runtime_turn_id: str | None = None,
        runtime_event_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> InterAgentEventRecord:
        """Append one normalized event with per-run sequence assignment."""
        created_at = now or datetime.now(tz=UTC)
        retention_policy = self.store.get_retention_policy(run.retention_policy_id, workspace_id=run.workspace_id)
        event = _event_record(
            run,
            event_type=event_type,
            visibility_plane=visibility_plane,
            participant_id=participant_id,
            runtime_session_id=runtime_session_id,
            runtime_turn_id=runtime_turn_id,
            runtime_event_id=runtime_event_id,
            correlation_id=_clean_optional(correlation_id) or _clean_optional(idempotency_key) or run.run_id,
            idempotency_key=_clean_optional(idempotency_key),
            payload=payload,
            created_at=created_at,
        )
        return self.store.append_event(event, retention_policy=retention_policy)

    def reserve_budget(
        self,
        run: InterAgentRunRecord,
        *,
        reservation_id: str,
        participant_slots: int = 0,
        running_participants: int = 0,
        turns: int = 0,
        tool_calls: int = 0,
        handoffs: int = 0,
        estimated_tokens: int = 0,
        estimated_cost: Decimal | int | str = Decimal("0"),
        now: datetime | None = None,
    ):
        """Reserve budget for future executor work without starting that work."""
        reserved_at = now or datetime.now(tz=UTC)
        ledger = self.store.reserve_budget(
            workspace_id=run.workspace_id,
            budget_ledger_id=run.budget_ledger_id,
            budget_policy_id=run.budget_policy_id,
            reservation_id=reservation_id,
            participant_slots=participant_slots,
            running_participants=running_participants,
            turns=turns,
            tool_calls=tool_calls,
            handoffs=handoffs,
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
            now=reserved_at,
        )
        self.record_event(
            run,
            event_type="inter_agent.budget.reserved",
            visibility_plane="detail",
            idempotency_key=f"{run.run_id}:budget.reserved:{reservation_id}",
            correlation_id=reservation_id,
            payload={
                "reservation_id": reservation_id,
                "participant_slots": participant_slots,
                "running_participants": running_participants,
                "turns": turns,
                "tool_calls": tool_calls,
                "handoffs": handoffs,
                "estimated_tokens": estimated_tokens,
                "estimated_cost": str(estimated_cost),
            },
            now=reserved_at,
        )
        return ledger

    def release_budget(
        self,
        run: InterAgentRunRecord,
        *,
        reservation_id: str,
        now: datetime | None = None,
    ):
        """Release a reservation idempotently after failure, cancellation, or completion."""
        released_at = now or datetime.now(tz=UTC)
        ledger = self.store.release_budget(
            workspace_id=run.workspace_id,
            budget_ledger_id=run.budget_ledger_id,
            reservation_id=reservation_id,
            now=released_at,
        )
        self.record_event(
            run,
            event_type="inter_agent.budget.released",
            visibility_plane="detail",
            idempotency_key=f"{run.run_id}:budget.released:{reservation_id}",
            correlation_id=reservation_id,
            payload={"reservation_id": reservation_id},
            now=released_at,
        )
        return ledger

    def expire_pending_approvals(self, run: InterAgentRunRecord, *, now: datetime | None = None) -> list[ApprovalRequestRecord]:
        """Fail closed for pending approvals whose timeout has passed."""
        checked_at = now or datetime.now(tz=UTC)
        expired: list[ApprovalRequestRecord] = []
        for approval in self.store.list_approvals(run.run_id, workspace_id=run.workspace_id):
            if approval.status != "pending" or approval.expires_at > checked_at:
                continue
            updated = replace(
                approval,
                status="expired",
                resolved_at=checked_at,
                resolution_reason="approval_timeout",
            )
            self.store.save_approval(updated)
            expired.append(updated)
            self.record_event(
                run,
                event_type="inter_agent.approval.resolved",
                participant_id=approval.participant_id,
                visibility_plane="summary",
                idempotency_key=f"{run.run_id}:approval.expired:{approval.approval_id}",
                correlation_id=approval.approval_id,
                payload={"approval_id": approval.approval_id, "status": "expired"},
                now=checked_at,
            )
        return expired


def default_event_retention_policy(
    *,
    retention_policy_id: str,
    workspace_id: str,
    created_at: datetime,
) -> EventRetentionPolicyRecord:
    """Return the initial inter-agent event retention policy."""
    return EventRetentionPolicyRecord(
        retention_policy_id=retention_policy_id,
        workspace_id=workspace_id,
        summary_max_events=DEFAULT_SUMMARY_EVENT_LIMIT,
        detail_max_events=DEFAULT_DETAIL_EVENT_LIMIT,
        debug_max_events=DEFAULT_DEBUG_EVENT_LIMIT,
        created_at=created_at,
    )


def _event_record(
    run: InterAgentRunRecord,
    *,
    event_type: InterAgentEventType,
    visibility_plane: InterAgentVisibilityPlane,
    participant_id: str | None = None,
    payload: dict[str, Any] | None = None,
    runtime_session_id: str | None = None,
    runtime_turn_id: str | None = None,
    runtime_event_id: str | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    created_at: datetime,
) -> InterAgentEventRecord:
    return InterAgentEventRecord(
        event_id=_new_id("iaevt"),
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        thread_id=run.thread_id,
        root_runtime_session_id=run.root_runtime_session_id,
        participant_id=_clean_optional(participant_id),
        runtime_session_id=_clean_optional(runtime_session_id),
        runtime_turn_id=_clean_optional(runtime_turn_id),
        runtime_event_id=_clean_optional(runtime_event_id),
        event_type=event_type,
        visibility_plane=visibility_plane,
        sequence=0,
        correlation_id=_clean_optional(correlation_id) or _clean_optional(idempotency_key) or run.run_id,
        idempotency_key=_clean_optional(idempotency_key),
        payload=dict(payload or {}),
        created_at=created_at,
    )


def _participant_records_from_specs(
    specs: list[ParticipantSpec],
    *,
    participant_ids: dict[int, str],
    run: InterAgentRunRecord,
    created_at: datetime,
) -> list[InterAgentParticipantRecord]:
    records: list[InterAgentParticipantRecord] = []
    for index, spec in enumerate(specs):
        snapshot_digest = spec.agent_snapshot.digest() if spec.agent_snapshot is not None else None
        snapshot_document = _agent_snapshot_document(spec)
        skill_ids = list(spec.skill_ids)
        provider_id = spec.provider_id
        agent_type_id = spec.agent_type_id
        if spec.agent_snapshot is not None:
            skill_ids = list(spec.agent_snapshot.skill_ids)
            provider_id = spec.agent_snapshot.provider_id or provider_id
            agent_type_id = spec.agent_snapshot.agent_type_id
        records.append(
            InterAgentParticipantRecord(
                participant_id=participant_ids[index],
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                kind=spec.kind,
                execution_mode=spec.execution_mode,
                agent_type_id=agent_type_id,
                agent_snapshot_digest=snapshot_digest,
                agent_snapshot=snapshot_document,
                prompt_snapshot_ref=spec.prompt_snapshot_ref,
                label=spec.label,
                runtime_session_id=None,
                status="idle",
                current_task_id=None,
                skill_ids=skill_ids,
                provider_id=provider_id,
                authority_grant_ids=list(spec.authority_grant_ids),
                thread_visibility=spec.thread_visibility or "hidden",
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return records


def _edge_records_from_specs(
    specs: list[EdgeSpec],
    *,
    run: InterAgentRunRecord,
    created_at: datetime,
) -> list[InterAgentEdgeRecord]:
    return [
        InterAgentEdgeRecord(
            edge_id=_stable_id(
                "iaedge",
                run.run_id,
                index,
                spec.source_id,
                spec.target_id,
                spec.kind,
                spec.label.strip(),
            ),
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            source_id=spec.source_id,
            target_id=spec.target_id,
            kind=spec.kind,
            label=spec.label.strip(),
            status="created",
            created_at=created_at,
        )
        for index, spec in enumerate(specs)
    ]


def _materialized_run_id(spec: InterAgentRunSpec, *, idempotency_key: str | None) -> str:
    explicit_run_id = _clean_optional(spec.run_id)
    if explicit_run_id:
        return explicit_run_id
    if idempotency_key:
        return _stable_id("iarun", spec.workspace_id, idempotency_key)
    return _new_id("iarun")


def _materialized_participant_ids(specs: list[ParticipantSpec], *, run_id: str) -> dict[int, str]:
    return {
        index: _clean_optional(spec.participant_id)
        or _stable_id("iap", run_id, index, spec.kind, spec.execution_mode, spec.label)
        for index, spec in enumerate(specs)
    }


def _agent_snapshot_document(spec: ParticipantSpec) -> dict[str, Any] | None:
    if spec.agent_snapshot is None:
        return None
    document = asdict(spec.agent_snapshot)
    document["digest"] = spec.agent_snapshot.digest()
    return document


def _run_spec_fingerprint(spec: InterAgentRunSpec) -> str:
    payload = {
        "workspace_id": spec.workspace_id,
        "thread_id": spec.thread_id,
        "root_runtime_session_id": spec.root_runtime_session_id,
        "source_app_id": spec.source_app_id,
        "mode": spec.mode,
        "created_by_user_id": spec.created_by_user_id,
        "participants": [_participant_spec_fingerprint_payload(participant) for participant in spec.participants],
        "budget": asdict(spec.budget),
        "edges": [asdict(edge) for edge in spec.edges],
        "run_id": spec.run_id,
        "orchestrator_participant_id": spec.orchestrator_participant_id,
        "aggregator_participant_id": spec.aggregator_participant_id,
        "merge_policy": spec.merge_policy,
        "visibility_level": spec.visibility_level,
    }
    encoded = json.dumps(_canonical_fingerprint_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _participant_spec_fingerprint_payload(spec: ParticipantSpec) -> dict[str, Any]:
    return {
        "kind": spec.kind,
        "execution_mode": spec.execution_mode,
        "label": spec.label,
        "participant_id": spec.participant_id,
        "agent_type_id": spec.agent_type_id,
        "agent_snapshot_digest": spec.agent_snapshot.digest() if spec.agent_snapshot is not None else None,
        "prompt_snapshot_ref": spec.prompt_snapshot_ref,
        "skill_ids": sorted(spec.skill_ids),
        "provider_id": spec.provider_id,
        "authority_grant_ids": sorted(spec.authority_grant_ids),
        "thread_visibility": spec.thread_visibility,
    }


def _canonical_fingerprint_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_canonical_fingerprint_value(item) for item in value]
    return value


def _first_root_orchestrator_id(specs: list[ParticipantSpec], participant_ids: dict[int, str]) -> str:
    for index, spec in enumerate(specs):
        if spec.kind == "orchestrator" and spec.execution_mode == "root_orchestrator":
            return participant_ids[index]
    raise ValueError("validated run spec did not include a root orchestrator")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = json.dumps(_canonical_fingerprint_value(list(parts)), sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
