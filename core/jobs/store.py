"""Storage-agnostic durable job store contracts and document adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.jobs.errors import (
    ExecutorNotFoundError,
    JobConcurrencyError,
    JobIdempotencyConflictError,
    JobNotFoundError,
)
from core.jobs.executor_models import ExecutorAdvertisement
from core.jobs.models import JobState
from core.jobs.records import JobAuditRecord, JobEventRecord, JobLogRecord, JobRecord, WorkspaceJobQuota
from core.jobs.serialization import (
    audit_from_document,
    event_from_document,
    executor_from_document,
    executor_to_document,
    job_record_from_document,
    job_record_to_document,
    log_from_document,
    quota_from_document,
)


class DocumentCollection(Protocol):
    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def insert_one_if_absent(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        ...

    def delete_one(self, query: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class JobCollections:
    jobs: DocumentCollection
    events: DocumentCollection
    audits: DocumentCollection
    logs: DocumentCollection
    executors: DocumentCollection
    quotas: DocumentCollection


class JobStore(Protocol):
    def submit(self, record: JobRecord) -> tuple[JobRecord, bool]:
        ...

    def get_job(self, job_id: str, *, workspace_id: str) -> JobRecord:
        ...

    def get_by_idempotency_key(self, *, workspace_id: str, idempotency_key: str) -> JobRecord | None:
        ...

    def list_jobs(self, *, workspace_id: str | None = None, state: JobState | None = None) -> list[JobRecord]:
        ...

    def compare_and_set(self, record: JobRecord, *, expected_revision: int) -> JobRecord:
        ...

    def append_event(self, record: JobEventRecord) -> JobEventRecord:
        ...

    def append_audit(self, record: JobAuditRecord) -> JobAuditRecord:
        ...

    def list_events(self, job_id: str, *, workspace_id: str) -> list[JobEventRecord]:
        ...

    def list_workspace_events(self, *, workspace_id: str) -> list[JobEventRecord]:
        ...

    def list_audits(self, job_id: str, *, workspace_id: str) -> list[JobAuditRecord]:
        ...

    def append_log(self, record: JobLogRecord) -> JobLogRecord:
        ...

    def list_logs(self, job_id: str, *, workspace_id: str) -> list[JobLogRecord]:
        ...

    def save_executor(self, record: ExecutorAdvertisement) -> ExecutorAdvertisement:
        ...

    def get_executor(self, executor_id: str) -> ExecutorAdvertisement:
        ...

    def list_executors(self) -> list[ExecutorAdvertisement]:
        ...

    def save_quota(self, record: WorkspaceJobQuota) -> WorkspaceJobQuota:
        ...

    def get_quota(self, workspace_id: str) -> WorkspaceJobQuota | None:
        ...


class JobDocumentStore:
    """Persist durable job records without leaking adapter types to services."""

    def __init__(self, collections: JobCollections, *, max_log_records_per_job: int = 1000) -> None:
        if max_log_records_per_job < 1:
            raise ValueError("max_log_records_per_job must be positive.")
        self.collections = collections
        self.max_log_records_per_job = max_log_records_per_job

    def submit(self, record: JobRecord) -> tuple[JobRecord, bool]:
        document, inserted = self.collections.jobs.insert_one_if_absent(
            {"workspace_id": record.spec.workspace_id, "idempotency_key": record.spec.idempotency_key},
            {
                **job_record_to_document(record),
                "workspace_id": record.spec.workspace_id,
                "idempotency_key": record.spec.idempotency_key,
            },
        )
        existing = job_record_from_document(_without_index_fields(document))
        if not inserted and existing.spec_fingerprint != record.spec_fingerprint:
            raise JobIdempotencyConflictError(
                f"Idempotency key `{record.spec.idempotency_key}` is already bound to another job spec."
            )
        return existing, inserted

    def get_job(self, job_id: str, *, workspace_id: str) -> JobRecord:
        document = self.collections.jobs.find_one({"workspace_id": workspace_id, "job_id": job_id})
        if document is None:
            raise JobNotFoundError(f"Job `{job_id}` was not found in workspace `{workspace_id}`.")
        return job_record_from_document(_without_index_fields(document))

    def get_by_idempotency_key(self, *, workspace_id: str, idempotency_key: str) -> JobRecord | None:
        document = self.collections.jobs.find_one(
            {"workspace_id": workspace_id, "idempotency_key": idempotency_key}
        )
        return None if document is None else job_record_from_document(_without_index_fields(document))

    def list_jobs(
        self,
        *,
        workspace_id: str | None = None,
        state: JobState | None = None,
    ) -> list[JobRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if state is not None:
            query["state"] = state
        records = [job_record_from_document(_without_index_fields(item)) for item in self.collections.jobs.find(query)]
        return sorted(records, key=lambda item: (item.created_at, item.job_id))

    def compare_and_set(self, record: JobRecord, *, expected_revision: int) -> JobRecord:
        self.collections.jobs.update_one(
            {
                "workspace_id": record.spec.workspace_id,
                "job_id": record.job_id,
                "revision": expected_revision,
            },
            {
                "$set": {
                    **job_record_to_document(record),
                    "workspace_id": record.spec.workspace_id,
                    "idempotency_key": record.spec.idempotency_key,
                }
            },
        )
        updated = self.collections.jobs.find_one(
            {
                "workspace_id": record.spec.workspace_id,
                "job_id": record.job_id,
                "revision": record.revision,
                "last_mutation_id": record.last_mutation_id,
            }
        )
        if updated is None:
            raise JobConcurrencyError(f"Job `{record.job_id}` changed concurrently.")
        return job_record_from_document(_without_index_fields(updated))

    def append_event(self, record: JobEventRecord) -> JobEventRecord:
        document, _ = self.collections.events.insert_one_if_absent(
            {"event_id": record.event_id},
            asdict(record),
        )
        return event_from_document(document)

    def append_audit(self, record: JobAuditRecord) -> JobAuditRecord:
        document, _ = self.collections.audits.insert_one_if_absent(
            {"audit_id": record.audit_id},
            asdict(record),
        )
        return audit_from_document(document)

    def list_events(self, job_id: str, *, workspace_id: str) -> list[JobEventRecord]:
        records = [
            event_from_document(item)
            for item in self.collections.events.find({"workspace_id": workspace_id, "job_id": job_id})
        ]
        return sorted(records, key=lambda item: (item.occurred_at, _record_revision(item), item.event_id))

    def list_workspace_events(self, *, workspace_id: str) -> list[JobEventRecord]:
        records = [
            event_from_document(item)
            for item in self.collections.events.find({"workspace_id": workspace_id})
        ]
        return sorted(
            records,
            key=lambda item: (item.occurred_at, item.job_id, _record_revision(item), item.event_id),
        )

    def list_audits(self, job_id: str, *, workspace_id: str) -> list[JobAuditRecord]:
        records = [
            audit_from_document(item)
            for item in self.collections.audits.find({"workspace_id": workspace_id, "job_id": job_id})
        ]
        return sorted(records, key=lambda item: (item.occurred_at, _record_revision(item), item.audit_id))

    def append_log(self, record: JobLogRecord) -> JobLogRecord:
        document, _ = self.collections.logs.insert_one_if_absent(
            {"log_id": record.log_id},
            asdict(record),
        )
        persisted = log_from_document(document)
        records = self.list_logs(record.job_id, workspace_id=record.workspace_id)
        overflow = len(records) - self.max_log_records_per_job
        for stale in records[: max(0, overflow)]:
            self.collections.logs.delete_one({"log_id": stale.log_id})
        return persisted

    def list_logs(self, job_id: str, *, workspace_id: str) -> list[JobLogRecord]:
        records = [
            log_from_document(item)
            for item in self.collections.logs.find({"workspace_id": workspace_id, "job_id": job_id})
        ]
        return sorted(records, key=lambda item: (item.occurred_at, item.log_id))

    def save_executor(self, record: ExecutorAdvertisement) -> ExecutorAdvertisement:
        self.collections.executors.update_one(
            {"executor_id": record.executor_id},
            {"$set": executor_to_document(record)},
            upsert=True,
        )
        return record

    def get_executor(self, executor_id: str) -> ExecutorAdvertisement:
        document = self.collections.executors.find_one({"executor_id": executor_id})
        if document is None:
            raise ExecutorNotFoundError(f"Executor `{executor_id}` was not found.")
        return executor_from_document(document)

    def list_executors(self) -> list[ExecutorAdvertisement]:
        return sorted(
            [executor_from_document(item) for item in self.collections.executors.find({})],
            key=lambda item: item.executor_id,
        )

    def save_quota(self, record: WorkspaceJobQuota) -> WorkspaceJobQuota:
        self.collections.quotas.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_quota(self, workspace_id: str) -> WorkspaceJobQuota | None:
        document = self.collections.quotas.find_one({"workspace_id": workspace_id})
        return quota_from_document(document) if document is not None else None


def _without_index_fields(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document)
    payload.pop("workspace_id", None)
    payload.pop("idempotency_key", None)
    return payload


def _record_revision(record: JobEventRecord | JobAuditRecord) -> int:
    revision = record.payload.get("revision")
    return revision if isinstance(revision, int) and not isinstance(revision, bool) else -1
