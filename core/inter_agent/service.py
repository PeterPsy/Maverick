"""Inter-agent service facade for schema-only F1 operations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.events import (
    EventRetentionPolicyRecord,
    InterAgentEventRecord,
    InterAgentEventType,
    InterAgentVisibilityPlane,
)
from core.inter_agent.models import (
    EDGE_KINDS,
    ApprovalRequestRecord,
    EdgeSpec,
    InterAgentEdgeRecord,
    InterAgentParticipantRecord,
    InterAgentRunRecord,
    InterAgentRunSpec,
    ParticipantSpec,
    budget_policy_from_spec,
    empty_budget_ledger,
    validate_participant_spec,
    validate_run_spec,
)
from core.inter_agent.store import InterAgentRunCreateBundle, InterAgentStore
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.lifecycle_service_sessions import create_child_runtime_session
from core.runtime.runtime_session import RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.runtime_threads import runtime_thread_availability_for_session, update_runtime_thread_availability
from core.runtime.store import RuntimeStore
from core.runtime.service import (
    record_runtime_event,
    request_runtime_turn_cancellation,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.turn_submission import (
    interrupt_runtime_provider_turn,
    release_idle_runtime_processes,
    submit_runtime_turn,
    submit_runtime_turn_async,
)
from core.runtime.turn_terminalization import terminalize_runtime_turn_cancellation
DEFAULT_SUMMARY_EVENT_LIMIT = 1000
DEFAULT_DETAIL_EVENT_LIMIT = 500
DEFAULT_DEBUG_EVENT_LIMIT = 100
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_PARTICIPANT_STATUSES = {"completed", "failed", "cancelled"}
RUNTIME_CHILD_EXECUTION_MODE = "child_runtime_session"
DEFAULT_WAIT_TIMEOUT_SECONDS = 0.0
MAX_WAIT_TIMEOUT_SECONDS = 30.0


class InterAgentService:
    """Coordinate inter-agent records and F2 runtime operations."""

    def __init__(self, store: InterAgentStore, *, workspace_store=None) -> None:
        self.workspace_store = workspace_store
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
            aggregator_participant_id=_clean_optional(validated.aggregator_participant_id),
            merge_policy=_clean_optional(validated.merge_policy),
            source_runtime_turn_id=_clean_optional(validated.source_runtime_turn_id),
            orchestration_policy=_clean_optional(validated.orchestration_policy),
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

    def add_participant(
        self,
        *,
        workspace_id: str,
        run_id: str,
        spec: ParticipantSpec,
        now: datetime | None = None,
    ) -> InterAgentParticipantRecord:
        """Persist one core-authorized dynamic worker before it can be scheduled."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.mode != "orchestrated":
            raise InterAgentOperationError("Dynamic participants are available only for orchestrated runs.")
        if run.status == "paused" or run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError(f"Orchestrated runs cannot add participants while {run.status}.")
        validated = validate_participant_spec(spec)
        participant_id = _clean_optional(validated.participant_id)
        if not participant_id:
            raise InterAgentValidationError("Dynamic participants require participant_id.")
        if validated.kind == "orchestrator":
            raise InterAgentValidationError("An orchestrated run cannot add another orchestrator.")
        existing_participants = self.store.list_participants(run.run_id, workspace_id=workspace_id)
        existing = next((item for item in existing_participants if item.participant_id == participant_id), None)
        if existing is not None:
            if (
                existing.kind == validated.kind
                and existing.execution_mode == validated.execution_mode
                and existing.label == validated.label
                and existing.agent_type_id == validated.agent_type_id
            ):
                return existing
            raise InterAgentValidationError(f"Dynamic participant `{participant_id}` already exists with different material.")
        policy = self.store.get_budget_policy(run.budget_policy_id, workspace_id=workspace_id)
        if len(existing_participants) >= policy.max_participants:
            raise InterAgentValidationError("Dynamic participant would exceed max_participants.")
        record = _participant_records_from_specs(
            [validated],
            participant_ids={0: participant_id},
            run=run,
            created_at=timestamp,
        )[0]
        next_sequence = max((item.sequence_index for item in existing_participants), default=-1) + 1
        record = replace(record, sequence_index=next_sequence)
        self.store.save_participant(record)
        self.record_event(
            run,
            event_type="inter_agent.participant.added",
            participant_id=record.participant_id,
            visibility_plane="detail",
            correlation_id=f"{run.run_id}:participant:{record.participant_id}",
            idempotency_key=f"{run.run_id}:dynamic.participant:{record.participant_id}",
            payload={
                "participant_id": record.participant_id,
                "kind": record.kind,
                "label": record.label,
                "dynamic": True,
            },
            now=timestamp,
        )
        return record

    def add_edge(
        self,
        *,
        workspace_id: str,
        run_id: str,
        spec: EdgeSpec,
        now: datetime | None = None,
    ) -> InterAgentEdgeRecord:
        """Persist one dynamic dependency edge after both endpoints exist."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.mode != "orchestrated":
            raise InterAgentOperationError("Dynamic edges are available only for orchestrated runs.")
        if run.status == "paused" or run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError(f"Orchestrated runs cannot add edges while {run.status}.")
        source_id = str(spec.source_id or "").strip()
        target_id = str(spec.target_id or "").strip()
        label = str(spec.label or "").strip()
        if spec.kind not in EDGE_KINDS:
            raise InterAgentValidationError(f"Unsupported inter-agent edge kind `{spec.kind}`.")
        participant_ids = {
            item.participant_id for item in self.store.list_participants(run.run_id, workspace_id=workspace_id)
        }
        if source_id not in participant_ids or target_id not in participant_ids:
            raise InterAgentValidationError("Dynamic edges must reference existing run participants.")
        edge_id = _stable_id("iaedge", run.run_id, source_id, target_id, spec.kind, label)
        existing = next(
            (item for item in self.store.list_edges(run.run_id, workspace_id=workspace_id) if item.edge_id == edge_id),
            None,
        )
        if existing is not None:
            return existing
        record = InterAgentEdgeRecord(
            edge_id=edge_id,
            workspace_id=workspace_id,
            run_id=run.run_id,
            source_id=source_id,
            target_id=target_id,
            kind=spec.kind,
            label=label,
            status="created",
            created_at=timestamp,
        )
        self.store.save_edge(record)
        self.record_event(
            run,
            event_type="inter_agent.graph.edge_added",
            participant_id=run.orchestrator_participant_id,
            visibility_plane="detail",
            correlation_id=edge_id,
            idempotency_key=f"{run.run_id}:dynamic.edge:{edge_id}",
            payload={
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "kind": spec.kind,
                "label": label,
            },
            now=timestamp,
        )
        return record

    def record_directive(
        self,
        *,
        workspace_id: str,
        run_id: str,
        text: str,
        source_kind: str,
        source_runtime_event_id: str | None = None,
        source_runtime_turn_id: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> InterAgentEventRecord:
        """Append bounded live steering for later orchestrator delivery."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.mode != "orchestrated":
            raise InterAgentOperationError("Directives are available only for orchestrated runs.")
        if run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError("Terminal orchestrated runs do not accept directives.")
        if source_kind not in {"root_generalist", "user"}:
            raise InterAgentValidationError("Directive source_kind must be root_generalist or user.")
        directive_text = str(text or "").strip()
        if not directive_text:
            raise InterAgentValidationError("Directives require non-empty text.")
        if len(directive_text) > 6000:
            raise InterAgentValidationError("Directives must be 6000 characters or fewer.")
        turn_id = _clean_optional(source_runtime_turn_id)
        if source_kind == "root_generalist" and not turn_id:
            raise InterAgentValidationError("Generalist directives require a linked runtime turn.")
        directive_id = _stable_id(
            "iadirective",
            run.run_id,
            source_kind,
            _clean_optional(source_runtime_event_id) or turn_id or idempotency_key or directive_text,
        )
        return self.record_event(
            run,
            event_type="inter_agent.directive.received",
            participant_id=run.orchestrator_participant_id,
            runtime_turn_id=turn_id,
            runtime_event_id=_clean_optional(source_runtime_event_id),
            visibility_plane="detail",
            correlation_id=directive_id,
            idempotency_key=_clean_optional(idempotency_key) or f"{run.run_id}:directive:{directive_id}",
            payload={
                "directive_id": directive_id,
                "source_kind": source_kind,
                "text": directive_text,
            },
            now=timestamp,
            expected_recovery_generation=expected_recovery_generation,
        )

    def link_generalist_directive(
        self,
        *,
        workspace_id: str,
        run_id: str,
        source_runtime_turn_id: str,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> InterAgentEventRecord:
        """Link a later root generalist turn for delivery at a scheduler safe point."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.mode != "orchestrated" or run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError("Only active orchestrated runs accept generalist steering.")
        turn_id = _clean_optional(source_runtime_turn_id)
        if not turn_id:
            raise InterAgentValidationError("Generalist steering requires a runtime turn id.")
        link_id = _stable_id("ialink", run.run_id, turn_id)
        return self.record_event(
            run,
            event_type="inter_agent.generalist.directive_linked",
            participant_id=run.orchestrator_participant_id,
            runtime_turn_id=turn_id,
            visibility_plane="detail",
            correlation_id=link_id,
            idempotency_key=_clean_optional(idempotency_key) or f"{run.run_id}:generalist.link:{turn_id}",
            payload={"link_id": link_id, "source_runtime_turn_id": turn_id},
            now=timestamp,
        )

    def pending_generalist_directive_links(self, run: InterAgentRunRecord) -> list[InterAgentEventRecord]:
        events = self.store.list_recovery_events(
            run.run_id,
            workspace_id=run.workspace_id,
            event_types={
                "inter_agent.generalist.directive_linked",
                "inter_agent.generalist.directive_resolved",
            },
        )
        resolved = {
            str(event.payload.get("link_id") or "")
            for event in events
            if event.event_type == "inter_agent.generalist.directive_resolved"
        }
        return [
            event
            for event in events
            if event.event_type == "inter_agent.generalist.directive_linked"
            and str(event.payload.get("link_id") or "") not in resolved
        ]

    def resolve_generalist_directive_link(
        self,
        run: InterAgentRunRecord,
        link: InterAgentEventRecord,
        *,
        status: str,
        directive_id: str | None = None,
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> InterAgentEventRecord:
        link_id = str(link.payload.get("link_id") or "").strip()
        if status not in {"delivered", "ignored"} or not link_id:
            raise InterAgentValidationError("Generalist directive link resolution is invalid.")
        return self.record_event(
            run,
            event_type="inter_agent.generalist.directive_resolved",
            participant_id=run.orchestrator_participant_id,
            runtime_turn_id=link.runtime_turn_id,
            visibility_plane="detail",
            correlation_id=link_id,
            idempotency_key=f"{run.run_id}:generalist.link.resolved:{link_id}",
            payload={"link_id": link_id, "status": status, "directive_id": directive_id},
            now=now,
            expected_recovery_generation=expected_recovery_generation,
        )

    def pending_directives(self, run: InterAgentRunRecord) -> list[InterAgentEventRecord]:
        """Return received directive events not yet delivered to the orchestrator."""
        events = self.store.list_recovery_events(
            run.run_id,
            workspace_id=run.workspace_id,
            event_types={"inter_agent.directive.received", "inter_agent.directive.delivered"},
        )
        delivered = {
            str(event.payload.get("directive_id") or "")
            for event in events
            if event.event_type == "inter_agent.directive.delivered"
        }
        return [
            event
            for event in events
            if event.event_type == "inter_agent.directive.received"
            and str(event.payload.get("directive_id") or "") not in delivered
        ]

    def mark_directives_delivered(
        self,
        run: InterAgentRunRecord,
        directives: list[InterAgentEventRecord],
        *,
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> None:
        """Record directive delivery after it is included in an orchestrator turn."""
        timestamp = now or datetime.now(tz=UTC)
        for directive in directives:
            directive_id = str(directive.payload.get("directive_id") or "").strip()
            if not directive_id:
                continue
            self.record_event(
                run,
                event_type="inter_agent.directive.delivered",
                participant_id=run.orchestrator_participant_id,
                visibility_plane="detail",
                correlation_id=directive_id,
                idempotency_key=f"{run.run_id}:directive.delivered:{directive_id}",
                payload={"directive_id": directive_id},
                now=timestamp,
                expected_recovery_generation=expected_recovery_generation,
            )

    def decide_completion(
        self,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        complete: bool,
        quality_passed: bool,
        summary: str,
        final_answer: str = "",
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> InterAgentRunRecord:
        """Apply the only valid completion gate for a dynamic orchestration."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.mode != "orchestrated":
            raise InterAgentOperationError("Completion decisions apply only to orchestrated runs.")
        if participant_id != run.orchestrator_participant_id:
            raise InterAgentOperationError("Only the orchestrator may decide run completion.")
        if run.status == "completed" and complete:
            return run
        if run.status == "paused" or run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError(f"Inter-agent run is {run.status}; completion is not allowed.")
        if complete and not quality_passed:
            raise InterAgentValidationError("Completion requires a passing quality decision.")
        answer = str(final_answer or "").strip()
        if complete and not answer:
            raise InterAgentValidationError("Completed orchestrations require a final answer.")
        decision_summary = str(summary or "").strip() or ("Quality accepted." if quality_passed else "Revision required.")
        summary_digest = hashlib.sha256(decision_summary.encode()).hexdigest()[:16]
        answer_digest = hashlib.sha256(answer.encode()).hexdigest()[:16]
        scheduler_generation = (
            run.recovery_generation
            if expected_recovery_generation is None
            else expected_recovery_generation
        )
        self.record_event(
            run,
            event_type="inter_agent.quality.assessed",
            participant_id=participant_id,
            visibility_plane="summary",
            correlation_id=f"{run.run_id}:quality",
            idempotency_key=f"{run.run_id}:quality:{int(complete)}:{summary_digest}",
            payload={"passed": quality_passed, "summary": decision_summary},
            now=timestamp,
            expected_recovery_generation=scheduler_generation,
        )
        self.record_event(
            run,
            event_type="inter_agent.completion.decided",
            participant_id=participant_id,
            visibility_plane="summary",
            correlation_id=f"{run.run_id}:completion",
            idempotency_key=f"{run.run_id}:completion:{int(complete)}:{answer_digest}",
            payload={
                "complete": complete,
                "quality_passed": quality_passed,
                "summary": decision_summary,
                "final_answer": answer if complete else "",
            },
            now=timestamp,
            expected_recovery_generation=scheduler_generation,
        )
        if not complete:
            with self.store.scheduler_mutation(
                workspace_id=workspace_id,
                run_id=run.run_id,
                expected_recovery_generation=scheduler_generation,
            ) as current_run:
                updated = replace(current_run, status="running", updated_at=timestamp)
                self.store.save_run(updated)
                return updated
        with self.store.scheduler_mutation(
            workspace_id=workspace_id,
            run_id=run.run_id,
            expected_recovery_generation=scheduler_generation,
        ) as current_run:
            orchestrator = self.store.get_participant(
                participant_id,
                workspace_id=workspace_id,
                run_id=current_run.run_id,
            )
            if orchestrator.status == "cancelled":
                raise InterAgentOperationError("Cancelled orchestrators cannot complete an inter-agent run.")
            self.store.save_participant(replace(orchestrator, status="completed", updated_at=timestamp))
            completed = replace(current_run, status="completed", updated_at=timestamp, ended_at=timestamp)
            self.store.save_run(completed)
        self.record_event(
            completed,
            event_type="inter_agent.run.completed",
            participant_id=participant_id,
            visibility_plane="summary",
            correlation_id=completed.run_id,
            idempotency_key=f"{completed.run_id}:orchestrator.completed",
            payload={"status": "completed", "summary": decision_summary, "final_answer": answer},
            now=timestamp,
        )
        return completed

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
        expected_recovery_generation: int | None = None,
        scheduler_statuses: set[str] | None = None,
    ) -> InterAgentEventRecord:
        """Append one normalized event with per-run sequence assignment."""
        def append(current_run: InterAgentRunRecord) -> InterAgentEventRecord:
            created_at = now or datetime.now(tz=UTC)
            retention_policy = self.store.get_retention_policy(
                current_run.retention_policy_id,
                workspace_id=current_run.workspace_id,
            )
            event = _event_record(
                current_run,
                event_type=event_type,
                visibility_plane=visibility_plane,
                participant_id=participant_id,
                runtime_session_id=runtime_session_id,
                runtime_turn_id=runtime_turn_id,
                runtime_event_id=runtime_event_id,
                correlation_id=(
                    _clean_optional(correlation_id)
                    or _clean_optional(idempotency_key)
                    or current_run.run_id
                ),
                idempotency_key=_clean_optional(idempotency_key),
                payload=payload,
                created_at=created_at,
            )
            return self.store.append_event(event, retention_policy=retention_policy)

        if expected_recovery_generation is None:
            return append(run)
        with self.store.scheduler_mutation(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            expected_recovery_generation=expected_recovery_generation,
            allowed_statuses=scheduler_statuses,
        ) as current_run:
            return append(current_run)

    def mark_run_planning(
        self,
        *,
        workspace_id: str,
        run_id: str,
        now: datetime | None = None,
    ) -> InterAgentRunRecord:
        """Persist a recoverable planning state before asynchronous execution is scheduled."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.status != "created":
            return run
        if run.mode != "orchestrated":
            updated = replace(run, status="planning", updated_at=timestamp)
            self.store.save_run(updated)
            return updated
        try:
            with self.store.scheduler_mutation(
                workspace_id=workspace_id,
                run_id=run_id,
                expected_recovery_generation=run.recovery_generation,
                allowed_statuses={"created"},
            ) as current_run:
                updated = replace(current_run, status="planning", updated_at=timestamp)
                self.store.save_run(updated)
                return updated
        except InterAgentOperationError:
            return self.store.get_run(run_id, workspace_id=workspace_id)

    def reserve_budget(
        self,
        run: InterAgentRunRecord,
        *,
        reservation_id: str,
        participant_id: str | None = None,
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
            participant_id=_clean_optional(participant_id),
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
                "participant_id": _clean_optional(participant_id),
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

    def resolve_approval(
        self,
        *,
        workspace_id: str,
        approval_id: str,
        approved: bool,
        resolved_by_user_id: str,
        resolved_by_role_ids: list[str] | None = None,
        resolution_reason: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalRequestRecord:
        """Resolve one pending approval and emit the user-visible audit event."""
        resolved_at = now or datetime.now(tz=UTC)
        approval = self.store.get_approval(approval_id, workspace_id=workspace_id)
        run = self.store.get_run(approval.run_id, workspace_id=workspace_id)
        if approval.status != "pending":
            raise InterAgentOperationError("approval_not_pending")
        if not _approval_resolver_is_eligible(
            approval,
            user_id=resolved_by_user_id,
            role_ids=resolved_by_role_ids,
        ):
            raise InterAgentOperationError("approval_resolver_forbidden")
        if approval.expires_at <= resolved_at:
            self.expire_pending_approvals(run, now=resolved_at)
            raise InterAgentOperationError("approval_expired")
        status = "approved" if approved else "rejected"
        updated = replace(
            approval,
            status=status,
            resolved_by_user_id=_clean_optional(resolved_by_user_id),
            resolved_at=resolved_at,
            resolution_reason=_clean_optional(resolution_reason) or status,
        )
        self.store.save_approval(updated)
        self.record_event(
            run,
            event_type="inter_agent.approval.resolved",
            participant_id=approval.participant_id,
            visibility_plane="summary",
            idempotency_key=f"{run.run_id}:approval.resolved:{approval.approval_id}:{status}",
            correlation_id=approval.approval_id,
            payload={
                "approval_id": approval.approval_id,
                "participant_id": approval.participant_id,
                "operation_kind": approval.operation_kind,
                "status": status,
                "summary": approval.summary,
                "risk_level": approval.risk_level,
            },
            now=resolved_at,
        )
        return updated

    def spawn_participant_runtime_session(
        self,
        runtime_store: RuntimeStore,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        child_session_id: str | None = None,
        child_agent_id: str | None = None,
        system_prompt: str | None = None,
        skill_ids: list[str] | None = None,
        skill_catalog_app_id: str | None = None,
        source_app_id: str | None = None,
        owner_user_id: str | None = None,
        created_by_user_id: str | None = None,
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> tuple[InterAgentParticipantRecord, RuntimeSessionRecord, bool]:
        """Spawn one hidden runtime session for an existing child participant.

        The child receives only explicit materialized prompt, skills, and owner.
        Nothing is copied from the root runtime session by this service.
        """
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        scheduler_generation = (
            run.recovery_generation
            if expected_recovery_generation is None
            else expected_recovery_generation
        )
        if run.status == "paused" or run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError(f"Inter-agent run is {run.status}; participant spawn is not allowed.")
        participant = self.store.get_participant(participant_id, workspace_id=workspace_id, run_id=run.run_id)
        if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
            raise InterAgentOperationError("Only child_runtime_session participants can spawn hidden runtime sessions.")
        if participant.thread_visibility != "hidden":
            raise InterAgentOperationError("Child runtime participants must remain hidden.")
        try:
            root_session = runtime_store.get_session(run.root_runtime_session_id)
        except (RuntimeSessionNotFoundError, ValueError) as exc:
            raise InterAgentOperationError("Root runtime session is not available for this inter-agent run.") from exc
        if root_session.workspace_id != run.workspace_id or root_session.workspace_id != workspace_id:
            raise InterAgentOperationError("Root runtime session workspace does not match the inter-agent run.")
        if not runtime_session_allows_user_thread(root_session):
            raise InterAgentOperationError("Inter-agent runs must be rooted in a user-visible runtime session.")
        existing_session_id = _clean_optional(participant.runtime_session_id)
        if existing_session_id:
            try:
                existing_session = runtime_store.get_session(existing_session_id)
            except (RuntimeSessionNotFoundError, ValueError):
                existing_session = None
            if existing_session is not None:
                return participant, existing_session, False
        materialized_prompt = _materialized_system_prompt(participant, explicit_prompt=system_prompt)
        materialized_skill_ids = _materialized_skill_ids(participant, explicit_skill_ids=skill_ids)
        materialized_skill_catalog_app_id = _materialized_skill_catalog_app_id(
            participant,
            explicit_skill_catalog_app_id=skill_catalog_app_id,
        )
        session_generation = str(run.recovery_generation) if run.recovery_generation else "initial"
        session_id = _clean_optional(child_session_id) or _stable_id(
            "iasess",
            run.run_id,
            participant.participant_id,
            session_generation,
        )
        agent_id = _clean_optional(child_agent_id) or participant.agent_type_id or participant.participant_id
        reservation_id = _participant_spawn_reservation_id(participant.participant_id)
        if run.mode == "orchestrated":
            with self.store.scheduler_mutation(
                workspace_id=workspace_id,
                run_id=run.run_id,
                expected_recovery_generation=scheduler_generation,
            ) as current_run:
                current_participant = self.store.get_participant(
                    participant.participant_id,
                    workspace_id=workspace_id,
                    run_id=run.run_id,
                )
                if current_participant.status in TERMINAL_PARTICIPANT_STATUSES:
                    raise InterAgentOperationError(
                        f"Participant `{current_participant.participant_id}` is {current_participant.status}."
                    )
                run = current_run
                participant = current_participant
                self.reserve_budget(
                    run,
                    reservation_id=reservation_id,
                    participant_id=participant.participant_id,
                    participant_slots=1,
                    running_participants=1,
                    now=timestamp,
                )
        else:
            self.reserve_budget(
                run,
                reservation_id=reservation_id,
                participant_id=participant.participant_id,
                participant_slots=1,
                running_participants=1,
                now=timestamp,
            )
        try:
            child = create_child_runtime_session(
                runtime_store,
                workspace_store=self.workspace_store,
                parent_session_id=run.root_runtime_session_id,
                child_session_id=session_id,
                child_agent_id=agent_id,
                system_prompt=materialized_prompt,
                skill_ids=materialized_skill_ids,
                skill_catalog_app_id=materialized_skill_catalog_app_id,
                skill_activation_mode=_materialized_skill_activation_mode(participant),
                source_app_id=_clean_optional(source_app_id) or run.source_app_id,
                owner_user_id=_clean_optional(owner_user_id),
                created_by_user_id=_clean_optional(created_by_user_id) or run.created_by_user_id,
                grants=[],
                now=timestamp,
            )
            child = transition_runtime_session(runtime_store, session_id=child.session_id, target_status="running", now=timestamp)
        except ValueError as error:
            self.release_budget(run, reservation_id=reservation_id, now=timestamp)
            raise InterAgentValidationError(str(error)) from error
        except Exception:
            self.release_budget(run, reservation_id=reservation_id, now=timestamp)
            raise
        latest_run = self.store.get_run(run.run_id, workspace_id=workspace_id)
        latest_participant = self.store.get_participant(
            participant.participant_id,
            workspace_id=workspace_id,
            run_id=run.run_id,
        )
        if (
            latest_run.recovery_generation != scheduler_generation
            or latest_run.status == "paused"
            or latest_run.status in TERMINAL_RUN_STATUSES
            or latest_participant.status in TERMINAL_PARTICIPANT_STATUSES
        ):
            _discard_unclaimed_child_session(
                runtime_store,
                child=child,
                parent=root_session,
            )
            self.release_budget(run, reservation_id=reservation_id, now=timestamp)
            if latest_run.recovery_generation != scheduler_generation:
                raise InterAgentOperationError(
                    "Inter-agent scheduler generation changed; the late participant session was discarded."
                )
            raise InterAgentOperationError(
                f"Inter-agent run is {latest_run.status}; the late participant session was discarded."
            )
        committed_run, updated, claimed = self.store.claim_participant_runtime_session(
            workspace_id=workspace_id,
            run_id=run.run_id,
            participant_id=latest_participant.participant_id,
            runtime_session_id=child.session_id,
            expected_recovery_generation=scheduler_generation,
            now=timestamp,
        )
        if not claimed:
            _discard_unclaimed_child_session(
                runtime_store,
                child=child,
                parent=root_session,
            )
            self.release_budget(run, reservation_id=reservation_id, now=timestamp)
            committed_participant = self.store.get_participant(
                updated.participant_id,
                workspace_id=workspace_id,
                run_id=run.run_id,
            )
            if committed_run.recovery_generation == scheduler_generation:
                self._cancel_interrupted_participant(
                    committed_run,
                    committed_participant,
                    reason="participant_spawn_after_pause",
                    now=datetime.now(tz=UTC),
                )
            if committed_run.recovery_generation != scheduler_generation:
                raise InterAgentOperationError(
                    "Inter-agent scheduler generation changed; the late participant session was discarded."
                )
            raise InterAgentOperationError(
                f"Inter-agent run is {committed_run.status}; the late participant session was discarded."
            )
        self.record_event(
            committed_run,
            event_type="inter_agent.participant.started",
            participant_id=updated.participant_id,
            runtime_session_id=child.session_id,
            visibility_plane="detail",
            idempotency_key=f"{run.run_id}:participant.started:{updated.participant_id}:{child.session_id}",
            correlation_id=child.session_id,
            payload={
                "participant_id": updated.participant_id,
                "runtime_session_id": child.session_id,
                "thread_visibility": child.thread_visibility,
            },
            now=timestamp,
        )
        return updated, child, True

    def send_runtime_message(
        self,
        state: Any,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        input_text: str,
        client_message_id: str | None = None,
        invoked_skill_ids: list[str] | None = None,
        async_requested: bool = False,
        now: datetime | None = None,
        expected_recovery_generation: int | None = None,
    ) -> tuple[InterAgentParticipantRecord, Any, list[Any]]:
        """Send one runtime turn to a spawned child participant session."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        scheduler_generation = (
            run.recovery_generation
            if expected_recovery_generation is None
            else expected_recovery_generation
        )
        if run.status != "running":
            raise InterAgentOperationError("Inter-agent run is not accepting new messages.")
        participant = self.store.get_participant(participant_id, workspace_id=workspace_id, run_id=run.run_id)
        if participant.status != "running":
            raise InterAgentOperationError("Participant is not accepting new messages.")
        runtime_session_id = _clean_optional(participant.runtime_session_id)
        if not runtime_session_id:
            raise InterAgentOperationError("Participant has no spawned runtime session.")
        try:
            session = state.runtime_store.get_session(runtime_session_id)
        except (RuntimeSessionNotFoundError, ValueError) as exc:
            raise InterAgentOperationError("Participant runtime session is not available.") from exc
        if session.workspace_id != workspace_id or session.thread_visibility != "hidden":
            raise InterAgentOperationError("Participant runtime session violates hidden-session policy.")
        message = str(input_text or "").strip()
        if not message:
            raise InterAgentOperationError("Inter-agent messages require input_text.")
        reservation_id = _message_turn_reservation_id(
            run_id=run.run_id,
            participant_id=participant.participant_id,
            client_message_id=client_message_id,
        )
        budget_reserved = False
        queue_fence = None
        if run.mode == "orchestrated":

            @contextmanager
            def orchestrated_queue_fence():
                nonlocal budget_reserved, run, participant
                with self.store.scheduler_mutation(
                    workspace_id=workspace_id,
                    run_id=run.run_id,
                    expected_recovery_generation=scheduler_generation,
                    allowed_statuses={"running"},
                ) as current_run:
                    current_participant = self.store.get_participant(
                        participant.participant_id,
                        workspace_id=workspace_id,
                        run_id=run.run_id,
                    )
                    if (
                        current_participant.status != "running"
                        or current_participant.runtime_session_id != runtime_session_id
                    ):
                        raise InterAgentOperationError(
                            "Participant lost its runtime-session claim before message send."
                        )
                    run = current_run
                    participant = current_participant
                    self.reserve_budget(
                        run,
                        reservation_id=reservation_id,
                        participant_id=participant.participant_id,
                        turns=1,
                        now=timestamp,
                    )
                    budget_reserved = True
                    yield

            queue_fence = orchestrated_queue_fence
        else:
            self.reserve_budget(
                run,
                reservation_id=reservation_id,
                participant_id=participant.participant_id,
                turns=1,
                now=timestamp,
            )
            budget_reserved = True
        submit = submit_runtime_turn_async if async_requested else submit_runtime_turn
        submit_kwargs: dict[str, Any] = {
            "session": session,
            "input_text": message,
            "client_message_id": _clean_optional(client_message_id),
        }
        if session.skill_activation_mode == "explicit" or invoked_skill_ids is not None:
            submit_kwargs["invoked_skill_ids"] = list(invoked_skill_ids or [])
        if queue_fence is not None:
            submit_kwargs["queue_fence"] = queue_fence
        try:
            turn, events = submit(state, **submit_kwargs)
        except Exception:
            if budget_reserved:
                self.release_budget(run, reservation_id=reservation_id, now=timestamp)
            raise
        self.record_event(
            run,
            event_type="inter_agent.message.sent",
            participant_id=participant.participant_id,
            runtime_session_id=session.session_id,
            runtime_turn_id=turn.turn_id,
            visibility_plane="detail",
            idempotency_key=f"{run.run_id}:message.sent:{turn.turn_id}",
            correlation_id=turn.turn_id,
            payload={
                "participant_id": participant.participant_id,
                "runtime_session_id": session.session_id,
                "runtime_turn_id": turn.turn_id,
                **(
                    {"invoked_skill_ids": list(turn.invoked_skill_ids)}
                    if "invoked_skill_ids" in submit_kwargs
                    else {}
                ),
            },
            now=timestamp,
            expected_recovery_generation=(
                scheduler_generation if run.mode == "orchestrated" else None
            ),
        )
        return participant, turn, events

    def wait_for_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.1,
    ) -> InterAgentRunRecord:
        """Wait briefly for one run to reach a terminal state."""
        timeout = max(0.0, min(float(timeout_seconds), MAX_WAIT_TIMEOUT_SECONDS))
        deadline = time.monotonic() + timeout
        while True:
            run = self.store.get_run(run_id, workspace_id=workspace_id)
            if run.status in TERMINAL_RUN_STATUSES or time.monotonic() >= deadline:
                return run
            time.sleep(max(0.01, min(float(poll_interval_seconds), 1.0)))

    def interrupt_run(
        self,
        state: Any,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str | None = None,
        reason: str = "inter_agent_interrupt",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Interrupt active child participant turns without deleting sessions."""
        timestamp = now or datetime.now(tz=UTC)
        with self.store.run_control_handoff(workspace_id=workspace_id, run_id=run_id):
            return self._interrupt_run_with_handoff(
                state,
                workspace_id=workspace_id,
                run_id=run_id,
                participant_id=participant_id,
                reason=reason,
                timestamp=timestamp,
            )

    def _interrupt_run_with_handoff(
        self,
        state: Any,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str | None,
        reason: str,
        timestamp: datetime,
    ) -> dict[str, Any]:
        """Complete one interrupt while its run-control handoff is held."""
        self.store.get_run(run_id, workspace_id=workspace_id)
        target_participant_id = _clean_optional(participant_id)
        if target_participant_id is not None:
            target = self.store.get_participant(
                target_participant_id,
                workspace_id=workspace_id,
                run_id=run_id,
            )
            if target.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
                raise InterAgentOperationError(
                    f"Child runtime participant `{target_participant_id}` was not found."
                )
        run, pause_applied, participant_snapshot = (
            self.store.pause_run_if_active_with_participant_snapshot(
                run_id,
                workspace_id=workspace_id,
                now=timestamp,
            )
        )
        participants = _selected_child_participants(
            participant_snapshot,
            participant_id=target_participant_id,
        )
        if pause_applied:
            self.record_event(
                run,
                event_type="inter_agent.run.paused",
                participant_id=target_participant_id,
                visibility_plane="summary",
                idempotency_key=f"{run.run_id}:run.paused:{timestamp.isoformat()}",
                correlation_id=run.run_id,
                payload={"reason": reason, "participant_id": target_participant_id},
                now=timestamp,
            )
        if run.status in TERMINAL_RUN_STATUSES:
            return {"run": run, "interrupted_sessions": []}
        interrupted_sessions: list[dict[str, Any]] = []
        for participant in participants:
            runtime_session_id = participant.runtime_session_id
            if runtime_session_id:
                interrupted_sessions.append(
                    _interrupt_runtime_session(
                        state,
                        session_id=runtime_session_id,
                        reason=reason,
                    )
                )
            if run.mode == "orchestrated" and runtime_session_id:
                try:
                    session = state.runtime_store.get_session(runtime_session_id)
                    if session.status in {"created", "running", "stopping"}:
                        transition_runtime_session(
                            state.runtime_store,
                            session_id=session.session_id,
                            target_status="stopped",
                            forced_stop_reason=reason,
                            now=timestamp,
                        )
                except (RuntimeSessionNotFoundError, ValueError):
                    pass
            should_cancel = bool(runtime_session_id) or (
                run.mode == "orchestrated" and bool(participant.current_task_id)
            )
            if not should_cancel:
                continue
            self.release_budget(
                run,
                reservation_id=_participant_spawn_reservation_id(participant.participant_id),
                now=timestamp,
            )
            self._cancel_interrupted_participant(
                run,
                participant,
                reason=reason,
                now=timestamp,
            )
        return {"run": run, "interrupted_sessions": interrupted_sessions}

    def _cancel_interrupted_participant(
        self,
        run: InterAgentRunRecord,
        participant: InterAgentParticipantRecord,
        *,
        reason: str,
        now: datetime,
    ) -> InterAgentParticipantRecord:
        previous, updated, cancelled = self.store.cancel_participant_for_interrupt(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=participant.participant_id,
            expected_recovery_generation=run.recovery_generation,
            expected_runtime_session_id=participant.runtime_session_id,
            expected_current_task_id=participant.current_task_id,
            now=now,
        )
        if not cancelled:
            return updated
        current_task_id = previous.current_task_id
        if (
            run.mode == "orchestrated"
            and previous.kind == "agent"
            and previous.participant_id != run.orchestrator_participant_id
            and current_task_id
            and not _task_result_recorded(self.store, run, current_task_id)
        ):
            self.record_event(
                run,
                event_type="inter_agent.task.completed",
                participant_id=previous.participant_id,
                runtime_session_id=previous.runtime_session_id,
                visibility_plane="detail",
                idempotency_key=f"{run.run_id}:task.interrupted:{current_task_id}",
                correlation_id=current_task_id,
                payload={
                    "task_id": current_task_id,
                    "participant_id": previous.participant_id,
                    "status": "cancelled",
                    "summary": "Cancelled by run interruption.",
                    "output_text": "",
                    "error": None,
                    "reason": reason,
                },
                now=now,
            )
        self.record_event(
            run,
            event_type="inter_agent.participant.status_changed",
            participant_id=previous.participant_id,
            runtime_session_id=previous.runtime_session_id,
            visibility_plane="detail",
            idempotency_key=(
                f"{run.run_id}:participant.cancelled:{previous.participant_id}:{now.isoformat()}"
            ),
            correlation_id=previous.participant_id,
            payload={
                "participant_id": previous.participant_id,
                "status": "cancelled",
                "reason": reason,
            },
            now=now,
        )
        return updated

    def resume_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        reason: str = "inter_agent_resume",
        now: datetime | None = None,
    ) -> InterAgentRunRecord:
        """Mark a paused or recovering run runnable; hosted surfaces enqueue execution."""
        timestamp = now or datetime.now(tz=UTC)
        with self.store.run_control_handoff(workspace_id=workspace_id, run_id=run_id):
            return self._resume_run_with_handoff(
                workspace_id=workspace_id,
                run_id=run_id,
                reason=reason,
                timestamp=timestamp,
            )

    def _resume_run_with_handoff(
        self,
        *,
        workspace_id: str,
        run_id: str,
        reason: str,
        timestamp: datetime,
    ) -> InterAgentRunRecord:
        """Resume one run only after any in-flight interrupt releases ownership."""
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError("Terminal inter-agent runs cannot be resumed.")
        recovery_generation = run.recovery_generation
        if run.mode == "orchestrated" and run.status == "paused":
            orchestrator = self.store.get_participant(
                run.orchestrator_participant_id,
                workspace_id=workspace_id,
                run_id=run.run_id,
            )
            if orchestrator.status == "cancelled":
                self.store.save_participant(
                    replace(
                        orchestrator,
                        runtime_session_id=None,
                        status="idle",
                        current_task_id=None,
                        updated_at=timestamp,
                    )
                )
                self.record_event(
                    run,
                    event_type="inter_agent.participant.status_changed",
                    participant_id=orchestrator.participant_id,
                    runtime_session_id=orchestrator.runtime_session_id,
                    visibility_plane="detail",
                    idempotency_key=(
                        f"{run.run_id}:participant.resumed:{orchestrator.participant_id}:"
                        f"{recovery_generation + 1}"
                    ),
                    correlation_id=orchestrator.participant_id,
                    payload={
                        "participant_id": orchestrator.participant_id,
                        "status": "idle",
                        "reason": reason,
                        "runtime_session_detached": True,
                    },
                    now=timestamp,
                )
            recovery_generation += 1
        updated = replace(
            run,
            status="running",
            updated_at=timestamp,
            ended_at=None,
            recovery_generation=recovery_generation,
        )
        self.store.save_run(updated)
        self.record_event(
            updated,
            event_type="inter_agent.run.resumed",
            participant_id=updated.orchestrator_participant_id,
            visibility_plane="summary",
            idempotency_key=f"{updated.run_id}:run.resumed:{timestamp.isoformat()}",
            correlation_id=updated.run_id,
            payload={"reason": reason, "recovery_generation": updated.recovery_generation},
            now=timestamp,
        )
        return updated

    def close_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        cleanup_runtime_session: Callable[[str, str], dict[str, object]],
        reason: str = "inter_agent_run_closed",
        terminal_status: str = "cancelled",
        delete_records: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Close one run and clean up all non-root child runtime sessions."""
        timestamp = now or datetime.now(tz=UTC)
        if terminal_status not in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError("terminal_status must be completed, failed, or cancelled.")
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        participants = self.store.list_participants(run.run_id, workspace_id=workspace_id)
        cleanups: list[dict[str, object]] = []
        for participant in participants:
            if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE or not participant.runtime_session_id:
                continue
            cleanup_result = cleanup_runtime_session(participant.runtime_session_id, reason)
            cleanups.append({"participant_id": participant.participant_id, **cleanup_result})
            self.release_budget(
                run,
                reservation_id=_participant_spawn_reservation_id(participant.participant_id),
                now=timestamp,
            )
            if participant.status not in TERMINAL_PARTICIPANT_STATUSES:
                cancelled_participant = replace(participant, status="cancelled", updated_at=timestamp)
                self.store.save_participant(cancelled_participant)
                self.record_event(
                    run,
                    event_type="inter_agent.participant.status_changed",
                    participant_id=participant.participant_id,
                    runtime_session_id=participant.runtime_session_id,
                    visibility_plane="detail",
                    idempotency_key=f"{run.run_id}:participant.closed_cancelled:{participant.participant_id}:{timestamp.isoformat()}",
                    correlation_id=participant.participant_id,
                    payload={"participant_id": participant.participant_id, "status": "cancelled", "reason": reason},
                    now=timestamp,
                )
        updated = replace(run, status=terminal_status, updated_at=timestamp, ended_at=timestamp)
        self.store.save_run(updated)
        event_type: InterAgentEventType = {
            "completed": "inter_agent.run.completed",
            "failed": "inter_agent.run.failed",
            "cancelled": "inter_agent.run.cancelled",
        }[terminal_status]  # type: ignore[assignment]
        self.record_event(
            updated,
            event_type=event_type,
            participant_id=updated.orchestrator_participant_id,
            visibility_plane="summary",
            idempotency_key=f"{updated.run_id}:run.closed:{terminal_status}:{timestamp.isoformat()}",
            correlation_id=updated.run_id,
            payload={"reason": reason, "status": terminal_status},
            now=timestamp,
        )
        deleted: dict[str, int] | None = None
        if delete_records:
            deleted = self.store.delete_run_records(updated.run_id, workspace_id=workspace_id)
        return {"run": updated, "participant_cleanups": cleanups, "deleted": deleted}

    def recover_non_terminal_runs(
        self,
        runtime_store: RuntimeStore,
        *,
        workspace_id: str,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Reconcile non-terminal inter-agent runs after backend startup."""
        timestamp = now or datetime.now(tz=UTC)
        inspected = 0
        recovered = 0
        failed_participants = 0
        failed_runs = 0
        closed_root_turns = 0
        for run in self.store.list_runs(workspace_id):
            recover_unapplied_completion = (
                run.mode == "orchestrated"
                and run.status == "completed"
                and _has_unapplied_completion_decision(self.store, run)
            )
            if run.status in TERMINAL_RUN_STATUSES and not recover_unapplied_completion:
                continue
            inspected += 1
            participants = self.store.list_participants(run.run_id, workspace_id=workspace_id)
            if run.mode == "orchestrated":
                if run.status == "paused":
                    continue
                next_generation = run.recovery_generation + 1
                for participant in participants:
                    if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
                        continue
                    if participant.status in TERMINAL_PARTICIPANT_STATUSES:
                        continue
                    previous_session_id = participant.runtime_session_id
                    if previous_session_id:
                        try:
                            session = runtime_store.get_session(previous_session_id)
                            if session.status in {"created", "running", "stopping"}:
                                transition_runtime_session(
                                    runtime_store,
                                    session_id=session.session_id,
                                    target_status="stopped",
                                    forced_stop_reason="inter_agent_scheduler_recovery",
                                    now=timestamp,
                                )
                        except (RuntimeSessionNotFoundError, ValueError):
                            pass
                    self.release_budget(
                        run,
                        reservation_id=_participant_spawn_reservation_id(participant.participant_id),
                        now=timestamp,
                    )
                    if participant.current_task_id:
                        self.record_event(
                            run,
                            event_type="inter_agent.task.retry_scheduled",
                            participant_id=participant.participant_id,
                            runtime_session_id=previous_session_id,
                            visibility_plane="detail",
                            idempotency_key=(
                                f"{run.run_id}:task.retry:{participant.current_task_id}:{next_generation}"
                            ),
                            correlation_id=participant.current_task_id,
                            payload={
                                "task_id": participant.current_task_id,
                                "participant_id": participant.participant_id,
                                "attempt": next_generation + 1,
                                "reason": "backend_restart",
                            },
                            now=timestamp,
                        )
                    self.store.save_participant(
                        replace(
                            participant,
                            runtime_session_id=None,
                            status="idle",
                            current_task_id=None,
                            updated_at=timestamp,
                        )
                    )
                updated = replace(
                    run,
                    status="recovering",
                    updated_at=timestamp,
                    ended_at=None,
                    recovery_generation=next_generation,
                )
                self.store.save_run(updated)
                recovered += 1
                self.record_event(
                    updated,
                    event_type="inter_agent.run.recovered",
                    participant_id=updated.orchestrator_participant_id,
                    visibility_plane="summary",
                    idempotency_key=f"{updated.run_id}:run.recovered:{updated.recovery_generation}",
                    correlation_id=updated.run_id,
                    payload={"recovery_generation": updated.recovery_generation, "scheduler_resume": True},
                    now=timestamp,
                )
                continue
            active_child_count = 0
            for participant in participants:
                if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
                    continue
                if not participant.runtime_session_id:
                    continue
                try:
                    runtime_store.get_session(participant.runtime_session_id)
                    active_child_count += 1
                except (RuntimeSessionNotFoundError, ValueError):
                    if participant.status not in TERMINAL_PARTICIPANT_STATUSES:
                        failed = replace(participant, status="failed", updated_at=timestamp)
                        self.store.save_participant(failed)
                        failed_participants += 1
                        self.record_event(
                            run,
                            event_type="inter_agent.participant.status_changed",
                            participant_id=participant.participant_id,
                            runtime_session_id=participant.runtime_session_id,
                            visibility_plane="detail",
                            idempotency_key=f"{run.run_id}:participant.recovery_failed:{participant.participant_id}:{timestamp.isoformat()}",
                            correlation_id=participant.participant_id,
                            payload={
                                "participant_id": participant.participant_id,
                                "status": "failed",
                                "reason": "runtime_session_missing_after_restart",
                            },
                            now=timestamp,
                        )
            if active_child_count == 0 and run.status in {"running", "planning", "recovering"}:
                updated = replace(run, status="failed", updated_at=timestamp, ended_at=timestamp)
                self.store.save_run(updated)
                closed_root_turns += _close_non_terminal_root_turns_for_run(
                    runtime_store,
                    run=updated,
                    now=timestamp,
                )
                failed_runs += 1
                self.record_event(
                    updated,
                    event_type="inter_agent.run.failed",
                    participant_id=updated.orchestrator_participant_id,
                    visibility_plane="summary",
                    idempotency_key=f"{updated.run_id}:run.recovery_failed:{timestamp.isoformat()}",
                    correlation_id=updated.run_id,
                    payload={"reason": "no_active_child_runtime_sessions_after_restart"},
                    now=timestamp,
                )
                continue
            updated = replace(run, status="recovering" if run.status == "running" else run.status, updated_at=timestamp, recovery_generation=run.recovery_generation + 1)
            self.store.save_run(updated)
            recovered += 1
            self.record_event(
                updated,
                event_type="inter_agent.run.recovered",
                participant_id=updated.orchestrator_participant_id,
                visibility_plane="summary",
                idempotency_key=f"{updated.run_id}:run.recovered:{updated.recovery_generation}",
                correlation_id=updated.run_id,
                payload={"recovery_generation": updated.recovery_generation},
                now=timestamp,
            )
        return {
            "inspected_runs": inspected,
            "recovered_runs": recovered,
            "failed_runs": failed_runs,
            "failed_participants": failed_participants,
            "closed_root_turns": closed_root_turns,
        }


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
                invoked_skill_ids=list(spec.invoked_skill_ids),
                provider_id=provider_id,
                authority_grant_ids=list(spec.authority_grant_ids),
                thread_visibility=spec.thread_visibility or "hidden",
                created_at=created_at,
                updated_at=created_at,
                sequence_index=index,
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
        "source_runtime_turn_id": spec.source_runtime_turn_id,
        "orchestration_policy": spec.orchestration_policy,
    }
    encoded = json.dumps(_canonical_fingerprint_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _participant_spec_fingerprint_payload(spec: ParticipantSpec) -> dict[str, Any]:
    payload = {
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
    if spec.invoked_skill_ids:
        payload["invoked_skill_ids"] = sorted(spec.invoked_skill_ids)
    return payload


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
        if spec.kind == "orchestrator":
            return participant_ids[index]
    raise ValueError("validated run spec did not include an orchestrator")


def _materialized_system_prompt(participant: InterAgentParticipantRecord, *, explicit_prompt: str | None) -> str | None:
    prompt = _clean_optional(explicit_prompt)
    if prompt:
        return prompt
    snapshot = participant.agent_snapshot if isinstance(participant.agent_snapshot, dict) else {}
    return _clean_optional(snapshot.get("system_prompt")) if isinstance(snapshot.get("system_prompt"), str) else None


def _materialized_skill_ids(
    participant: InterAgentParticipantRecord,
    *,
    explicit_skill_ids: list[str] | None,
) -> list[str]:
    if explicit_skill_ids is not None:
        return _clean_string_list(explicit_skill_ids)
    return _clean_string_list(participant.skill_ids)


def _materialized_skill_activation_mode(participant: InterAgentParticipantRecord) -> str:
    snapshot = participant.agent_snapshot if isinstance(participant.agent_snapshot, dict) else {}
    return str(snapshot.get("skill_activation_mode") or "implicit")


def _materialized_skill_catalog_app_id(
    participant: InterAgentParticipantRecord,
    *,
    explicit_skill_catalog_app_id: str | None,
) -> str | None:
    value = _clean_optional(explicit_skill_catalog_app_id)
    if value:
        return value
    snapshot = participant.agent_snapshot if isinstance(participant.agent_snapshot, dict) else {}
    snapshot_catalog = snapshot.get("skill_catalog_app_id")
    return _clean_optional(snapshot_catalog) if isinstance(snapshot_catalog, str) else None


def _approval_resolver_is_eligible(
    approval: ApprovalRequestRecord,
    *,
    user_id: str,
    role_ids: list[str] | None,
) -> bool:
    normalized_user_id = _clean_optional(user_id)
    eligible_user_ids = set(_clean_string_list(approval.eligible_approver_user_ids))
    if normalized_user_id and normalized_user_id in eligible_user_ids:
        return True
    eligible_roles = {item.lower() for item in _clean_string_list(approval.eligible_approver_roles)}
    if not eligible_roles:
        return False
    resolver_roles = {item.lower() for item in _clean_string_list(role_ids or [])}
    return bool(eligible_roles.intersection(resolver_roles))


def _close_non_terminal_root_turns_for_run(
    runtime_store: RuntimeStore,
    *,
    run: InterAgentRunRecord,
    now: datetime,
) -> int:
    try:
        runtime_store.get_session(run.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return 0
    root_turn_ids = {
        event.turn_id
        for event in runtime_store.list_events(run.root_runtime_session_id)
        if event.turn_id and isinstance(event.payload, dict) and event.payload.get("inter_agent_run_id") == run.run_id
    }
    if not root_turn_ids:
        return 0
    closed = 0
    for turn in runtime_store.list_turns(run.root_runtime_session_id):
        if turn.turn_id not in root_turn_ids or turn.status not in {"queued", "active"}:
            continue
        target_status = "cancelled" if turn.status == "queued" else "failed"
        updated = transition_runtime_turn(
            runtime_store,
            turn_id=turn.turn_id,
            target_status=target_status,
            failure_reason="Inter-agent run failed during backend recovery.",
            now=now,
        )
        record_runtime_event(
            runtime_store,
            event_id=str(uuid.uuid4()),
            session_id=updated.session_id,
            turn_id=updated.turn_id,
            plane="turn",
            event_type=f"runtime.turn.{updated.status}",
            payload={
                "inter_agent_run_id": run.run_id,
                "reason": "inter_agent_recovery_failed",
            },
            now=now,
        )
        closed += 1
    if closed:
        availability = runtime_thread_availability_for_session(
            runtime_store,
            runtime_session_id=run.root_runtime_session_id,
        )
        update_runtime_thread_availability(
            runtime_store,
            workspace_id=run.workspace_id,
            runtime_session_id=run.root_runtime_session_id,
            availability=availability,
            now=now,
        )
    return closed


def _has_unapplied_completion_decision(store: Any, run: InterAgentRunRecord) -> bool:
    events = store.list_recovery_events(
        run.run_id,
        workspace_id=run.workspace_id,
        event_types={"inter_agent.control.decision", "inter_agent.control.decision_applied"},
    )
    completed_steps = {
        int(event.payload.get("control_step") or 0)
        for event in events
        if event.event_type == "inter_agent.control.decision" and event.payload.get("complete") is True
    }
    applied_steps = {
        int(event.payload.get("control_step") or 0)
        for event in events
        if event.event_type == "inter_agent.control.decision_applied"
    }
    return bool(completed_steps - applied_steps)


def _selected_child_participants(
    participants: list[InterAgentParticipantRecord],
    *,
    participant_id: str | None,
) -> list[InterAgentParticipantRecord]:
    target = _clean_optional(participant_id)
    selected = [
        participant
        for participant in participants
        if participant.execution_mode == RUNTIME_CHILD_EXECUTION_MODE and (target is None or participant.participant_id == target)
    ]
    if target is not None and not selected:
        raise InterAgentOperationError(f"Child runtime participant `{target}` was not found.")
    return selected


def _participant_spawn_reservation_id(participant_id: str) -> str:
    return f"spawn:{participant_id}"


def _message_turn_reservation_id(*, run_id: str, participant_id: str, client_message_id: str | None) -> str:
    client_key = _clean_optional(client_message_id)
    if client_key:
        return _stable_id("turn", run_id, participant_id, client_key)
    return _new_id("turn")


def _interrupt_runtime_session(state: Any, *, session_id: str, reason: str) -> dict[str, Any]:
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return {"session_id": session_id, "found": False, "cancelled_turns": 0, "provider_interrupted": False}
    cancellable_turns = [
        turn
        for turn in state.runtime_store.list_turns(session.session_id)
        if turn.status in {"queued", "active"}
    ]
    for turn in cancellable_turns:
        request_runtime_turn_cancellation(
            state.runtime_store,
            turn_id=turn.turn_id,
            reason=reason,
        )
    provider_interrupted = False
    for turn in cancellable_turns:
        provider_interrupted = (
            interrupt_runtime_provider_turn(state, session, turn_id=turn.turn_id)
            or provider_interrupted
        )
    cancelled_turns = 0
    for turn in cancellable_turns:
        terminalization = terminalize_runtime_turn_cancellation(
            state.runtime_store,
            turn_id=turn.turn_id,
            reason=reason,
            event_payload={"reason": reason},
            event_bus=getattr(state, "runtime_event_bus", None),
            request_intent=False,
        )
        if terminalization.turn.status == "cancelled" and terminalization.claimed:
            cancelled_turns += 1
    refreshed_session = state.runtime_store.get_session(session.session_id)
    for turn in cancellable_turns:
        provider_interrupted = (
            interrupt_runtime_provider_turn(
                state,
                refreshed_session,
                turn_id=turn.turn_id,
                wait_for_termination=True,
            )
            or provider_interrupted
        )
    release_idle_runtime_processes(
        state,
        session_id=session.session_id,
        provider_id=session.provider_id or "unconfigured",
        reason=reason,
        idle_ttl_seconds=0,
    )
    return {
        "session_id": session.session_id,
        "found": True,
        "cancelled_turns": cancelled_turns,
        "provider_interrupted": provider_interrupted,
    }


def _clean_string_list(values: list[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _discard_unclaimed_child_session(
    runtime_store: RuntimeStore,
    *,
    child: RuntimeSessionRecord,
    parent: RuntimeSessionRecord,
) -> None:
    child_root = Path(child.runtime_root)
    expected_parent = Path(parent.runtime_root).parent.resolve()
    if child_root.parent.resolve() != expected_parent or child_root.name != child.session_id:
        raise InterAgentValidationError("Late child runtime root is outside the parent session boundary.")
    if child_root.is_symlink():
        child_root.unlink()
    elif child_root.exists():
        shutil.rmtree(child_root)
    runtime_store.delete_session_records(child.session_id)


def _task_result_recorded(
    store: InterAgentStore,
    run: InterAgentRunRecord,
    task_id: str,
) -> bool:
    return any(
        str(event.payload.get("task_id") or event.correlation_id or "").strip() == task_id
        for event in store.list_recovery_events(
            run.run_id,
            workspace_id=run.workspace_id,
            event_types={"inter_agent.task.completed"},
        )
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = json.dumps(_canonical_fingerprint_value(list(parts)), sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
