"""Observability-domain service facade and redaction helpers."""

from __future__ import annotations

from pathlib import Path

from core.observability.audit_log import record_audit_event
from core.observability.event_log import emit_structured_event
from core.observability.metrics import record_metric
from core.observability.models import AuditRecord, MetricRecord, RuntimeLogRecord, StructuredEventRecord
from core.observability.redaction import redact_payload
from core.observability.runtime_log import append_runtime_log, ensure_log_roots
from core.observability.store import ObservabilityStore


def ensure_observability_roots(*, workspace_id: str | None = None, app_id: str | None = None, start_path: Path | None = None) -> dict[str, Path]:
    """Create canonical platform and workspace log roots."""
    return ensure_log_roots(workspace_id=workspace_id, app_id=app_id, start_path=start_path)


def record_platform_event(store: ObservabilityStore, **kwargs) -> StructuredEventRecord:
    """Persist one structured event."""
    return emit_structured_event(store, **kwargs)


def record_platform_audit(store: ObservabilityStore, **kwargs) -> AuditRecord:
    """Persist one structured audit record."""
    return record_audit_event(store, **kwargs)


def record_platform_metric(store: ObservabilityStore, **kwargs) -> MetricRecord:
    """Persist one metric sample."""
    return record_metric(store, **kwargs)


def append_platform_log(**kwargs) -> RuntimeLogRecord:
    """Append one runtime or platform log line."""
    return append_runtime_log(**kwargs)
