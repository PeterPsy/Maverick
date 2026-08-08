"""Public application service facade for durable jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from core.jobs.change_recorder import JobChangeRecorder
from core.jobs.execution_service import JobExecutionOperations
from core.jobs.executor_registry import ExecutorRegistry
from core.jobs.input_validators import JobInputGrantValidator, JobInputGrantValidatorRegistry
from core.jobs.models import JobSpec, JobState
from core.jobs.output_publishers import JobOutputPublisher, JobOutputPublisherRegistry
from core.jobs.records import (
    JobAuditRecord,
    JobEventRecord,
    JobLogRecord,
    JobRecord,
    WorkspaceJobQuota,
)
from core.jobs.recovery_service import JobRecoveryOperations
from core.jobs.store import JobStore
from core.jobs.submission_service import JobSubmissionOperations


Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class JobService:
    """Expose one storage-agnostic service while domain modules own behavior."""

    def __init__(
        self,
        store: JobStore,
        *,
        clock: Clock = utcnow,
        event_bus=None,
        observability_store=None,
        input_validators: JobInputGrantValidatorRegistry | None = None,
        output_publishers: JobOutputPublisherRegistry | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.executors = ExecutorRegistry(store, clock=clock)
        self.input_validators = input_validators or JobInputGrantValidatorRegistry()
        self.output_publishers = output_publishers or JobOutputPublisherRegistry()
        self.change_recorder = JobChangeRecorder(
            store,
            event_bus=event_bus,
            observability_store=observability_store,
        )
        self.submission = JobSubmissionOperations(self)
        self.execution = JobExecutionOperations(self)
        self.recovery = JobRecoveryOperations(self)

    def submit(self, spec: JobSpec, *, job_id: str | None = None, actor_id: str | None = None) -> JobRecord:
        return self.submission.submit(spec, job_id=job_id, actor_id=actor_id)

    def get(self, job_id: str, *, workspace_id: str) -> JobRecord:
        return self.store.get_job(job_id, workspace_id=workspace_id)

    def list(self, *, workspace_id: str | None = None, state: JobState | None = None) -> list[JobRecord]:
        return self.store.list_jobs(workspace_id=workspace_id, state=state)

    def list_events(self, job_id: str, *, workspace_id: str) -> list[JobEventRecord]:
        self.get(job_id, workspace_id=workspace_id)
        return self.store.list_events(job_id, workspace_id=workspace_id)

    def list_workspace_events(self, *, workspace_id: str) -> list[JobEventRecord]:
        return self.store.list_workspace_events(workspace_id=workspace_id)

    def list_audits(self, job_id: str, *, workspace_id: str) -> list[JobAuditRecord]:
        self.get(job_id, workspace_id=workspace_id)
        return self.store.list_audits(job_id, workspace_id=workspace_id)

    def list_logs(self, job_id: str, *, workspace_id: str) -> list[JobLogRecord]:
        self.get(job_id, workspace_id=workspace_id)
        return self.store.list_logs(job_id, workspace_id=workspace_id)

    def advertise_executor(self, advertisement):
        return self.executors.advertise(advertisement)

    def select_executor(self, spec: JobSpec):
        return self.executors.select(spec)

    def register_output_publisher(self, provider_interface: str, publisher: JobOutputPublisher) -> None:
        self.output_publishers.register(provider_interface, publisher)

    def register_input_validator(self, provider_interface: str, validator: JobInputGrantValidator) -> None:
        self.input_validators.register(provider_interface, validator)

    def claim_next(self, *, executor_id: str, lease_seconds: int) -> JobRecord | None:
        return self.submission.claim_next(executor_id=executor_id, lease_seconds=lease_seconds)

    def configure_quota(self, quota: WorkspaceJobQuota) -> WorkspaceJobQuota:
        return self.submission.configure_quota(quota)

    def quota_for(self, workspace_id: str) -> WorkspaceJobQuota:
        return self.submission.quota_for(workspace_id)

    def lease(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.lease(job_id, **kwargs)

    def heartbeat(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.heartbeat(job_id, **kwargs)

    def advance(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.advance(job_id, **kwargs)

    def report_progress(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.report_progress(job_id, **kwargs)

    def record_log(self, job_id: str, **kwargs) -> JobLogRecord:
        return self.execution.record_log(job_id, **kwargs)

    def request_cancel(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.request_cancel(job_id, **kwargs)

    def acknowledge_cancel(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.acknowledge_cancel(job_id, **kwargs)

    def complete(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.complete(job_id, **kwargs)

    def fail(self, job_id: str, **kwargs) -> JobRecord:
        return self.execution.fail(job_id, **kwargs)

    def recover_expired_jobs(self) -> list[JobRecord]:
        return self.recovery.recover_expired_jobs()

    def commit(self, previous: JobRecord, updated: JobRecord, **context) -> JobRecord:
        persisted = self.store.compare_and_set(updated, expected_revision=previous.revision)
        self.record_change(previous, persisted, **context)
        return persisted

    def record_change(self, previous: JobRecord | None, current: JobRecord, **context) -> None:
        self.change_recorder.record(previous, current, **context)
