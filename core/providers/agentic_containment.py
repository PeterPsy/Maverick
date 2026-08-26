"""Store-backed Phase-0 containment for remote agentic profiles and sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.observability.service import record_platform_audit
from core.providers.agentic_containment_models import (
    ContainmentMode,
    RemoteAgenticContainmentReport,
)
from core.providers.agentic_containment_plan import build_remote_agentic_containment_plan
from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.capability_models import CapabilityCertificateStatus
from core.providers.certificate_service import revoke_capability_certificate
from core.providers.errors import (
    AgenticProfileConflictError,
    CapabilityCertificateConflictError,
)
from core.providers.store import ProviderStore
from core.runtime.errors import RuntimeTransitionError
from core.runtime.lifecycle_service import transition_runtime_session
from core.runtime.store import RuntimeStore


_REVOCATION_REASON = "phase0_remote_agentic_containment"


class RemoteAgenticContainmentApplyError(ValueError):
    """Apply failure that forbids retrying the reviewed operation."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.requires_new_dry_run = True
        self.safe_to_retry = False
        super().__init__(reason_code)


def run_remote_agentic_containment(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    *,
    mode: ContainmentMode = "dry_run",
    expected_plan_digest: str | None = None,
    now: datetime | None = None,
    observability_store=None,
) -> RemoteAgenticContainmentReport:
    """Plan or apply the complete Phase-0 remote containment saga."""
    if mode not in {"dry_run", "apply"}:
        raise ValueError("remote_agentic_containment_mode_invalid")
    if mode == "apply" and not expected_plan_digest:
        raise ValueError("remote_agentic_containment_plan_digest_required")
    timestamp = now or datetime.now(tz=UTC)
    plan = build_remote_agentic_containment_plan(provider_store, runtime_store)
    if (
        mode == "apply"
        and expected_plan_digest is not None
        and plan["digest"] != expected_plan_digest
    ):
        try:
            _record_apply_audit(
                observability_store,
                status="failed",
                plan_digest=plan["digest"],
                counts=_empty_applied_counts(),
                now=timestamp,
                failure_code="reviewed_plan_changed",
                failure_stage="plan_validation",
            )
        except Exception:
            pass
        raise RemoteAgenticContainmentApplyError(
            "remote_agentic_containment_plan_changed"
        )
    applied = _empty_applied_counts()
    if mode == "apply":
        applied = _apply_plan(
            provider_store,
            runtime_store,
            plan=plan,
            now=timestamp,
            observability_store=observability_store,
        )
    counts = {
        "remote_sessions_inventoried": len(plan["inventory"]),
        "bindings_to_disable": len(plan["bindings"]),
        "profiles_to_suspend": len(plan["profiles"]),
        "certificates_to_revoke": len(plan["certificates"]),
        "sessions_to_quarantine": len(plan["sessions"]),
        **applied,
    }
    return RemoteAgenticContainmentReport(
        mode=mode,
        generated_at=timestamp,
        implementation_status="implementation_ready",
        dry_run_status="dry_run_verified",
        operational_status=(
            "live_apply_pending_review"
            if mode == "dry_run"
            else "live_apply_applied_pending_verification"
        ),
        counts=counts,
        binding_targets=plan["bindings"],
        profile_targets=plan["profiles"],
        certificate_targets=plan["certificates"],
        session_targets=plan["sessions"],
        session_inventory=plan["inventory"],
        plan_digest=plan["digest"],
    )


