"""Versioned protocol models for durable app-agnostic compute jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import re
from typing import Any, Literal

from core.jobs.errors import JobValidationError


JOB_PROTOCOL_VERSION = "app-job.v1"
JOB_INTERFACE_ID = "compute.job.execution"
JOB_INTERFACE_VERSION = "1"
MAX_PARAMETERS_BYTES = 262_144
MAX_BYTE_VALUE = 9_223_372_036_854_775_807

JobState = Literal[
    "queued",
    "leased",
    "preparing",
    "running",
    "validating",
    "publishing",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "expired",
]
NetworkMode = Literal["deny_all", "allowlist"]

TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "expired"})
LEASED_JOB_STATES = frozenset(
    {"leased", "preparing", "running", "validating", "publishing", "cancel_requested"}
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_HOST = re.compile(r"^(?:\*\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def require_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise JobValidationError(f"{field_name} must be a safe non-empty identifier.")
    return normalized


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise JobValidationError(f"{field_name} must be timezone-aware.")
    return value


@dataclass(frozen=True)
class JobResourceRequirements:
    """Minimum capacity that a compatible executor must advertise."""

    cpu_cores: float = 1.0
    ram_bytes: int = 536_870_912
    gpu_count: int = 0
    accelerator_kinds: tuple[str, ...] = ()
    disk_bytes: int = 0
    runtime: str = "native"
    runtime_version: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.cpu_cores, bool) or not math.isfinite(self.cpu_cores) or not 0 < self.cpu_cores <= 4096:
            raise JobValidationError("resources.cpu_cores must be greater than zero.")
        if not _bounded_integer(self.ram_bytes, minimum=1):
            raise JobValidationError("resources.ram_bytes is outside the supported range.")
        if not _bounded_integer(self.disk_bytes, minimum=0):
            raise JobValidationError("resources.disk_bytes is outside the supported range.")
        if not _bounded_integer(self.gpu_count, minimum=0, maximum=4096):
            raise JobValidationError("Resource byte and GPU requirements cannot be negative.")
        require_identifier(self.runtime, "resources.runtime")
        for item in self.accelerator_kinds:
            require_identifier(item, "resources.accelerator_kinds")
        if len(self.accelerator_kinds) > 32 or len(self.accelerator_kinds) != len(set(self.accelerator_kinds)):
            raise JobValidationError("resources.accelerator_kinds must be unique and bounded.")
        if self.runtime_version is not None:
            if not str(self.runtime_version).strip() or len(str(self.runtime_version)) > 256:
                raise JobValidationError("resources.runtime_version must be non-empty and bounded.")


@dataclass(frozen=True)
class JobBudget:
    """Hard execution and output budgets enforced by the control plane."""

    max_runtime_seconds: int
    max_output_bytes: int
    max_cost_microunits: int | None = None

    def __post_init__(self) -> None:
        if not _bounded_integer(self.max_runtime_seconds, minimum=1, maximum=31_536_000):
            raise JobValidationError("budget.max_runtime_seconds is outside the supported range.")
        if not _bounded_integer(self.max_output_bytes, minimum=0):
            raise JobValidationError("budget.max_output_bytes cannot be negative.")
        if self.max_cost_microunits is not None and not _bounded_integer(self.max_cost_microunits, minimum=0):
            raise JobValidationError("budget.max_cost_microunits cannot be negative.")


@dataclass(frozen=True)
class JobInputGrant:
    """Immutable, metadata-bound input authority delivered to an executor."""

    grant_id: str
    provider_interface: str
    resource_ref: str
    sha256: str
    size_bytes: int
    mime_type: str
    expires_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.grant_id, "input_grant.grant_id")
        require_identifier(self.provider_interface, "input_grant.provider_interface")
        require_identifier(self.resource_ref, "input_grant.resource_ref")
        if not _SHA256.fullmatch(self.sha256):
            raise JobValidationError("input_grant.sha256 must be a lowercase SHA-256 digest.")
        if not _bounded_integer(self.size_bytes, minimum=0):
            raise JobValidationError("input_grant.size_bytes cannot be negative.")
        if "/" not in self.mime_type or len(self.mime_type) > 255:
            raise JobValidationError("input_grant.mime_type must be a bounded MIME type.")
        require_aware_datetime(self.expires_at, "input_grant.expires_at")


@dataclass(frozen=True)
class JobOutputGrant:
    """Bounded authority for staging and publishing one or more outputs."""

    grant_id: str
    provider_interface: str
    expires_at: datetime
    max_bytes: int
    accepted_mime_types: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.grant_id, "output_grant.grant_id")
        require_identifier(self.provider_interface, "output_grant.provider_interface")
        require_aware_datetime(self.expires_at, "output_grant.expires_at")
        if not _bounded_integer(self.max_bytes, minimum=0):
            raise JobValidationError("output_grant.max_bytes cannot be negative.")
        if not self.accepted_mime_types:
            raise JobValidationError("output_grant.accepted_mime_types cannot be empty.")
        if len(self.accepted_mime_types) > 64 or len(self.accepted_mime_types) != len(set(self.accepted_mime_types)):
            raise JobValidationError("output_grant.accepted_mime_types must be unique and bounded.")
        if any("/" not in item or len(item) > 255 for item in self.accepted_mime_types):
            raise JobValidationError("output_grant.accepted_mime_types contains an invalid MIME type.")


@dataclass(frozen=True)
class JobRetryPolicy:
    """Retry count and deterministic exponential-backoff policy."""

    max_attempts: int = 1
    initial_backoff_seconds: int = 1
    multiplier: float = 2.0
    max_backoff_seconds: int = 300

    def __post_init__(self) -> None:
        if not _bounded_integer(self.max_attempts, minimum=1, maximum=100):
            raise JobValidationError("retry.max_attempts must be between 1 and 100.")
        if not _bounded_integer(self.initial_backoff_seconds, minimum=0, maximum=31_536_000) or not _bounded_integer(
            self.max_backoff_seconds,
            minimum=0,
            maximum=31_536_000,
        ):
            raise JobValidationError("Retry backoff cannot be negative.")
        if isinstance(self.multiplier, bool) or not math.isfinite(self.multiplier) or self.multiplier < 1:
            raise JobValidationError("retry.multiplier must be at least 1.")

    def backoff_seconds(self, completed_attempt: int) -> int:
        exponent = max(0, completed_attempt - 1)
        try:
            delay = self.initial_backoff_seconds * (self.multiplier**exponent)
        except OverflowError:
            return self.max_backoff_seconds
        if not math.isfinite(delay):
            return self.max_backoff_seconds
        return min(self.max_backoff_seconds, int(delay))


@dataclass(frozen=True)
class JobNetworkPolicy:
    """Deny-by-default executor egress policy."""

    mode: NetworkMode = "deny_all"
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"deny_all", "allowlist"}:
            raise JobValidationError("network_policy.mode is invalid.")
        if self.mode == "deny_all" and self.allowed_hosts:
            raise JobValidationError("deny_all network policy cannot include allowed hosts.")
        if self.mode == "allowlist" and not self.allowed_hosts:
            raise JobValidationError("allowlist network policy requires at least one host.")
        if len(self.allowed_hosts) > 128 or len(self.allowed_hosts) != len(set(self.allowed_hosts)):
            raise JobValidationError("network_policy.allowed_hosts must be unique and bounded.")
        if any(not _HOST.fullmatch(host) for host in self.allowed_hosts):
            raise JobValidationError("network_policy.allowed_hosts contains an invalid host pattern.")


@dataclass(frozen=True)
class JobSpec:
    """Canonical immutable submission envelope for ``app-job.v1``."""

    job_type: str
    handler_name: str
    handler_version: str
    workspace_id: str
    submitted_by_app_id: str
    submitted_by_actor_id: str
    priority: int
    resources: JobResourceRequirements
    budget: JobBudget
    idempotency_key: str
    input_grants: tuple[JobInputGrant, ...] = ()
    output_grant: JobOutputGrant | None = None
    retry: JobRetryPolicy = field(default_factory=JobRetryPolicy)
    timeout_seconds: int | None = None
    expires_at: datetime | None = None
    network_policy: JobNetworkPolicy = field(default_factory=JobNetworkPolicy)
    allowed_tools: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    runtime_versions: dict[str, str] = field(default_factory=dict)
    protocol_version: str = JOB_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != JOB_PROTOCOL_VERSION:
            raise JobValidationError(f"Unsupported job protocol `{self.protocol_version}`.")
        require_identifier(self.job_type, "job_type")
        require_identifier(self.handler_name, "handler_name")
        require_identifier(self.handler_version, "handler_version")
        require_identifier(self.workspace_id, "workspace_id")
        require_identifier(self.submitted_by_app_id, "submitted_by_app_id")
        require_identifier(self.submitted_by_actor_id, "submitted_by_actor_id")
        require_identifier(self.idempotency_key, "idempotency_key")
        if not _bounded_integer(self.priority, minimum=0, maximum=100):
            raise JobValidationError("priority must be between 0 and 100.")
        if self.timeout_seconds is not None:
            if not _bounded_integer(
                self.timeout_seconds,
                minimum=1,
                maximum=self.budget.max_runtime_seconds,
            ):
                raise JobValidationError("timeout_seconds must fit inside the runtime budget.")
        if self.expires_at is not None:
            require_aware_datetime(self.expires_at, "expires_at")
        grant_ids = [grant.grant_id for grant in self.input_grants]
        if len(grant_ids) > 128:
            raise JobValidationError("input_grants exceeds the protocol item limit.")
        if len(grant_ids) != len(set(grant_ids)):
            raise JobValidationError("input_grants must use unique grant ids.")
        for tool in self.allowed_tools:
            require_identifier(tool, "allowed_tools")
        if len(self.allowed_tools) > 128 or len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise JobValidationError("allowed_tools must be unique and bounded.")
        if not isinstance(self.runtime_versions, dict) or len(self.runtime_versions) > 128:
            raise JobValidationError("runtime_versions must be a bounded object.")
        for name, version in self.runtime_versions.items():
            require_identifier(name, "runtime_versions key")
            if not str(version).strip() or len(str(version)) > 256:
                raise JobValidationError("runtime_versions values must be non-empty and bounded.")
        if not isinstance(self.parameters, dict):
            raise JobValidationError("parameters must be an object.")
        try:
            encoded = json.dumps(self.parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise JobValidationError("parameters must be finite JSON data.") from exc
        if len(encoded.encode("utf-8")) > MAX_PARAMETERS_BYTES:
            raise JobValidationError("parameters exceed the protocol size limit.")


def _bounded_integer(value: object, *, minimum: int, maximum: int = MAX_BYTE_VALUE) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
