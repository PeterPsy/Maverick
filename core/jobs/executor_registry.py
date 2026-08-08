"""Executor advertisement, compatibility, capacity, and selection rules."""

from __future__ import annotations

from datetime import datetime

from core.jobs.errors import ExecutorCompatibilityError
from core.jobs.executor_models import ExecutorAdvertisement
from core.jobs.models import JobSpec, LEASED_JOB_STATES
from core.jobs.records import JobRecord
from core.jobs.store import JobStore


class ExecutorRegistry:
    """Persist advertisements and select executors without app-specific policy."""

    def __init__(self, store: JobStore, *, clock) -> None:
        self.store = store
        self.clock = clock

    def advertise(self, advertisement: ExecutorAdvertisement) -> ExecutorAdvertisement:
        now = self.clock()
        if advertisement.advertised_at > now:
            raise ExecutorCompatibilityError("Executor advertisement cannot be dated in the future.")
        if advertisement.expires_at <= now:
            raise ExecutorCompatibilityError("Executor advertisement is already expired.")
        return self.store.save_executor(advertisement)

    def get(self, executor_id: str) -> ExecutorAdvertisement:
        return self.store.get_executor(executor_id)

    def compatible(self, spec: JobSpec) -> list[ExecutorAdvertisement]:
        now = self.clock()
        active = [job for job in self.store.list_jobs() if job.state in LEASED_JOB_STATES and job.lease]
        compatible = [
            executor
            for executor in self.store.list_executors()
            if executor_compatibility_error(executor, spec, active_jobs=active, now=now) is None
        ]
        return sorted(compatible, key=lambda item: (_executor_load(item, active), item.executor_id))

    def select(self, spec: JobSpec) -> ExecutorAdvertisement:
        candidates = self.compatible(spec)
        if not candidates:
            raise ExecutorCompatibilityError("No active executor satisfies the job requirements.")
        return candidates[0]

    def require_compatible(self, executor_id: str, spec: JobSpec) -> ExecutorAdvertisement:
        executor = self.get(executor_id)
        active = [job for job in self.store.list_jobs() if job.state in LEASED_JOB_STATES and job.lease]
        error = executor_compatibility_error(executor, spec, active_jobs=active, now=self.clock())
        if error is not None:
            raise ExecutorCompatibilityError(error)
        return executor


def executor_compatibility_error(
    executor: ExecutorAdvertisement,
    spec: JobSpec,
    *,
    active_jobs: list[JobRecord],
    now: datetime,
) -> str | None:
    """Return a stable incompatibility reason or ``None`` when leaseable."""
    if executor.status != "active":
        return f"Executor `{executor.executor_id}` is not active."
    if executor.expires_at <= now:
        return f"Executor `{executor.executor_id}` advertisement has expired."
    if not _supports_handler(executor, spec):
        return f"Executor `{executor.executor_id}` does not advertise the requested handler."
    if spec.network_policy.mode not in executor.network_modes:
        return f"Executor `{executor.executor_id}` does not support the requested network policy."
    runtime_versions = executor.runtimes.get(spec.resources.runtime)
    if runtime_versions is None:
        return f"Executor `{executor.executor_id}` does not provide runtime `{spec.resources.runtime}`."
    if spec.resources.runtime_version is not None and spec.resources.runtime_version not in runtime_versions:
        return f"Executor `{executor.executor_id}` does not provide the requested runtime version."
    if not set(spec.resources.accelerator_kinds).issubset(executor.accelerator_kinds):
        return f"Executor `{executor.executor_id}` lacks a requested accelerator."
    owned = [job for job in active_jobs if job.lease and job.lease.executor_id == executor.executor_id]
    if len(owned) >= executor.max_concurrent_jobs:
        return f"Executor `{executor.executor_id}` has reached its concurrency limit."
    used_cpu = sum(job.spec.resources.cpu_cores for job in owned)
    used_ram = sum(job.spec.resources.ram_bytes for job in owned)
    used_gpu = sum(job.spec.resources.gpu_count for job in owned)
    used_disk = sum(job.spec.resources.disk_bytes for job in owned)
    resources = spec.resources
    if used_cpu + resources.cpu_cores > executor.cpu_cores:
        return f"Executor `{executor.executor_id}` lacks CPU capacity."
    if used_ram + resources.ram_bytes > executor.ram_bytes:
        return f"Executor `{executor.executor_id}` lacks RAM capacity."
    if used_gpu + resources.gpu_count > executor.gpu_count:
        return f"Executor `{executor.executor_id}` lacks GPU capacity."
    if used_disk + resources.disk_bytes > executor.disk_bytes:
        return f"Executor `{executor.executor_id}` lacks disk capacity."
    return None


def _supports_handler(executor: ExecutorAdvertisement, spec: JobSpec) -> bool:
    return any(
        handler.job_type == spec.job_type
        and handler.handler_name == spec.handler_name
        and spec.handler_version in handler.handler_versions
        for handler in executor.handlers
    )


def _executor_load(executor: ExecutorAdvertisement, active_jobs: list[JobRecord]) -> tuple[float, int]:
    count = sum(
        1
        for job in active_jobs
        if job.lease is not None and job.lease.executor_id == executor.executor_id
    )
    return count / executor.max_concurrent_jobs, count
