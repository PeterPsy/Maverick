"""Store contracts and Mongo-style adapters for recovery-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.recovery.errors import (
    RecoveryFailureNotFoundError,
    RecoveryIntentNotFoundError,
)
from core.recovery.models import HealthCheckResult, RecoveryIntentRecord, RuntimeFailureRecord


class MongoCollection(Protocol):
    """Minimal collection protocol used by Mongo-style recovery stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


class RecoveryStore(Protocol):
    """Persistence contract for recovery failures, intents, and health results."""

    def save_failure(self, record: RuntimeFailureRecord) -> RuntimeFailureRecord:
        ...

    def get_failure(self, failure_id: str) -> RuntimeFailureRecord:
        ...

    def list_failures(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[RuntimeFailureRecord]:
        ...

    def save_intent(self, record: RecoveryIntentRecord) -> RecoveryIntentRecord:
        ...

    def get_intent(self, intent_id: str) -> RecoveryIntentRecord:
        ...

    def list_intents(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[RecoveryIntentRecord]:
        ...

    def save_health_result(self, record: HealthCheckResult) -> HealthCheckResult:
        ...

    def list_health_results(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
        target_kind: str | None = None,
    ) -> list[HealthCheckResult]:
        ...


@dataclass(frozen=True)
class RecoveryCollections:
    """Mongo collection bundle for recovery persistence."""

    failures: MongoCollection
    intents: MongoCollection
    health_results: MongoCollection


class MongoRecoveryStore:
    """Persist recovery-domain records in Mongo-style collections."""

    def __init__(self, collections: RecoveryCollections) -> None:
        self.collections = collections

    def save_failure(self, record: RuntimeFailureRecord) -> RuntimeFailureRecord:
        self.collections.failures.update_one({"failure_id": record.failure_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_failure(self, failure_id: str) -> RuntimeFailureRecord:
        document = self.collections.failures.find_one({"failure_id": failure_id})
        if document is None:
            raise RecoveryFailureNotFoundError(f"Recovery failure `{failure_id}` was not found.")
        return RuntimeFailureRecord(**document)

    def list_failures(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[RuntimeFailureRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if session_id is not None:
            query["session_id"] = session_id
        return [RuntimeFailureRecord(**document) for document in self.collections.failures.find(query)]

    def save_intent(self, record: RecoveryIntentRecord) -> RecoveryIntentRecord:
        self.collections.intents.update_one({"intent_id": record.intent_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def get_intent(self, intent_id: str) -> RecoveryIntentRecord:
        document = self.collections.intents.find_one({"intent_id": intent_id})
        if document is None:
            raise RecoveryIntentNotFoundError(f"Recovery intent `{intent_id}` was not found.")
        return RecoveryIntentRecord(**document)

    def list_intents(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> list[RecoveryIntentRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if session_id is not None:
            query["session_id"] = session_id
        return [RecoveryIntentRecord(**document) for document in self.collections.intents.find(query)]

    def save_health_result(self, record: HealthCheckResult) -> HealthCheckResult:
        self.collections.health_results.update_one({"check_id": record.check_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def list_health_results(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
        target_kind: str | None = None,
    ) -> list[HealthCheckResult]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if session_id is not None:
            query["session_id"] = session_id
        if target_kind is not None:
            query["target_kind"] = target_kind
        return [HealthCheckResult(**document) for document in self.collections.health_results.find(query)]
