"""Executor capability advertisement models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Literal

from core.jobs.errors import JobValidationError
from core.jobs.models import MAX_BYTE_VALUE, NetworkMode, require_aware_datetime, require_identifier


ExecutorStatus = Literal["active", "draining", "offline"]


@dataclass(frozen=True)
class HandlerCapability:
    job_type: str
    handler_name: str
    handler_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.job_type, "handler.job_type")
        require_identifier(self.handler_name, "handler.handler_name")
        if not self.handler_versions:
            raise JobValidationError("handler.handler_versions cannot be empty.")
        if len(self.handler_versions) > 128 or len(self.handler_versions) != len(set(self.handler_versions)):
            raise JobValidationError("handler.handler_versions must be unique.")
        for version in self.handler_versions:
            require_identifier(version, "handler.handler_versions")


@dataclass(frozen=True)
class ExecutorAdvertisement:
    """Leaseable executor capacity and supported handler advertisement."""

    executor_id: str
    status: ExecutorStatus
    handlers: tuple[HandlerCapability, ...]
    cpu_cores: float
    ram_bytes: int
    gpu_count: int
    accelerator_kinds: tuple[str, ...]
    disk_bytes: int
    runtimes: dict[str, tuple[str, ...]]
    network_modes: tuple[NetworkMode, ...]
    max_concurrent_jobs: int
    labels: dict[str, str]
    advertised_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.executor_id, "executor_id")
        if self.status not in {"active", "draining", "offline"}:
            raise JobValidationError("executor.status is invalid.")
        if not self.handlers or len(self.handlers) > 256:
            raise JobValidationError("executor.handlers must be non-empty and bounded.")
        if (
            isinstance(self.cpu_cores, bool)
            or not math.isfinite(self.cpu_cores)
            or self.cpu_cores <= 0
            or not _bounded_integer(self.ram_bytes, minimum=1)
            or not _bounded_integer(self.gpu_count, minimum=0, maximum=4096)
            or not _bounded_integer(self.disk_bytes, minimum=0)
        ):
            raise JobValidationError("Executor capacity is invalid.")
        if not _bounded_integer(self.max_concurrent_jobs, minimum=1, maximum=100_000):
            raise JobValidationError("executor.max_concurrent_jobs must be positive.")
        require_aware_datetime(self.advertised_at, "executor.advertised_at")
        require_aware_datetime(self.expires_at, "executor.expires_at")
        if self.expires_at <= self.advertised_at:
            raise JobValidationError("executor.expires_at must follow advertised_at.")
        handler_keys = [(item.job_type, item.handler_name) for item in self.handlers]
        if len(handler_keys) != len(set(handler_keys)):
            raise JobValidationError("executor.handlers must not contain duplicate handler identities.")
        for accelerator in self.accelerator_kinds:
            require_identifier(accelerator, "executor.accelerator_kinds")
        if len(self.accelerator_kinds) != len(set(self.accelerator_kinds)):
            raise JobValidationError("executor.accelerator_kinds must be unique.")
        if not self.network_modes or any(mode not in {"deny_all", "allowlist"} for mode in self.network_modes):
            raise JobValidationError("executor.network_modes contains an invalid mode.")
        if len(self.network_modes) != len(set(self.network_modes)):
            raise JobValidationError("executor.network_modes must be unique.")
        for runtime, versions in self.runtimes.items():
            require_identifier(runtime, "executor.runtimes key")
            if (
                not versions
                or len(versions) > 128
                or len(versions) != len(set(versions))
                or any(not str(version).strip() or len(str(version)) > 256 for version in versions)
            ):
                raise JobValidationError("executor.runtimes must advertise non-empty version lists.")
        if len(self.runtimes) > 128 or len(self.labels) > 64:
            raise JobValidationError("executor runtime or label advertisement exceeds protocol limits.")
        for name, value in self.labels.items():
            require_identifier(name, "executor.labels key")
            if not str(value).strip() or len(str(value)) > 256:
                raise JobValidationError("executor.labels values must be non-empty and bounded.")


def _bounded_integer(value: object, *, minimum: int, maximum: int = MAX_BYTE_VALUE) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
