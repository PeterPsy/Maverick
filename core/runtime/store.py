"""Runtime-domain store contracts and document-store adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol

from core.runtime.errors import (
    RuntimeProcessNotFoundError,
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
from core.runtime.models import RuntimeLocation
from core.runtime.paths import workspace_runtime_root
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord
from core.runtime.runtime_session import RuntimeApiTokenRecord, RuntimeSessionRecord, runtime_session_from_document
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord


MAX_RUNTIME_EVENTS_PER_SESSION = 500


@dataclass(frozen=True)
class RuntimeEventPage:
    """One bounded page of ordered runtime events."""

    events: list[RuntimeEventRecord]
    has_more_before: bool
    before_event_id: str | None
    oldest_event_id: str | None
    newest_event_id: str | None


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


class RuntimeStore(Protocol):
    """Persistence contract for runtime-domain records."""

    def save_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        ...

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        ...

    def list_sessions(self, workspace_id: str) -> list[RuntimeSessionRecord]:
        ...

    def list_all_sessions(self) -> list[RuntimeSessionRecord]:
        ...

    def save_turn(self, record: RuntimeTurnRecord) -> RuntimeTurnRecord:
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

    def delete_session_records(self, session_id: str) -> dict[str, int]:
        ...

    def save_thread(self, record: RuntimeThreadRecord) -> RuntimeThreadRecord:
        ...

    def get_thread(self, thread_id: str) -> RuntimeThreadRecord:
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


class RuntimeDocumentStore:
    """Persist runtime-domain records in document-style collections."""

    def __init__(self, collections: RuntimeCollections) -> None:
        self.collections = collections
        self._fallback_lock = RLock()

    def save_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        self.collections.sessions.update_one({"session_id": record.session_id}, {"$set": asdict(record)}, upsert=True)
        return record

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
        document = self.collections.sessions.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeSessionNotFoundError(f"Runtime session `{session_id}` was not found.")
        return runtime_session_from_document(document)

    def list_sessions(self, workspace_id: str) -> list[RuntimeSessionRecord]:
        return _valid_runtime_sessions(self.collections.sessions.find({"workspace_id": workspace_id}))

    def list_all_sessions(self) -> list[RuntimeSessionRecord]:
        return _valid_runtime_sessions(self.collections.sessions.find({}))

    def delete_session_records(self, session_id: str) -> dict[str, int]:
        session_document = self.collections.sessions.find_one({"session_id": session_id}) or {}
        workspace_id = session_document.get("workspace_id") if isinstance(session_document, dict) else None
        deleted = {
            "sessions": 1 if session_document else 0,
            "turns": 0,
            "events": 0,
            "processes": 0,
            "states": 0,
            "api_tokens": 0,
            "client_messages": 0,
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
        session_delete_query = {"session_id": session_id}
        if workspace_id:
            session_delete_query["workspace_id"] = workspace_id
        self.collections.sessions.delete_one(session_delete_query)
        return deleted

    def save_turn(self, record: RuntimeTurnRecord) -> RuntimeTurnRecord:
        self.collections.turns.update_one({"turn_id": record.turn_id}, {"$set": asdict(record)}, upsert=True)
        return record

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
        return RuntimeTurnRecord(**document), inserted

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
            self.mark_client_message_claim_queued(
                workspace_id=claim.workspace_id,
                client_message_id=claim.client_message_id,
                session_id=claim.session_id,
                turn_id=claim.turn_id,
                now=timestamp,
            )
            return turn, inserted

    def get_turn(self, turn_id: str) -> RuntimeTurnRecord:
        document = self.collections.turns.find_one({"turn_id": turn_id})
        if document is None:
            raise RuntimeTurnNotFoundError(f"Runtime turn `{turn_id}` was not found.")
        return RuntimeTurnRecord(**document)

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        return [RuntimeTurnRecord(**document) for document in self.collections.turns.find({"session_id": session_id})]

    def list_recent_turns(self, session_id: str, *, limit: int) -> list[RuntimeTurnRecord]:
        if limit < 1:
            return []
        find_recent = getattr(self.collections.turns, "find_recent", None)
        if callable(find_recent):
            documents = find_recent({"session_id": session_id}, limit=limit)
        else:
            documents = self.collections.turns.find({"session_id": session_id})
            documents.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("turn_id") or "")))
            documents = documents[-limit:]
        return [RuntimeTurnRecord(**document) for document in documents]

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
        return RuntimeTurnRecord(**document) if document is not None else None

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
        normalized_client_message_id = client_message_id.strip()
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
            {"$set": {"status": "queued", "lease_expires_at": None, "updated_at": timestamp}},
            upsert=False,
        )
        document = collection.find_one(query)
        return _client_message_claim_from_document(document) if document is not None else None

    def _claim_has_persisted_turn(self, claim: RuntimeClientMessageClaim) -> bool:
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
            return record
        self.collections.events.update_one({"event_id": record.event_id}, {"$set": asdict(record)}, upsert=True)
        self._prune_session_events(record.session_id)
        return record

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        return [RuntimeEventRecord(**document) for document in self.collections.events.find({"session_id": session_id})]

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        find_recent = getattr(self.collections.events, "find_recent", None)
        if callable(find_recent):
            documents = find_recent({"session_id": session_id}, limit=limit)
        else:
            documents = self.collections.events.find({"session_id": session_id})
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
        find_event_page = getattr(self.collections.events, "find_event_page", None)
        if callable(find_event_page):
            page = find_event_page({"session_id": session_id}, before_event_id=before_event_id, limit=bounded_limit)
            events = [RuntimeEventRecord(**document) for document in page["documents"]]
            return RuntimeEventPage(
                events=events,
                has_more_before=bool(page["has_more_before"]),
                before_event_id=before_event_id,
                oldest_event_id=events[0].event_id if events else None,
                newest_event_id=events[-1].event_id if events else None,
            )
        documents = self.collections.events.find({"session_id": session_id})
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

    def has_events_before(self, session_id: str, *, before_event_id: str | None) -> bool:
        if not before_event_id:
            return False
        has_event_before = getattr(self.collections.events, "has_event_before", None)
        if callable(has_event_before):
            return bool(has_event_before({"session_id": session_id}, before_event_id=before_event_id))
        documents = self.collections.events.find({"session_id": session_id})
        documents.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or "")))
        for index, document in enumerate(documents):
            if document.get("event_id") == before_event_id:
                return index > 0
        return False

    def list_all_events(self) -> list[RuntimeEventRecord]:
        return [RuntimeEventRecord(**document) for document in self.collections.events.find({})]

    def save_process(self, record: RuntimeProcessRecord) -> RuntimeProcessRecord:
        self.collections.processes.update_one({"process_id": record.process_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_process(self, process_id: str) -> RuntimeProcessRecord:
        document = self.collections.processes.find_one({"process_id": process_id})
        if document is None:
            raise RuntimeProcessNotFoundError(f"Runtime process `{process_id}` was not found.")
        return RuntimeProcessRecord(**document)

    def list_processes(self, session_id: str) -> list[RuntimeProcessRecord]:
        return [RuntimeProcessRecord(**document) for document in self.collections.processes.find({"session_id": session_id})]

    def save_state(self, record: RuntimeStateRecord) -> RuntimeStateRecord:
        self.collections.states.update_one({"session_id": record.session_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_state(self, session_id: str) -> RuntimeStateRecord:
        document = self.collections.states.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeStateNotFoundError(f"Runtime state for session `{session_id}` was not found.")
        return RuntimeStateRecord(**document)

    def save_thread(self, record: RuntimeThreadRecord) -> RuntimeThreadRecord:
        self.collections.threads.update_one({"thread_id": record.thread_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_thread(self, thread_id: str) -> RuntimeThreadRecord:
        document = self.collections.threads.find_one({"thread_id": thread_id})
        if document is None:
            raise RuntimeThreadNotFoundError(f"Runtime thread `{thread_id}` was not found.")
        return RuntimeThreadRecord(**document)

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

    def _prune_session_events(self, session_id: str) -> None:
        try:
            documents = list(self.collections.events.find({"session_id": session_id}))
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


def runtime_location(workspace_id: str, start_path=None) -> RuntimeLocation:
    """Return the canonical runtime location for one workspace."""
    return RuntimeLocation(
        workspace_id=workspace_id,
        path=workspace_runtime_root(workspace_id=workspace_id, start_path=start_path),
    )


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
    if claim.status == "queued":
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
