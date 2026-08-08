"""Mutable control-plane records for durable jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from core.jobs.errors import JobValidationError
from core.jobs.models import MAX_BYTE_VALUE, JobSpec, JobState, require_aware_datetime, require_identifier


@dataclass(frozen=True)
class JobLease:
    executor_id: str
    lease_token: str
    leased_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class JobProgress:
    phase: str
    completed: int
    total: int | None
    unit: str | None
    message: str | None
    updated_at: datetime


@dataclass(frozen=True)
class JobOutputReference:
    grant_id: str
    resource_id: str
    sha256: str
    size_bytes: int
    mime_type: str


@dataclass(frozen=True)
class JobExecutionResult:
    outputs: tuple[JobOutputReference, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class JobFailure:
    error_code: str
    message: str
    retryable: bool
    failed_at: datetime


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    spec: JobSpec
    spec_fingerprint: str
    state: JobState
    attempt: int
    available_at: datetime
    lease: JobLease | None
    progress: JobProgress | None
    result: JobExecutionResult | None
    failure: JobFailure | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    last_leased_at: datetime | None
    finished_at: datetime | None
    revision: int
    last_mutation_id: str


@dataclass(frozen=True)
class JobEventRecord:
    event_id: str
    event_type: str
    workspace_id: str
    job_id: str
    previous_state: JobState | None
    state: JobState
    attempt: int
    executor_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class JobAuditRecord:
    audit_id: str
    action: str
    status: str
    workspace_id: str
    job_id: str
    attempt: int
    actor_id: str | None
    executor_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class JobLogRecord:
    log_id: str
    workspace_id: str
    job_id: str
    attempt: int
    executor_id: str
    level: str
    code: str
    fields: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class WorkspaceJobQuota:
    workspace_id: str
    max_queued_jobs: int
    max_concurrent_jobs: int
    max_cpu_cores_per_job: float | None
    max_ram_bytes_per_job: int | None
    max_gpu_count_per_job: int | None
    updated_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.workspace_id, "quota.workspace_id")
        if not _integer_between(self.max_queued_jobs, 1, 1_000_000):
            raise JobValidationError("quota.max_queued_jobs is outside the supported range.")
        if not _integer_between(self.max_concurrent_jobs, 1, 100_000):
            raise JobValidationError("quota.max_concurrent_jobs is outside the supported range.")
        if self.max_cpu_cores_per_job is not None and (
            isinstance(self.max_cpu_cores_per_job, bool)
            or not math.isfinite(self.max_cpu_cores_per_job)
            or self.max_cpu_cores_per_job <= 0
        ):
            raise JobValidationError("quota.max_cpu_cores_per_job is invalid.")
        if self.max_ram_bytes_per_job is not None and not _integer_between(
            self.max_ram_bytes_per_job,
            1,
            MAX_BYTE_VALUE,
        ):
            raise JobValidationError("quota.max_ram_bytes_per_job is invalid.")
        if self.max_gpu_count_per_job is not None and not _integer_between(
            self.max_gpu_count_per_job,
            0,
            4096,
        ):
            raise JobValidationError("quota.max_gpu_count_per_job is invalid.")
        require_aware_datetime(self.updated_at, "quota.updated_at")


def _integer_between(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
