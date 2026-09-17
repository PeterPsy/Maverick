"""Direct admission checks for persisted runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.providers.errors import AgenticProfileError, ProviderError
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.authority import validate_live_runtime_binding_governance
from core.runtime.errors import (
    RuntimeProviderStateError,
    RuntimeSessionRestartRequiredError,
)
from core.runtime.hosted_agentic_lifecycle import recover_hosted_agentic_session
from core.runtime.provider_step_admission import provider_step_admission_reason
from core.runtime.remote_agentic_admission import require_remote_agentic_authority
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore


RuntimeAdmissionStatus = Literal["direct", "restart_required"]


@dataclass(frozen=True)
class RuntimeAdmissionAssessment:
    """Result of checking whether an existing session can run as persisted."""

    status: RuntimeAdmissionStatus
    session_id: str
    reason_code: str | None
    detail_code: str | None


def runtime_session_admission_payload(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    workspace_store: object | None = None,
) -> dict[str, object]:
    assessment = assess_runtime_session_admission(
        provider_store,
        runtime_store,
        registry,
        session=session,
        workspace_store=workspace_store,
    )
    return {
        "status": assessment.status,
        "reason_code": assessment.reason_code,
        "detail_code": assessment.detail_code,
        "model_id": None if session.execution_binding is None else session.execution_binding.model_id,
    }


def assess_runtime_session_admission(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    provider_pairing_source_turn_id: str | None = None,
    workspace_store: object | None = None,
) -> RuntimeAdmissionAssessment:
    """Check the stored config and current credentials, adapter, and policy.

    There is deliberately no schema migration, revision roll-forward, or
    automatic continuation fork here. A session either remains directly usable
    or reports the concrete reason it must be restarted.
    """
    try:
        persisted = runtime_store.get_session(session.session_id)
    except Exception:
        return _blocked(session, "runtime_session_unavailable")
    if persisted.workspace_id != session.workspace_id:
        return _blocked(session, "runtime_session_identity_mismatch")
    session = persisted
    if session.status == "recovery_required":
        return _blocked(session, "runtime_session_recovery_required")
    journal_reason = provider_step_admission_reason(
        runtime_store,
        session_id=session.session_id,
        pairing_source_turn_id=provider_pairing_source_turn_id,
    )
    if journal_reason is not None:
        return _blocked(session, journal_reason)
    if session.runtime_mode != "agentic":
        return _direct(session)
    if session.execution_binding is None:
        return _blocked(session, "runtime_execution_binding_missing")
    try:
        _validate_direct_authority(
            provider_store,
            registry,
            session=session,
            workspace_store=workspace_store,
        )
    except (ProviderError, ValueError, RuntimeProviderStateError) as error:
        return _blocked(session, _provider_reason(error))
    return _direct(session)


def _validate_direct_authority(
    provider_store: ProviderStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    workspace_store: object | None,
) -> None:
    binding = session.execution_binding
    if binding is None:
        raise ValueError("runtime_execution_binding_missing")
    require_remote_agentic_authority(
        binding,
        workspace_id=session.workspace_id,
        workspace_store=workspace_store,
    )
    adapter = registry.get_agentic_runtime_adapter(binding.runtime_engine_id)
    if (
        str(getattr(adapter, "runtime_engine_id", "")) != binding.runtime_engine_id
        or str(getattr(adapter, "adapter_id", "")) != binding.adapter_id
        or str(getattr(adapter, "adapter_version", "")) != binding.adapter_version
    ):
        raise AgenticProfileError("runtime_adapter_identity_mismatch")
    validate_live_runtime_binding_governance(provider_store, binding=binding)


def _provider_reason(error: BaseException) -> str:
    return str(getattr(error, "reason_code", None) or error or "provider_unavailable").strip()


def _direct(session: RuntimeSessionRecord) -> RuntimeAdmissionAssessment:
    return RuntimeAdmissionAssessment("direct", session.session_id, None, None)


def _blocked(session: RuntimeSessionRecord, detail_code: str) -> RuntimeAdmissionAssessment:
    detail = str(detail_code or "runtime_session_restart_required")
    return RuntimeAdmissionAssessment(
        "restart_required",
        session.session_id,
        "runtime_session_restart_required",
        detail,
    )


@dataclass(frozen=True)
class RuntimeSessionAdmissionResult:
    """A directly admitted current runtime session."""

    status: str
    session: RuntimeSessionRecord
    assessment: RuntimeAdmissionAssessment


def admit_runtime_session(
    state,
    *,
    session: RuntimeSessionRecord,
    provider_pairing_source_turn_id: str | None = None,
) -> RuntimeSessionAdmissionResult:
    """Admit one persisted session without migration or automatic forking."""
    if session.status == "recovery_required":
        raise RuntimeSessionRestartRequiredError(
            "runtime_session_restart_required",
            detail_code=session.recovery_reason_code or "runtime_state_ambiguous",
        )
    if provider_pairing_source_turn_id is None:
        recovery = recover_hosted_agentic_session(
            state,
            session=session,
            trigger="pre_admission",
        )
        if recovery.applicable and not recovery.recovered:
            raise RuntimeSessionRestartRequiredError(
                "runtime_session_restart_required",
                detail_code=recovery.reason_code,
            )
    current = state.runtime_store.get_session(session.session_id)
    assessment = assess_runtime_session_admission(
        state.provider_store,
        state.runtime_store,
        state.provider_registry,
        session=current,
        provider_pairing_source_turn_id=provider_pairing_source_turn_id,
        workspace_store=getattr(state, "workspace_store", None),
    )
    if assessment.status != "direct":
        raise RuntimeSessionRestartRequiredError(
            assessment.reason_code or "runtime_session_restart_required",
            detail_code=assessment.detail_code,
        )
    return RuntimeSessionAdmissionResult("direct", current, assessment)