def _apply_plan(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    *,
    plan: dict,
    now: datetime,
    observability_store,
) -> dict[str, int]:
    counts = _empty_applied_counts()
    active_target = None
    try:
        for target in plan["bindings"]:
            active_target = target
            current = provider_store.get_workspace_agentic_profile_binding(target.identity)
            provider_store.save_workspace_agentic_profile_binding(
                replace(
                    current,
                    enabled=False,
                    is_default=False,
                    revision=current.revision + 1,
                    updated_at=now,
                ),
                expected_revision=target.current_revision,
            )
            counts["bindings_disabled"] += 1
        for target in plan["profiles"]:
            active_target = target
            current = provider_store.get_agentic_profile_definition_status(
                target.definition_id or "",
                target.definition_revision or "",
            )
            if current is None:
                provider_store.save_agentic_profile_definition_status(
                    AgenticProfileDefinitionStatus(
                        definition_id=target.definition_id or "",
                        definition_revision=target.definition_revision or "",
                        rollout_status="suspended",
                        revision=0,
                        updated_at=now,
                    ),
                    expected_revision=None,
                )
            else:
                provider_store.save_agentic_profile_definition_status(
                    replace(
                        current,
                        rollout_status="suspended",
                        revision=current.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=target.current_revision,
                )
            counts["profiles_suspended"] += 1
        for target in plan["certificates"]:
            active_target = target
            if target.current_revision is None:
                provider_store.save_capability_certificate_status(
                    CapabilityCertificateStatus(
                        certificate_id=target.identity,
                        status="revoked",
                        revision=0,
                        updated_at=now,
                        revoked_at=now,
                        revocation_reason=_REVOCATION_REASON,
                    ),
                    expected_revision=None,
                )
            else:
                revoke_capability_certificate(
                    provider_store,
                    certificate_id=target.identity,
                    expected_revision=target.current_revision,
                    reason=_REVOCATION_REASON,
                    now=now,
                    observability_store=observability_store,
                )
            counts["certificates_revoked"] += 1
        for target in plan["sessions"]:
            active_target = target
            transition_runtime_session(
                runtime_store,
                session_id=target.identity,
                target_status="recovery_required",
                expected_status=target.current_status,
                forced_stop_reason="remote_agentic_state_ambiguous",
                recovery_reason_code="remote_agentic_state_ambiguous",
                now=now,
            )
            counts["sessions_quarantined"] += 1
        active_target = None
        _record_apply_audit(
            observability_store,
            status="succeeded",
            plan_digest=plan["digest"],
            counts=counts,
            now=now,
        )
    except Exception as error:
        try:
            _record_apply_audit(
                observability_store,
                status="failed",
                plan_digest=plan["digest"],
                counts=counts,
                now=now,
                failure_code=_apply_failure_code(error),
                failure_stage=(
                    "apply_audit" if active_target is None else active_target.target_kind
                ),
                failed_target_digest=(
                    None if active_target is None else active_target.target_digest
                ),
            )
        except Exception:
            pass
        raise RemoteAgenticContainmentApplyError(
            "remote_agentic_containment_apply_failed_new_review_required"
        ) from error
    return counts


def _empty_applied_counts() -> dict[str, int]:
    return {
        "bindings_disabled": 0,
        "profiles_suspended": 0,
        "certificates_revoked": 0,
        "sessions_quarantined": 0,
    }


def _apply_failure_code(error: Exception) -> str:
    if isinstance(
        error,
        (AgenticProfileConflictError, CapabilityCertificateConflictError),
    ):
        return "provider_record_cas_conflict"
    if isinstance(error, RuntimeTransitionError):
        return "session_lifecycle_conflict"
    return "containment_apply_failed"


def _record_apply_audit(
    observability_store,
    *,
    status,
    plan_digest: str,
    counts: dict[str, int],
    now: datetime,
    failure_code: str | None = None,
    failure_stage: str | None = None,
    failed_target_digest: str | None = None,
) -> None:
    if observability_store is None:
        return
    failed = status == "failed"
    record_platform_audit(
        observability_store,
        action="provider.remote_agentic_containment.apply",
        status=status,
        source_domain="providers",
        detail=(
            "Phase-0 containment apply stopped; partial writes may exist and a new dry-run review is required."
            if failed
            else "Completed every reviewed Phase-0 containment transition; post-apply verification remains required."
        ),
        payload={
            "plan_digest": plan_digest,
            **counts,
            "partial_apply": failed and any(counts.values()),
            "safe_to_retry": False,
            "requires_new_dry_run": True,
            "requires_post_apply_verification": not failed,
            **({"failure_code": failure_code} if failure_code else {}),
            **({"failure_stage": failure_stage} if failure_stage else {}),
            **(
                {"failed_target_digest": failed_target_digest}
                if failed_target_digest
                else {}
            ),
        },
        now=now,
    )
