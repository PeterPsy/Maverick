"""Deterministic fixtures for durable job tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from core.jobs.executor_models import ExecutorAdvertisement, HandlerCapability
from core.jobs.models import (
    JobBudget,
    JobInputGrant,
    JobOutputGrant,
    JobResourceRequirements,
    JobRetryPolicy,
    JobSpec,
)
from core.jobs.service import JobService
from core.jobs.store import JobCollections, JobDocumentStore
from core.shared.in_memory_collection import InMemoryCollection


START = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def make_store(collection_factory=InMemoryCollection) -> JobDocumentStore:
    return JobDocumentStore(
        JobCollections(
            jobs=collection_factory(),
            events=collection_factory(),
            audits=collection_factory(),
            logs=collection_factory(),
            executors=collection_factory(),
            quotas=collection_factory(),
        )
    )


def make_service(clock: FixedClock | None = None) -> tuple[JobService, FixedClock]:
    fixed_clock = clock or FixedClock()
    service = JobService(make_store(), clock=fixed_clock)
    service.register_input_validator("file.content.read", lambda _spec, _grant: True)
    return service, fixed_clock


def make_spec(
    *,
    workspace_id: str = "workspace-a",
    idempotency_key: str = "idem-1",
    priority: int = 50,
    max_attempts: int = 2,
    with_output: bool = True,
    submitted_by_actor_id: str = "agent-one",
) -> JobSpec:
    output = (
        JobOutputGrant(
            grant_id="output-grant",
            provider_interface="file.content.write",
            expires_at=START + timedelta(hours=2),
            max_bytes=10_000,
            accepted_mime_types=("application/octet-stream",),
        )
        if with_output
        else None
    )
    return JobSpec(
        job_type="test.compute",
        handler_name="test-handler",
        handler_version="1",
        workspace_id=workspace_id,
        submitted_by_app_id="test-app",
        submitted_by_actor_id=submitted_by_actor_id,
        priority=priority,
        resources=JobResourceRequirements(
            cpu_cores=1,
            ram_bytes=128,
            disk_bytes=64,
            runtime="python",
            runtime_version="3.12",
        ),
        budget=JobBudget(max_runtime_seconds=3600, max_output_bytes=10_000),
        idempotency_key=idempotency_key,
        input_grants=(
            JobInputGrant(
                grant_id="input-grant",
                provider_interface="file.content.read",
                resource_ref="file-input",
                sha256="a" * 64,
                size_bytes=10,
                mime_type="application/octet-stream",
                expires_at=START + timedelta(hours=2),
            ),
        ),
        output_grant=output,
        retry=JobRetryPolicy(max_attempts=max_attempts, initial_backoff_seconds=5),
        timeout_seconds=300,
        expires_at=START + timedelta(hours=1),
        parameters={"value": 1},
    )


def make_executor(
    *,
    executor_id: str = "executor-a",
    cpu_cores: float = 4,
    max_concurrent_jobs: int = 2,
    status: str = "active",
) -> ExecutorAdvertisement:
    return ExecutorAdvertisement(
        executor_id=executor_id,
        status=status,
        handlers=(HandlerCapability("test.compute", "test-handler", ("1",)),),
        cpu_cores=cpu_cores,
        ram_bytes=4096,
        gpu_count=0,
        accelerator_kinds=(),
        disk_bytes=4096,
        runtimes={"python": ("3.12",)},
        network_modes=("deny_all",),
        max_concurrent_jobs=max_concurrent_jobs,
        labels={"pool": "test"},
        advertised_at=START,
        expires_at=START + timedelta(hours=1),
    )


def changed_spec(spec: JobSpec) -> JobSpec:
    return replace(spec, parameters={"value": 2})
