"""Recovery-domain service facade."""

from __future__ import annotations

from core.providers.provider_registry import ProviderRegistry
from core.recovery.failed_start_recovery import classify_failed_start, plan_failed_start_recovery
from core.recovery.health_checks import run_app_health_check, run_provider_health_check, run_runtime_health_check
from core.recovery.models import HealthCheckResult, RecoveryIntentRecord, RuntimeFailureRecord
from core.recovery.runtime_recovery import plan_runtime_restart
from core.recovery.store import RecoveryStore
from core.runtime.runtime_session import RuntimeSessionRecord


def record_failed_start(
    store: RecoveryStore,
    *,
    category: str,
    detail: str,
    workspace_id: str | None = None,
    session_id: str | None = None,
    now=None,
) -> tuple[RuntimeFailureRecord, RecoveryIntentRecord]:
    """Persist one failed-start record and the first recovery intent derived from it."""
    failure = classify_failed_start(
        category=category,
        detail=detail,
        workspace_id=workspace_id,
        session_id=session_id,
        now=now,
    )
    intent = plan_failed_start_recovery(failure, now=now)
    return store.save_failure(failure), store.save_intent(intent)


def plan_session_restart(
    store: RecoveryStore,
    *,
    session: RuntimeSessionRecord,
    reason: str,
    now=None,
) -> RecoveryIntentRecord:
    """Persist one explicit runtime restart intent."""
    intent = plan_runtime_restart(session, reason=reason, now=now)
    return store.save_intent(intent)


def record_runtime_health(
    store: RecoveryStore,
    *,
    session: RuntimeSessionRecord,
    now=None,
) -> HealthCheckResult:
    """Persist one runtime health result."""
    result = run_runtime_health_check(session, now=now)
    return store.save_health_result(result)


def record_provider_health(
    store: RecoveryStore,
    *,
    provider_registry: ProviderRegistry,
    provider_id: str,
    workspace_id: str | None = None,
    now=None,
) -> HealthCheckResult:
    """Persist one provider health result."""
    result = run_provider_health_check(provider_registry, provider_id=provider_id, workspace_id=workspace_id, now=now)
    return store.save_health_result(result)


def record_app_health(
    store: RecoveryStore,
    *,
    workspace_id: str,
    app_id: str,
    is_healthy: bool,
    detail: str | None = None,
    now=None,
) -> HealthCheckResult:
    """Persist one app health result."""
    result = run_app_health_check(workspace_id=workspace_id, app_id=app_id, is_healthy=is_healthy, detail=detail, now=now)
    return store.save_health_result(result)


def recovery_status(
    store: RecoveryStore,
    *,
    workspace_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Return a structured recovery snapshot for operator inspection."""
    failures = store.list_failures(workspace_id=workspace_id, session_id=session_id)
    intents = store.list_intents(workspace_id=workspace_id, session_id=session_id)
    health_results = store.list_health_results(workspace_id=workspace_id, session_id=session_id)
    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "failure_count": len(failures),
        "intent_count": len(intents),
        "health_check_count": len(health_results),
        "latest_failure_category": None if not failures else failures[-1].category,
        "latest_intent_action": None if not intents else intents[-1].action,
        "latest_health_status": None if not health_results else health_results[-1].status,
    }
