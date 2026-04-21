"""Runtime-domain store contracts and Mongo-oriented adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.runtime.errors import (
    RuntimeProcessNotFoundError,
    RuntimeSessionNotFoundError,
    RuntimeStateNotFoundError,
    RuntimeTurnNotFoundError,
)
from core.runtime.models import RuntimeLocation
from core.runtime.paths import workspace_runtime_root
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord


class MongoCollection(Protocol):
    """Minimal collection protocol used by Mongo-backed runtime stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


@dataclass(frozen=True)
class RuntimeCollections:
    """Mongo collection bundle for runtime-domain persistence."""

    sessions: MongoCollection
    turns: MongoCollection
    events: MongoCollection
    processes: MongoCollection
    states: MongoCollection


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

    def get_turn(self, turn_id: str) -> RuntimeTurnRecord:
        ...

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        ...

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        ...

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
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


class MongoRuntimeStore:
    """Persist runtime-domain records in Mongo-style collections."""

    def __init__(self, collections: RuntimeCollections) -> None:
        self.collections = collections

    def save_session(self, record: RuntimeSessionRecord) -> RuntimeSessionRecord:
        self.collections.sessions.update_one({"session_id": record.session_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        document = self.collections.sessions.find_one({"session_id": session_id})
        if document is None:
            raise RuntimeSessionNotFoundError(f"Runtime session `{session_id}` was not found.")
        return RuntimeSessionRecord(**document)

    def list_sessions(self, workspace_id: str) -> list[RuntimeSessionRecord]:
        return [RuntimeSessionRecord(**document) for document in self.collections.sessions.find({"workspace_id": workspace_id})]

    def list_all_sessions(self) -> list[RuntimeSessionRecord]:
        return [RuntimeSessionRecord(**document) for document in self.collections.sessions.find({})]

    def save_turn(self, record: RuntimeTurnRecord) -> RuntimeTurnRecord:
        self.collections.turns.update_one({"turn_id": record.turn_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_turn(self, turn_id: str) -> RuntimeTurnRecord:
        document = self.collections.turns.find_one({"turn_id": turn_id})
        if document is None:
            raise RuntimeTurnNotFoundError(f"Runtime turn `{turn_id}` was not found.")
        return RuntimeTurnRecord(**document)

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        return [RuntimeTurnRecord(**document) for document in self.collections.turns.find({"session_id": session_id})]

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        self.collections.events.update_one({"event_id": record.event_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        return [RuntimeEventRecord(**document) for document in self.collections.events.find({"session_id": session_id})]

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


def runtime_location(workspace_id: str, start_path=None) -> RuntimeLocation:
    """Return the canonical runtime location for one workspace."""
    return RuntimeLocation(
        workspace_id=workspace_id,
        path=workspace_runtime_root(workspace_id=workspace_id, start_path=start_path),
    )
