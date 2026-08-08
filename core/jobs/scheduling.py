"""Deterministic workspace-fair ordering for durable queued jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from core.jobs.models import LEASED_JOB_STATES
from core.jobs.records import JobRecord, WorkspaceJobQuota


def fair_ready_jobs(
    records: list[JobRecord],
    *,
    now: datetime,
    quota_for: Callable[[str], WorkspaceJobQuota],
) -> list[JobRecord]:
    """Order ready jobs round-robin by durable workspace scheduling history."""
    ready = [record for record in records if record.state == "queued" and record.available_at <= now]
    active_by_workspace: dict[str, int] = {}
    last_started_by_workspace: dict[str, datetime] = {}
    for record in records:
        workspace_id = record.spec.workspace_id
        if record.state in LEASED_JOB_STATES:
            active_by_workspace[workspace_id] = active_by_workspace.get(workspace_id, 0) + 1
        if record.last_leased_at is not None:
            previous = last_started_by_workspace.get(workspace_id)
            if previous is None or record.last_leased_at > previous:
                last_started_by_workspace[workspace_id] = record.last_leased_at

    jobs_by_workspace: dict[str, list[JobRecord]] = {}
    for record in ready:
        workspace_id = record.spec.workspace_id
        quota = quota_for(workspace_id)
        if active_by_workspace.get(workspace_id, 0) >= quota.max_concurrent_jobs:
            continue
        jobs_by_workspace.setdefault(workspace_id, []).append(record)

    never_scheduled = datetime.min.replace(tzinfo=UTC)
    workspace_order = sorted(
        jobs_by_workspace,
        key=lambda workspace_id: (
            last_started_by_workspace.get(workspace_id, never_scheduled),
            active_by_workspace.get(workspace_id, 0) / quota_for(workspace_id).max_concurrent_jobs,
            min(item.created_at for item in jobs_by_workspace[workspace_id]),
            workspace_id,
        ),
    )
    ordered: list[JobRecord] = []
    for workspace_id in workspace_order:
        ordered.extend(
            sorted(
                jobs_by_workspace[workspace_id],
                key=lambda item: (-item.spec.priority, item.available_at, item.created_at, item.job_id),
            )
        )
    return ordered
