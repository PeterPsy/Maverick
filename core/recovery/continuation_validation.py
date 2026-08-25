"""Live revalidation for durable runtime continuation handoffs."""

from __future__ import annotations

from datetime import datetime

from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.errors import ProviderError
from core.recovery.continuation_admission import (
    COMPATIBLE_UPGRADE_SOURCE_REASONS,
)
from core.recovery.continuation_compatibility import (
    prove_compatible_runtime_upgrade,
)
from core.runtime.continuation_handoff import RuntimeContinuationHandoff
from core.runtime.authority import validate_live_runtime_binding_governance
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from core.runtime.runtime_session import RuntimeSessionRecord


def revalidate_continuation_handoff(
    state,
    *,
    predecessor: RuntimeSessionRecord,
    handoff: RuntimeContinuationHandoff,
    now: datetime,
) -> bool:
    """Recompute authority and return whether the target may become executable."""
    source = predecessor.execution_binding
    target = handoff.target_execution_binding
    if source is None:
        _reject("runtime_continuation_source_binding_missing")
    try:
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            target.runtime_engine_id
        )
        source_reason = _certificate_problem(
            state,
            binding=source,
            adapter=adapter,
            now=now,
        )
        target_reason = _certificate_problem(
            state,
            binding=target,
            adapter=adapter,
            now=now,
        )
        if source_reason not in COMPATIBLE_UPGRADE_SOURCE_REASONS:
            _reject(
                "runtime_continuation_source_authority_changed"
                if source_reason is None
                else f"runtime_continuation_{source_reason}"
            )
        if (
            target_reason is not None
            and target_reason not in COMPATIBLE_UPGRADE_SOURCE_REASONS
        ):
            _reject(f"runtime_continuation_{target_reason}")
        validate_live_runtime_binding_governance(
            state.provider_store,
            binding=source,
            allow_inactive_definition=True,
        )
        validate_live_runtime_binding_governance(
            state.provider_store,
            binding=target,
            allow_inactive_definition=(
                target_reason in COMPATIBLE_UPGRADE_SOURCE_REASONS
            ),
        )
        capabilities, proof_digest = prove_compatible_runtime_upgrade(
            state.provider_store,
            source=source,
            target=target,
            source_reason=source_reason,
        )
    except RuntimeProfileUpgradeRequiredError:
        raise
    except (ProviderError, ValueError) as error:
        _reject(f"runtime_continuation_{_reason(error)}")
    if capabilities != handoff.compatible_capabilities:
        _reject("runtime_continuation_capabilities_changed")
    if proof_digest != handoff.compatibility_digest:
        _reject("runtime_continuation_compatibility_proof_changed")
    return target_reason is None


def _certificate_problem(state, *, binding, adapter, now: datetime) -> str | None:
    try:
        validate_certificate_for_binding(
            state.provider_store,
            binding=binding,
            adapter=adapter,
            now=now,
        )
    except ProviderError as error:
        return _reason(error)
    return None


def _reason(error: BaseException) -> str:
    return str(getattr(error, "reason_code", None) or error or "authority_invalid").strip()


def _reject(detail_code: str) -> None:
    raise RuntimeProfileUpgradeRequiredError(
        "runtime_profile_upgrade_required",
        detail_code=detail_code,
    )
