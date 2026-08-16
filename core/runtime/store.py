"""Runtime-domain store contracts and document-store adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, ContextManager, Protocol

from core.runtime.errors import (
    RuntimeProcessNotFoundError,
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
    RuntimeStateNotFoundError,
    RuntimeThreadNotFoundError,
    RuntimeTurnNotFoundError,
)
from core.runtime.client_message_claims import (
    CLIENT_MESSAGE_CLAIM_LEASE_SECONDS,
    RuntimeClientMessageClaim,
    RuntimeClientMessageClaimConflictError,
)
from core.runtime.app_streams import (
    RuntimeAppStreamError,
    RuntimeAppStreamEventRecord,
    RuntimeAppStreamRecord,
    changed_project_files,
    normalized_stream_event,
    snapshot_project_files,
    stream_status_for_event,
)
from core.runtime.archive_pagination import page_archive_documents
from core.runtime.models import RuntimeLocation
from core.runtime.paths import workspace_runtime_root
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord
from core.runtime.provider_state import RuntimeProviderState, runtime_provider_state_from_document
from core.runtime.runtime_session import RuntimeApiTokenRecord, RuntimeSessionRecord, runtime_session_allows_user_thread, runtime_session_from_document
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.tool_models import ToolConfirmationGrant, ToolInvocationRecord
from core.egress.agentic_models import AgenticEgressDecision
from core.shared.in_memory_collection import InMemoryCollection


MAX_RUNTIME_EVENTS_PER_SESSION = 500
RUNTIME_SESSION_METADATA_FIELDS = frozenset(
    {
        "effective_mode",
        "provider_id",
        "provider_thread_id",
        "runtime_root",
        "thread_visibility",
        "workdir",
        "workspace_root",
    }
)
RUNTIME_TURN_CONTROL_FIELDS = frozenset(
    {
        "cancellation_requested_at",
        "cancellation_reason",
        "provider_request_started_at",
        "provider_request_finished_at",
        "provider_request_owner_id",
        "provider_request_generation",
        "provider_request_owner_kind",
        "provider_request_owner_host_id",
        "provider_request_owner_pid",
        "provider_request_owner_process_start",
        "provider_request_cancellation_acknowledged_at",
        "terminalization_event_id",
        "terminalization_event_type",
        "terminalization_event_payload",
        "terminalization_claimed_at",
        "terminalization_event_persisted_at",
        "terminalization_thread_released_at",
        "terminalization_callback_delivered_at",
    }
)
RUNTIME_TURN_IMMUTABLE_SUBMISSION_FIELDS = frozenset(
    {
        "input_text",
        "client_message_id",
        "created_at",
        "runtime_mode",
        "invoked_skill_ids",
    }
)


def _runtime_turn_lifecycle_payload(record: RuntimeTurnRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in asdict(record).items()
        if key not in RUNTIME_TURN_CONTROL_FIELDS | RUNTIME_TURN_IMMUTABLE_SUBMISSION_FIELDS
    }


@dataclass(frozen=True)
class RuntimeEventPage:
    """One bounded page of ordered runtime events."""

    events: list[RuntimeEventRecord]
    has_more_before: bool
    before_event_id: str | None
    oldest_event_id: str | None
    newest_event_id: str | None


@dataclass(frozen=True)
class RuntimeEventArchivePage:
    """One physical append-order page bounded by an immutable snapshot."""

    events: list[RuntimeEventRecord]
    has_more_before: bool
    oldest_position: int | None
    newest_position: int | None
    snapshot_position: int
    snapshot_event_id: str | None
    snapshot_found: bool


class DocumentCollection(Protocol):
    """Minimal collection protocol used by runtime stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        ...

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class RuntimeCollections:
    """Collection bundle for runtime-domain persistence."""

    sessions: DocumentCollection
    turns: DocumentCollection
    events: DocumentCollection
    processes: DocumentCollection
    states: DocumentCollection
    threads: DocumentCollection
    api_tokens: DocumentCollection | None = None
    client_messages: DocumentCollection | None = None
    app_streams: DocumentCollection | None = None
    app_stream_events: DocumentCollection | None = None
    provider_states: DocumentCollection | None = None
    tool_invocations: DocumentCollection | None = None
    tool_confirmation_grants: DocumentCollection | None = None
    egress_decisions: DocumentCollection | None = None


