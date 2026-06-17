"""Inter-agent service facade for schema-only F1 operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
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
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.lifecycle_service_sessions import create_child_runtime_session
from core.runtime.runtime_session import RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.store import RuntimeStore
from core.runtime.service import record_runtime_event, transition_runtime_session, transition_runtime_turn
from core.runtime.turn_submission import (
    interrupt_runtime_provider_turn,
    release_idle_runtime_processes,
    submit_runtime_turn,
    submit_runtime_turn_async,
)


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
            aggregator_participant_id=_clean_optional(validated.aggregator_participant_id),
            merge_policy=_clean_optional(validated.merge_policy),
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
    ) -> tuple[InterAgentParticipantRecord, RuntimeSessionRecord, bool]:
        """Spawn one hidden runtime session for an existing child participant.

        The child receives only explicit materialized prompt, skills, and owner.
        Nothing is copied from the root runtime session by this service.
        """
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
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
        session_id = _clean_optional(child_session_id) or _stable_id("iasess", run.run_id, participant.participant_id)
        agent_id = _clean_optional(child_agent_id) or participant.agent_type_id or participant.participant_id
        reservation_id = _participant_spawn_reservation_id(participant.participant_id)
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
                parent_session_id=run.root_runtime_session_id,
                child_session_id=session_id,
                child_agent_id=agent_id,
                system_prompt=materialized_prompt,
                skill_ids=materialized_skill_ids,
                skill_catalog_app_id=materialized_skill_catalog_app_id,
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
        updated = replace(
            participant,
            runtime_session_id=child.session_id,
            status="running",
            updated_at=timestamp,
        )
        self.store.save_participant(updated)
        if run.status in {"created", "planning", "recovering"}:
            run = replace(run, status="running", updated_at=timestamp)
            self.store.save_run(run)
        self.record_event(
            run,
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
        async_requested: bool = False,
        now: datetime | None = None,
    ) -> tuple[InterAgentParticipantRecord, Any, list[Any]]:
        """Send one runtime turn to a spawned child participant session."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
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
        self.reserve_budget(run, reservation_id=reservation_id, participant_id=participant.participant_id, turns=1, now=timestamp)
        submit = submit_runtime_turn_async if async_requested else submit_runtime_turn
        try:
            turn, events = submit(
                state,
                session=session,
                input_text=message,
                client_message_id=_clean_optional(client_message_id),
            )
        except Exception:
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
            },
            now=timestamp,
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
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        participants = _selected_child_participants(
            self.store.list_participants(run.run_id, workspace_id=workspace_id),
            participant_id=participant_id,
        )
        interrupted_sessions: list[dict[str, Any]] = []
        for participant in participants:
            if not participant.runtime_session_id:
                continue
            interrupted_sessions.append(
                _interrupt_runtime_session(
                    state,
                    session_id=participant.runtime_session_id,
                    reason=reason,
                )
            )
            self.release_budget(
                run,
                reservation_id=_participant_spawn_reservation_id(participant.participant_id),
                now=timestamp,
            )
            if participant.status not in TERMINAL_PARTICIPANT_STATUSES:
                updated = replace(participant, status="cancelled", updated_at=timestamp)
                self.store.save_participant(updated)
                self.record_event(
                    run,
                    event_type="inter_agent.participant.status_changed",
                    participant_id=participant.participant_id,
                    runtime_session_id=participant.runtime_session_id,
                    visibility_plane="detail",
                    idempotency_key=f"{run.run_id}:participant.cancelled:{participant.participant_id}:{timestamp.isoformat()}",
                    correlation_id=participant.participant_id,
                    payload={"participant_id": participant.participant_id, "status": "cancelled", "reason": reason},
                    now=timestamp,
                )
        if run.status not in TERMINAL_RUN_STATUSES:
            run = replace(run, status="paused", updated_at=timestamp)
            self.store.save_run(run)
            self.record_event(
                run,
                event_type="inter_agent.run.paused",
                participant_id=participant_id,
                visibility_plane="summary",
                idempotency_key=f"{run.run_id}:run.paused:{timestamp.isoformat()}",
                correlation_id=run.run_id,
                payload={"reason": reason, "participant_id": participant_id},
                now=timestamp,
            )
        return {"run": run, "interrupted_sessions": interrupted_sessions}

    def resume_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        reason: str = "inter_agent_resume",
        now: datetime | None = None,
    ) -> InterAgentRunRecord:
        """Mark a paused or recovering run runnable again without queuing work."""
        timestamp = now or datetime.now(tz=UTC)
        run = self.store.get_run(run_id, workspace_id=workspace_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise InterAgentOperationError("Terminal inter-agent runs cannot be resumed.")
        updated = replace(run, status="running", updated_at=timestamp)
        self.store.save_run(updated)
        self.record_event(
            updated,
            event_type="inter_agent.run.resumed",
            participant_id=updated.orchestrator_participant_id,
            visibility_plane="summary",
            idempotency_key=f"{updated.run_id}:run.resumed:{timestamp.isoformat()}",
            correlation_id=updated.run_id,
            payload={"reason": reason},
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
                self.store.save_participant(replace(participant, status="cancelled", updated_at=timestamp))
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
        for run in self.store.list_runs(workspace_id):
            if run.status in TERMINAL_RUN_STATUSES:
                continue
            inspected += 1
            participants = self.store.list_participants(run.run_id, workspace_id=workspace_id)
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
    provider_interrupted = interrupt_runtime_provider_turn(state, session)
    cancelled_turns = 0
    for turn in state.runtime_store.list_turns(session.session_id):
        if turn.status not in {"queued", "active"}:
            continue
        cancelled = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn.turn_id,
            target_status="cancelled",
            failure_reason=reason,
        )
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid.uuid4()),
            session_id=session.session_id,
            turn_id=cancelled.turn_id,
            plane="turn",
            event_type="runtime.turn.cancelled",
            payload={"reason": reason},
            event_bus=getattr(state, "runtime_event_bus", None),
        )
        cancelled_turns += 1
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


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _stable_id(prefix: str, *parts: object) -> str:
    encoded = json.dumps(_canonical_fingerprint_value(list(parts)), sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
