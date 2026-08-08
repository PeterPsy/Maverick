"""Durable submission, quota, and fair-claim operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from core.jobs.errors import (
    JobConcurrencyError,
    JobIdempotencyConflictError,
    JobQuotaExceededError,
    JobTransitionError,
    JobValidationError,
)
from core.jobs.executor_registry import executor_compatibility_error
from core.jobs.models import JobSpec, require_identifier
from core.jobs.records import JobRecord, WorkspaceJobQuota
from core.jobs.scheduling import fair_ready_jobs
from core.jobs.serialization import job_spec_fingerprint


DEFAULT_JOB_QUOTA = (1000, 2)


class JobSubmissionOperations:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def submit(self, spec: JobSpec, *, job_id: str | None, actor_id: str | None) -> JobRecord:
        now = self.owner.clock()
        effective_actor_id = actor_id or spec.submitted_by_actor_id
        if effective_actor_id != spec.submitted_by_actor_id:
            raise JobValidationError("Job spec actor must match the trusted actor context.")
        fingerprint = job_spec_fingerprint(spec)
        existing = self.owner.store.get_by_idempotency_key(
            workspace_id=spec.workspace_id,
            idempotency_key=spec.idempotency_key,
        )
        if existing is not None:
            if existing.spec_fingerprint != fingerprint:
                raise JobIdempotencyConflictError(
                    f"Idempotency key `{spec.idempotency_key}` is already bound to another job spec."
                )
            return existing
        self.validate_grants(spec, now=now)
        self.owner.input_validators.validate(spec)
        self.enforce_quota(spec)
        record = JobRecord(
            job_id=require_identifier(job_id or f"job_{uuid4().hex}", "job_id"),
            spec=spec,
            spec_fingerprint=fingerprint,
            state="queued",
            attempt=0,
            available_at=now,
            lease=None,
            progress=None,
            result=None,
            failure=None,
            cancellation_reason=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            last_leased_at=None,
            finished_at=None,
            revision=0,
            last_mutation_id=str(uuid4()),
        )
        persisted, inserted = self.owner.store.submit(record)
        if inserted:
            self.owner.record_change(None, persisted, action="job.submit", actor_id=effective_actor_id)
        return persisted

    def claim_next(self, *, executor_id: str, lease_seconds: int) -> JobRecord | None:
        self.owner.recover_expired_jobs()
        now = self.owner.clock()
        executor = self.owner.executors.get(executor_id)
        records = self.owner.list()
        candidates = fair_ready_jobs(records, now=now, quota_for=self.quota_for)
        for candidate in candidates:
            if executor_compatibility_error(executor, candidate.spec, active_jobs=records, now=now) is not None:
                continue
            try:
                return self.owner.lease(
                    candidate.job_id,
                    workspace_id=candidate.spec.workspace_id,
                    executor_id=executor_id,
                    lease_seconds=lease_seconds,
                )
            except (JobConcurrencyError, JobQuotaExceededError, JobTransitionError):
                records = self.owner.list()
        return None

    def configure_quota(self, quota: WorkspaceJobQuota) -> WorkspaceJobQuota:
        return self.owner.store.save_quota(quota)

    def quota_for(self, workspace_id: str) -> WorkspaceJobQuota:
        existing = self.owner.store.get_quota(workspace_id)
        if existing is not None:
            return existing
        return WorkspaceJobQuota(
            workspace_id=workspace_id,
            max_queued_jobs=DEFAULT_JOB_QUOTA[0],
            max_concurrent_jobs=DEFAULT_JOB_QUOTA[1],
            max_cpu_cores_per_job=None,
            max_ram_bytes_per_job=None,
            max_gpu_count_per_job=None,
            updated_at=self.owner.clock(),
        )

    def enforce_quota(self, spec: JobSpec) -> None:
        quota = self.quota_for(spec.workspace_id)
        queued = sum(1 for item in self.owner.list(workspace_id=spec.workspace_id) if item.state == "queued")
        if queued >= quota.max_queued_jobs:
            raise JobQuotaExceededError(f"Workspace `{spec.workspace_id}` has reached its queued job quota.")
        resources = spec.resources
        if quota.max_cpu_cores_per_job is not None and resources.cpu_cores > quota.max_cpu_cores_per_job:
            raise JobQuotaExceededError("Job CPU requirement exceeds the workspace quota.")
        if quota.max_ram_bytes_per_job is not None and resources.ram_bytes > quota.max_ram_bytes_per_job:
            raise JobQuotaExceededError("Job RAM requirement exceeds the workspace quota.")
        if quota.max_gpu_count_per_job is not None and resources.gpu_count > quota.max_gpu_count_per_job:
            raise JobQuotaExceededError("Job GPU requirement exceeds the workspace quota.")

    @staticmethod
    def validate_grants(spec: JobSpec, *, now: datetime) -> None:
        expired = [grant.grant_id for grant in spec.input_grants if grant.expires_at <= now]
        if spec.output_grant is not None and spec.output_grant.expires_at <= now:
            expired.append(spec.output_grant.grant_id)
        if spec.expires_at is not None and spec.expires_at <= now:
            expired.append("job")
        if expired:
            raise JobValidationError("Job contains expired grants: " + ", ".join(sorted(expired)))
        if spec.output_grant is not None and spec.output_grant.max_bytes > spec.budget.max_output_bytes:
            raise JobValidationError("Output grant exceeds the job output budget.")
