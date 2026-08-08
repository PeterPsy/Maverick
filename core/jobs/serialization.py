"""Canonical fingerprints and document conversion for job records."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from typing import Any

from core.jobs.executor_models import ExecutorAdvertisement, HandlerCapability
from core.jobs.models import (
    JobBudget,
    JobInputGrant,
    JobNetworkPolicy,
    JobOutputGrant,
    JobResourceRequirements,
    JobRetryPolicy,
    JobSpec,
)
from core.jobs.records import (
    JobAuditRecord,
    JobEventRecord,
    JobExecutionResult,
    JobFailure,
    JobLease,
    JobLogRecord,
    JobOutputReference,
    JobProgress,
    JobRecord,
    WorkspaceJobQuota,
)


def job_spec_fingerprint(spec: JobSpec) -> str:
    payload = _json_value(asdict(spec))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def job_spec_to_payload(spec: JobSpec) -> dict[str, Any]:
    return _json_value(asdict(spec))


def job_record_to_payload(record: JobRecord) -> dict[str, Any]:
    return _json_value(asdict(record))


def public_job_record_to_payload(record: JobRecord) -> dict[str, Any]:
    """Serialize a workspace-visible record without executor lease authority."""
    payload = job_record_to_payload(record)
    lease = payload.get("lease")
    if isinstance(lease, dict):
        lease.pop("lease_token", None)
    return payload


def record_to_payload(record) -> dict[str, Any]:
    return _json_value(asdict(record))


def job_record_to_document(record: JobRecord) -> dict[str, Any]:
    return asdict(record)


def job_record_from_document(document: dict[str, Any]) -> JobRecord:
    payload = dict(document)
    spec = job_spec_from_document(payload.pop("spec"))
    lease_payload = payload.pop("lease", None)
    progress_payload = payload.pop("progress", None)
    result_payload = payload.pop("result", None)
    failure_payload = payload.pop("failure", None)
    return JobRecord(
        spec=spec,
        lease=JobLease(**lease_payload) if lease_payload else None,
        progress=JobProgress(**progress_payload) if progress_payload else None,
        result=_job_result(result_payload) if result_payload else None,
        failure=JobFailure(**failure_payload) if failure_payload else None,
        **payload,
    )


def executor_to_document(record: ExecutorAdvertisement) -> dict[str, Any]:
    return asdict(record)


def executor_from_document(document: dict[str, Any]) -> ExecutorAdvertisement:
    payload = dict(document)
    payload["handlers"] = tuple(HandlerCapability(**item) for item in payload.get("handlers", []))
    payload["accelerator_kinds"] = tuple(payload.get("accelerator_kinds", []))
    payload["network_modes"] = tuple(payload.get("network_modes", []))
    payload["runtimes"] = {name: tuple(versions) for name, versions in payload.get("runtimes", {}).items()}
    return ExecutorAdvertisement(**payload)


def event_from_document(document: dict[str, Any]) -> JobEventRecord:
    return JobEventRecord(**document)


def audit_from_document(document: dict[str, Any]) -> JobAuditRecord:
    return JobAuditRecord(**document)


def log_from_document(document: dict[str, Any]) -> JobLogRecord:
    return JobLogRecord(**document)


def quota_from_document(document: dict[str, Any]) -> WorkspaceJobQuota:
    return WorkspaceJobQuota(**document)


def job_spec_from_document(payload: dict[str, Any]) -> JobSpec:
    document = dict(payload)
    resources = document["resources"]
    document["resources"] = JobResourceRequirements(
        **{**resources, "accelerator_kinds": tuple(resources.get("accelerator_kinds", []))}
    )
    document["budget"] = JobBudget(**document["budget"])
    document["retry"] = JobRetryPolicy(**document.get("retry", {}))
    document["network_policy"] = JobNetworkPolicy(
        **{
            **document.get("network_policy", {}),
            "allowed_hosts": tuple(document.get("network_policy", {}).get("allowed_hosts", [])),
        }
    )
    document["input_grants"] = tuple(
        JobInputGrant(**{**item, "expires_at": _datetime_value(item["expires_at"], "input_grant.expires_at")})
        for item in document.get("input_grants", [])
    )
    output = document.get("output_grant")
    if output:
        document["output_grant"] = JobOutputGrant(
            **{
                **output,
                "expires_at": _datetime_value(output["expires_at"], "output_grant.expires_at"),
                "accepted_mime_types": tuple(output.get("accepted_mime_types", [])),
            }
        )
    if document.get("expires_at") is not None:
        document["expires_at"] = _datetime_value(document["expires_at"], "expires_at")
    document["allowed_tools"] = tuple(document.get("allowed_tools", []))
    document.setdefault("runtime_versions", {})
    document.setdefault("parameters", {})
    return JobSpec(**document)


def _job_result(payload: dict[str, Any]) -> JobExecutionResult:
    return JobExecutionResult(
        outputs=tuple(JobOutputReference(**item) for item in payload.get("outputs", [])),
        metadata=dict(payload.get("metadata", {})),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _datetime_value(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} is not a valid ISO-8601 datetime.") from exc
    raise ValueError(f"{field_name} must be an ISO-8601 datetime.")
