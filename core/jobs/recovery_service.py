"""Restart and lease-expiry reconciliation for durable jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.jobs.errors import JobConcurrencyError, JobValidationError
from core.jobs.lifecycle import transition_record
from core.jobs.models import JobState, LEASED_JOB_STATES, TERMINAL_JOB_STATES
from core.jobs.records import JobRecord


class JobRecoveryOperations:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def recover_expired_jobs(self) -> list[JobRecord]:
        now = self.owner.clock()
        recovered: list[JobRecord] = []
        for current in self.owner.list():
            if current.state in TERMINAL_JOB_STATES:
                continue
            hard_expired = self.hard_expiration(current) <= now
            lease_expired = (
                current.state in LEASED_JOB_STATES
                and current.lease is not None
                and current.lease.expires_at <= now
            )
            lease_missing = current.state in LEASED_JOB_STATES and current.lease is None
            if not hard_expired and not lease_expired and not lease_missing:
                continue
            if current.state == "queued" or hard_expired:
                state: JobState = "expired"
            elif current.state == "cancel_requested":
                state = "cancelled"
            elif current.attempt < current.spec.retry.max_attempts:
                state = "queued"
            else:
                state = "expired"
            changes = {"lease": None, "progress": None}
            if state == "queued":
                changes["available_at"] = now + timedelta(
                    seconds=current.spec.retry.backoff_seconds(current.attempt)
                )
            updated = transition_record(current, state=state, now=now, **changes)
            try:
                recovered.append(self.owner.commit(current, updated, action="job.lease.expired"))
            except JobConcurrencyError:
                continue
        return recovered

    def lease_expiration(self, record: JobRecord, *, now: datetime, requested_seconds: int) -> datetime:
        deadlines = [
            now + timedelta(seconds=requested_seconds),
            self.hard_expiration(record, started_at=record.started_at or now),
        ]
        expiration = min(deadlines)
        if expiration <= now:
            raise JobValidationError("Job deadline does not permit a new lease interval.")
        return expiration

    @staticmethod
    def hard_expiration(record: JobRecord, *, started_at: datetime | None = None) -> datetime:
        deadlines: list[datetime] = [grant.expires_at for grant in record.spec.input_grants]
        if record.spec.output_grant is not None:
            deadlines.append(record.spec.output_grant.expires_at)
        if record.spec.expires_at is not None:
            deadlines.append(record.spec.expires_at)
        effective_started_at = started_at or record.started_at
        if effective_started_at is not None:
            runtime_seconds = record.spec.timeout_seconds or record.spec.budget.max_runtime_seconds
            deadlines.append(effective_started_at + timedelta(seconds=runtime_seconds))
        return min(deadlines) if deadlines else datetime.max.replace(tzinfo=UTC)