class RuntimeStore(Protocol):
    """Persistence contract for runtime-domain records."""

    def session_lifecycle_handoff(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> ContextManager[object]:
        ...

    def save_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        ...

    def insert_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        ...

    def patch_session_metadata(
        self,
        *,
        session_id: str,
        workspace_id: str,
        updates: dict[str, object],
        now: datetime | None = None,
    ) -> RuntimeSessionRecord:
        ...

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        ...

    def list_sessions(self, workspace_id: str) -> list[RuntimeSessionRecord]:
        ...

    def runtime_session_thread_visibility_map(self, workspace_id: str) -> dict[str, bool]:
        ...

    def list_all_sessions(self) -> list[RuntimeSessionRecord]:
        ...

    def save_turn(self, record: RuntimeTurnRecord) -> RuntimeTurnRecord:
        ...

    def save_turn_if_cancellation_absent(
        self,
        record: RuntimeTurnRecord,
        *,
        expected_status: str,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def request_turn_cancellation(
        self,
        *,
        turn_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def mark_turn_provider_request_started(
        self,
        *,
        turn_id: str,
        owner_id: str,
        generation: str,
        owner_kind: str,
        owner_host_id: str,
        owner_pid: int,
        owner_process_start: str,
        now: datetime | None = None,
    ) -> RuntimeTurnRecord:
        ...

    def mark_turn_provider_request_finished(
        self,
        *,
        turn_id: str,
        owner_id: str,
        generation: str,
        cancellation_observed: bool = False,
        now: datetime | None = None,
    ) -> RuntimeTurnRecord:
        ...

    def reconcile_turn_provider_request_if_current(
        self,
        *,
        turn_id: str,
        expected_owner_id: str | None,
        expected_generation: str | None,
        expected_started_at: datetime,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def claim_turn_terminalization(
        self,
        *,
        turn_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, object],
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def migrate_legacy_turn_terminalization(
        self,
        *,
        turn_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, object],
        delivered_at: datetime,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def mark_turn_terminalization_phase(
        self,
        *,
        turn_id: str,
        event_id: str,
        phase: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def save_turn_if_client_message_absent(self, record: RuntimeTurnRecord) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def save_turn_if_current_client_message_claim(
        self,
        record: RuntimeTurnRecord,
        claim: RuntimeClientMessageClaim,
        *,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        ...

    def get_turn(self, turn_id: str) -> RuntimeTurnRecord:
        ...

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        ...

    def has_turn_with_status(self, session_id: str, statuses: set[str]) -> bool:
        ...

    def list_recent_turns(self, session_id: str, *, limit: int) -> list[RuntimeTurnRecord]:
        ...

    def find_turn_by_client_message_id(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str | None = None,
    ) -> RuntimeTurnRecord | None:
        ...

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        ...

    def save_turn_event_if_absent(self, record: RuntimeEventRecord) -> tuple[RuntimeEventRecord, bool]:
        ...

    def find_turn_event(self, *, turn_id: str, event_type: str) -> RuntimeEventRecord | None:
        ...

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        ...

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        ...

    def list_event_page(
        self,
        session_id: str,
        *,
        before_event_id: str | None = None,
        limit: int = 200,
    ) -> RuntimeEventPage:
        ...

    def list_event_archive_page(
        self,
        session_id: str,
        *,
        before_position: int | None = None,
        snapshot_position: int | None = None,
        snapshot_event_id: str | None = None,
        limit: int = 200,
    ) -> RuntimeEventArchivePage:
        ...

    def has_events_before(self, session_id: str, *, before_event_id: str | None) -> bool:
        ...

    def list_all_events(self) -> list[RuntimeEventRecord]:
        ...

    def save_process(self, record: RuntimeProcessRecord) -> RuntimeProcessRecord:
        ...

    def get_process(self, process_id: str) -> RuntimeProcessRecord:
        ...

    def list_processes(self, session_id: str) -> list[RuntimeProcessRecord]:
        ...

    def save_state(self, record: RuntimeStateRecord) -> RuntimeStateRecord:
        ...

    def get_state(self, session_id: str) -> RuntimeStateRecord:
        ...

    def initialize_provider_state(self, record: RuntimeProviderState) -> RuntimeProviderState:
        ...

    def get_provider_state(self, session_id: str) -> RuntimeProviderState:
        ...

    def update_provider_state(
        self,
        record: RuntimeProviderState,
        *,
        expected_revision: int,
    ) -> RuntimeProviderState:
        ...

    def initialize_egress_decision(
        self,
        *,
        workspace_id: str,
        record: AgenticEgressDecision,
    ) -> AgenticEgressDecision:
        ...

    def list_egress_decisions(self, *, session_id: str) -> list[AgenticEgressDecision]:
        ...

    def initialize_tool_invocation(self, record: ToolInvocationRecord) -> ToolInvocationRecord:
        ...

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocationRecord:
        ...

    def find_tool_invocation_by_provider_call(
        self, *, session_id: str, turn_id: str, provider_tool_call_id: str
    ) -> ToolInvocationRecord | None:
        ...

    def list_tool_invocations(self, *, session_id: str, turn_id: str | None = None) -> list[ToolInvocationRecord]:
        ...

    def update_tool_invocation(
        self, record: ToolInvocationRecord, *, expected_revision: int
    ) -> ToolInvocationRecord:
        ...

    def initialize_tool_confirmation_grant(self, record: ToolConfirmationGrant) -> ToolConfirmationGrant:
        ...

    def get_tool_confirmation_grant(self, grant_id: str) -> ToolConfirmationGrant:
        ...

    def list_tool_confirmation_grants(self, *, invocation_id: str) -> list[ToolConfirmationGrant]:
        ...

    def update_tool_confirmation_grant(
        self, record: ToolConfirmationGrant, *, expected_revision: int
    ) -> ToolConfirmationGrant:
        ...

    def delete_session_records(self, session_id: str) -> dict[str, int]:
        ...

    def save_thread(self, record: RuntimeThreadRecord) -> RuntimeThreadRecord:
        ...

    def get_thread(self, thread_id: str) -> RuntimeThreadRecord:
        ...

    def get_thread_by_runtime_session_id(self, *, workspace_id: str, runtime_session_id: str) -> RuntimeThreadRecord | None:
        ...

    def list_threads(self, workspace_id: str) -> list[RuntimeThreadRecord]:
        ...

    def delete_thread(self, thread_id: str) -> bool:
        ...

    def save_api_token(self, record: RuntimeApiTokenRecord) -> RuntimeApiTokenRecord:
        ...

    def get_api_token(self, token_id: str) -> RuntimeApiTokenRecord | None:
        ...

    def revoke_api_token(self, token_id: str, *, now: datetime | None = None) -> RuntimeApiTokenRecord | None:
        ...

    def claim_client_message_id(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeClientMessageClaim, bool]:
        ...

    def get_client_message_claim(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
    ) -> RuntimeClientMessageClaim | None:
        ...

    def release_client_message_claim(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        ...

    def mark_client_message_claim_queued(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> RuntimeClientMessageClaim | None:
        ...

    def mark_client_message_claim_status(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        status: str,
        now: datetime | None = None,
    ) -> RuntimeClientMessageClaim | None:
        ...

    def reserve_app_stream(self, record: RuntimeAppStreamRecord) -> tuple[RuntimeAppStreamRecord, bool]:
        ...

    def bind_app_stream(
        self,
        *,
        stream_id: str,
        workspace_id: str,
        source_app_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> RuntimeAppStreamRecord:
        ...

    def get_app_stream(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
    ) -> RuntimeAppStreamRecord:
        ...

    def read_app_stream_events(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
        after_sequence: int = 0,
        limit: int = 64,
    ) -> list[RuntimeAppStreamEventRecord]:
        ...

    def fail_app_stream(
        self,
        *,
        stream_id: str,
        workspace_id: str,
        source_app_id: str,
        now: datetime | None = None,
    ) -> RuntimeAppStreamRecord:
        ...

    def list_app_streams_for_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> list[RuntimeAppStreamRecord]:
        ...

    def has_nonterminal_app_stream_for_session(self, *, workspace_id: str, session_id: str) -> bool:
        ...


class RuntimeDocumentStore:
    """Persist runtime-domain records in document-style collections."""

    def __init__(self, collections: RuntimeCollections) -> None:
        self.collections = collections
        self._provider_states = collections.provider_states or InMemoryCollection()
        self._tool_invocations = collections.tool_invocations or InMemoryCollection()
        self._tool_confirmation_grants = collections.tool_confirmation_grants or InMemoryCollection()
        self._egress_decisions = collections.egress_decisions or InMemoryCollection()
        self._fallback_lock = RLock()
        self._partition_index_lock = RLock()
        self._session_workspace_index: dict[str, str] = {}
        self._turn_partition_index: dict[str, tuple[str, str]] = {}

    def session_lifecycle_handoff(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> ContextManager[object]:
        """Return the shared lock for persisted session and turn transitions."""
        lifecycle_handoff = getattr(self.collections.sessions, "lifecycle_handoff", None)
        if callable(lifecycle_handoff):
            return lifecycle_handoff(workspace_id=workspace_id, session_id=session_id)
        return self._fallback_lock

    def save_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        identity = {"session_id": record.session_id, "workspace_id": record.workspace_id}
        existing_document = self.collections.sessions.find_one(identity)
        if existing_document is not None:
            existing_binding = runtime_session_from_document(existing_document).execution_binding
            binding_changed = existing_binding != record.execution_binding
            legacy_migration = (
                existing_binding is None
                and record.execution_binding is not None
                and record.execution_binding.legacy_inferred
            )
            if binding_changed and not legacy_migration:
                raise RuntimeProviderStateError(
                    f"Runtime session `{record.session_id}` execution binding is immutable."
                )
        payload = asdict(record)
        # Mutable provider continuation metadata is authoritative only in
        # RuntimeProviderState. Keep the legacy field readable for migration,
        # but never create or update it through session writes.
        payload.pop("provider_thread_id", None)
        self.collections.sessions.update_one(
            identity,
            {"$set": payload},
            upsert=True,
        )
        self._remember_session_partition(record.session_id, record.workspace_id)
        return record

    def initialize_tool_invocation(self, record: ToolInvocationRecord) -> ToolInvocationRecord:
        if record.revision != 0 or record.state != "proposed":
            raise RuntimeProviderStateError("Initial tool invocation must be proposed at revision zero.")
        existing, inserted = self._insert_one_if_absent(
            self._tool_invocations,
            {"invocation_id": record.invocation_id},
            asdict(record),
        )
        if not inserted:
            raise RuntimeProviderStateError(f"Tool invocation `{record.invocation_id}` already exists.")
        return ToolInvocationRecord(**existing)

    def initialize_egress_decision(
        self,
        *,
        workspace_id: str,
        record: AgenticEgressDecision,
    ) -> AgenticEgressDecision:
        """Persist one content decision before export; exact retries are idempotent."""
        payload = {**asdict(record), "workspace_id": workspace_id}
        existing, inserted = self._insert_one_if_absent(
            self._egress_decisions,
            {
                "decision_id": record.decision_id,
                "session_id": record.session_id,
                "workspace_id": workspace_id,
            },
            payload,
        )
        existing_payload = dict(existing)
        existing_payload.pop("workspace_id", None)
        persisted = AgenticEgressDecision(**existing_payload)
        if not inserted and replace(persisted, decided_at=record.decided_at) != record:
            raise RuntimeProviderStateError(
                f"Egress decision `{record.decision_id}` identity conflict."
            )
        return persisted

    def list_egress_decisions(self, *, session_id: str) -> list[AgenticEgressDecision]:
        records: list[AgenticEgressDecision] = []
        for document in self._egress_decisions.find({"session_id": session_id}):
            payload = dict(document)
            payload.pop("workspace_id", None)
            records.append(AgenticEgressDecision(**payload))
        return records

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocationRecord:
        document = self._tool_invocations.find_one({"invocation_id": invocation_id})
        if document is None:
            raise RuntimeProviderStateError(f"Tool invocation `{invocation_id}` was not found.")
        return ToolInvocationRecord(**document)

    def find_tool_invocation_by_provider_call(
        self, *, session_id: str, turn_id: str, provider_tool_call_id: str
    ) -> ToolInvocationRecord | None:
        document = self._tool_invocations.find_one(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "provider_tool_call_id": provider_tool_call_id,
            }
        )
        return None if document is None else ToolInvocationRecord(**document)

    def list_tool_invocations(
        self, *, session_id: str, turn_id: str | None = None
    ) -> list[ToolInvocationRecord]:
        query = {"session_id": session_id}
        if turn_id is not None:
            query["turn_id"] = turn_id
        return [ToolInvocationRecord(**document) for document in self._tool_invocations.find(query)]

    def update_tool_invocation(
        self, record: ToolInvocationRecord, *, expected_revision: int
    ) -> ToolInvocationRecord:
        if record.revision != expected_revision + 1:
            raise RuntimeProviderStateError("Tool invocation revision must advance by one.")
        current = self.get_tool_invocation(record.invocation_id)
        permitted = replace(
            current,
            state=record.state,
            confirmation_grant_id=record.confirmation_grant_id,
            result_private_ref=record.result_private_ref,
            result_summary=record.result_summary,
            failure_reason=record.failure_reason,
            revision=record.revision,
            updated_at=record.updated_at,
        )
        if permitted != record:
            raise RuntimeProviderStateError("Tool invocation identity fields are immutable.")
        applied = self._tool_invocations.compare_and_set(
            {
                "invocation_id": record.invocation_id,
                "workspace_id": record.workspace_id,
                "session_id": record.session_id,
                "revision": expected_revision,
            },
            {"$set": asdict(record)},
        )
        if not applied:
            raise RuntimeProviderStateError("tool_invocation_revision_conflict")
        return record

    def initialize_tool_confirmation_grant(self, record: ToolConfirmationGrant) -> ToolConfirmationGrant:
        if record.revision != 0:
            raise RuntimeProviderStateError("Initial tool confirmation grant must use revision zero.")
        existing, inserted = self._insert_one_if_absent(
            self._tool_confirmation_grants,
            {"grant_id": record.grant_id},
            asdict(record),
        )
        if not inserted:
            raise RuntimeProviderStateError(f"Tool confirmation grant `{record.grant_id}` already exists.")
        return ToolConfirmationGrant(**existing)

    def get_tool_confirmation_grant(self, grant_id: str) -> ToolConfirmationGrant:
        document = self._tool_confirmation_grants.find_one({"grant_id": grant_id})
        if document is None:
            raise RuntimeProviderStateError(f"Tool confirmation grant `{grant_id}` was not found.")
        return ToolConfirmationGrant(**document)

    def list_tool_confirmation_grants(self, *, invocation_id: str) -> list[ToolConfirmationGrant]:
        return [
            ToolConfirmationGrant(**document)
            for document in self._tool_confirmation_grants.find({"invocation_id": invocation_id})
        ]

    def update_tool_confirmation_grant(
        self, record: ToolConfirmationGrant, *, expected_revision: int
    ) -> ToolConfirmationGrant:
        if record.revision != expected_revision + 1:
            raise RuntimeProviderStateError("Tool confirmation revision must advance by one.")
        current = self.get_tool_confirmation_grant(record.grant_id)
        permitted = replace(
            current,
            state=record.state,
            revision=record.revision,
            updated_at=record.updated_at,
        )
        if permitted != record:
            raise RuntimeProviderStateError("Tool confirmation grant identity fields are immutable.")
        applied = self._tool_confirmation_grants.compare_and_set(
            {
                "grant_id": record.grant_id,
                "workspace_id": record.workspace_id,
                "session_id": record.session_id,
                "revision": expected_revision,
            },
            {"$set": asdict(record)},
        )
        if not applied:
            raise RuntimeProviderStateError("tool_confirmation_revision_conflict")
        return record

    def insert_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        """Insert one session aggregate without overwriting an existing binding."""
        payload = asdict(record)
        payload.pop("provider_thread_id", None)
        _document, inserted = self._insert_one_if_absent(
            self.collections.sessions,
            {"session_id": record.session_id, "workspace_id": record.workspace_id},
            payload,
        )
        if not inserted:
            raise RuntimeProviderStateError(
                f"Runtime session `{record.session_id}` already exists; its execution binding is immutable."
            )
        self._remember_session_partition(record.session_id, record.workspace_id)
        return record

    def patch_session_metadata(
        self,
        *,
        session_id: str,
        workspace_id: str,
        updates: dict[str, object],
        now: datetime | None = None,
    ) -> RuntimeSessionRecord:
        """Patch allowlisted session metadata without writing lifecycle fields."""
        invalid_fields = sorted(set(updates) - RUNTIME_SESSION_METADATA_FIELDS)
        if invalid_fields:
            raise ValueError(
                "Runtime session metadata patch contains forbidden fields: "
                + ", ".join(invalid_fields)
            )
        with self.session_lifecycle_handoff(workspace_id=workspace_id, session_id=session_id):
            current = self.get_session(session_id)
            if current.workspace_id != workspace_id:
                raise RuntimeSessionNotFoundError(
                    f"Runtime session `{session_id}` was not found in workspace `{workspace_id}`."
                )
            if not updates:
                return current
            if "provider_thread_id" in updates and current.execution_binding is not None:
                raise RuntimeProviderStateError(
                    "Pinned sessions store provider thread metadata only in RuntimeProviderState."
                )
            payload = {**updates, "updated_at": now or datetime.now(tz=UTC)}
            self.collections.sessions.update_one(
                {"session_id": session_id, "workspace_id": workspace_id},
                {"$set": payload},
                upsert=False,
            )
            return replace(current, **payload)

    def save_api_token(self, record: RuntimeApiTokenRecord) -> RuntimeApiTokenRecord:
        if self.collections.api_tokens is None:
            return record
        self.collections.api_tokens.update_one({"token_id": record.token_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_api_token(self, token_id: str) -> RuntimeApiTokenRecord | None:
        if self.collections.api_tokens is None:
            return None
        document = self.collections.api_tokens.find_one({"token_id": token_id})
        if document is None:
            return None
        return RuntimeApiTokenRecord(**document)

    def revoke_api_token(self, token_id: str, *, now: datetime | None = None) -> RuntimeApiTokenRecord | None:
        record = self.get_api_token(token_id)
        if record is None:
            return None
        revoked = replace(record, status="revoked", revoked_at=now or datetime.now(tz=UTC))
        self.save_api_token(revoked)
        return revoked

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        query = self._session_query(session_id)
        document = self.collections.sessions.find_one(query)
        if document is None and "workspace_id" in query:
            self._forget_session_partition(session_id)
            document = self.collections.sessions.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeSessionNotFoundError(f"Runtime session `{session_id}` was not found.")
        session = runtime_session_from_document(document)
        self._remember_session_partition(session.session_id, session.workspace_id)
        return self._session_with_provider_state(session)

    def list_sessions(self, workspace_id: str) -> list[RuntimeSessionRecord]:
        return [
            self._session_with_provider_state(session)
            for session in _valid_runtime_sessions(self.collections.sessions.find({"workspace_id": workspace_id}))
        ]

    def runtime_session_thread_visibility_map(self, workspace_id: str) -> dict[str, bool]:
        visibility: dict[str, bool] = {}
        for document in self.collections.sessions.find({"workspace_id": workspace_id}):
            session_id = str(document.get("session_id") or "").strip()
            if not session_id:
                continue
            try:
                visibility[session_id] = runtime_session_allows_user_thread(runtime_session_from_document(document))
            except ValueError:
                visibility[session_id] = False
        return visibility

    def list_all_sessions(self) -> list[RuntimeSessionRecord]:
        return [
            self._session_with_provider_state(session)
            for session in _valid_runtime_sessions(self.collections.sessions.find({}))
        ]

    def delete_session_records(self, session_id: str) -> dict[str, int]:
        session_document = self.collections.sessions.find_one({"session_id": session_id}) or {}
        workspace_id = session_document.get("workspace_id") if isinstance(session_document, dict) else None
        deleted = {
            "sessions": 1 if session_document else 0,
            "turns": 0,
            "events": 0,
            "processes": 0,
            "states": 0,
            "provider_states": 0,
            "api_tokens": 0,
            "client_messages": 0,
            "app_streams": 0,
            "app_stream_events": 0,
            "tool_invocations": 0,
            "tool_confirmation_grants": 0,
            "egress_decisions": 0,
        }
        deleted["turns"] = _delete_session_records(
            self.collections.turns,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="turn_id",
        )
        deleted["events"] = _delete_session_records(
            self.collections.events,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="event_id",
        )
        deleted["processes"] = _delete_session_records(
            self.collections.processes,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="process_id",
        )
        deleted["states"] = _delete_session_records(
            self.collections.states,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="session_id",
        )
        deleted["provider_states"] = _delete_session_records(
            self._provider_states,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="session_id",
        )
        deleted["tool_invocations"] = _delete_session_records(
            self._tool_invocations,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="invocation_id",
        )
        deleted["tool_confirmation_grants"] = _delete_session_records(
            self._tool_confirmation_grants,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="grant_id",
        )
        deleted["egress_decisions"] = _delete_session_records(
            self._egress_decisions,
            session_id=session_id,
            workspace_id=workspace_id,
            identity_field="decision_id",
        )
        if self.collections.api_tokens is not None:
            deleted["api_tokens"] = _delete_session_records(
                self.collections.api_tokens,
                session_id=session_id,
                workspace_id=workspace_id,
                identity_field="token_id",
            )
        if self.collections.client_messages is not None:
            deleted["client_messages"] = _delete_session_records(
                self.collections.client_messages,
                session_id=session_id,
                workspace_id=workspace_id,
                identity_field="client_message_id",
            )
        if self.collections.app_stream_events is not None:
            deleted["app_stream_events"] = _delete_session_records(
                self.collections.app_stream_events,
                session_id=session_id,
                workspace_id=workspace_id,
                identity_field="event_id",
            )
        if self.collections.app_streams is not None:
            stream_query = {"session_id": session_id}
            if workspace_id:
                stream_query["workspace_id"] = workspace_id
            for document in self.collections.app_streams.find(stream_query):
                stream_id = document.get("stream_id")
                if not isinstance(stream_id, str):
                    continue
                delete_query = {"stream_id": stream_id}
                if workspace_id:
                    delete_query["workspace_id"] = workspace_id
                self.collections.app_streams.delete_one(delete_query)
                deleted["app_streams"] += 1
        session_delete_query = {"session_id": session_id}
        if workspace_id:
            session_delete_query["workspace_id"] = workspace_id
        self.collections.sessions.delete_one(session_delete_query)
        self._forget_session_partition(session_id)
        self._forget_turns_for_session(session_id)
        return deleted

    def save_turn(self, record: RuntimeTurnRecord) -> RuntimeTurnRecord:
        payload = _runtime_turn_lifecycle_payload(record)
        identity = {
            "turn_id": record.turn_id,
            "workspace_id": record.workspace_id,
            "session_id": record.session_id,
        }
        existing, inserted = self._insert_runtime_turn_if_absent(identity, asdict(record))
        if inserted:
            persisted = RuntimeTurnRecord(**existing)
            self._remember_turn_partition(persisted)
            return persisted
        self.collections.turns.update_one(identity, {"$set": payload}, upsert=False)
        persisted = RuntimeTurnRecord(**{**existing, **payload})
        self._remember_turn_partition(persisted)
        return persisted

    def save_turn_if_cancellation_absent(
        self,
        record: RuntimeTurnRecord,
        *,
        expected_status: str,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Atomically save one lifecycle transition only while no cancel intent exists."""
        self.collections.turns.update_one(
            {
                "turn_id": record.turn_id,
                "workspace_id": record.workspace_id,
                "session_id": record.session_id,
                "status": expected_status,
                "cancellation_requested_at": None,
            },
            {"$set": _runtime_turn_lifecycle_payload(record)},
            upsert=False,
        )
        persisted = self.get_turn(record.turn_id)
        applied = persisted.status == record.status
        return persisted, applied

    def request_turn_cancellation(
        self,
        *,
        turn_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Persist a cancellation intent and report whether this caller won its CAS."""
        timestamp = now or datetime.now(tz=UTC)
        while True:
            current = self.get_turn(turn_id)
            if current.status not in {
                "queued",
                "active",
                "waiting_for_tool_confirmation",
            } or current.cancellation_requested_at is not None:
                return current, False
            update_result = self.collections.turns.update_one(
                {
                    "turn_id": current.turn_id,
                    "workspace_id": current.workspace_id,
                    "session_id": current.session_id,
                    "status": current.status,
                    "cancellation_requested_at": None,
                },
                {
                    "$set": {
                        "cancellation_requested_at": timestamp,
                        "cancellation_reason": reason,
                    }
                },
                upsert=False,
            )
            refreshed = self.get_turn(turn_id)
            applied = update_result is True or bool(getattr(update_result, "modified_count", 0))
            if applied:
                return refreshed, True
            if refreshed.cancellation_requested_at is not None or refreshed.status not in {
                "queued",
                "active",
                "waiting_for_tool_confirmation",
            }:
                return refreshed, False

    def mark_turn_provider_request_started(
        self,
        *,
        turn_id: str,
        owner_id: str,
        generation: str,
        owner_kind: str,
        owner_host_id: str,
        owner_pid: int,
        owner_process_start: str,
        now: datetime | None = None,
    ) -> RuntimeTurnRecord:
        """Acquire a generation-fenced lease before one hosted request blocks."""
        normalized_owner_id = owner_id.strip()
        normalized_generation = generation.strip()
        normalized_owner_kind = owner_kind.strip()
        normalized_owner_host_id = owner_host_id.strip()
        normalized_owner_process_start = owner_process_start.strip()
        if (
            not normalized_owner_id
            or not normalized_generation
            or not normalized_owner_kind
            or not normalized_owner_host_id
            or owner_pid < 1
            or not normalized_owner_process_start
        ):
            raise ValueError("Hosted provider request leases require verifiable process ownership.")
        current = self.get_turn(turn_id)
        if current.provider_request_started_at is not None and current.provider_request_finished_at is None:
            if (
                current.provider_request_owner_id == normalized_owner_id
                and current.provider_request_generation == normalized_generation
            ):
                return current
            raise RuntimeError(f"Runtime turn `{turn_id}` already has an active hosted provider request lease.")
        timestamp = now or datetime.now(tz=UTC)
        self.collections.turns.update_one(
            {
                "turn_id": current.turn_id,
                "workspace_id": current.workspace_id,
                "session_id": current.session_id,
                "provider_request_started_at": current.provider_request_started_at,
                "provider_request_finished_at": current.provider_request_finished_at,
                "provider_request_owner_id": current.provider_request_owner_id,
                "provider_request_generation": current.provider_request_generation,
            },
            {
                "$set": {
                    "provider_request_started_at": timestamp,
                    "provider_request_finished_at": None,
                    "provider_request_owner_id": normalized_owner_id,
                    "provider_request_generation": normalized_generation,
                    "provider_request_owner_kind": normalized_owner_kind,
                    "provider_request_owner_host_id": normalized_owner_host_id,
                    "provider_request_owner_pid": owner_pid,
                    "provider_request_owner_process_start": normalized_owner_process_start,
                    "provider_request_cancellation_acknowledged_at": None,
                }
            },
            upsert=False,
        )
        persisted = self.get_turn(turn_id)
        if (
            persisted.provider_request_owner_id != normalized_owner_id
            or persisted.provider_request_generation != normalized_generation
        ):
            raise RuntimeError(f"Runtime turn `{turn_id}` hosted provider request lease was acquired concurrently.")
        return persisted

    def mark_turn_provider_request_finished(
        self,
        *,
        turn_id: str,
        owner_id: str,
        generation: str,
        cancellation_observed: bool = False,
        now: datetime | None = None,
    ) -> RuntimeTurnRecord:
        """Acknowledge one hosted request only when its exact lease still owns the turn."""
        normalized_owner_id = owner_id.strip()
        normalized_generation = generation.strip()
        if not normalized_owner_id or not normalized_generation:
            raise ValueError("Hosted provider request acknowledgement requires owner_id and generation.")
        current = self.get_turn(turn_id)
        if (
            current.provider_request_started_at is None
            or current.provider_request_finished_at is not None
            or current.provider_request_owner_id != normalized_owner_id
            or current.provider_request_generation != normalized_generation
        ):
            return current
        timestamp = now or datetime.now(tz=UTC)
        finished_payload = {"provider_request_finished_at": timestamp}
        if cancellation_observed:
            finished_payload["provider_request_cancellation_acknowledged_at"] = timestamp
        self.collections.turns.update_one(
            {
                "turn_id": current.turn_id,
                "workspace_id": current.workspace_id,
                "session_id": current.session_id,
                "provider_request_finished_at": None,
                "provider_request_owner_id": normalized_owner_id,
                "provider_request_generation": normalized_generation,
            },
            {"$set": finished_payload},
            upsert=False,
        )
        return self.get_turn(turn_id)

    def reconcile_turn_provider_request_if_current(
        self,
        *,
        turn_id: str,
        expected_owner_id: str | None,
        expected_generation: str | None,
        expected_started_at: datetime,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Close one exact lease after its process owner was proven dead."""
        current = self.get_turn(turn_id)
        if (
            current.provider_request_started_at != expected_started_at
            or current.provider_request_finished_at is not None
            or current.provider_request_owner_id != expected_owner_id
            or current.provider_request_generation != expected_generation
        ):
            return current, False
        timestamp = now or datetime.now(tz=UTC)
        self.collections.turns.update_one(
            {
                "turn_id": current.turn_id,
                "workspace_id": current.workspace_id,
                "session_id": current.session_id,
                "provider_request_started_at": expected_started_at,
                "provider_request_finished_at": None,
                "provider_request_owner_id": expected_owner_id,
                "provider_request_generation": expected_generation,
            },
            {"$set": {"provider_request_finished_at": timestamp}},
            upsert=False,
        )
        persisted = self.get_turn(turn_id)
        applied = (
            persisted.provider_request_started_at == expected_started_at
            and persisted.provider_request_owner_id == expected_owner_id
            and persisted.provider_request_generation == expected_generation
            and persisted.provider_request_finished_at is not None
        )
        return persisted, applied

    def claim_turn_terminalization(
        self,
        *,
        turn_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, object],
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Atomically assign the durable terminalization outbox to one writer."""
        normalized_event_id = event_id.strip()
        normalized_event_type = event_type.strip()
        if not normalized_event_id or not normalized_event_type:
            raise ValueError("Runtime turn terminalization requires event_id and event_type.")
        timestamp = now or datetime.now(tz=UTC)
        while True:
            current = self.get_turn(turn_id)
            expected_event_type = f"runtime.turn.{current.status}"
            if current.status not in {"completed", "failed", "cancelled", "timed-out"}:
                return current, False
            if normalized_event_type != expected_event_type:
                return current, False
            if current.terminalization_event_id is not None:
                return current, False
            self.collections.turns.update_one(
                {
                    "turn_id": current.turn_id,
                    "workspace_id": current.workspace_id,
                    "session_id": current.session_id,
                    "status": current.status,
                    "terminalization_event_id": None,
                },
                {
                    "$set": {
                        "terminalization_event_id": normalized_event_id,
                        "terminalization_event_type": normalized_event_type,
                        "terminalization_event_payload": dict(payload),
                        "terminalization_claimed_at": timestamp,
                    }
                },
                upsert=False,
            )
            persisted = self.get_turn(turn_id)
            if persisted.terminalization_event_id is not None:
                return persisted, persisted.terminalization_event_id == normalized_event_id

    def migrate_legacy_turn_terminalization(
        self,
        *,
        turn_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, object],
        delivered_at: datetime,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Adopt pre-outbox event/callback delivery while leaving thread reconciliation pending."""
        normalized_event_id = event_id.strip()
        normalized_event_type = event_type.strip()
        if not normalized_event_id or not normalized_event_type:
            raise ValueError("Legacy runtime turn terminalization requires event_id and event_type.")
        current = self.get_turn(turn_id)
        if normalized_event_type != f"runtime.turn.{current.status}":
            return current, False
        if current.terminalization_event_id is not None:
            return current, False
        self.collections.turns.update_one(
            {
                "turn_id": current.turn_id,
                "workspace_id": current.workspace_id,
                "session_id": current.session_id,
                "status": current.status,
                "terminalization_event_id": None,
            },
            {
                "$set": {
                    "terminalization_event_id": normalized_event_id,
                    "terminalization_event_type": normalized_event_type,
                    "terminalization_event_payload": dict(payload),
                    "terminalization_claimed_at": delivered_at,
                    "terminalization_event_persisted_at": delivered_at,
                    "terminalization_callback_delivered_at": delivered_at,
                }
            },
            upsert=False,
        )
        persisted = self.get_turn(turn_id)
        applied = (
            persisted.terminalization_event_id == normalized_event_id
            and persisted.terminalization_event_type == normalized_event_type
            and persisted.terminalization_event_persisted_at is not None
            and persisted.terminalization_callback_delivered_at is not None
        )
        return persisted, applied

    def mark_turn_terminalization_phase(
        self,
        *,
        turn_id: str,
        event_id: str,
        phase: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        """Mark one exact outbox phase complete without accepting a stale worker."""
        phase_fields = {
            "event": "terminalization_event_persisted_at",
            "thread": "terminalization_thread_released_at",
            "callback": "terminalization_callback_delivered_at",
        }
        field = phase_fields.get(phase)
        if field is None:
            raise ValueError(f"Unknown runtime turn terminalization phase `{phase}`.")
        current = self.get_turn(turn_id)
        if current.terminalization_event_id != event_id or getattr(current, field) is not None:
            return current, False
        timestamp = now or datetime.now(tz=UTC)
        self.collections.turns.update_one(
            {
                "turn_id": current.turn_id,
                "workspace_id": current.workspace_id,
                "session_id": current.session_id,
                "terminalization_event_id": event_id,
                field: None,
            },
            {"$set": {field: timestamp}},
            upsert=False,
        )
        persisted = self.get_turn(turn_id)
        return persisted, persisted.terminalization_event_id == event_id and getattr(persisted, field) is not None

    def save_turn_if_client_message_absent(self, record: RuntimeTurnRecord) -> tuple[RuntimeTurnRecord, bool]:
        normalized_client_message_id = record.client_message_id.strip() if isinstance(record.client_message_id, str) else ""
        if not normalized_client_message_id:
            return self.save_turn(record), True
        query = {
            "workspace_id": record.workspace_id,
            "session_id": record.session_id,
            "client_message_id": normalized_client_message_id,
        }
        document, inserted = self._insert_one_if_absent(self.collections.turns, query, asdict(record))
        turn = RuntimeTurnRecord(**document)
        self._remember_turn_partition(turn)
        return turn, inserted

    def save_turn_if_current_client_message_claim(
        self,
        record: RuntimeTurnRecord,
        claim: RuntimeClientMessageClaim,
        *,
        now: datetime | None = None,
    ) -> tuple[RuntimeTurnRecord, bool]:
        normalized_client_message_id = record.client_message_id.strip() if isinstance(record.client_message_id, str) else ""
        if not normalized_client_message_id:
            return self.save_turn(record), True
        collection = self.collections.client_messages
        if collection is None:
            return self.save_turn_if_client_message_absent(record)
        if not _client_message_claim_matches_record(claim, record, normalized_client_message_id):
            raise ValueError("Runtime turn does not match the expected client message claim.")
        timestamp = now or datetime.now(tz=UTC)
        identity_query = {"workspace_id": record.workspace_id, "client_message_id": normalized_client_message_id}
        with self._fallback_lock:
            current_document = collection.find_one(identity_query)
            current_claim = _client_message_claim_from_document(current_document) if current_document is not None else None
            if current_claim is None or not _client_message_claim_matches(current_claim, claim):
                raise RuntimeClientMessageClaimConflictError(current_claim)
            if _client_message_claim_is_expired(current_claim, timestamp):
                raise RuntimeClientMessageClaimConflictError(current_claim)
            turn_query = {
                "workspace_id": record.workspace_id,
                "client_message_id": normalized_client_message_id,
            }
            document, inserted = self._insert_one_if_absent(self.collections.turns, turn_query, asdict(record))
            turn = RuntimeTurnRecord(**document)
            if turn.session_id != record.session_id or turn.turn_id != record.turn_id:
                raise RuntimeClientMessageClaimConflictError(current_claim)
            self._remember_turn_partition(turn)
            self.mark_client_message_claim_queued(
                workspace_id=claim.workspace_id,
                client_message_id=claim.client_message_id,
                session_id=claim.session_id,
                turn_id=claim.turn_id,
                now=timestamp,
            )
            return turn, inserted

    def get_turn(self, turn_id: str) -> RuntimeTurnRecord:
        query = self._turn_query(turn_id)
        document = self.collections.turns.find_one(query)
        if document is None and "workspace_id" in query:
            self._forget_turn_partition(turn_id)
            document = self.collections.turns.find_one({"turn_id": turn_id})
        if document is None:
            raise RuntimeTurnNotFoundError(f"Runtime turn `{turn_id}` was not found.")
        turn = RuntimeTurnRecord(**document)
        self._remember_turn_partition(turn)
        return turn

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        turns = [RuntimeTurnRecord(**document) for document in self.collections.turns.find(self._session_query(session_id))]
        for turn in turns:
            self._remember_turn_partition(turn)
        return turns

    def has_turn_with_status(self, session_id: str, statuses: set[str]) -> bool:
        base_query = self._session_query(session_id)
        for status in statuses:
            if self.collections.turns.find_one({**base_query, "status": status}) is not None:
                return True
        return False

    def list_recent_turns(self, session_id: str, *, limit: int) -> list[RuntimeTurnRecord]:
        if limit < 1:
            return []
        find_recent = getattr(self.collections.turns, "find_recent", None)
        query = self._session_query(session_id)
        if callable(find_recent):
            documents = find_recent(query, limit=limit)
        else:
            documents = self.collections.turns.find(query)
            documents.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("turn_id") or "")))
            documents = documents[-limit:]
        turns = [RuntimeTurnRecord(**document) for document in documents]
        for turn in turns:
            self._remember_turn_partition(turn)
        return turns

    def find_turn_by_client_message_id(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str | None = None,
    ) -> RuntimeTurnRecord | None:
        normalized_client_message_id = client_message_id.strip()
        if not workspace_id or not normalized_client_message_id:
            return None
        query = {
            "workspace_id": workspace_id,
            "client_message_id": normalized_client_message_id,
        }
        if session_id:
            query["session_id"] = session_id
        document = self.collections.turns.find_one(query)
        if document is None:
            return None
        turn = RuntimeTurnRecord(**document)
        self._remember_turn_partition(turn)
        return turn

    def claim_client_message_id(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeClientMessageClaim, bool]:
        normalized_client_message_id = client_message_id.strip()
        if not workspace_id or not normalized_client_message_id or not session_id or not turn_id:
            raise ValueError("Runtime client message claims require workspace_id, client_message_id, session_id, and turn_id.")
        timestamp = now or datetime.now(tz=UTC)
        lease_expires_at = timestamp + timedelta(seconds=CLIENT_MESSAGE_CLAIM_LEASE_SECONDS)
        claim = RuntimeClientMessageClaim(
            workspace_id=workspace_id,
            client_message_id=normalized_client_message_id,
            session_id=session_id,
            turn_id=turn_id,
            created_at=timestamp,
            updated_at=timestamp,
            status="claimed",
            lease_expires_at=lease_expires_at,
        )
        collection = self.collections.client_messages
        if collection is None:
            return claim, True
        identity_query = {"workspace_id": workspace_id, "client_message_id": normalized_client_message_id}
        with self._fallback_lock:
            document, inserted = self._insert_one_if_absent(collection, identity_query, asdict(claim))
            existing = _client_message_claim_from_document(document)
            if inserted:
                return existing, True
            if self._claim_has_persisted_turn(existing):
                return existing, False
            if not _client_message_claim_is_expired(existing, timestamp):
                return existing, False
            replace_query = _client_message_claim_replace_query(document, identity_query)
            collection.update_one(replace_query, {"$set": asdict(claim)}, upsert=False)
            replaced_document = collection.find_one(identity_query)
            if replaced_document is None:
                return existing, False
            replaced = _client_message_claim_from_document(replaced_document)
            return replaced, replaced.session_id == session_id and replaced.turn_id == turn_id

    def get_client_message_claim(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
    ) -> RuntimeClientMessageClaim | None:
        normalized_client_message_id = client_message_id.strip()
        collection = self.collections.client_messages
        if collection is None or not workspace_id or not normalized_client_message_id:
            return None
        document = collection.find_one(
            {"workspace_id": workspace_id, "client_message_id": normalized_client_message_id}
        )
        return _client_message_claim_from_document(document) if document is not None else None

    def release_client_message_claim(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        normalized_client_message_id = client_message_id.strip()
        collection = self.collections.client_messages
        if collection is None or not workspace_id or not normalized_client_message_id:
            return False
        query = {
            "workspace_id": workspace_id,
            "client_message_id": normalized_client_message_id,
            "session_id": session_id,
            "turn_id": turn_id,
        }
        if collection.find_one(query) is None:
            return False
        collection.delete_one(query)
        return True

    def mark_client_message_claim_queued(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> RuntimeClientMessageClaim | None:
        return self.mark_client_message_claim_status(
            workspace_id=workspace_id,
            client_message_id=client_message_id,
            session_id=session_id,
            turn_id=turn_id,
            status="queued",
            now=now,
        )

    def mark_client_message_claim_status(
        self,
        *,
        workspace_id: str,
        client_message_id: str,
        session_id: str,
        turn_id: str,
        status: str,
        now: datetime | None = None,
    ) -> RuntimeClientMessageClaim | None:
        normalized_client_message_id = client_message_id.strip()
        normalized_status = status.strip()
        if normalized_status not in {"queued", "steered", "delivery_uncertain"}:
            raise ValueError(f"Unsupported runtime client message claim status `{normalized_status}`.")
        collection = self.collections.client_messages
        if collection is None or not workspace_id or not normalized_client_message_id:
            return None
        timestamp = now or datetime.now(tz=UTC)
        query = {
            "workspace_id": workspace_id,
            "client_message_id": normalized_client_message_id,
            "session_id": session_id,
            "turn_id": turn_id,
        }
        collection.update_one(
            query,
            {"$set": {"status": normalized_status, "lease_expires_at": None, "updated_at": timestamp}},
            upsert=False,
        )
        document = collection.find_one(query)
        return _client_message_claim_from_document(document) if document is not None else None

    def reserve_app_stream(self, record: RuntimeAppStreamRecord) -> tuple[RuntimeAppStreamRecord, bool]:
        """Atomically reserve one workspace/app idempotency key."""
        collection = self.collections.app_streams
        if collection is None:
            raise RuntimeAppStreamError("runtime_app_streams_unavailable")
        query = {
            "workspace_id": record.workspace_id,
            "source_app_id": record.source_app_id,
            "idempotency_key": record.idempotency_key,
        }
        document, inserted = self._insert_one_if_absent(collection, query, asdict(record))
        existing = _app_stream_from_document(document)
        if existing.request_fingerprint != record.request_fingerprint:
            raise RuntimeAppStreamError("runtime_app_stream_idempotency_conflict")
        return existing, inserted

    def get_app_stream(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
    ) -> RuntimeAppStreamRecord:
        """Read one stream only through its stamped workspace/app ownership."""
        collection = self.collections.app_streams
        if collection is None:
            raise RuntimeAppStreamError("runtime_app_streams_unavailable")
        document = collection.find_one(
            {
                "stream_id": stream_id,
                "workspace_id": workspace_id,
                "source_app_id": source_app_id,
            }
        )
        if document is None:
            raise RuntimeAppStreamError("runtime_app_stream_not_found")
        return _app_stream_from_document(document)

    def list_app_streams_for_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> list[RuntimeAppStreamRecord]:
        """List generic streams bound to one runtime session."""
        collection = self.collections.app_streams
        if collection is None:
            return []
        return [
            _app_stream_from_document(document)
            for document in collection.find({"workspace_id": workspace_id, "session_id": session_id})
        ]

    def has_nonterminal_app_stream_for_session(self, *, workspace_id: str, session_id: str) -> bool:
        """Return whether automatic restart must not create a second app turn."""
        terminal = {"completed", "failed", "cancelled", "timed-out"}
        return any(
            stream.status not in terminal
            for stream in self.list_app_streams_for_session(workspace_id=workspace_id, session_id=session_id)
        )

    def bind_app_stream(
        self,
        *,
        stream_id: str,
        workspace_id: str,
        source_app_id: str,
        session_id: str,
        turn_id: str,
        now: datetime | None = None,
    ) -> RuntimeAppStreamRecord:
        """Bind a reserved stream and backfill already-persisted turn events."""
        collection = self.collections.app_streams
        if collection is None:
            raise RuntimeAppStreamError("runtime_app_streams_unavailable")
        timestamp = now or datetime.now(tz=UTC)
        with self.session_lifecycle_handoff(workspace_id=workspace_id, session_id=session_id):
            stream = self.get_app_stream(stream_id, workspace_id=workspace_id, source_app_id=source_app_id)
            if stream.session_id and (stream.session_id != session_id or stream.turn_id != turn_id):
                raise RuntimeAppStreamError("runtime_app_stream_already_bound")
            session = self.get_session(session_id)
            turn = self.get_turn(turn_id)
            if (
                session.workspace_id != workspace_id
                or turn.workspace_id != workspace_id
                or turn.session_id != session_id
                or (session.source_app_id or "") != source_app_id
            ):
                raise RuntimeAppStreamError("runtime_app_stream_ownership_mismatch")
            bound = replace(
                stream,
                session_id=session_id,
                turn_id=turn_id,
                status="submitted",
                initial_file_state=snapshot_project_files(session.workdir),
                updated_at=timestamp,
            )
            collection.update_one(
                {"stream_id": stream_id, "workspace_id": workspace_id, "source_app_id": source_app_id},
                {"$set": asdict(bound)},
                upsert=False,
            )
            for event in self.list_events(session_id):
                if event.turn_id == turn_id:
                    self._append_event_to_one_app_stream(bound, event)
                    bound = self.get_app_stream(
                        stream_id,
                        workspace_id=workspace_id,
                        source_app_id=source_app_id,
                    )
            return bound

    def fail_app_stream(
        self,
        *,
        stream_id: str,
        workspace_id: str,
        source_app_id: str,
        now: datetime | None = None,
    ) -> RuntimeAppStreamRecord:
        """Mark a reservation failed without fabricating a runtime turn."""
        collection = self.collections.app_streams
        if collection is None:
            raise RuntimeAppStreamError("runtime_app_streams_unavailable")
        stream = self.get_app_stream(stream_id, workspace_id=workspace_id, source_app_id=source_app_id)
        if stream.status in {"completed", "failed", "cancelled", "timed-out"}:
            return stream
        failed = replace(stream, status="failed", updated_at=now or datetime.now(tz=UTC))
        collection.update_one(
            {"stream_id": stream_id, "workspace_id": workspace_id, "source_app_id": source_app_id},
            {"$set": asdict(failed)},
            upsert=False,
        )
        return failed

    def read_app_stream_events(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
        after_sequence: int = 0,
        limit: int = 64,
    ) -> list[RuntimeAppStreamEventRecord]:
        """Read one bounded ordered page after an acknowledged sequence."""
        stream = self.get_app_stream(stream_id, workspace_id=workspace_id, source_app_id=source_app_id)
        collection = self.collections.app_stream_events
        if collection is None:
            raise RuntimeAppStreamError("runtime_app_stream_events_unavailable")
        bounded_after = max(0, int(after_sequence))
        bounded_limit = max(1, min(int(limit), 256))
        documents = collection.find(
            {
                "workspace_id": workspace_id,
                "session_id": stream.session_id,
                "stream_id": stream_id,
                "source_app_id": source_app_id,
            }
        )
        documents.sort(key=lambda item: int(item.get("sequence") or 0))
        return [
            _app_stream_event_from_document(document)
            for document in documents
            if int(document.get("sequence") or 0) > bounded_after
        ][:bounded_limit]

    def _claim_has_persisted_turn(self, claim: RuntimeClientMessageClaim) -> bool:
        if claim.status in {"steered", "delivery_uncertain"}:
            return True
        return (
            self.collections.turns.find_one(
                {
                    "workspace_id": claim.workspace_id,
                    "session_id": claim.session_id,
                    "turn_id": claim.turn_id,
                    "client_message_id": claim.client_message_id,
                }
            )
            is not None
        )

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        self._remember_session_partition(record.session_id, record.workspace_id)
        append_history_upsert = getattr(self.collections.events, "append_history_upsert", None)
        if callable(append_history_upsert):
            append_history_upsert(
                {"event_id": record.event_id},
                {"$set": asdict(record)},
            )
        append_bounded_upsert = getattr(self.collections.events, "append_bounded_upsert", None)
        if callable(append_bounded_upsert):
            append_bounded_upsert(
                {"event_id": record.event_id},
                {"$set": asdict(record)},
                max_documents=MAX_RUNTIME_EVENTS_PER_SESSION,
            )
            self._append_event_to_app_streams(record)
            return record
        self.collections.events.update_one({"event_id": record.event_id}, {"$set": asdict(record)}, upsert=True)
        self._prune_session_events(record.session_id)
        self._append_event_to_app_streams(record)
        return record

    def save_turn_event_if_absent(self, record: RuntimeEventRecord) -> tuple[RuntimeEventRecord, bool]:
        """Idempotently materialize one turn event in history, tail, and app streams."""
        if not record.turn_id:
            raise ValueError("Idempotent turn events require turn_id.")
        query = {
            "workspace_id": record.workspace_id,
            "session_id": record.session_id,
            "turn_id": record.turn_id,
            "event_type": record.event_type,
        }
        self._remember_session_partition(record.session_id, record.workspace_id)
        history_inserted = False
        append_history_if_absent = getattr(self.collections.events, "append_history_upsert_if_absent", None)
        if callable(append_history_if_absent):
            _history_document, history_inserted = append_history_if_absent(
                {"workspace_id": record.workspace_id, "session_id": record.session_id, "event_id": record.event_id},
                {"$set": asdict(record)},
            )
        document, tail_inserted = self._insert_one_if_absent(
            self.collections.events,
            query,
            asdict(record),
        )
        saved = RuntimeEventRecord(**document)
        if saved.event_id != record.event_id:
            raise RuntimeError(
                f"Runtime turn `{record.turn_id}` terminal event identity conflicts with `{saved.event_id}`."
            )
        if not callable(append_history_if_absent):
            append_history_upsert = getattr(self.collections.events, "append_history_upsert", None)
            if callable(append_history_upsert) and tail_inserted:
                append_history_upsert({"event_id": saved.event_id}, {"$set": asdict(saved)})
                history_inserted = True
        if tail_inserted:
            self._prune_session_events(saved.session_id)
        self._append_event_to_app_streams(saved)
        return saved, bool(history_inserted or tail_inserted)

    def find_turn_event(self, *, turn_id: str, event_type: str) -> RuntimeEventRecord | None:
        """Find the persisted terminal event in either bounded tail or full history."""
        turn = self.get_turn(turn_id)
        query = {
            "workspace_id": turn.workspace_id,
            "session_id": turn.session_id,
            "turn_id": turn_id,
            "event_type": event_type,
        }
        document = self.collections.events.find_one(query)
        if document is None:
            find_history_one = getattr(self.collections.events, "find_history_one", None)
            if callable(find_history_one):
                document = find_history_one(query)
        return RuntimeEventRecord(**document) if document is not None else None

    def _append_event_to_app_streams(self, record: RuntimeEventRecord) -> None:
        streams = self.collections.app_streams
        if streams is None or self.collections.app_stream_events is None or not record.turn_id:
            return
        matches = streams.find({"workspace_id": record.workspace_id, "turn_id": record.turn_id})
        if not matches:
            return
        with self.session_lifecycle_handoff(workspace_id=record.workspace_id, session_id=record.session_id):
            for document in matches:
                stream = _app_stream_from_document(document)
                if stream.session_id != record.session_id:
                    continue
                if record.event_type in {
                    "runtime.turn.completed",
                    "runtime.turn.failed",
                    "runtime.turn.cancelled",
                    "runtime.turn.timed-out",
                }:
                    self._append_project_file_events(stream, record)
                    stream = self.get_app_stream(
                        stream.stream_id,
                        workspace_id=stream.workspace_id,
                        source_app_id=stream.source_app_id,
                    )
                self._append_event_to_one_app_stream(stream, record)

    def _append_project_file_events(self, stream: RuntimeAppStreamRecord, terminal_event: RuntimeEventRecord) -> None:
        try:
            session = self.get_session(stream.session_id)
        except RuntimeSessionNotFoundError:
            return
        current = snapshot_project_files(session.workdir)
        for index, (path, change) in enumerate(changed_project_files(stream.initial_file_state, current), start=1):
            synthetic = RuntimeEventRecord(
                event_id=f"{terminal_event.event_id}:file:{index}",
                workspace_id=terminal_event.workspace_id,
                session_id=terminal_event.session_id,
                plane="turn",
                event_type="runtime.file.changed",
                turn_id=terminal_event.turn_id,
                process_id=None,
                payload={"path": path, "change": change},
                created_at=terminal_event.created_at,
            )
            self._append_event_to_one_app_stream(stream, synthetic)
            stream = self.get_app_stream(
                stream.stream_id,
                workspace_id=stream.workspace_id,
                source_app_id=stream.source_app_id,
            )

    def _append_event_to_one_app_stream(
        self,
        stream: RuntimeAppStreamRecord,
        record: RuntimeEventRecord,
    ) -> RuntimeAppStreamEventRecord | None:
        normalized = normalized_stream_event(record)
        collection = self.collections.app_stream_events
        streams = self.collections.app_streams
        if normalized is None or collection is None or streams is None:
            return None
        event_type, payload, terminal = normalized
        identity = {
            "workspace_id": stream.workspace_id,
            "session_id": stream.session_id,
            "stream_id": stream.stream_id,
            "event_id": record.event_id,
        }
        existing = collection.find_one(identity)
        if existing is not None:
            persisted = _app_stream_event_from_document(existing)
            current = self.get_app_stream(
                stream.stream_id,
                workspace_id=stream.workspace_id,
                source_app_id=stream.source_app_id,
            )
            repaired = replace(
                current,
                status=stream_status_for_event(persisted.event_type, current.status),
                last_sequence=max(current.last_sequence, persisted.sequence),
                updated_at=max(current.updated_at, persisted.created_at),
            )
            if repaired != current:
                streams.update_one(
                    {
                        "stream_id": current.stream_id,
                        "workspace_id": current.workspace_id,
                        "source_app_id": current.source_app_id,
                    },
                    {"$set": asdict(repaired)},
                    upsert=False,
                )
            return persisted
        current = self.get_app_stream(
            stream.stream_id,
            workspace_id=stream.workspace_id,
            source_app_id=stream.source_app_id,
        )
        projected = RuntimeAppStreamEventRecord(
            stream_id=current.stream_id,
            workspace_id=current.workspace_id,
            source_app_id=current.source_app_id,
            session_id=current.session_id,
            turn_id=current.turn_id,
            sequence=current.last_sequence + 1,
            event_id=record.event_id,
            event_type=event_type,
            payload=payload,
            terminal=terminal,
            created_at=record.created_at,
        )
        document, inserted = self._insert_one_if_absent(collection, identity, asdict(projected))
        if not inserted:
            return _app_stream_event_from_document(document)
        updated = replace(
            current,
            status=stream_status_for_event(event_type, current.status),
            last_sequence=projected.sequence,
            updated_at=record.created_at,
        )
        streams.update_one(
            {
                "stream_id": current.stream_id,
                "workspace_id": current.workspace_id,
                "source_app_id": current.source_app_id,
            },
            {"$set": asdict(updated)},
            upsert=False,
        )
        return projected

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        documents = self.collections.events.find(self._session_query(session_id))
        return [RuntimeEventRecord(**document) for document in documents[-MAX_RUNTIME_EVENTS_PER_SESSION:]]

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        find_recent = getattr(self.collections.events, "find_recent", None)
        query = self._session_query(session_id)
        if callable(find_recent):
            documents = find_recent(query, limit=limit)
        else:
            documents = self.collections.events.find(query)
            documents.sort(key=lambda item: str(item.get("created_at") or ""))
            documents = documents[-limit:]
        return [RuntimeEventRecord(**document) for document in documents]

    def list_event_page(
        self,
        session_id: str,
        *,
        before_event_id: str | None = None,
        limit: int = 200,
    ) -> RuntimeEventPage:
        bounded_limit = max(1, min(int(limit), MAX_RUNTIME_EVENTS_PER_SESSION))
        query = self._session_query(session_id)
        find_event_page = getattr(self.collections.events, "find_event_page", None)
        if callable(find_event_page):
            page = find_event_page(query, before_event_id=before_event_id, limit=bounded_limit)
            events = [RuntimeEventRecord(**document) for document in page["documents"]]
            return RuntimeEventPage(
                events=events,
                has_more_before=bool(page["has_more_before"]),
                before_event_id=before_event_id,
                oldest_event_id=events[0].event_id if events else None,
                newest_event_id=events[-1].event_id if events else None,
            )
        documents = self.collections.events.find(query)
        documents.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or "")))
        if before_event_id:
            cursor_found = False
            for index, document in enumerate(documents):
                if document.get("event_id") == before_event_id:
                    documents = documents[:index]
                    cursor_found = True
                    break
            if not cursor_found:
                documents = []
        has_more_before = len(documents) > bounded_limit
        documents = documents[-bounded_limit:]
        events = [RuntimeEventRecord(**document) for document in documents]
        return RuntimeEventPage(
            events=events,
            has_more_before=has_more_before,
            before_event_id=before_event_id,
            oldest_event_id=events[0].event_id if events else None,
            newest_event_id=events[-1].event_id if events else None,
        )

    def list_event_archive_page(
        self,
        session_id: str,
        *,
        before_position: int | None = None,
        snapshot_position: int | None = None,
        snapshot_event_id: str | None = None,
        limit: int = 200,
    ) -> RuntimeEventArchivePage:
        """Read a bounded page by physical append position, not event time."""
        bounded_limit = max(1, min(int(limit), MAX_RUNTIME_EVENTS_PER_SESSION))
        query = self._session_query(session_id)
        find_archive_page = getattr(self.collections.events, "find_event_archive_page", None)
        if callable(find_archive_page):
            page = find_archive_page(
                query,
                before_position=before_position,
                snapshot_position=snapshot_position,
                snapshot_event_id=snapshot_event_id,
                limit=bounded_limit,
            )
        else:
            page = page_archive_documents(
                list(self.collections.events.find(query)),
                identity_field="event_id",
                before_position=before_position,
                snapshot_position=snapshot_position,
                snapshot_record_id=snapshot_event_id,
                limit=bounded_limit,
            )
        return RuntimeEventArchivePage(
            events=[RuntimeEventRecord(**document) for document in page["documents"]],
            has_more_before=bool(page["has_more_before"]),
            oldest_position=page["oldest_position"],
            newest_position=page["newest_position"],
            snapshot_position=int(page["snapshot_position"]),
            snapshot_event_id=page["snapshot_record_id"],
            snapshot_found=bool(page["snapshot_found"]),
        )

    def has_events_before(self, session_id: str, *, before_event_id: str | None) -> bool:
        if not before_event_id:
            return False
        query = self._session_query(session_id)
        has_event_before = getattr(self.collections.events, "has_event_before", None)
        if callable(has_event_before):
            return bool(has_event_before(query, before_event_id=before_event_id))
        documents = self.collections.events.find(query)
        documents.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or "")))
        for index, document in enumerate(documents):
            if document.get("event_id") == before_event_id:
                return index > 0
        return False

    def list_all_events(self) -> list[RuntimeEventRecord]:
        return [RuntimeEventRecord(**document) for document in self.collections.events.find({})]

    def save_process(self, record: RuntimeProcessRecord) -> RuntimeProcessRecord:
        self.collections.processes.update_one({"process_id": record.process_id}, {"$set": asdict(record)}, upsert=True)
        self._remember_session_partition(record.session_id, record.workspace_id)
        return record

    def get_process(self, process_id: str) -> RuntimeProcessRecord:
        document = self.collections.processes.find_one({"process_id": process_id})
        if document is None:
            raise RuntimeProcessNotFoundError(f"Runtime process `{process_id}` was not found.")
        return RuntimeProcessRecord(**document)

    def list_processes(self, session_id: str) -> list[RuntimeProcessRecord]:
        return [RuntimeProcessRecord(**document) for document in self.collections.processes.find(self._session_query(session_id))]

    def save_state(self, record: RuntimeStateRecord) -> RuntimeStateRecord:
        self.collections.states.update_one(
            {"session_id": record.session_id, "workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        self._remember_session_partition(record.session_id, record.workspace_id)
        return record

    def get_state(self, session_id: str) -> RuntimeStateRecord:
        query = self._session_query(session_id)
        document = self.collections.states.find_one(query)
        if document is None and "workspace_id" in query:
            self._forget_session_partition(session_id)
            document = self.collections.states.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeStateNotFoundError(f"Runtime state for session `{session_id}` was not found.")
        state = RuntimeStateRecord(**document)
        self._remember_session_partition(state.session_id, state.workspace_id)
        return state

    def initialize_provider_state(self, record: RuntimeProviderState) -> RuntimeProviderState:
        """Insert revision zero for one bound session exactly once."""
        if record.revision != 0:
            raise RuntimeProviderStateError("Initial runtime provider state must use revision zero.")
        document, inserted = self._insert_one_if_absent(
            self._provider_states,
            {"session_id": record.session_id, "workspace_id": record.workspace_id},
            asdict(record),
        )
        existing = runtime_provider_state_from_document(document)
        if not inserted and existing != record:
            raise RuntimeProviderStateError(
                f"Runtime provider state for session `{record.session_id}` already exists."
            )
        self._remember_session_partition(record.session_id, record.workspace_id)
        return existing

    def get_provider_state(self, session_id: str) -> RuntimeProviderState:
        """Read the mutable provider state for one runtime session."""
        query = self._session_query(session_id)
        document = self._provider_states.find_one(query)
        if document is None and "workspace_id" in query:
            document = self._provider_states.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeProviderStateError(
                f"Runtime provider state for session `{session_id}` was not found."
            )
        state = runtime_provider_state_from_document(document)
        self._remember_session_partition(state.session_id, state.workspace_id)
        return state

    def update_provider_state(
        self,
        record: RuntimeProviderState,
        *,
        expected_revision: int,
    ) -> RuntimeProviderState:
        """Advance provider-private state by exactly one revision through CAS."""
        if expected_revision < 0 or record.revision != expected_revision + 1:
            raise RuntimeProviderStateError(
                "Runtime provider state updates must advance the expected revision by exactly one."
            )
        current = self.get_provider_state(record.session_id)
        if (
            current.workspace_id != record.workspace_id
            or current.runtime_engine_id != record.runtime_engine_id
            or current.model_provider_id != record.model_provider_id
        ):
            raise RuntimeProviderStateError("Runtime provider state identity fields are immutable.")
        applied = self._provider_states.compare_and_set(
            {
                "session_id": record.session_id,
                "workspace_id": record.workspace_id,
                "revision": expected_revision,
            },
            {"$set": asdict(record)},
        )
        if not applied:
            raise RuntimeProviderStateError(
                f"Stale runtime provider state revision `{expected_revision}` for session `{record.session_id}`."
            )
        return record

    def save_thread(self, record: RuntimeThreadRecord) -> RuntimeThreadRecord:
        self.collections.threads.update_one({"thread_id": record.thread_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_thread(self, thread_id: str) -> RuntimeThreadRecord:
        document = self.collections.threads.find_one({"thread_id": thread_id})
        if document is None:
            raise RuntimeThreadNotFoundError(f"Runtime thread `{thread_id}` was not found.")
        return RuntimeThreadRecord(**document)

    def get_thread_by_runtime_session_id(self, *, workspace_id: str, runtime_session_id: str) -> RuntimeThreadRecord | None:
        document = self.collections.threads.find_one(
            {
                "workspace_id": workspace_id,
                "runtime_session_id": runtime_session_id,
            }
        )
        return RuntimeThreadRecord(**document) if document is not None else None

    def list_threads(self, workspace_id: str) -> list[RuntimeThreadRecord]:
        return [RuntimeThreadRecord(**document) for document in self.collections.threads.find({"workspace_id": workspace_id})]

    def delete_thread(self, thread_id: str) -> bool:
        document = self.collections.threads.find_one({"thread_id": thread_id})
        if document is None:
            return False
        self.collections.threads.delete_one({"thread_id": thread_id})
        return True

    def _insert_one_if_absent(
        self,
        collection: DocumentCollection,
        query: dict[str, Any],
        document: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        insert_one_if_absent = getattr(collection, "insert_one_if_absent", None)
        if callable(insert_one_if_absent):
            return insert_one_if_absent(query, document)
        with self._fallback_lock:
            existing = collection.find_one(query)
            if existing is not None:
                return existing, False
            collection.update_one(query, {"$set": document}, upsert=True)
            return {**query, **document}, True

    def _insert_runtime_turn_if_absent(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Insert a turn atomically through the turn collection boundary."""
        insert_one_if_absent = getattr(self.collections.turns, "insert_one_if_absent", None)
        if callable(insert_one_if_absent):
            return insert_one_if_absent(query, document)
        with self._fallback_lock:
            existing = self.collections.turns.find_one(query)
            if existing is not None:
                return existing, False
            self.collections.turns.update_one(query, {"$set": document}, upsert=True)
            return {**query, **document}, True

    def _prune_session_events(self, session_id: str) -> None:
        try:
            documents = list(self.collections.events.find(self._session_query(session_id)))
        except ValueError:
            return
        excess_count = len(documents) - MAX_RUNTIME_EVENTS_PER_SESSION
        if excess_count <= 0:
            return
        documents.sort(key=lambda item: str(item.get("created_at") or ""))
        kept_documents = documents[excess_count:]
        workspace_id = _workspace_id_from_documents(kept_documents) or _workspace_id_from_documents(documents)
        replace_session_partition = getattr(self.collections.events, "replace_session_partition", None)
        if callable(replace_session_partition) and workspace_id:
            replace_session_partition(
                session_id=session_id,
                workspace_id=workspace_id,
                documents=kept_documents,
            )
            return
        for document in documents[:excess_count]:
            event_id = document.get("event_id")
            if isinstance(event_id, str):
                self.collections.events.delete_one({"event_id": event_id})

    def _session_query(self, session_id: str) -> dict[str, str]:
        query = {"session_id": session_id}
        with self._partition_index_lock:
            workspace_id = self._session_workspace_index.get(session_id)
        if workspace_id:
            query["workspace_id"] = workspace_id
        return query

    def _session_with_provider_state(self, session: RuntimeSessionRecord) -> RuntimeSessionRecord:
        """Project mutable continuation state onto the legacy read model only."""
        try:
            provider_state = self.get_provider_state(session.session_id)
        except RuntimeProviderStateError:
            return session
        return replace(session, provider_thread_id=provider_state.provider_thread_id)

    def _turn_query(self, turn_id: str) -> dict[str, str]:
        query = {"turn_id": turn_id}
        with self._partition_index_lock:
            partition = self._turn_partition_index.get(turn_id)
        if partition is not None:
            workspace_id, session_id = partition
            query["workspace_id"] = workspace_id
            query["session_id"] = session_id
        return query

    def _remember_session_partition(self, session_id: str, workspace_id: str) -> None:
        if not session_id or not workspace_id:
            return
        with self._partition_index_lock:
            self._session_workspace_index[session_id] = workspace_id

    def _forget_session_partition(self, session_id: str) -> None:
        with self._partition_index_lock:
            self._session_workspace_index.pop(session_id, None)

    def _remember_turn_partition(self, turn: RuntimeTurnRecord) -> None:
        if not turn.turn_id or not turn.workspace_id or not turn.session_id:
            return
        with self._partition_index_lock:
            self._session_workspace_index[turn.session_id] = turn.workspace_id
            self._turn_partition_index[turn.turn_id] = (turn.workspace_id, turn.session_id)

    def _forget_turn_partition(self, turn_id: str) -> None:
        with self._partition_index_lock:
            self._turn_partition_index.pop(turn_id, None)

    def _forget_turns_for_session(self, session_id: str) -> None:
        with self._partition_index_lock:
            stale_turn_ids = [
                turn_id
                for turn_id, (_workspace_id, indexed_session_id) in self._turn_partition_index.items()
                if indexed_session_id == session_id
            ]
            for turn_id in stale_turn_ids:
                self._turn_partition_index.pop(turn_id, None)


def runtime_location(workspace_id: str, start_path=None) -> RuntimeLocation:
    """Return the canonical runtime location for one workspace."""
    return RuntimeLocation(
        workspace_id=workspace_id,
        path=workspace_runtime_root(workspace_id=workspace_id, start_path=start_path),
    )


def _app_stream_from_document(document: dict[str, Any]) -> RuntimeAppStreamRecord:
    payload = dict(document)
    payload.setdefault("initial_file_state", {})
    payload.setdefault("created_at", None)
    payload.setdefault("updated_at", None)
    return RuntimeAppStreamRecord(**payload)


def _app_stream_event_from_document(document: dict[str, Any]) -> RuntimeAppStreamEventRecord:
    return RuntimeAppStreamEventRecord(**document)


def _delete_session_records(
    collection: DocumentCollection,
    *,
    session_id: str,
    workspace_id: str | None,
    identity_field: str,
) -> int:
    delete_session_partition = getattr(collection, "delete_session_partition", None)
    if callable(delete_session_partition):
        return int(delete_session_partition(session_id=session_id, workspace_id=workspace_id))
    deleted = 0
    find_query = {"session_id": session_id}
    if workspace_id:
        find_query["workspace_id"] = workspace_id
    for document in collection.find(find_query):
        identity_value = document.get(identity_field)
        if isinstance(identity_value, str):
            delete_query = {identity_field: identity_value, "session_id": session_id}
            if workspace_id:
                delete_query["workspace_id"] = workspace_id
            collection.delete_one(delete_query)
            deleted += 1
    return deleted


def _client_message_claim_from_document(document: dict[str, Any]) -> RuntimeClientMessageClaim:
    if "status" not in document:
        document = {**document, "status": "claimed"}
    if "lease_expires_at" not in document:
        document = {**document, "lease_expires_at": None}
    return RuntimeClientMessageClaim(**document)


def _client_message_claim_is_expired(claim: RuntimeClientMessageClaim, now: datetime) -> bool:
    if claim.status in {"queued", "steered", "delivery_uncertain"}:
        return False
    if claim.lease_expires_at is None:
        return True
    lease_expires_at = claim.lease_expires_at
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at <= now


def _client_message_claim_matches(left: RuntimeClientMessageClaim, right: RuntimeClientMessageClaim) -> bool:
    return (
        left.workspace_id == right.workspace_id
        and left.client_message_id == right.client_message_id
        and left.session_id == right.session_id
        and left.turn_id == right.turn_id
    )


def _client_message_claim_matches_record(
    claim: RuntimeClientMessageClaim,
    record: RuntimeTurnRecord,
    client_message_id: str,
) -> bool:
    return (
        claim.workspace_id == record.workspace_id
        and claim.client_message_id == client_message_id
        and claim.session_id == record.session_id
        and claim.turn_id == record.turn_id
    )


def _client_message_claim_replace_query(
    document: dict[str, Any],
    identity_query: dict[str, str],
) -> dict[str, Any]:
    query: dict[str, Any] = dict(identity_query)
    for field in ("session_id", "turn_id", "status", "lease_expires_at"):
        if field in document:
            query[field] = document[field]
    return query


def _workspace_id_from_documents(documents: list[dict[str, Any]]) -> str | None:
    for document in documents:
        workspace_id = document.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            return workspace_id
    return None


def _valid_runtime_sessions(documents: Any) -> list[RuntimeSessionRecord]:
    sessions: list[RuntimeSessionRecord] = []
    for document in documents:
        try:
            sessions.append(runtime_session_from_document(document))
        except ValueError:
            continue
    return sessions
