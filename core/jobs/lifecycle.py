"""Pure durable-job state transition and result validation rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import re
from uuid import uuid4

from core.jobs.errors import JobLeaseError, JobTransitionError, JobValidationError
from core.jobs.models import MAX_BYTE_VALUE, JobState, LEASED_JOB_STATES, TERMINAL_JOB_STATES, require_identifier
from core.jobs.records import JobExecutionResult, JobLease, JobRecord


_SHA256 = re.compile(r"^[a-f0-9]{64}$")
STATE_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    "queued": frozenset({"leased", "cancelled", "expired"}),
    "leased": frozenset({"preparing", "cancel_requested", "cancelled", "failed", "queued", "expired"}),
    "preparing": frozenset({"running", "cancel_requested", "cancelled", "failed", "queued", "expired"}),
    "running": frozenset({"validating", "cancel_requested", "cancelled", "failed", "queued", "expired"}),
    "validating": frozenset({"publishing", "cancel_requested", "cancelled", "failed", "queued", "expired"}),
    "publishing": frozenset({"succeeded", "cancel_requested", "cancelled", "failed", "queued", "expired"}),
    "cancel_requested": frozenset({"cancelled", "failed", "queued", "expired"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}


def transition_record(
    record: JobRecord,
    *,
    state: JobState,
    now: datetime,
    lease: JobLease | None | object = ...,
    **changes,
) -> JobRecord:
    if state != record.state and state not in STATE_TRANSITIONS[record.state]:
        raise JobTransitionError(f"Job cannot transition from `{record.state}` to `{state}`.")
    finished_at = record.finished_at
    if state in TERMINAL_JOB_STATES:
        finished_at = now
    mutation = {
        "state": state,
        "updated_at": now,
        "finished_at": finished_at,
        "revision": record.revision + 1,
        "last_mutation_id": str(uuid4()),
        **changes,
    }
    if lease is not ...:
        mutation["lease"] = lease
    return replace(record, **mutation)


def require_lease(record: JobRecord, *, executor_id: str, lease_token: str, now: datetime) -> JobLease:
    lease = record.lease
    if record.state not in LEASED_JOB_STATES or lease is None:
        raise JobLeaseError(f"Job `{record.job_id}` does not have an active lease.")
    if lease.executor_id != executor_id or lease.lease_token != lease_token:
        raise JobLeaseError(f"Executor `{executor_id}` does not own job `{record.job_id}`.")
    if lease.expires_at <= now:
        raise JobLeaseError(f"Lease for job `{record.job_id}` has expired.")
    return lease


def validate_execution_result(record: JobRecord, result: JobExecutionResult) -> None:
    if len(result.outputs) > 64:
        raise JobValidationError("Execution result exceeds the output reference limit.")
    if not isinstance(result.metadata, dict):
        raise JobValidationError("Execution result metadata must be an object.")
    try:
        metadata_json = json.dumps(result.metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise JobValidationError("Execution result metadata must be finite JSON data.") from exc
    if len(metadata_json.encode("utf-8")) > 65_536:
        raise JobValidationError("Execution result metadata exceeds the bounded record limit.")
    grant = record.spec.output_grant
    if grant is None:
        if result.outputs:
            raise JobValidationError("A metadata-only job cannot publish output references.")
        return
    if not result.outputs:
        raise JobValidationError("A job with an output grant must publish at least one output.")
    total_bytes = 0
    for output in result.outputs:
        if output.grant_id != grant.grant_id:
            raise JobValidationError("Published output does not match the job output grant.")
        require_identifier(output.resource_id, "output.resource_id")
        if not _SHA256.fullmatch(output.sha256):
            raise JobValidationError("Published output requires a lowercase SHA-256 digest.")
        if (
            not isinstance(output.size_bytes, int)
            or isinstance(output.size_bytes, bool)
            or not 0 <= output.size_bytes <= MAX_BYTE_VALUE
        ):
            raise JobValidationError("Published output size cannot be negative.")
        if output.mime_type not in grant.accepted_mime_types:
            raise JobValidationError("Published output MIME type is not allowed by the grant.")
        total_bytes += output.size_bytes
    if total_bytes > grant.max_bytes or total_bytes > record.spec.budget.max_output_bytes:
        raise JobValidationError("Published outputs exceed the granted output budget.")
