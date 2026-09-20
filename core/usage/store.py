"""Persistence contracts and document adapter for usage metering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from core.usage.handoff import document_operation
from core.usage.canonical import canonical_usage_samples
from core.usage.models import ChatUsageSummary, ProviderQuotaSnapshotRecord, UsageBucketRecord, UsageSampleRecord


class UsageHistory(Protocol):
    def previous_cumulative_sample(self, *, workspace_id: str, session_id: str, provider_id: str,
        model_id: str | None, source: str, before: datetime, sample_id: str) -> UsageSampleRecord | None: ...


SampleBuilder = Callable[[UsageHistory], UsageSampleRecord | None]


@runtime_checkable
class UsageStore(UsageHistory, Protocol):
    """Usage-owned persistence, independent of the control-plane document adapter."""

    def ingest_observation(self, builder: SampleBuilder, *, payload: dict) -> tuple[UsageSampleRecord, bool] | None: ...
    def chat_summary(self, *, workspace_id: str, root_session_id: str, direct_session_ids: set[str]) -> ChatUsageSummary: ...
    def timeseries(self, **filters) -> dict[str, object]: ...
    def list_samples(self, *, workspace_id: str | None = None, root_session_id: str | None = None,
        session_id: str | None = None) -> list[UsageSampleRecord]: ...
    def save_quota_snapshot_if_absent(self, record: ProviderQuotaSnapshotRecord) -> tuple[ProviderQuotaSnapshotRecord, bool]: ...
    def list_quota_snapshots(self, *, workspace_id: str) -> list[ProviderQuotaSnapshotRecord]: ...
    def delete_session(self, session_id: str) -> int: ...
    def delete_sessions(self, session_ids: list[str]) -> dict[str, int]: ...


class UsageCollection(Protocol):
    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any: ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any: ...

    def insert_one_if_absent(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]: ...

    def delete_many(self, query: dict[str, Any]) -> int: ...

    def delete_many_documents(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class UsageCollections:
    """Collections required by the durable usage domain."""

    samples: UsageCollection
    buckets: UsageCollection
    quota_snapshots: UsageCollection


class UsageDocumentStore:
    """Persist canonical usage samples, chart rollups, and quota snapshots."""

    def __init__(self, collections: UsageCollections, *, handoff_root: Path | None = None) -> None:
        self.collections = collections
        self.handoff_root = handoff_root

    @document_operation
    def ingest_observation(self, builder: SampleBuilder, *, payload: dict) -> tuple[UsageSampleRecord, bool] | None:
        """Temporary pre-cutover adapter; transactional stores own their projections."""
        from core.usage.timeseries import reconcile_sample_buckets
        sample = builder(self)
        if sample is None:
            return None
        persisted, inserted = self.save_sample_if_absent(sample)
        if inserted:
            reconcile_sample_buckets(self, persisted)
        return persisted, inserted

    @document_operation
    def previous_cumulative_sample(self, *, workspace_id: str, session_id: str, provider_id: str,
        model_id: str | None, source: str, before: datetime, sample_id: str) -> UsageSampleRecord | None:
        matching = [sample for sample in self.list_samples(session_id=session_id)
            if sample.workspace_id == workspace_id and sample.semantics == 'cumulative' and sample.provider_id == provider_id
            and sample.model_id == model_id and sample.source == source
            and (sample.observed_at, sample.sample_id) < (before, sample_id)]
        return matching[-1] if matching else None

    @document_operation
    def chat_summary(self, *, workspace_id: str, root_session_id: str, direct_session_ids: set[str]) -> ChatUsageSummary:
        from core.usage.service import summarize_samples
        return summarize_samples(self.list_samples(workspace_id=workspace_id, root_session_id=root_session_id),
            workspace_id=workspace_id, root_session_id=root_session_id, direct_session_ids=direct_session_ids)

    @document_operation
    def timeseries(self, **filters) -> dict[str, object]:
        from core.usage.timeseries import document_usage_timeseries_payload
        return document_usage_timeseries_payload(self, **filters)

    @document_operation
    def save_sample_if_absent(self, record: UsageSampleRecord) -> tuple[UsageSampleRecord, bool]:
        document, inserted = self.collections.samples.insert_one_if_absent(
            {"sample_id": record.sample_id},
            asdict(record),
        )
        return UsageSampleRecord(**document), inserted

    @document_operation
    def list_samples(
        self,
        *,
        workspace_id: str | None = None,
        root_session_id: str | None = None,
        session_id: str | None = None,
    ) -> list[UsageSampleRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if root_session_id is not None:
            query["root_session_id"] = root_session_id
        if session_id is not None:
            query["session_id"] = session_id
        records = [UsageSampleRecord(**document) for document in self.collections.samples.find(query)]
        ordered = sorted(records, key=lambda item: (item.observed_at, item.sample_id))
        return canonical_usage_samples(ordered)

    @document_operation
    def save_bucket(self, record: UsageBucketRecord) -> UsageBucketRecord:
        self.collections.buckets.update_one(
            {"bucket_id": record.bucket_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    @document_operation
    def list_buckets(self, *, workspace_id: str, resolution: str) -> list[UsageBucketRecord]:
        records = [
            UsageBucketRecord(**document)
            for document in self.collections.buckets.find(
                {"workspace_id": workspace_id, "resolution": resolution}
            )
        ]
        return sorted(records, key=lambda item: (item.bucket_start, item.provider_id, item.model_id or ""))

    @document_operation
    def save_quota_snapshot_if_absent(
        self,
        record: ProviderQuotaSnapshotRecord,
    ) -> tuple[ProviderQuotaSnapshotRecord, bool]:
        document, inserted = self.collections.quota_snapshots.insert_one_if_absent(
            {"snapshot_id": record.snapshot_id},
            asdict(record),
        )
        return ProviderQuotaSnapshotRecord(**document), inserted

    @document_operation
    def list_quota_snapshots(self, *, workspace_id: str) -> list[ProviderQuotaSnapshotRecord]:
        records = [
            ProviderQuotaSnapshotRecord(**document)
            for document in self.collections.quota_snapshots.find({"workspace_id": workspace_id})
        ]
        return sorted(records, key=lambda item: (item.observed_at, item.snapshot_id))

    @document_operation
    def delete_session(self, session_id: str) -> int:
        """Delete detailed usage for one runtime session; rollups reconcile on read."""
        return self.delete_sessions([session_id]).get(session_id, 0)

    @document_operation
    def delete_sessions(self, session_ids: list[str]) -> dict[str, int]:
        """Delete detailed usage for many sessions with one collection mutation."""
        unique_session_ids = list(dict.fromkeys(session_ids))
        deleted_by_session_id = {session_id: 0 for session_id in unique_session_ids}
        if not unique_session_ids:
            return deleted_by_session_id
        deleted_documents = self.collections.samples.delete_many_documents(
            {"session_id": {"$in": unique_session_ids}}
        )
        for document in deleted_documents:
            session_id = document.get("session_id")
            if isinstance(session_id, str) and session_id in deleted_by_session_id:
                deleted_by_session_id[session_id] += 1
        return deleted_by_session_id
