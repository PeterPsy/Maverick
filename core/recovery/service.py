"""Recovery-domain service facade."""

from __future__ import annotations

from pathlib import Path

from core.apps.store import AppStore
from core.observability.service import record_platform_audit, record_platform_event
from core.providers.provider_registry import ProviderRegistry
from core.recovery.failed_start_recovery import classify_failed_start, plan_failed_start_recovery
from core.recovery.health_checks import run_app_health_check, run_provider_health_check, run_runtime_health_check
from core.recovery.models import HealthCheckResult, RecoveryIntentRecord, RuntimeFailureRecord
from core.recovery.runtime_recovery import plan_runtime_restart
from core.recovery.store import RecoveryStore
from core.runtime.lifecycle import transition_runtime_session
from core.runtime.store import RuntimeStore
from core.runtime.runtime_session import RuntimeSessionRecord


def record_failed_start(
    store: RecoveryStore,
    *,
    category: str,
    detail: str,
    workspace_id: str | None = None,
    session_id: str | None = None,
    observability_store=None,
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
    saved_failure = store.save_failure(failure)
    saved_intent = store.save_intent(intent)
    if observability_store is not None:
        payload = {
            "failure_id": saved_failure.failure_id,
            "intent_id": saved_intent.intent_id,
            "category": saved_failure.category,
            "recoverability": saved_failure.recoverability,
        }
        record_platform_audit(
            observability_store,
            action="recovery.failed_start.record",
            status="succeeded",
            source_domain="recovery",
            detail=f"Recorded failed-start recovery plan for `{saved_failure.category}`.",
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="recovery.failed_start.recorded",
            event_plane="platform",
            source_domain="recovery",
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            payload=payload,
        )
    return saved_failure, saved_intent


def plan_session_restart(
    store: RecoveryStore,
    *,
    session: RuntimeSessionRecord,
    reason: str,
    observability_store=None,
    now=None,
) -> RecoveryIntentRecord:
    """Persist one explicit runtime restart intent."""
    intent = plan_runtime_restart(session, reason=reason, now=now)
    saved_intent = store.save_intent(intent)
    if observability_store is not None:
        payload = {"intent_id": saved_intent.intent_id, "action": saved_intent.action, "reason": reason}
        record_platform_audit(
            observability_store,
            action="recovery.restart.plan",
            status="succeeded",
            source_domain="recovery",
            detail=f"Planned restart recovery for runtime session `{session.session_id}`.",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="recovery.restart.planned",
            event_plane="runtime",
            source_domain="recovery",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            payload=payload,
        )
    return saved_intent


def execute_session_restart(
    store: RecoveryStore,
    *,
    runtime_store: RuntimeStore,
    session_id: str,
    reason: str,
    observability_store=None,
    now=None,
) -> tuple[RecoveryIntentRecord, RuntimeSessionRecord]:
    """Execute a runtime restart intent against the runtime lifecycle when allowed."""
    session = runtime_store.get_session(session_id)
    intent = plan_session_restart(store, session=session, reason=reason, observability_store=observability_store, now=now)
    if session.status == "running":
        transition_runtime_session(
            runtime_store,
            session_id=session_id,
            target_status="stopping",
            forced_stop_reason="recovery restart",
            observability_store=observability_store,
            now=now,
        )
        transition_runtime_session(
            runtime_store,
            session_id=session_id,
            target_status="stopped",
            forced_stop_reason="recovery restart",
            observability_store=observability_store,
            now=now,
        )
    restarted = transition_runtime_session(
        runtime_store,
        session_id=session_id,
        target_status="running",
        observability_store=observability_store,
        now=now,
    )
    return intent, restarted


def record_runtime_health(
    store: RecoveryStore,
    *,
    session: RuntimeSessionRecord,
    provider_store=None,
    runtime_store=None,
    provider_registry=None,
    observability_store=None,
    now=None,
) -> HealthCheckResult:
    """Persist one runtime health result."""
    result = run_runtime_health_check(
        session,
        provider_store=provider_store,
        runtime_store=runtime_store,
        provider_registry=provider_registry,
        now=now,
    )
    saved = store.save_health_result(result)
    if observability_store is not None:
        record_platform_event(
            observability_store,
            event_type="recovery.health.runtime",
            event_plane="runtime",
            source_domain="recovery",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            payload={"status": saved.status, "target_id": saved.target_id, "detail": saved.detail},
        )
    return saved


def record_provider_health(
    store: RecoveryStore,
    *,
    provider_registry: ProviderRegistry,
    provider_id: str,
    workspace_id: str | None = None,
    observability_store=None,
    now=None,
) -> HealthCheckResult:
    """Persist one provider health result."""
    result = run_provider_health_check(provider_registry, provider_id=provider_id, workspace_id=workspace_id, now=now)
    saved = store.save_health_result(result)
    if observability_store is not None:
        record_platform_event(
            observability_store,
            event_type="recovery.health.provider",
            event_plane="platform",
            source_domain="recovery",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload={"status": saved.status, "target_id": saved.target_id, "detail": saved.detail},
        )
    return saved


def record_app_health(
    store: RecoveryStore,
    *,
    app_store: AppStore,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
    observability_store=None,
    now=None,
) -> HealthCheckResult:
    """Persist one app health result."""
    result = run_app_health_check(
        app_store=app_store,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
        now=now,
    )
    saved = store.save_health_result(result)
    if observability_store is not None:
        record_platform_event(
            observability_store,
            event_type="recovery.health.app",
            event_plane="app",
            source_domain="recovery",
            workspace_id=workspace_id,
            app_id=app_id,
            payload={"status": saved.status, "target_id": saved.target_id, "detail": saved.detail},
        )
    return saved


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
