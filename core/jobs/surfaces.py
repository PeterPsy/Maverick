"""Workspace-scoped operations shared by generic job CLI and MCP surfaces."""

from __future__ import annotations

from core.jobs.errors import JobValidationError
from core.jobs.models import TERMINAL_JOB_STATES, require_identifier
from core.jobs.protocol import parse_job_spec, require_string
from core.jobs.serialization import public_job_record_to_payload, record_to_payload
from core.jobs.service import JobService


ALL_JOB_STATES = TERMINAL_JOB_STATES | {
    "queued",
    "leased",
    "preparing",
    "running",
    "validating",
    "publishing",
    "cancel_requested",
}


def submit_job(service: JobService, arguments: dict, *, workspace_id: str, actor_id: str | None) -> dict:
    if actor_id is None:
        raise JobValidationError("A trusted actor context is required.")
    raw_spec = arguments.get("spec")
    if not isinstance(raw_spec, dict):
        raise JobValidationError("Job spec must be an object.")
    claimed_actor_id = str(raw_spec.get("submitted_by_actor_id") or "").strip()
    if claimed_actor_id and claimed_actor_id != actor_id:
        raise JobValidationError("Job spec actor must match the trusted actor context.")
    spec = parse_job_spec({**raw_spec, "submitted_by_actor_id": actor_id})
    if spec.workspace_id != workspace_id:
        raise JobValidationError("Job spec workspace_id must match the trusted workspace context.")
    job_id = str(arguments.get("job_id") or "").strip() or None
    if job_id is not None:
        require_identifier(job_id, "job_id")
    record = service.submit(spec, job_id=job_id, actor_id=actor_id)
    return {"job": public_job_record_to_payload(record)}


def list_jobs(service: JobService, arguments: dict, *, workspace_id: str) -> dict:
    state_value = str(arguments.get("state") or "").strip()
    if state_value and state_value not in ALL_JOB_STATES:
        raise JobValidationError("Job state filter is invalid.")
    limit = _limit(arguments.get("limit"), default=50)
    records = service.list(
        workspace_id=workspace_id,
        state=state_value if state_value else None,  # type: ignore[arg-type]
    )
    selected = list(reversed(records[-limit:]))
    return {"jobs": [public_job_record_to_payload(record) for record in selected], "count": len(selected)}


def get_job(service: JobService, arguments: dict, *, workspace_id: str) -> dict:
    job_id = require_identifier(require_string(arguments.get("job_id"), "job_id"), "job_id")
    record = service.get(job_id, workspace_id=workspace_id)
    payload = {"job": public_job_record_to_payload(record)}
    if _boolean(arguments.get("include_history"), default=False):
        limit = _limit(arguments.get("limit"), default=100)
        payload.update(
            {
                "events": [
                    record_to_payload(item)
                    for item in service.list_events(job_id, workspace_id=workspace_id)[-limit:]
                ],
                "logs": [
                    record_to_payload(item)
                    for item in service.list_logs(job_id, workspace_id=workspace_id)[-limit:]
                ],
            }
        )
    return payload


def cancel_job(service: JobService, arguments: dict, *, workspace_id: str, actor_id: str | None) -> dict:
    job_id = require_identifier(require_string(arguments.get("job_id"), "job_id"), "job_id")
    reason = require_string(arguments.get("reason"), "reason")
    record = service.request_cancel(
        job_id,
        workspace_id=workspace_id,
        reason=reason,
        actor_id=actor_id,
        force=_boolean(arguments.get("force"), default=False),
    )
    return {"job": public_job_record_to_payload(record)}


def _limit(value, *, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise JobValidationError("limit must be an integer between 1 and 200.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise JobValidationError("limit must be an integer between 1 and 200.") from exc
    if parsed < 1 or parsed > 200:
        raise JobValidationError("limit must be an integer between 1 and 200.")
    return parsed


def _boolean(value, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise JobValidationError("Boolean argument is invalid.")
