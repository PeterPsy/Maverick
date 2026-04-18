"""Store contracts and Mongo-style adapters for observability-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.observability.models import AuditRecord, MetricRecord, StructuredEventRecord


class MongoCollection(Protocol):
    """Minimal collection protocol used by Mongo-style observability stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


class ObservabilityStore(Protocol):
    """Persistence contract for events, audit records, and metrics."""

    def save_event(self, record: StructuredEventRecord) -> StructuredEventRecord:
        ...

    def list_events(
        self,
        *,
        workspace_id: str | None = None,
        runtime_session_id: str | None = None,
        event_plane: str | None = None,
    ) -> list[StructuredEventRecord]:
        ...

    def save_audit(self, record: AuditRecord) -> AuditRecord:
        ...

    def list_audit(
        self,
        *,
        workspace_id: str | None = None,
        source_domain: str | None = None,
    ) -> list[AuditRecord]:
        ...

    def save_metric(self, record: MetricRecord) -> MetricRecord:
        ...

    def list_metrics(
        self,
        *,
        workspace_id: str | None = None,
        metric_name: str | None = None,
    ) -> list[MetricRecord]:
        ...


@dataclass(frozen=True)
class ObservabilityCollections:
    """Mongo collection bundle for observability persistence."""

    events: MongoCollection
    audit: MongoCollection
    metrics: MongoCollection


class MongoObservabilityStore:
    """Persist observability-domain records in Mongo-style collections."""

    def __init__(self, collections: ObservabilityCollections) -> None:
        self.collections = collections

    def save_event(self, record: StructuredEventRecord) -> StructuredEventRecord:
        self.collections.events.update_one({"event_id": record.event_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def list_events(
        self,
        *,
        workspace_id: str | None = None,
        runtime_session_id: str | None = None,
        event_plane: str | None = None,
    ) -> list[StructuredEventRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if runtime_session_id is not None:
            query["runtime_session_id"] = runtime_session_id
        if event_plane is not None:
            query["event_plane"] = event_plane
        return [StructuredEventRecord(**document) for document in self.collections.events.find(query)]

    def save_audit(self, record: AuditRecord) -> AuditRecord:
        self.collections.audit.update_one({"audit_id": record.audit_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def list_audit(
        self,
        *,
        workspace_id: str | None = None,
        source_domain: str | None = None,
    ) -> list[AuditRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if source_domain is not None:
            query["source_domain"] = source_domain
        return [AuditRecord(**document) for document in self.collections.audit.find(query)]

    def save_metric(self, record: MetricRecord) -> MetricRecord:
        self.collections.metrics.update_one({"metric_id": record.metric_id}, {"$set": asdict(record)}, upsert=True)
        return record

    def list_metrics(
        self,
        *,
        workspace_id: str | None = None,
        metric_name: str | None = None,
    ) -> list[MetricRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if metric_name is not None:
            query["metric_name"] = metric_name
        return [MetricRecord(**document) for document in self.collections.metrics.find(query)]
