"""Fail-closed parsing for untrusted ``app-job.v1`` envelopes."""

from __future__ import annotations

from typing import Any

from core.jobs.errors import JobValidationError
from core.jobs.models import JobSpec
from core.jobs.serialization import job_spec_from_document


def parse_job_spec(payload: object) -> JobSpec:
    """Parse a JSON-shaped job spec without accepting undeclared fields."""
    if not isinstance(payload, dict):
        raise JobValidationError("Job spec must be an object.")
    try:
        return job_spec_from_document(payload)
    except JobValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise JobValidationError("Job spec does not match the app-job.v1 schema.") from exc


def require_string(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise JobValidationError(f"{field_name} is required.")
    return normalized
