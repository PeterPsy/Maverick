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
from core.providers.store import ProviderStore
from core.runtime.lifecycle_service import transition_runtime_session
from core.runtime.store import RuntimeStore


_REVOCATION_REASON = "phase0_remote_agentic_containment"


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
        # A fully contained state has no remaining targets, so a retry cannot
        # mutate state even though the post-apply plan digest has changed.
        and any(plan[key] for key in ("bindings", "profiles", "certificates", "sessions"))
    ):
        raise ValueError("remote_agentic_containment_plan_changed")
    applied = {
        "bindings_disabled": 0,
        "profiles_suspended": 0,
        "certificates_revoked": 0,
        "sessions_quarantined": 0,
    }
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
    counts = {
        "bindings_disabled": 0,
        "profiles_suspended": 0,
        "certificates_revoked": 0,
        "sessions_quarantined": 0,
    }
    for target in plan["bindings"]:
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
        current = runtime_store.get_session(target.identity)
        if current.status == "recovery_required":
            continue
        transition_runtime_session(
            runtime_store,
            session_id=current.session_id,
            target_status="recovery_required",
            forced_stop_reason="remote_agentic_state_ambiguous",
            recovery_reason_code="remote_agentic_state_ambiguous",
            now=now,
        )
        counts["sessions_quarantined"] += 1
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.remote_agentic_containment.apply",
            status="succeeded",
            source_domain="providers",
            detail="Applied Phase-0 remote agentic containment through store CAS transitions.",
            payload={"plan_digest": plan["digest"], **counts},
            now=now,
        )
    return counts
