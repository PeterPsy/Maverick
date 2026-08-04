"""Inter-agent store contracts and workspace-scoped JSON adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import tempfile
from typing import Any, Callable, Protocol

from core.inter_agent.errors import (
    InterAgentApprovalNotFoundError,
    InterAgentBudgetExceededError,
    InterAgentBudgetLedgerNotFoundError,
    InterAgentBudgetPolicyNotFoundError,
    InterAgentEdgeNotFoundError,
    InterAgentEventNotFoundError,
    InterAgentIdempotencyConflictError,
    InterAgentParticipantNotFoundError,
    InterAgentRunNotFoundError,
    InterAgentValidationError,
)
from core.inter_agent.events import (
    EventRetentionPolicyRecord,
    InterAgentEventPage,
    InterAgentEventRecord,
    InterAgentVisibilityPlane,
    INTER_AGENT_RECOVERY_EVENT_TYPES,
    validate_event_record,
    validate_visibility_plane,
    visible_planes_for,
)
from core.inter_agent.models import (
    ApprovalRequestRecord,
    BudgetLedgerRecord,
    BudgetPolicyRecord,
    BudgetReservation,
    InterAgentEdgeRecord,
    InterAgentParticipantRecord,
    InterAgentRunRecord,
    budget_reservation_from_document,
    budget_reservation_to_document,
)
from core.runtime.paths import workspace_runtime_root
from core.shared.json_file_collection import _decode_document_value, _encode_document_value, _matches


DEFAULT_INTER_AGENT_EVENT_LIMIT = 200
MAX_INTER_AGENT_EVENT_LIMIT = 500


@dataclass(frozen=True)
class InterAgentCollections:
    """Collection bundle for inter-agent-domain persistence."""

    runs: "DocumentCollection"
    participants: "DocumentCollection"
    edges: "DocumentCollection"
    approvals: "DocumentCollection"
    budget_policies: "DocumentCollection"
    budget_ledgers: "DocumentCollection"
    events: "InterAgentEventCollection"
    retention_policies: "DocumentCollection"


@dataclass(frozen=True)
class InterAgentRunCreateBundle:
    """All records needed to materialize one F1 run under a workspace lock."""

    run: InterAgentRunRecord
    budget_policy: BudgetPolicyRecord
    budget_ledger: BudgetLedgerRecord
    retention_policy: EventRetentionPolicyRecord
    participants: list[InterAgentParticipantRecord]
    edges: list[InterAgentEdgeRecord]
    initial_events: list[InterAgentEventRecord]


class DocumentCollection(Protocol):
    """Minimal document collection protocol used by inter-agent stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class InterAgentEventCollection(DocumentCollection, Protocol):
    """Event collection protocol with run-scoped atomic append and paging."""

    def append_event(
        self,
        record: InterAgentEventRecord,
        *,
        retention_policy: EventRetentionPolicyRecord,
    ) -> dict[str, Any]:
        ...

    def find_event_page(
        self,
        query: dict[str, Any],
        *,
        visibility_plane: InterAgentVisibilityPlane,
        event_types: set[str] | None,
        after_event_id: str | None,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        ...


class InterAgentStore(Protocol):
    """Persistence contract for inter-agent records and ledgers."""

    def create_run(self, bundle: InterAgentRunCreateBundle) -> InterAgentRunRecord:
        ...

    def save_run(self, record: InterAgentRunRecord) -> InterAgentRunRecord:
        ...

    def pause_run_if_active(
        self,
        run_id: str,
        *,
        workspace_id: str,
        now: datetime,
    ) -> InterAgentRunRecord:
        ...

    def get_run(self, run_id: str, *, workspace_id: str) -> InterAgentRunRecord:
        ...

    def find_run_by_idempotency_key(self, workspace_id: str, idempotency_key: str) -> InterAgentRunRecord | None:
        ...

    def list_runs(self, workspace_id: str) -> list[InterAgentRunRecord]:
        ...

    def delete_run_records(self, run_id: str, *, workspace_id: str) -> dict[str, int]:
        ...

    def save_participant(self, record: InterAgentParticipantRecord) -> InterAgentParticipantRecord:
        ...

    def claim_participant_runtime_session(
        self,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        runtime_session_id: str,
        now: datetime,
    ) -> tuple[InterAgentRunRecord, InterAgentParticipantRecord, bool]:
        ...

    def cancel_participant_if_active(
        self,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        now: datetime,
    ) -> tuple[InterAgentParticipantRecord, InterAgentParticipantRecord, bool]:
        ...

    def get_participant(
        self,
        participant_id: str,
        *,
        workspace_id: str,
        run_id: str,
    ) -> InterAgentParticipantRecord:
        ...

    def list_participants(self, run_id: str, *, workspace_id: str) -> list[InterAgentParticipantRecord]:
        ...

    def save_edge(self, record: InterAgentEdgeRecord) -> InterAgentEdgeRecord:
        ...

    def get_edge(self, edge_id: str, *, workspace_id: str) -> InterAgentEdgeRecord:
        ...

    def list_edges(self, run_id: str, *, workspace_id: str) -> list[InterAgentEdgeRecord]:
        ...

    def save_approval(self, record: ApprovalRequestRecord) -> ApprovalRequestRecord:
        ...

    def get_approval(self, approval_id: str, *, workspace_id: str) -> ApprovalRequestRecord:
        ...

    def list_approvals(self, run_id: str, *, workspace_id: str) -> list[ApprovalRequestRecord]:
        ...

    def save_budget_policy(self, record: BudgetPolicyRecord) -> BudgetPolicyRecord:
        ...

    def get_budget_policy(self, budget_policy_id: str, *, workspace_id: str) -> BudgetPolicyRecord:
        ...

    def save_budget_ledger(self, record: BudgetLedgerRecord) -> BudgetLedgerRecord:
        ...

    def get_budget_ledger(self, budget_ledger_id: str, *, workspace_id: str) -> BudgetLedgerRecord:
        ...

    def reserve_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        budget_policy_id: str,
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
    ) -> BudgetLedgerRecord:
        ...

    def release_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        reservation_id: str,
        now: datetime | None = None,
    ) -> BudgetLedgerRecord:
        ...

    def save_retention_policy(self, record: EventRetentionPolicyRecord) -> EventRetentionPolicyRecord:
        ...

    def get_retention_policy(self, retention_policy_id: str, *, workspace_id: str) -> EventRetentionPolicyRecord:
        ...

    def append_event(
        self,
        record: InterAgentEventRecord,
        *,
        retention_policy: EventRetentionPolicyRecord,
    ) -> InterAgentEventRecord:
        ...

    def list_event_page(
        self,
        run_id: str,
        *,
        workspace_id: str,
        visibility_plane: InterAgentVisibilityPlane = "summary",
        event_types: set[str] | None = None,
        after_event_id: str | None = None,
        before_event_id: str | None = None,
        limit: int = DEFAULT_INTER_AGENT_EVENT_LIMIT,
    ) -> InterAgentEventPage:
        ...

    def list_recovery_events(
        self,
        run_id: str,
        *,
        workspace_id: str,
        event_types: set[str] | None = None,
    ) -> list[InterAgentEventRecord]:
        ...


