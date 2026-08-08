"""Record-aware redaction for executor-controlled job text and structures."""

from __future__ import annotations

from typing import Any

from core.jobs.records import JobRecord
from core.observability.redaction import redact_payload


def redact_job_payload(record: JobRecord, value: Any) -> Any:
    """Redact generic secret patterns plus authority values from one job."""
    redacted = redact_payload(value)
    literals = _authority_literals(record)
    return _redact_literals(redacted, literals)


def _authority_literals(record: JobRecord) -> tuple[str, ...]:
    values: list[str] = []
    if record.lease is not None:
        values.append(record.lease.lease_token)
    for grant in record.spec.input_grants:
        values.extend((grant.grant_id, grant.resource_ref))
    if record.spec.output_grant is not None:
        values.append(record.spec.output_grant.grant_id)
    return tuple(value for value in values if value)


def _redact_literals(value: Any, literals: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {key: _redact_literals(item, literals) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_literals(item, literals) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_literals(item, literals) for item in value)
    if isinstance(value, str):
        for literal in literals:
            value = value.replace(literal, "<redacted>")
    return value
