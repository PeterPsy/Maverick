"""Persist redaction-safe job events, audit records, and live notifications."""

from __future__ import annotations

from uuid import uuid4

from core.jobs.records import JobAuditRecord, JobEventRecord, JobRecord
from core.observability.redaction import redact_payload


class JobChangeRecorder:
    def __init__(self, store, *, event_bus=None, observability_store=None) -> None:
        self.store = store
        self.event_bus = event_bus
        self.observability_store = observability_store

    def record(
        self,
        previous: JobRecord | None,
        current: JobRecord,
        *,
        action: str,
        actor_id: str | None = None,
        executor_id: str | None = None,
    ) -> None:
        progress = current.progress
        payload = redact_payload(
            {
                "revision": current.revision,
                "progress": (
                    {
                        "phase": progress.phase,
                        "completed": progress.completed,
                        "total": progress.total,
                        "unit": progress.unit,
                        "updated_at": progress.updated_at,
                    }
                    if progress
                    else None
                ),
                "failure_code": current.failure.error_code if current.failure else None,
            }
        )
        event = self.store.append_event(
            JobEventRecord(
                event_id=f"jobevt_{uuid4().hex}",
                event_type="compute.job.state.changed",
                workspace_id=current.spec.workspace_id,
                job_id=current.job_id,
                previous_state=previous.state if previous else None,
                state=current.state,
                attempt=current.attempt,
                executor_id=executor_id or (current.lease.executor_id if current.lease else None),
                payload=payload,
                occurred_at=current.updated_at,
            )
        )
        self.store.append_audit(
            JobAuditRecord(
                audit_id=f"jobaudit_{uuid4().hex}",
                action=action,
                status="succeeded",
                workspace_id=current.spec.workspace_id,
                job_id=current.job_id,
                attempt=current.attempt,
                actor_id=actor_id,
                executor_id=executor_id,
                payload=payload,
                occurred_at=current.updated_at,
            )
        )
        if self.event_bus is not None:
            self.event_bus.publish(event)
        self._record_observability(event, action=action)

    def _record_observability(self, event: JobEventRecord, *, action: str) -> None:
        if self.observability_store is None:
            return
        from core.observability.service import record_platform_audit, record_platform_event

        record_platform_event(
            self.observability_store,
            event_type=event.event_type,
            event_plane="workspace",
            source_domain="jobs",
            workspace_id=event.workspace_id,
            payload={"job_id": event.job_id, "state": event.state, "attempt": event.attempt},
            now=event.occurred_at,
        )
        record_platform_audit(
            self.observability_store,
            action=action,
            status="succeeded",
            source_domain="jobs",
            detail="Durable job control-plane transition.",
            workspace_id=event.workspace_id,
            payload={"job_id": event.job_id, "state": event.state, "attempt": event.attempt},
            now=event.occurred_at,
        )