class InterAgentDocumentStore:
    """Persist inter-agent records in document collections."""

    def __init__(self, collections: InterAgentCollections) -> None:
        self.collections = collections
        self._lock = RLock()

    def create_run(self, bundle: InterAgentRunCreateBundle) -> InterAgentRunRecord:
        workspace_id = _require_identifier(bundle.run.workspace_id, "workspace_id")
        run = bundle.run
        _validate_run_create_bundle(bundle)
        with self._workspace_lock(workspace_id):
            if run.idempotency_key:
                existing = self.find_run_by_idempotency_key(workspace_id, run.idempotency_key)
                if existing is not None:
                    _ensure_spec_fingerprint_matches(existing, run)
                    if existing.run_id == run.run_id:
                        self._repair_run_create_bundle(bundle)
                    return existing
            existing_run = self.collections.runs.find_one({"workspace_id": workspace_id, "run_id": run.run_id})
            if existing_run is not None:
                raise InterAgentIdempotencyConflictError(
                    f"Inter-agent run `{run.run_id}` already exists in workspace `{workspace_id}`."
                )
            # The run record is the visible root. Write it last so a failed
            # bundle materialization leaves only orphaned child records that a
            # deterministic retry can repair or supersede.
            self._materialize_run_create_bundle(bundle)
            self.save_run(run)
            return run

    def _materialize_run_create_bundle(self, bundle: InterAgentRunCreateBundle) -> None:
        self.save_budget_policy(bundle.budget_policy)
        self.save_budget_ledger(bundle.budget_ledger)
        self.save_retention_policy(bundle.retention_policy)
        for participant in bundle.participants:
            self.save_participant(participant)
        for edge in bundle.edges:
            self.save_edge(edge)
        for event in bundle.initial_events:
            self.append_event(event, retention_policy=bundle.retention_policy)

    def _repair_run_create_bundle(self, bundle: InterAgentRunCreateBundle) -> None:
        workspace_id = bundle.run.workspace_id
        self._save_budget_policy_if_missing(bundle.budget_policy)
        self._save_budget_ledger_if_missing(bundle.budget_ledger)
        self._save_retention_policy_if_missing(bundle.retention_policy)
        for participant in bundle.participants:
            if self.collections.participants.find_one(
                {
                    "workspace_id": workspace_id,
                    "run_id": participant.run_id,
                    "participant_id": participant.participant_id,
                }
            ) is None:
                self.save_participant(participant)
        for edge in bundle.edges:
            if self.collections.edges.find_one({"workspace_id": workspace_id, "edge_id": edge.edge_id}) is None:
                self.save_edge(edge)
        for event in bundle.initial_events:
            self.append_event(event, retention_policy=bundle.retention_policy)

    def _save_budget_policy_if_missing(self, record: BudgetPolicyRecord) -> None:
        if self.collections.budget_policies.find_one(
            {"workspace_id": record.workspace_id, "budget_policy_id": record.budget_policy_id}
        ) is None:
            self.save_budget_policy(record)

    def _save_budget_ledger_if_missing(self, record: BudgetLedgerRecord) -> None:
        if self.collections.budget_ledgers.find_one(
            {"workspace_id": record.workspace_id, "budget_ledger_id": record.budget_ledger_id}
        ) is None:
            self.save_budget_ledger(record)

    def _save_retention_policy_if_missing(self, record: EventRetentionPolicyRecord) -> None:
        if self.collections.retention_policies.find_one(
            {"workspace_id": record.workspace_id, "retention_policy_id": record.retention_policy_id}
        ) is None:
            self.save_retention_policy(record)

    def save_run(self, record: InterAgentRunRecord) -> InterAgentRunRecord:
        self.collections.runs.update_one(
            {"workspace_id": record.workspace_id, "run_id": record.run_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def pause_run_if_active(
        self,
        run_id: str,
        *,
        workspace_id: str,
        now: datetime,
    ) -> InterAgentRunRecord:
        """Persist the pause under the workspace transition lock."""
        with self._workspace_lock(workspace_id):
            run = self.get_run(run_id, workspace_id=workspace_id)
            if run.status in {"completed", "failed", "cancelled"}:
                return run
            paused = replace(run, status="paused", updated_at=now)
            self.save_run(paused)
            return paused

    def get_run(self, run_id: str, *, workspace_id: str) -> InterAgentRunRecord:
        document = self.collections.runs.find_one({"workspace_id": workspace_id, "run_id": run_id})
        if document is None:
            raise InterAgentRunNotFoundError(
                f"Inter-agent run `{run_id}` was not found in workspace `{workspace_id}`."
            )
        return _run_from_document(document)

    def find_run_by_idempotency_key(self, workspace_id: str, idempotency_key: str) -> InterAgentRunRecord | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        document = self.collections.runs.find_one({"workspace_id": workspace_id, "idempotency_key": key})
        return _run_from_document(document) if document is not None else None

    def list_runs(self, workspace_id: str) -> list[InterAgentRunRecord]:
        return [_run_from_document(document) for document in self.collections.runs.find({"workspace_id": workspace_id})]

    def delete_run_records(self, run_id: str, *, workspace_id: str) -> dict[str, int]:
        """Delete one run's inter-agent records from the workspace store."""
        normalized_run_id = _require_identifier(run_id, "run_id")
        normalized_workspace_id = _require_identifier(workspace_id, "workspace_id")
        run_documents = list(
            self.collections.runs.find({"workspace_id": normalized_workspace_id, "run_id": normalized_run_id})
        )
        deleted = {
            "runs": 0,
            "participants": self._delete_matching(
                self.collections.participants,
                {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
                "participant_id",
            ),
            "edges": self._delete_matching(
                self.collections.edges,
                {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
                "edge_id",
            ),
            "approvals": self._delete_matching(
                self.collections.approvals,
                {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
                "approval_id",
            ),
            "budget_policies": 0,
            "budget_ledgers": self._delete_matching(
                self.collections.budget_ledgers,
                {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
                "budget_ledger_id",
            ),
            "retention_policies": 0,
            "events": self._delete_matching(
                self.collections.events,
                {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
                "event_id",
            ),
        }
        for run_document in run_documents:
            budget_policy_id = run_document.get("budget_policy_id")
            retention_policy_id = run_document.get("retention_policy_id")
            if isinstance(budget_policy_id, str):
                deleted["budget_policies"] += self._delete_matching(
                    self.collections.budget_policies,
                    {"workspace_id": normalized_workspace_id, "budget_policy_id": budget_policy_id},
                    "budget_policy_id",
                )
            if isinstance(retention_policy_id, str):
                deleted["retention_policies"] += self._delete_matching(
                    self.collections.retention_policies,
                    {"workspace_id": normalized_workspace_id, "retention_policy_id": retention_policy_id},
                    "retention_policy_id",
                )
        deleted["runs"] = self._delete_matching(
            self.collections.runs,
            {"workspace_id": normalized_workspace_id, "run_id": normalized_run_id},
            "run_id",
        )
        return deleted

    def _delete_matching(self, collection: DocumentCollection, query: dict[str, Any], identity_field: str) -> int:
        deleted = 0
        for document in list(collection.find(query)):
            identity_value = document.get(identity_field)
            if isinstance(identity_value, str):
                collection.delete_one({**query, identity_field: identity_value})
                deleted += 1
        return deleted

    def save_participant(self, record: InterAgentParticipantRecord) -> InterAgentParticipantRecord:
        self.collections.participants.update_one(
            {
                "workspace_id": record.workspace_id,
                "run_id": record.run_id,
                "participant_id": record.participant_id,
            },
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def claim_participant_runtime_session(
        self,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        runtime_session_id: str,
        now: datetime,
    ) -> tuple[InterAgentRunRecord, InterAgentParticipantRecord, bool]:
        """Link a child session only while its run and participant remain runnable."""
        with self._workspace_lock(workspace_id):
            run = self.get_run(run_id, workspace_id=workspace_id)
            participant = self.get_participant(
                participant_id,
                workspace_id=workspace_id,
                run_id=run_id,
            )
            if run.status in {"paused", "completed", "failed", "cancelled"} or participant.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                return run, participant, False
            updated_participant = replace(
                participant,
                runtime_session_id=runtime_session_id,
                status="running",
                updated_at=now,
            )
            self.save_participant(updated_participant)
            if run.status in {"created", "planning", "recovering"}:
                run = replace(run, status="running", updated_at=now)
                self.save_run(run)
            return run, updated_participant, True

    def cancel_participant_if_active(
        self,
        *,
        workspace_id: str,
        run_id: str,
        participant_id: str,
        now: datetime,
    ) -> tuple[InterAgentParticipantRecord, InterAgentParticipantRecord, bool]:
        """Cancel a participant once under the workspace transition lock."""
        with self._workspace_lock(workspace_id):
            participant = self.get_participant(
                participant_id,
                workspace_id=workspace_id,
                run_id=run_id,
            )
            if participant.status in {"completed", "failed", "cancelled"}:
                return participant, participant, False
            updated = replace(participant, status="cancelled", current_task_id=None, updated_at=now)
            self.save_participant(updated)
            return participant, updated, True

    def get_participant(
        self,
        participant_id: str,
        *,
        workspace_id: str,
        run_id: str,
    ) -> InterAgentParticipantRecord:
        document = self.collections.participants.find_one(
            {"workspace_id": workspace_id, "run_id": run_id, "participant_id": participant_id}
        )
        if document is None:
            raise InterAgentParticipantNotFoundError(
                f"Inter-agent participant `{participant_id}` was not found in run `{run_id}`."
            )
        return _participant_from_document(document)

    def list_participants(self, run_id: str, *, workspace_id: str) -> list[InterAgentParticipantRecord]:
        documents = self.collections.participants.find({"workspace_id": workspace_id, "run_id": run_id})
        records = [_participant_from_document(document) for document in documents]
        records.sort(key=_participant_sort_key)
        return records

    def save_edge(self, record: InterAgentEdgeRecord) -> InterAgentEdgeRecord:
        self.collections.edges.update_one(
            {"workspace_id": record.workspace_id, "edge_id": record.edge_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_edge(self, edge_id: str, *, workspace_id: str) -> InterAgentEdgeRecord:
        document = self.collections.edges.find_one({"workspace_id": workspace_id, "edge_id": edge_id})
        if document is None:
            raise InterAgentEdgeNotFoundError(
                f"Inter-agent edge `{edge_id}` was not found in workspace `{workspace_id}`."
            )
        return _edge_from_document(document)

    def list_edges(self, run_id: str, *, workspace_id: str) -> list[InterAgentEdgeRecord]:
        records = [
            _edge_from_document(document)
            for document in self.collections.edges.find({"workspace_id": workspace_id, "run_id": run_id})
        ]
        records.sort(key=lambda item: (item.created_at, item.edge_id))
        return records

    def save_approval(self, record: ApprovalRequestRecord) -> ApprovalRequestRecord:
        self.collections.approvals.update_one(
            {"workspace_id": record.workspace_id, "approval_id": record.approval_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_approval(self, approval_id: str, *, workspace_id: str) -> ApprovalRequestRecord:
        document = self.collections.approvals.find_one({"workspace_id": workspace_id, "approval_id": approval_id})
        if document is None:
            raise InterAgentApprovalNotFoundError(
                f"Inter-agent approval `{approval_id}` was not found in workspace `{workspace_id}`."
            )
        return _approval_from_document(document)

    def list_approvals(self, run_id: str, *, workspace_id: str) -> list[ApprovalRequestRecord]:
        records = [
            _approval_from_document(document)
            for document in self.collections.approvals.find({"workspace_id": workspace_id, "run_id": run_id})
        ]
        records.sort(key=lambda item: (item.expires_at, item.approval_id))
        return records

    def save_budget_policy(self, record: BudgetPolicyRecord) -> BudgetPolicyRecord:
        self.collections.budget_policies.update_one(
            {"workspace_id": record.workspace_id, "budget_policy_id": record.budget_policy_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_budget_policy(self, budget_policy_id: str, *, workspace_id: str) -> BudgetPolicyRecord:
        document = self.collections.budget_policies.find_one(
            {"workspace_id": workspace_id, "budget_policy_id": budget_policy_id}
        )
        if document is None:
            raise InterAgentBudgetPolicyNotFoundError(
                f"Budget policy `{budget_policy_id}` was not found in workspace `{workspace_id}`."
            )
        return _budget_policy_from_document(document)

    def save_budget_ledger(self, record: BudgetLedgerRecord) -> BudgetLedgerRecord:
        self.collections.budget_ledgers.update_one(
            {"workspace_id": record.workspace_id, "budget_ledger_id": record.budget_ledger_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_budget_ledger(self, budget_ledger_id: str, *, workspace_id: str) -> BudgetLedgerRecord:
        document = self.collections.budget_ledgers.find_one(
            {"workspace_id": workspace_id, "budget_ledger_id": budget_ledger_id}
        )
        if document is None:
            raise InterAgentBudgetLedgerNotFoundError(
                f"Budget ledger `{budget_ledger_id}` was not found in workspace `{workspace_id}`."
            )
        return _budget_ledger_from_document(document)

    def reserve_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        budget_policy_id: str,
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
    ) -> BudgetLedgerRecord:
        policy = self.get_budget_policy(budget_policy_id, workspace_id=workspace_id)
        if policy.workspace_id != workspace_id:
            raise InterAgentValidationError("Budget policy workspace_id does not match the requested ledger workspace.")
        mutation = _BudgetReservationMutation(
            policy=policy,
            reservation=BudgetReservation(
                reservation_id=_require_identifier(reservation_id, "reservation_id"),
                participant_id=_clean_optional(participant_id),
                participant_slots=_non_negative_int(participant_slots, "participant_slots"),
                running_participants=_non_negative_int(running_participants, "running_participants"),
                turns=_non_negative_int(turns, "turns"),
                tool_calls=_non_negative_int(tool_calls, "tool_calls"),
                handoffs=_non_negative_int(handoffs, "handoffs"),
                estimated_tokens=_non_negative_int(estimated_tokens, "estimated_tokens"),
                estimated_cost=_to_decimal(estimated_cost),
                status="reserved",
                created_at=now or datetime.now(tz=UTC),
            ),
        )
        ledger = self._mutate_budget_ledger(
            workspace_id=workspace_id,
            budget_ledger_id=budget_ledger_id,
            mutator=mutation.reserve,
        )
        return ledger

    def release_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        reservation_id: str,
        now: datetime | None = None,
    ) -> BudgetLedgerRecord:
        mutation = _BudgetReleaseMutation(
            reservation_id=_require_identifier(reservation_id, "reservation_id"),
            released_at=now or datetime.now(tz=UTC),
        )
        return self._mutate_budget_ledger(
            workspace_id=workspace_id,
            budget_ledger_id=budget_ledger_id,
            mutator=mutation.release,
        )

    def save_retention_policy(self, record: EventRetentionPolicyRecord) -> EventRetentionPolicyRecord:
        self.collections.retention_policies.update_one(
            {"workspace_id": record.workspace_id, "retention_policy_id": record.retention_policy_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_retention_policy(self, retention_policy_id: str, *, workspace_id: str) -> EventRetentionPolicyRecord:
        document = self.collections.retention_policies.find_one(
            {"workspace_id": workspace_id, "retention_policy_id": retention_policy_id}
        )
        if document is None:
            raise InterAgentEventNotFoundError(
                f"Retention policy `{retention_policy_id}` was not found in workspace `{workspace_id}`."
            )
        return _retention_policy_from_document(document)

    def append_event(
        self,
        record: InterAgentEventRecord,
        *,
        retention_policy: EventRetentionPolicyRecord,
    ) -> InterAgentEventRecord:
        if retention_policy.workspace_id != record.workspace_id:
            raise InterAgentValidationError("Retention policy workspace_id does not match the event workspace_id.")
        stored_document = self.collections.events.append_event(
            validate_event_record(record),
            retention_policy=retention_policy,
        )
        return _event_from_document(stored_document)

    def list_event_page(
        self,
        run_id: str,
        *,
        workspace_id: str,
        visibility_plane: InterAgentVisibilityPlane = "summary",
        event_types: set[str] | None = None,
        after_event_id: str | None = None,
        before_event_id: str | None = None,
        limit: int = DEFAULT_INTER_AGENT_EVENT_LIMIT,
    ) -> InterAgentEventPage:
        bounded_limit = max(1, min(int(limit), MAX_INTER_AGENT_EVENT_LIMIT))
        query: dict[str, Any] = {"workspace_id": workspace_id, "run_id": run_id}
        page = self.collections.events.find_event_page(
            query,
            visibility_plane=validate_visibility_plane(visibility_plane),
            event_types=set(event_types) if event_types else None,
            after_event_id=after_event_id,
            before_event_id=before_event_id,
            limit=bounded_limit,
        )
        if (after_event_id or before_event_id) and not page.get("cursor_found", True):
            cursor = after_event_id or before_event_id
            raise InterAgentEventNotFoundError(
                f"Inter-agent event cursor `{cursor}` was not found in run `{run_id}`."
            )
        events = [_event_from_document(document) for document in page["documents"]]
        return InterAgentEventPage(
            events=events,
            visibility_plane=validate_visibility_plane(visibility_plane),
            limit=bounded_limit,
            after_event_id=after_event_id,
            before_event_id=before_event_id,
            has_more_before=bool(page.get("has_more_before")),
            has_more_after=bool(page.get("has_more_after")),
            oldest_event_id=events[0].event_id if events else None,
            newest_event_id=events[-1].event_id if events else None,
        )

    def list_recovery_events(
        self,
        run_id: str,
        *,
        workspace_id: str,
        event_types: set[str] | None = None,
    ) -> list[InterAgentEventRecord]:
        """Replay durable scheduler records completely in sequence order."""
        requested_types = (
            set(INTER_AGENT_RECOVERY_EVENT_TYPES) if event_types is None else set(event_types)
        )
        unsupported_types = requested_types - INTER_AGENT_RECOVERY_EVENT_TYPES
        if unsupported_types:
            raise InterAgentValidationError(
                "Inter-agent recovery replay does not support event types: "
                + ", ".join(sorted(unsupported_types))
            )
        if not requested_types:
            return []
        pages: list[list[InterAgentEventRecord]] = []
        before_event_id: str | None = None
        visited_cursors: set[str] = set()
        while True:
            page = self.list_event_page(
                run_id,
                workspace_id=workspace_id,
                visibility_plane="debug",
                event_types=requested_types,
                before_event_id=before_event_id,
                limit=MAX_INTER_AGENT_EVENT_LIMIT,
            )
            pages.append(page.events)
            if not page.has_more_before:
                break
            next_cursor = page.oldest_event_id
            if not next_cursor or next_cursor in visited_cursors:
                raise InterAgentValidationError(
                    f"Inter-agent recovery replay for run `{run_id}` could not advance its event cursor."
                )
            visited_cursors.add(next_cursor)
            before_event_id = next_cursor
        return [event for page_events in reversed(pages) for event in page_events]

    def _mutate_budget_ledger(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        mutator: Callable[[BudgetLedgerRecord], BudgetLedgerRecord],
    ) -> BudgetLedgerRecord:
        mutate_one = getattr(self.collections.budget_ledgers, "mutate_one", None)
        if callable(mutate_one):
            document = mutate_one(
                {"workspace_id": workspace_id, "budget_ledger_id": budget_ledger_id},
                lambda item: _to_document(mutator(_budget_ledger_from_document(item))),
            )
            return _budget_ledger_from_document(document)
        ledger = self.get_budget_ledger(budget_ledger_id, workspace_id=workspace_id)
        if ledger.workspace_id != workspace_id:
            raise InterAgentValidationError("Budget ledger workspace_id does not match the requested workspace.")
        updated = mutator(ledger)
        self.save_budget_ledger(updated)
        return updated

    def _workspace_lock(self, workspace_id: str):
        lock_path = getattr(self.collections.runs, "workspace_lock_path", None)
        if callable(lock_path):
            return _locked_json_path(lock_path(workspace_id))
        return self._lock


class WorkspaceInterAgentJsonCollection:
    """Persist workspace-scoped inter-agent records under runtime/inter_agent."""

    def __init__(self, *, start_path: Path, filename: str) -> None:
        self.start_path = start_path
        self.filename = filename
        self._lock = RLock()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_json_path(path):
                    for document in _read_documents(path):
                        if _matches(document, query):
                            return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        with self._lock:
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_json_path(path):
                    matches.extend(deepcopy(document) for document in _read_documents(path) if _matches(document, query))
        return matches

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Inter-agent {self.filename} updates require workspace_id.")
        path = self._record_path(workspace_id)
        with self._lock:
            with _locked_json_path(path):
                documents = _read_documents(path)
                for index, document in enumerate(documents):
                    if _matches(document, query):
                        documents[index] = {**document, **payload}
                        _write_documents(path, documents)
                        return
                if upsert:
                    documents.append({**deepcopy(query), **payload})
                    _write_documents(path, documents)

    def mutate_one(
        self,
        query: dict[str, Any],
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        workspace_id = str(query.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Inter-agent {self.filename} mutations require workspace_id.")
        path = self._record_path(workspace_id)
        with self._lock:
            with _locked_json_path(path):
                documents = _read_documents(path)
                for index, document in enumerate(documents):
                    if _matches(document, query):
                        updated = mutator(deepcopy(document))
                        documents[index] = updated
                        _write_documents(path, documents)
                        return deepcopy(updated)
        raise InterAgentBudgetLedgerNotFoundError(f"Budget ledger `{query.get('budget_ledger_id')}` was not found.")

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_json_path(path):
                    documents = _read_documents(path)
                    filtered = [document for document in documents if not _matches(document, query)]
                    if len(filtered) != len(documents):
                        _write_documents(path, filtered)
                        return

    def _candidate_paths(self, query: dict[str, Any]) -> list[Path]:
        workspace_id = str(query.get("workspace_id") or "").strip()
        if workspace_id:
            return [self._record_path(workspace_id)]
        raise InterAgentValidationError(f"Inter-agent {self.filename} reads require workspace_id.")

    def _record_path(self, workspace_id: str) -> Path:
        return workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path) / "inter_agent" / self.filename

    def workspace_lock_path(self, workspace_id: str) -> Path:
        return (
            workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path)
            / "inter_agent"
            / "workspace_lock.json"
        )


class InterAgentEventJsonCollection(WorkspaceInterAgentJsonCollection):
    """Persist inter-agent events in per-run partitions."""

    def __init__(self, *, start_path: Path) -> None:
        super().__init__(start_path=start_path, filename="events.json")

    def append_event(
        self,
        record: InterAgentEventRecord,
        *,
        retention_policy: EventRetentionPolicyRecord,
    ) -> dict[str, Any]:
        path = self._event_path(workspace_id=record.workspace_id, run_id=record.run_id)
        incoming = _to_document(record)
        incoming["idempotency_fingerprint"] = _event_idempotency_fingerprint(incoming)
        with self._lock:
            with _locked_json_path(path):
                documents = _read_documents(path)
                existing = _find_existing_event(documents, incoming)
                if existing is not None:
                    _ensure_idempotency_fingerprint_matches(
                        existing.get("idempotency_fingerprint") or _event_idempotency_fingerprint(existing),
                        incoming["idempotency_fingerprint"],
                        alternate_incoming=_legacy_inter_agent_event_fingerprint(existing, incoming),
                        entity="inter-agent event",
                    )
                    return deepcopy(existing)
                next_sequence = _next_event_sequence(documents)
                stored = {**incoming, "sequence": next_sequence}
                documents.append(stored)
                documents = _pruned_event_documents(documents, retention_policy=retention_policy)
                _write_documents(path, documents)
                return deepcopy(stored)

    def find_event_page(
        self,
        query: dict[str, Any],
        *,
        visibility_plane: InterAgentVisibilityPlane,
        event_types: set[str] | None,
        after_event_id: str | None,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        if after_event_id and before_event_id:
            raise InterAgentValidationError("Use either after_event_id or before_event_id, not both.")
        documents: list[dict[str, Any]] = []
        for path in self._candidate_paths(query):
            if not path.is_file():
                continue
            with self._lock:
                with _locked_json_path(path):
                    documents.extend(deepcopy(document) for document in _read_documents(path) if _matches(document, query))
        documents.sort(key=_event_sort_key)
        visible_planes = visible_planes_for(visibility_plane)
        documents = [document for document in documents if document.get("visibility_plane") in visible_planes]
        if after_event_id:
            cursor_index = _event_cursor_index(documents, after_event_id)
            if cursor_index is None:
                return {"documents": [], "has_more_before": False, "has_more_after": False, "cursor_found": False}
            selected = _filter_event_documents_by_type(documents[cursor_index + 1 :], event_types)
            return {
                "documents": selected[:limit],
                "has_more_before": bool(selected),
                "has_more_after": len(selected) > limit,
                "cursor_found": True,
            }
        if before_event_id:
            cursor_index = _event_cursor_index(documents, before_event_id)
            if cursor_index is None:
                return {"documents": [], "has_more_before": False, "has_more_after": False, "cursor_found": False}
            before_documents = _filter_event_documents_by_type(documents[:cursor_index], event_types)
            has_more_before = len(before_documents) > limit
            return {
                "documents": before_documents[-limit:],
                "has_more_before": has_more_before,
                "has_more_after": True,
                "cursor_found": True,
            }
        documents = _filter_event_documents_by_type(documents, event_types)
        has_more_before = len(documents) > limit
        return {
            "documents": documents[-limit:],
            "has_more_before": has_more_before,
            "has_more_after": False,
            "cursor_found": True,
        }

    def _candidate_paths(self, query: dict[str, Any]) -> list[Path]:
        workspace_id = str(query.get("workspace_id") or "").strip()
        run_id = str(query.get("run_id") or "").strip()
        if workspace_id and run_id:
            return [self._event_path(workspace_id=workspace_id, run_id=run_id)]
        if workspace_id:
            return sorted(
                workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path).glob(
                    "inter_agent/runs/*/events.json"
                )
            )
        raise InterAgentValidationError("Inter-agent event reads require workspace_id.")

    def _event_path(self, *, workspace_id: str, run_id: str) -> Path:
        return (
            workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path)
            / "inter_agent"
            / "runs"
            / run_id
            / "events.json"
        )


def build_inter_agent_document_store(*, start_path: Path) -> InterAgentDocumentStore:
    """Build the workspace-scoped JSON store for inter-agent domain records."""
    return InterAgentDocumentStore(
        InterAgentCollections(
            runs=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="runs.json"),
            participants=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="participants.json"),
            edges=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="edges.json"),
            approvals=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="approvals.json"),
            budget_policies=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="budget_policies.json"),
            budget_ledgers=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="budget_ledgers.json"),
            events=InterAgentEventJsonCollection(start_path=start_path),
            retention_policies=WorkspaceInterAgentJsonCollection(start_path=start_path, filename="retention_policies.json"),
        )
    )


@dataclass(frozen=True)
class _BudgetReservationMutation:
    policy: BudgetPolicyRecord
    reservation: BudgetReservation

    def reserve(self, ledger: BudgetLedgerRecord) -> BudgetLedgerRecord:
        if ledger.workspace_id != self.policy.workspace_id:
            raise InterAgentValidationError("Budget ledger workspace_id does not match the policy workspace_id.")
        reservations = dict(ledger.operation_reservations)
        existing_document = reservations.get(self.reservation.reservation_id)
        incoming_fingerprint = _budget_reservation_fingerprint(self.reservation)
        if existing_document is not None:
            existing = budget_reservation_from_document(existing_document)
            _ensure_idempotency_fingerprint_matches(
                _existing_budget_reservation_fingerprint(existing_document, existing),
                incoming_fingerprint,
                alternate_incoming=_legacy_budget_reservation_fingerprint(self.reservation)
                if "participant_id" not in existing_document
                else None,
                entity="budget reservation",
            )
            if existing.status == "reserved":
                return ledger
            return ledger
        _ensure_budget_allows_reservation(ledger, self.policy, self.reservation)
        reservation = replace(self.reservation, fingerprint=incoming_fingerprint)
        reservations[self.reservation.reservation_id] = budget_reservation_to_document(reservation)
        return replace(
            ledger,
            reserved_participants=ledger.reserved_participants + reservation.participant_slots,
            running_participants=ledger.running_participants + reservation.running_participants,
            turns_used=ledger.turns_used + reservation.turns,
            tool_calls_used=ledger.tool_calls_used + reservation.tool_calls,
            handoffs_used=ledger.handoffs_used + reservation.handoffs,
            estimated_tokens_used=ledger.estimated_tokens_used + reservation.estimated_tokens,
            estimated_cost_used=ledger.estimated_cost_used + reservation.estimated_cost,
            operation_reservations=reservations,
            updated_at=reservation.created_at,
        )


@dataclass(frozen=True)
class _BudgetReleaseMutation:
    reservation_id: str
    released_at: datetime

    def release(self, ledger: BudgetLedgerRecord) -> BudgetLedgerRecord:
        reservations = dict(ledger.operation_reservations)
        existing_document = reservations.get(self.reservation_id)
        if existing_document is None:
            return ledger
        existing = budget_reservation_from_document(existing_document)
        if existing.status == "released":
            return ledger
        released = replace(existing, status="released", released_at=self.released_at)
        reservations[self.reservation_id] = budget_reservation_to_document(released)
        return replace(
            ledger,
            reserved_participants=max(0, ledger.reserved_participants - existing.participant_slots),
            running_participants=max(0, ledger.running_participants - existing.running_participants),
            turns_used=max(0, ledger.turns_used - existing.turns),
            tool_calls_used=max(0, ledger.tool_calls_used - existing.tool_calls),
            handoffs_used=max(0, ledger.handoffs_used - existing.handoffs),
            estimated_tokens_used=max(0, ledger.estimated_tokens_used - existing.estimated_tokens),
            estimated_cost_used=max(Decimal("0"), ledger.estimated_cost_used - existing.estimated_cost),
            operation_reservations=reservations,
            updated_at=self.released_at,
        )


def _ensure_budget_allows_reservation(
    ledger: BudgetLedgerRecord,
    policy: BudgetPolicyRecord,
    reservation: BudgetReservation,
) -> None:
    if ledger.reserved_participants + reservation.participant_slots > policy.max_participants:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_participants.")
    if ledger.running_participants + reservation.running_participants > policy.max_concurrent_participants:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_concurrent_participants.")
    if ledger.turns_used + reservation.turns > policy.max_total_turns:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_total_turns.")
    if reservation.turns:
        if not reservation.participant_id:
            raise InterAgentValidationError("Turn budget reservations require participant_id.")
        if (
            policy.max_turns_per_participant
            and _turns_used_by_participant(ledger, reservation.participant_id) + reservation.turns > policy.max_turns_per_participant
        ):
            raise InterAgentBudgetExceededError("Budget reservation would exceed max_turns_per_participant.")
    if ledger.tool_calls_used + reservation.tool_calls > policy.max_tool_calls:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_tool_calls.")
    if ledger.handoffs_used + reservation.handoffs > policy.max_handoffs:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_handoffs.")
    if policy.max_estimated_tokens and ledger.estimated_tokens_used + reservation.estimated_tokens > policy.max_estimated_tokens:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_estimated_tokens.")
    if policy.max_estimated_cost and ledger.estimated_cost_used + reservation.estimated_cost > policy.max_estimated_cost:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_estimated_cost.")


def _turns_used_by_participant(ledger: BudgetLedgerRecord, participant_id: str) -> int:
    turns = 0
    for document in ledger.operation_reservations.values():
        reservation = budget_reservation_from_document(document)
        if reservation.status == "released":
            continue
        owner_participant_id = _reservation_participant_id(reservation)
        if owner_participant_id is not None and owner_participant_id != participant_id:
            continue
        turns += reservation.turns
    return turns


def _reservation_participant_id(reservation: BudgetReservation) -> str | None:
    if reservation.participant_id:
        return reservation.participant_id
    parts = reservation.reservation_id.split(":")
    if len(parts) >= 3 and parts[0] == "executor.turn":
        return _clean_optional(parts[1])
    return None


def _validate_run_create_bundle(bundle: InterAgentRunCreateBundle) -> None:
    workspace_id = bundle.run.workspace_id
    run_id = bundle.run.run_id
    if bundle.budget_policy.workspace_id != workspace_id:
        raise InterAgentValidationError("Run budget policy workspace_id does not match the run workspace_id.")
    if bundle.budget_ledger.workspace_id != workspace_id or bundle.budget_ledger.run_id != run_id:
        raise InterAgentValidationError("Run budget ledger scope does not match the run scope.")
    if bundle.retention_policy.workspace_id != workspace_id:
        raise InterAgentValidationError("Run retention policy workspace_id does not match the run workspace_id.")
    for participant in bundle.participants:
        if participant.workspace_id != workspace_id or participant.run_id != run_id:
            raise InterAgentValidationError("Participant scope does not match the run scope.")
    for edge in bundle.edges:
        if edge.workspace_id != workspace_id or edge.run_id != run_id:
            raise InterAgentValidationError("Edge scope does not match the run scope.")
    for event in bundle.initial_events:
        if event.workspace_id != workspace_id or event.run_id != run_id:
            raise InterAgentValidationError("Initial event scope does not match the run scope.")


def _ensure_spec_fingerprint_matches(existing: InterAgentRunRecord, incoming: InterAgentRunRecord) -> None:
    if existing.spec_fingerprint and incoming.spec_fingerprint and existing.spec_fingerprint != incoming.spec_fingerprint:
        raise InterAgentIdempotencyConflictError(
            f"Inter-agent run idempotency key `{incoming.idempotency_key}` was reused with a different run spec."
        )


def _ensure_idempotency_fingerprint_matches(
    existing: str,
    incoming: str,
    *,
    entity: str,
    alternate_incoming: str | None = None,
) -> None:
    if existing != incoming and existing != alternate_incoming:
        raise InterAgentIdempotencyConflictError(f"Idempotent {entity} retry payload does not match the original.")


def _budget_reservation_fingerprint(reservation: BudgetReservation) -> str:
    document = budget_reservation_to_document(reservation)
    return _budget_reservation_document_fingerprint(document)


def _legacy_budget_reservation_fingerprint(reservation: BudgetReservation) -> str:
    document = budget_reservation_to_document(reservation)
    document.pop("participant_id", None)
    return _budget_reservation_document_fingerprint(document)


def _existing_budget_reservation_fingerprint(document: dict[str, Any], reservation: BudgetReservation) -> str:
    if reservation.fingerprint:
        return reservation.fingerprint
    return _budget_reservation_document_fingerprint(document)


def _budget_reservation_document_fingerprint(document: dict[str, Any]) -> str:
    document = dict(document)
    for key in ("status", "created_at", "released_at", "fingerprint"):
        document.pop(key, None)
    return _stable_fingerprint(document)


def _event_idempotency_fingerprint(document: dict[str, Any]) -> str:
    payload = dict(document)
    for key in ("event_id", "sequence", "created_at", "idempotency_fingerprint"):
        payload.pop(key, None)
    return _stable_fingerprint(payload)


def _legacy_inter_agent_event_fingerprint(existing: dict[str, Any], incoming: dict[str, Any]) -> str | None:
    if existing.get("event_type") != "inter_agent.budget.reserved":
        return None
    if incoming.get("event_type") != "inter_agent.budget.reserved":
        return None
    existing_payload = existing.get("payload")
    incoming_payload = incoming.get("payload")
    if not isinstance(existing_payload, dict) or not isinstance(incoming_payload, dict):
        return None
    if "participant_id" in existing_payload or "participant_id" not in incoming_payload:
        return None
    legacy_incoming = dict(incoming)
    legacy_payload = dict(incoming_payload)
    legacy_payload.pop("participant_id", None)
    legacy_incoming["payload"] = legacy_payload
    return _event_idempotency_fingerprint(legacy_incoming)


def _find_existing_event(documents: list[dict[str, Any]], incoming: dict[str, Any]) -> dict[str, Any] | None:
    event_id = incoming.get("event_id")
    idempotency_key = incoming.get("idempotency_key")
    for document in documents:
        if event_id and document.get("event_id") == event_id:
            return document
        if idempotency_key and document.get("idempotency_key") == idempotency_key:
            return document
    return None


def _next_event_sequence(documents: list[dict[str, Any]]) -> int:
    sequence = 0
    for document in documents:
        try:
            sequence = max(sequence, int(document.get("sequence") or 0))
        except (TypeError, ValueError):
            continue
    return sequence + 1


def _pruned_event_documents(
    documents: list[dict[str, Any]],
    *,
    retention_policy: EventRetentionPolicyRecord,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for visibility_plane in ("summary", "detail", "debug"):
        plane_documents = [document for document in documents if document.get("visibility_plane") == visibility_plane]
        plane_documents.sort(key=_event_sort_key)
        recovery_documents = [
            document
            for document in plane_documents
            if document.get("event_type") in INTER_AGENT_RECOVERY_EVENT_TYPES
        ]
        retained_history_documents = [
            document
            for document in plane_documents
            if document.get("event_type") not in INTER_AGENT_RECOVERY_EVENT_TYPES
        ]
        max_events = retention_policy.max_events_for(visibility_plane)  # type: ignore[arg-type]
        kept.extend(recovery_documents)
        if max_events > 0:
            kept.extend(retained_history_documents[-max_events:])
    kept.sort(key=_event_sort_key)
    return kept


def _event_cursor_index(documents: list[dict[str, Any]], event_id: str) -> int | None:
    for index, document in enumerate(documents):
        if document.get("event_id") == event_id:
            return index
    return None


def _filter_event_documents_by_type(documents: list[dict[str, Any]], event_types: set[str] | None) -> list[dict[str, Any]]:
    if not event_types:
        return documents
    return [document for document in documents if document.get("event_type") in event_types]


def _participant_sort_key(record: InterAgentParticipantRecord) -> tuple[int, datetime, str]:
    try:
        sequence_index = int(record.sequence_index)
    except (TypeError, ValueError):
        sequence_index = 0
    return sequence_index, record.created_at, record.participant_id


def _event_sort_key(document: dict[str, Any]) -> tuple[int, str]:
    try:
        sequence = int(document.get("sequence") or 0)
    except (TypeError, ValueError):
        sequence = 0
    return sequence, str(document.get("event_id") or "")


def _run_from_document(document: dict[str, Any]) -> InterAgentRunRecord:
    payload = dict(document)
    payload["visibility_level"] = validate_visibility_plane(payload.get("visibility_level", "summary"))
    payload.setdefault("spec_fingerprint", None)
    payload.setdefault("aggregator_participant_id", None)
    payload.setdefault("merge_policy", None)
    payload.setdefault("source_runtime_turn_id", None)
    payload.setdefault("orchestration_policy", None)
    return InterAgentRunRecord(**payload)


def _participant_from_document(document: dict[str, Any]) -> InterAgentParticipantRecord:
    payload = dict(document)
    payload.setdefault("agent_snapshot", None)
    payload.setdefault("sequence_index", 0)
    return InterAgentParticipantRecord(**payload)


def _edge_from_document(document: dict[str, Any]) -> InterAgentEdgeRecord:
    return InterAgentEdgeRecord(**document)


def _approval_from_document(document: dict[str, Any]) -> ApprovalRequestRecord:
    return ApprovalRequestRecord(**document)


def _budget_policy_from_document(document: dict[str, Any]) -> BudgetPolicyRecord:
    payload = dict(document)
    payload["max_estimated_cost"] = _to_decimal(payload.get("max_estimated_cost") or 0)
    payload["approval_required_above_cost"] = _to_decimal(payload.get("approval_required_above_cost") or 0)
    return BudgetPolicyRecord(**payload)


def _budget_ledger_from_document(document: dict[str, Any]) -> BudgetLedgerRecord:
    payload = dict(document)
    payload["estimated_cost_used"] = _to_decimal(payload.get("estimated_cost_used") or 0)
    payload["operation_reservations"] = {
        str(reservation_id): _normalize_reservation_document(reservation)
        for reservation_id, reservation in dict(payload.get("operation_reservations") or {}).items()
    }
    return BudgetLedgerRecord(**payload)


def _normalize_reservation_document(document: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(document)
    normalized["estimated_cost"] = _to_decimal(normalized.get("estimated_cost") or 0)
    return normalized


def _retention_policy_from_document(document: dict[str, Any]) -> EventRetentionPolicyRecord:
    return EventRetentionPolicyRecord(**document)


def _event_from_document(document: dict[str, Any]) -> InterAgentEventRecord:
    payload = dict(document)
    payload["visibility_plane"] = validate_visibility_plane(payload.get("visibility_plane", "summary"))
    payload.setdefault("idempotency_fingerprint", None)
    return InterAgentEventRecord(**payload)


def _to_document(record: Any) -> dict[str, Any]:
    return _encode_values(asdict(record))


def _encode_values(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _encode_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_values(item) for item in value]
    return value


def _to_decimal(value: Decimal | int | str | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _stable_fingerprint(payload: Any) -> str:
    encoded = json.dumps(_canonical_fingerprint_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_fingerprint_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_canonical_fingerprint_value(item) for item in value]
    return value


def _non_negative_int(value: int, field_name: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise InterAgentValidationError(f"Budget reservation `{field_name}` cannot be negative.")
    return normalized


def _require_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise InterAgentValidationError(f"`{field_name}` is required.")
    return normalized


def _clean_optional(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _read_documents(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to read malformed JSON collection: {path}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"JSON collection `{path}` must contain a JSON array.")
    if not all(isinstance(document, dict) for document in payload):
        raise ValueError(f"JSON collection `{path}` must contain only JSON objects.")
    return payload


def _write_documents(path: Path, documents: list[dict[str, Any]]) -> None:
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError("Inter-agent JSON collections can only store object documents.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(documents, indent=2, default=_encode_document_value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class _locked_json_path:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_locked_json_path":
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = lock_path.open("a+b")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
