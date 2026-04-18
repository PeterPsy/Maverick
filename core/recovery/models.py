"""Recovery-domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


FailureCategory = Literal[
    "missing_secret",
    "invalid_provider_setup",
    "contract_failure",
    "process_crash",
    "health_check_failed",
    "unknown",
]
FailureRecoverability = Literal["restartable", "repair_first", "manual"]
RecoveryAction = Literal["restart_runtime", "repair_then_restart", "manual_intervention"]
RecoveryIntentStatus = Literal["planned", "in_progress", "completed", "abandoned"]
HealthTargetKind = Literal["runtime", "provider", "app"]
HealthStatus = Literal["healthy", "degraded", "unhealthy"]


@dataclass(frozen=True)
class RuntimeFailureRecord:
    """Describe one runtime or startup failure relevant to recovery."""

    failure_id: str
    workspace_id: str | None
    session_id: str | None
    category: FailureCategory
    recoverability: FailureRecoverability
    detail: str
    created_at: datetime


@dataclass(frozen=True)
class RecoveryIntentRecord:
    """Describe one planned recovery action for one failure or runtime session."""

    intent_id: str
    workspace_id: str | None
    session_id: str | None
    failure_id: str | None
    action: RecoveryAction
    reason: str
    status: RecoveryIntentStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HealthCheckResult:
    """Structured health result for runtime, provider, or app checks."""

    check_id: str
    workspace_id: str | None
    session_id: str | None
    target_kind: HealthTargetKind
    target_id: str
    status: HealthStatus
    detail: str
    checked_at: datetime
