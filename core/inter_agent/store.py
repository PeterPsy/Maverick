"""Inter-agent store contracts and workspace-scoped JSON adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import fcntl
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
    InterAgentParticipantNotFoundError,
    InterAgentRunNotFoundError,
    InterAgentValidationError,
)
from core.inter_agent.events import (
    EventRetentionPolicyRecord,
    InterAgentEventPage,
    InterAgentEventRecord,
    InterAgentVisibilityPlane,
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
        after_event_id: str | None,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        ...


class InterAgentStore(Protocol):
    """Persistence contract for inter-agent records and ledgers."""

    def save_run(self, record: InterAgentRunRecord) -> InterAgentRunRecord:
        ...

    def get_run(self, run_id: str) -> InterAgentRunRecord:
        ...

    def find_run_by_idempotency_key(self, workspace_id: str, idempotency_key: str) -> InterAgentRunRecord | None:
        ...

    def list_runs(self, workspace_id: str) -> list[InterAgentRunRecord]:
        ...

    def save_participant(self, record: InterAgentParticipantRecord) -> InterAgentParticipantRecord:
        ...

    def get_participant(self, participant_id: str) -> InterAgentParticipantRecord:
        ...

    def list_participants(self, run_id: str) -> list[InterAgentParticipantRecord]:
        ...

    def save_edge(self, record: InterAgentEdgeRecord) -> InterAgentEdgeRecord:
        ...

    def get_edge(self, edge_id: str) -> InterAgentEdgeRecord:
        ...

    def list_edges(self, run_id: str) -> list[InterAgentEdgeRecord]:
        ...

    def save_approval(self, record: ApprovalRequestRecord) -> ApprovalRequestRecord:
        ...

    def get_approval(self, approval_id: str) -> ApprovalRequestRecord:
        ...

    def list_approvals(self, run_id: str) -> list[ApprovalRequestRecord]:
        ...

    def save_budget_policy(self, record: BudgetPolicyRecord) -> BudgetPolicyRecord:
        ...

    def get_budget_policy(self, budget_policy_id: str) -> BudgetPolicyRecord:
        ...

    def save_budget_ledger(self, record: BudgetLedgerRecord) -> BudgetLedgerRecord:
        ...

    def get_budget_ledger(self, budget_ledger_id: str) -> BudgetLedgerRecord:
        ...

    def reserve_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        budget_policy_id: str,
        reservation_id: str,
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

    def get_retention_policy(self, retention_policy_id: str) -> EventRetentionPolicyRecord:
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
        workspace_id: str | None = None,
        visibility_plane: InterAgentVisibilityPlane = "summary",
        after_event_id: str | None = None,
        before_event_id: str | None = None,
        limit: int = DEFAULT_INTER_AGENT_EVENT_LIMIT,
    ) -> InterAgentEventPage:
        ...


class InterAgentDocumentStore:
    """Persist inter-agent records in document collections."""

    def __init__(self, collections: InterAgentCollections) -> None:
        self.collections = collections

    def save_run(self, record: InterAgentRunRecord) -> InterAgentRunRecord:
        self.collections.runs.update_one({"run_id": record.run_id}, {"$set": _to_document(record)}, upsert=True)
        return record

    def get_run(self, run_id: str) -> InterAgentRunRecord:
        document = self.collections.runs.find_one({"run_id": run_id})
        if document is None:
            raise InterAgentRunNotFoundError(f"Inter-agent run `{run_id}` was not found.")
        return _run_from_document(document)

    def find_run_by_idempotency_key(self, workspace_id: str, idempotency_key: str) -> InterAgentRunRecord | None:
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        document = self.collections.runs.find_one({"workspace_id": workspace_id, "idempotency_key": key})
        return _run_from_document(document) if document is not None else None

    def list_runs(self, workspace_id: str) -> list[InterAgentRunRecord]:
        return [_run_from_document(document) for document in self.collections.runs.find({"workspace_id": workspace_id})]

    def save_participant(self, record: InterAgentParticipantRecord) -> InterAgentParticipantRecord:
        self.collections.participants.update_one(
            {"participant_id": record.participant_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_participant(self, participant_id: str) -> InterAgentParticipantRecord:
        document = self.collections.participants.find_one({"participant_id": participant_id})
        if document is None:
            raise InterAgentParticipantNotFoundError(f"Inter-agent participant `{participant_id}` was not found.")
        return _participant_from_document(document)

    def list_participants(self, run_id: str) -> list[InterAgentParticipantRecord]:
        documents = self.collections.participants.find({"run_id": run_id})
        records = [_participant_from_document(document) for document in documents]
        records.sort(key=lambda item: (item.created_at, item.participant_id))
        return records

    def save_edge(self, record: InterAgentEdgeRecord) -> InterAgentEdgeRecord:
        self.collections.edges.update_one({"edge_id": record.edge_id}, {"$set": _to_document(record)}, upsert=True)
        return record

    def get_edge(self, edge_id: str) -> InterAgentEdgeRecord:
        document = self.collections.edges.find_one({"edge_id": edge_id})
        if document is None:
            raise InterAgentEdgeNotFoundError(f"Inter-agent edge `{edge_id}` was not found.")
        return _edge_from_document(document)

    def list_edges(self, run_id: str) -> list[InterAgentEdgeRecord]:
        records = [_edge_from_document(document) for document in self.collections.edges.find({"run_id": run_id})]
        records.sort(key=lambda item: (item.created_at, item.edge_id))
        return records

    def save_approval(self, record: ApprovalRequestRecord) -> ApprovalRequestRecord:
        self.collections.approvals.update_one(
            {"approval_id": record.approval_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_approval(self, approval_id: str) -> ApprovalRequestRecord:
        document = self.collections.approvals.find_one({"approval_id": approval_id})
        if document is None:
            raise InterAgentApprovalNotFoundError(f"Inter-agent approval `{approval_id}` was not found.")
        return _approval_from_document(document)

    def list_approvals(self, run_id: str) -> list[ApprovalRequestRecord]:
        records = [_approval_from_document(document) for document in self.collections.approvals.find({"run_id": run_id})]
        records.sort(key=lambda item: (item.expires_at, item.approval_id))
        return records

    def save_budget_policy(self, record: BudgetPolicyRecord) -> BudgetPolicyRecord:
        self.collections.budget_policies.update_one(
            {"budget_policy_id": record.budget_policy_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_budget_policy(self, budget_policy_id: str) -> BudgetPolicyRecord:
        document = self.collections.budget_policies.find_one({"budget_policy_id": budget_policy_id})
        if document is None:
            raise InterAgentBudgetPolicyNotFoundError(f"Budget policy `{budget_policy_id}` was not found.")
        return _budget_policy_from_document(document)

    def save_budget_ledger(self, record: BudgetLedgerRecord) -> BudgetLedgerRecord:
        self.collections.budget_ledgers.update_one(
            {"budget_ledger_id": record.budget_ledger_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_budget_ledger(self, budget_ledger_id: str) -> BudgetLedgerRecord:
        document = self.collections.budget_ledgers.find_one({"budget_ledger_id": budget_ledger_id})
        if document is None:
            raise InterAgentBudgetLedgerNotFoundError(f"Budget ledger `{budget_ledger_id}` was not found.")
        return _budget_ledger_from_document(document)

    def reserve_budget(
        self,
        *,
        workspace_id: str,
        budget_ledger_id: str,
        budget_policy_id: str,
        reservation_id: str,
        participant_slots: int = 0,
        running_participants: int = 0,
        turns: int = 0,
        tool_calls: int = 0,
        handoffs: int = 0,
        estimated_tokens: int = 0,
        estimated_cost: Decimal | int | str = Decimal("0"),
        now: datetime | None = None,
    ) -> BudgetLedgerRecord:
        policy = self.get_budget_policy(budget_policy_id)
        if policy.workspace_id != workspace_id:
            raise InterAgentValidationError("Budget policy workspace_id does not match the requested ledger workspace.")
        mutation = _BudgetReservationMutation(
            policy=policy,
            reservation=BudgetReservation(
                reservation_id=_require_identifier(reservation_id, "reservation_id"),
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
            {"retention_policy_id": record.retention_policy_id},
            {"$set": _to_document(record)},
            upsert=True,
        )
        return record

    def get_retention_policy(self, retention_policy_id: str) -> EventRetentionPolicyRecord:
        document = self.collections.retention_policies.find_one({"retention_policy_id": retention_policy_id})
        if document is None:
            raise InterAgentEventNotFoundError(f"Retention policy `{retention_policy_id}` was not found.")
        return _retention_policy_from_document(document)

    def append_event(
        self,
        record: InterAgentEventRecord,
        *,
        retention_policy: EventRetentionPolicyRecord,
    ) -> InterAgentEventRecord:
        stored_document = self.collections.events.append_event(
            validate_event_record(record),
            retention_policy=retention_policy,
        )
        return _event_from_document(stored_document)

    def list_event_page(
        self,
        run_id: str,
        *,
        workspace_id: str | None = None,
        visibility_plane: InterAgentVisibilityPlane = "summary",
        after_event_id: str | None = None,
        before_event_id: str | None = None,
        limit: int = DEFAULT_INTER_AGENT_EVENT_LIMIT,
    ) -> InterAgentEventPage:
        bounded_limit = max(1, min(int(limit), MAX_INTER_AGENT_EVENT_LIMIT))
        query: dict[str, Any] = {"run_id": run_id}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        page = self.collections.events.find_event_page(
            query,
            visibility_plane=validate_visibility_plane(visibility_plane),
            after_event_id=after_event_id,
            before_event_id=before_event_id,
            limit=bounded_limit,
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
        ledger = self.get_budget_ledger(budget_ledger_id)
        if ledger.workspace_id != workspace_id:
            raise InterAgentValidationError("Budget ledger workspace_id does not match the requested workspace.")
        updated = mutator(ledger)
        self.save_budget_ledger(updated)
        return updated


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
        return sorted((self.start_path / "workspaces").glob(f"*/runtime/inter_agent/{self.filename}"))

    def _record_path(self, workspace_id: str) -> Path:
        return workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path) / "inter_agent" / self.filename


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
        with self._lock:
            with _locked_json_path(path):
                documents = _read_documents(path)
                existing = _find_existing_event(documents, incoming)
                if existing is not None:
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
        after_event_id: str | None,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        if after_event_id and before_event_id:
            raise InterAgentValidationError("Use either after_event_id or before_event_id, not both.")
        documents: list[dict[str, Any]] = []
        cursor_seen = after_event_id is None and before_event_id is None
        cursor_found = after_event_id is None and before_event_id is None
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
            selected = []
            for document in documents:
                if cursor_seen:
                    selected.append(document)
                    continue
                if document.get("event_id") == after_event_id:
                    cursor_seen = True
                    cursor_found = True
            return {
                "documents": selected[:limit],
                "has_more_before": bool(selected),
                "has_more_after": len(selected) > limit,
                "cursor_found": cursor_found,
            }
        if before_event_id:
            before_documents = []
            for document in documents:
                if document.get("event_id") == before_event_id:
                    cursor_found = True
                    break
                before_documents.append(document)
            if not cursor_found:
                return {"documents": [], "has_more_before": False, "has_more_after": False, "cursor_found": False}
            has_more_before = len(before_documents) > limit
            return {
                "documents": before_documents[-limit:],
                "has_more_before": has_more_before,
                "has_more_after": True,
                "cursor_found": True,
            }
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
        if run_id:
            return sorted((self.start_path / "workspaces").glob(f"*/runtime/inter_agent/runs/{run_id}/events.json"))
        if workspace_id:
            return sorted(
                workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path).glob(
                    "inter_agent/runs/*/events.json"
                )
            )
        return sorted((self.start_path / "workspaces").glob("*/runtime/inter_agent/runs/*/events.json"))

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
        if existing_document is not None:
            existing = budget_reservation_from_document(existing_document)
            if existing.status == "reserved":
                return ledger
            return ledger
        _ensure_budget_allows_reservation(ledger, self.policy, self.reservation)
        reservations[self.reservation.reservation_id] = budget_reservation_to_document(self.reservation)
        return replace(
            ledger,
            reserved_participants=ledger.reserved_participants + self.reservation.participant_slots,
            running_participants=ledger.running_participants + self.reservation.running_participants,
            turns_used=ledger.turns_used + self.reservation.turns,
            tool_calls_used=ledger.tool_calls_used + self.reservation.tool_calls,
            handoffs_used=ledger.handoffs_used + self.reservation.handoffs,
            estimated_tokens_used=ledger.estimated_tokens_used + self.reservation.estimated_tokens,
            estimated_cost_used=ledger.estimated_cost_used + self.reservation.estimated_cost,
            operation_reservations=reservations,
            updated_at=self.reservation.created_at,
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
    if ledger.tool_calls_used + reservation.tool_calls > policy.max_tool_calls:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_tool_calls.")
    if ledger.handoffs_used + reservation.handoffs > policy.max_handoffs:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_handoffs.")
    if policy.max_estimated_tokens and ledger.estimated_tokens_used + reservation.estimated_tokens > policy.max_estimated_tokens:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_estimated_tokens.")
    if policy.max_estimated_cost and ledger.estimated_cost_used + reservation.estimated_cost > policy.max_estimated_cost:
        raise InterAgentBudgetExceededError("Budget reservation would exceed max_estimated_cost.")


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
        max_events = retention_policy.max_events_for(visibility_plane)  # type: ignore[arg-type]
        if max_events > 0:
            kept.extend(plane_documents[-max_events:])
    kept.sort(key=_event_sort_key)
    return kept


def _event_sort_key(document: dict[str, Any]) -> tuple[int, str]:
    try:
        sequence = int(document.get("sequence") or 0)
    except (TypeError, ValueError):
        sequence = 0
    return sequence, str(document.get("event_id") or "")


def _run_from_document(document: dict[str, Any]) -> InterAgentRunRecord:
    payload = dict(document)
    payload["visibility_level"] = validate_visibility_plane(payload.get("visibility_level", "summary"))
    return InterAgentRunRecord(**payload)


def _participant_from_document(document: dict[str, Any]) -> InterAgentParticipantRecord:
    return InterAgentParticipantRecord(**document)


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
