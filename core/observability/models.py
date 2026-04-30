"""Observability-domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


EventPlane = Literal["platform", "runtime", "workspace", "app"]
AuditStatus = Literal["attempted", "succeeded", "failed"]
MetricKind = Literal["counter", "gauge"]
LogPlane = Literal["platform", "runtime", "workspace", "app"]


@dataclass(frozen=True)
class StructuredEventRecord:
    """Structured platform or runtime event with cross-plane attribution."""

    event_id: str
    event_type: str
    event_plane: EventPlane
    source_domain: str
    workspace_id: str | None
    app_id: str | None
    run_id: str | None
    runtime_session_id: str | None
    turn_id: str | None
    provider_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class AuditRecord:
    """Structured audit record for operator-relevant control-plane actions."""

    audit_id: str
    action: str
    status: AuditStatus
    source_domain: str
    workspace_id: str | None
    app_id: str | None
    runtime_session_id: str | None
    provider_id: str | None
    detail: str
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class MetricRecord:
    """Structured metric sample with attribution tags."""

    metric_id: str
    metric_name: str
    kind: MetricKind
    value: float
    workspace_id: str | None
    app_id: str | None
    runtime_session_id: str | None
    provider_id: str | None
    tags: dict[str, str]
    recorded_at: datetime


@dataclass(frozen=True)
class RuntimeLogRecord:
    """Metadata for one appended log line written to a filesystem log root."""

    log_id: str
    log_plane: LogPlane
    workspace_id: str | None
    app_id: str | None
    runtime_session_id: str | None
    provider_id: str | None
    log_path: str
    message: str
    occurred_at: datetime
