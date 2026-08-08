"""Lease-fenced job execution state operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from typing import Any
from uuid import uuid4

from core.jobs.errors import JobQuotaExceededError, JobTransitionError, JobValidationError
from core.jobs.lifecycle import require_lease, transition_record, validate_execution_result
from core.jobs.models import JobState, LEASED_JOB_STATES, TERMINAL_JOB_STATES, require_identifier
from core.jobs.redaction import redact_job_payload
from core.jobs.records import (
    JobFailure,
    JobLease,
    JobLogRecord,
    JobProgress,
    JobRecord,
)


MAX_PROGRESS_VALUE = 9_223_372_036_854_775_807
MAX_LEASE_SECONDS = 86_400


class JobExecutionOperations:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def lease(self, job_id: str, *, workspace_id: str, executor_id: str, lease_seconds: int) -> JobRecord:
        if not _bounded_seconds(lease_seconds):
            raise JobValidationError("lease_seconds must be an integer between 1 and 86400.")
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=workspace_id)
        if current.state != "queued" or current.available_at > now:
            raise JobTransitionError(f"Job `{job_id}` is not ready to lease.")
        self.owner.submission.validate_grants(current.spec, now=now)
        self.owner.input_validators.validate(current.spec)
        self.owner.executors.require_compatible(executor_id, current.spec)
        quota = self.owner.quota_for(workspace_id)
        active = sum(1 for item in self.owner.list(workspace_id=workspace_id) if item.state in LEASED_JOB_STATES)
        if active >= quota.max_concurrent_jobs:
            raise JobQuotaExceededError(f"Workspace `{workspace_id}` has reached its concurrent job quota.")
        lease = JobLease(
            executor_id=require_identifier(executor_id, "executor_id"),
            lease_token=f"lease_{uuid4().hex}",
            leased_at=now,
            heartbeat_at=now,
            expires_at=self.owner.recovery.lease_expiration(
                current,
                now=now,
                requested_seconds=lease_seconds,
            ),
        )
        updated = transition_record(
            current,
            state="leased",
            now=now,
            lease=lease,
            attempt=current.attempt + 1,
            started_at=current.started_at or now,
            last_leased_at=now,
            progress=None,
            failure=None,
        )
        return self.owner.commit(current, updated, action="job.lease", executor_id=executor_id)

    def heartbeat(self, job_id: str, **kwargs) -> JobRecord:
        extend_seconds = kwargs["extend_seconds"]
        if not _bounded_seconds(extend_seconds):
            raise JobValidationError("extend_seconds must be an integer between 1 and 86400.")
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        lease = require_lease(
            current,
            executor_id=kwargs["executor_id"],
            lease_token=kwargs["lease_token"],
            now=now,
        )
        refreshed = replace(
            lease,
            heartbeat_at=now,
            expires_at=self.owner.recovery.lease_expiration(current, now=now, requested_seconds=extend_seconds),
        )
        updated = transition_record(current, state=current.state, now=now, lease=refreshed)
        return self.owner.commit(current, updated, action="job.heartbeat", executor_id=kwargs["executor_id"])

    def advance(self, job_id: str, **kwargs) -> JobRecord:
        state = kwargs["state"]
        if state not in {"preparing", "running", "validating", "publishing"}:
            raise JobTransitionError(f"Executor cannot advance a job to `{state}`.")
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        updated = transition_record(current, state=state, now=now)
        return self.owner.commit(current, updated, action=f"job.{state}", executor_id=kwargs["executor_id"])

    def report_progress(self, job_id: str, **kwargs) -> JobRecord:
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        phase = _redacted_safe_identifier(
            current,
            kwargs["phase"],
            field_name="progress.phase",
            fallback="job.progress.redacted",
        )
        completed = kwargs["completed"]
        total = kwargs.get("total")
        if not _bounded_progress_integer(completed) or (
            total is not None and (not _bounded_progress_integer(total) or completed > total)
        ):
            raise JobValidationError("Structured progress values are invalid.")
        progress = JobProgress(
            phase,
            completed,
            total,
            _bounded(redact_job_payload(current, kwargs.get("unit")), 64),
            _bounded(redact_job_payload(current, kwargs.get("message")), 512),
            now,
        )
        updated = transition_record(current, state=current.state, now=now, progress=progress)
        return self.owner.commit(current, updated, action="job.progress", executor_id=kwargs["executor_id"])

    def record_log(self, job_id: str, **kwargs) -> JobLogRecord:
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        level = str(kwargs["level"] or "").strip().lower()
        if level not in {"debug", "info", "warning", "error"}:
            raise JobValidationError("Job log level is invalid.")
        fields = kwargs.get("fields")
        if fields is not None and not isinstance(fields, dict):
            raise JobValidationError("Job log fields must be an object.")
        safe_fields = redact_job_payload(current, fields or {})
        try:
            encoded = json.dumps(safe_fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise JobValidationError("Job log fields must be finite JSON data.") from exc
        if len(encoded.encode("utf-8")) > 16_384:
            raise JobValidationError("Job log fields exceed the bounded record limit.")
        return self.owner.store.append_log(
            JobLogRecord(
                log_id=f"joblog_{uuid4().hex}",
                workspace_id=kwargs["workspace_id"],
                job_id=job_id,
                attempt=current.attempt,
                executor_id=kwargs["executor_id"],
                level=level,
                code=_redacted_safe_identifier(
                    current,
                    kwargs["code"],
                    field_name="log.code",
                    fallback="job.log.redacted",
                ),
                fields=safe_fields,
                occurred_at=now,
            )
        )

    def request_cancel(self, job_id: str, **kwargs) -> JobRecord:
        force = kwargs.get("force", False)
        if not isinstance(force, bool):
            raise JobValidationError("force must be a boolean.")
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        if current.state in TERMINAL_JOB_STATES or current.state == "cancel_requested":
            return current
        state: JobState = "cancelled" if force or current.state == "queued" else "cancel_requested"
        updated = transition_record(
            current,
            state=state,
            now=now,
            lease=None if state == "cancelled" else current.lease,
            cancellation_reason=_bounded(redact_job_payload(current, kwargs["reason"]), 512),
        )
        return self.owner.commit(
            current,
            updated,
            action="job.cancel.force" if force else "job.cancel",
            actor_id=kwargs.get("actor_id"),
        )

    def acknowledge_cancel(self, job_id: str, **kwargs) -> JobRecord:
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        if current.state != "cancel_requested":
            raise JobTransitionError("Only cancel-requested jobs can acknowledge cancellation.")
        updated = transition_record(current, state="cancelled", now=now, lease=None)
        return self.owner.commit(current, updated, action="job.cancelled", executor_id=kwargs["executor_id"])

    def complete(self, job_id: str, **kwargs) -> JobRecord:
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        if current.state != "publishing":
            raise JobTransitionError("A job succeeds only after publishing validation.")
        result = replace(
            kwargs["result"],
            metadata=redact_job_payload(current, kwargs["result"].metadata),
        )
        validate_execution_result(current, result)
        published_result = self.owner.output_publishers.publish(current, result)
        published_result = replace(
            published_result,
            metadata=redact_job_payload(current, published_result.metadata),
        )
        validate_execution_result(current, published_result)
        updated = transition_record(current, state="succeeded", now=now, lease=None, result=published_result)
        return self.owner.commit(current, updated, action="job.succeeded", executor_id=kwargs["executor_id"])

    def fail(self, job_id: str, **kwargs) -> JobRecord:
        if not isinstance(kwargs["retryable"], bool):
            raise JobValidationError("retryable must be a boolean.")
        now = self.owner.clock()
        current = self.owner.get(job_id, workspace_id=kwargs["workspace_id"])
        require_lease(current, executor_id=kwargs["executor_id"], lease_token=kwargs["lease_token"], now=now)
        if current.state == "cancel_requested":
            updated = transition_record(current, state="cancelled", now=now, lease=None)
        else:
            failure = JobFailure(
                error_code=_redacted_safe_identifier(
                    current,
                    kwargs["error_code"],
                    field_name="error_code",
                    fallback="job.execution.failed",
                ),
                message=_bounded(redact_job_payload(current, kwargs["message"]), 1024)
                or "Job execution failed.",
                retryable=kwargs["retryable"],
                failed_at=now,
            )
            if kwargs["retryable"] and current.attempt < current.spec.retry.max_attempts:
                updated = transition_record(
                    current,
                    state="queued",
                    now=now,
                    lease=None,
                    available_at=now + timedelta(seconds=current.spec.retry.backoff_seconds(current.attempt)),
                    failure=failure,
                    progress=None,
                )
            else:
                updated = transition_record(current, state="failed", now=now, lease=None, failure=failure)
        return self.owner.commit(current, updated, action="job.failed", executor_id=kwargs["executor_id"])


def _bounded(value: object, limit: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:limit] if normalized else None


def _bounded_progress_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_PROGRESS_VALUE


def _bounded_seconds(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_LEASE_SECONDS


def _redacted_safe_identifier(
    record: JobRecord,
    value: object,
    *,
    field_name: str,
    fallback: str,
) -> str:
    identifier = require_identifier(value, field_name)
    return fallback if redact_job_payload(record, identifier) != identifier else identifier
