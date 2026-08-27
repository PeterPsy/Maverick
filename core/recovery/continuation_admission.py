"""Fail-closed admission classification for pinned runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Literal

from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.errors import AgenticProfileError, ProviderError
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.recovery.continuation_compatibility import (
    prove_compatible_runtime_upgrade,
)
from core.runtime.authority import validate_live_runtime_binding_governance
from core.runtime.execution_binding import RuntimeExecutionBinding
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore


RuntimeAdmissionStatus = Literal[
    "direct",
    "compatible_upgrade",
    "upgrade_required",
    "provider_thread_missing",
]

COMPATIBLE_UPGRADE_SOURCE_REASONS = {
    "adapter_artifact_mismatch",
    "certificate_expired",
}
NON_TERMINAL_CONTINUATION_TURN_STATUSES = frozenset(
    {"queued", "active", "waiting_for_tool_confirmation"}
)


@dataclass(frozen=True)
class RuntimeAdmissionAssessment:
    """Typed result of validating one session before turn persistence."""

    status: RuntimeAdmissionStatus
    session_id: str
    reason_code: str | None
    detail_code: str | None
    target_execution_binding: RuntimeExecutionBinding | None = None
    compatible_capabilities: tuple[str, ...] = ()
    compatibility_digest: str | None = None


def runtime_session_admission_payload(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return a redaction-safe read-only admission status for UI and operators."""
    digest = hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()[:24]
    assessment = assess_runtime_session_admission(
        provider_store,
        runtime_store,
        registry,
        session=session,
        target_session_id=f"runtime-admission-{digest}",
        now=now,
    )
    source = session.execution_binding
    target = assessment.target_execution_binding
    return {
        "status": assessment.status,
        "reason_code": assessment.reason_code,
        "detail_code": assessment.detail_code,
        "source_profile_revision": (
            None if source is None else source.profile_definition_revision
        ),
        "target_profile_revision": (
            None if target is None else target.profile_definition_revision
        ),
        "provider_thread_available": assessment.status != "provider_thread_missing",
    }


def assess_runtime_session_admission(
    provider_store: ProviderStore,
    runtime_store: RuntimeStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    target_session_id: str,
    now: datetime | None = None,
) -> RuntimeAdmissionAssessment:
    """Validate direct authority or prove one conservative continuation upgrade."""
    binding = session.execution_binding
    if session.status == "recovery_required":
        return _blocked(session, "runtime_session_recovery_required")
    if session.runtime_mode != "agentic":
        return _direct(session)
    if binding is None:
        return _blocked(session, "runtime_execution_binding_missing")
    try:
        _validate_direct_authority(
            provider_store,
            registry,
            session=session,
            now=now,
        )
    except ProviderError as error:
        source_reason = _provider_reason(error)
    else:
        return _direct(session)
    if source_reason not in COMPATIBLE_UPGRADE_SOURCE_REASONS:
        return _blocked(session, source_reason)
    try:
        validate_live_runtime_binding_governance(
            provider_store,
            binding=binding,
            allow_inactive_definition=True,
        )
    except ProviderError as error:
        return _blocked(session, _provider_reason(error))
    if session.session_kind != "chat_root":
        return _blocked(
            session,
            "runtime_profile_upgrade_session_kind_unsupported",
        )
    if binding.legacy_inferred:
        return _blocked(session, "runtime_profile_upgrade_legacy_authority_unproven")
    try:
        provider_state = runtime_store.get_provider_state(session.session_id)
    except RuntimeProviderStateError:
        return _provider_thread_missing(session, "runtime_provider_state_missing")
    if (
        provider_state.workspace_id != session.workspace_id
        or provider_state.runtime_engine_id != binding.runtime_engine_id
        or provider_state.model_provider_id != binding.model_provider_id
    ):
        return _blocked(session, "runtime_profile_upgrade_provider_state_mismatch")
    continuation_problem = _provider_continuation_problem(provider_state)
    if continuation_problem == "provider_thread_missing":
        return _provider_thread_missing(session, "provider_thread_missing")
    if continuation_problem is not None:
        return _blocked(session, continuation_problem)
    if runtime_session_has_nonterminal_turns(runtime_store, session.session_id):
        return _blocked(session, "runtime_profile_upgrade_turn_busy")
    try:
        target_workspace_binding_id = _compatible_target_workspace_binding_id(
            provider_store,
            source=binding,
        )
        target = build_pinned_execution_binding(
            provider_store,
            registry,
            session_id=target_session_id,
            workspace_id=session.workspace_id,
            execution_mode=session.effective_mode,
            workspace_binding_id=target_workspace_binding_id,
            reasoning_effort=binding.reasoning_effort,
            now=now,
        )
        capabilities, proof_digest = prove_compatible_runtime_upgrade(
            provider_store,
            source=binding,
            target=target,
            source_reason=source_reason,
        )
    except ProviderError as error:
        return _blocked(session, _provider_reason(error))
    except ValueError as error:
        return _blocked(session, str(error))
    return RuntimeAdmissionAssessment(
        status="compatible_upgrade",
        session_id=session.session_id,
        reason_code="runtime_profile_upgrade_compatible",
        detail_code=source_reason,
        target_execution_binding=target,
        compatible_capabilities=capabilities,
        compatibility_digest=proof_digest,
    )


def _validate_direct_authority(
    provider_store: ProviderStore,
    registry: ProviderRegistry,
    *,
    session: RuntimeSessionRecord,
    now: datetime | None,
) -> None:
    binding = session.execution_binding
    if binding is None:
        raise ValueError("runtime_execution_binding_missing")
    adapter = registry.get_agentic_runtime_adapter(binding.runtime_engine_id)
    validate_certificate_for_binding(
        provider_store,
        binding=binding,
        adapter=adapter,
        now=now,
    )
    validate_live_runtime_binding_governance(
        provider_store,
        binding=binding,
    )


def _provider_continuation_problem(state: RuntimeProviderState) -> str | None:
    if not str(state.provider_thread_id or "").strip() or not str(
        state.continuation_id or ""
    ).strip():
        return "provider_thread_missing"
    if state.provider_request_id is not None or state.turn_generation is not None:
        return "runtime_profile_upgrade_provider_state_busy"
    if state.provider_private_envelope is not None:
        return "runtime_profile_upgrade_private_state_not_transferable"
    return None


def runtime_session_has_nonterminal_turns(
    runtime_store: RuntimeStore,
    session_id: str,
) -> bool:
    """Return whether a continuation handoff must wait for persisted turn work."""
    return any(
        turn.status in NON_TERMINAL_CONTINUATION_TURN_STATUSES
        for turn in runtime_store.list_turns(session_id)
    )


def _compatible_target_workspace_binding_id(
    provider_store: ProviderStore,
    *,
    source: RuntimeExecutionBinding,
) -> str:
    candidates = []
    for binding in provider_store.list_workspace_agentic_profile_bindings(
        source.workspace_id
    ):
        if not binding.enabled or binding.definition_id != source.profile_definition_id:
            continue
        status = provider_store.get_agentic_profile_definition_status(
            binding.definition_id,
            binding.definition_revision,
        )
        if status is None or status.rollout_status in {"disabled", "suspended"}:
            continue
        candidates.append(binding)
    if not candidates:
        raise AgenticProfileError("runtime_profile_upgrade_target_binding_missing")
    exact_candidates = [
        binding
        for binding in candidates
        if binding.credential_binding_id == source.credential_binding_id
        and binding.workspace_policy_ceiling
        == source.workspace_policy_ceiling_snapshot
        and binding.egress_policy_id == source.egress_policy_id
        and binding.egress_policy_revision == source.egress_policy_revision
    ]
    if exact_candidates:
        candidates = exact_candidates
    candidates.sort(
        key=lambda item: (
            _numeric_revision(item.definition_revision),
            item.revision,
            item.updated_at,
            item.binding_id,
        ),
        reverse=True,
    )
    return candidates[0].binding_id


def _numeric_revision(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _provider_reason(error: BaseException) -> str:
    reason = getattr(error, "reason_code", None)
    return str(reason or error or "provider_unavailable").strip()


def _direct(session: RuntimeSessionRecord) -> RuntimeAdmissionAssessment:
    return RuntimeAdmissionAssessment(
        status="direct",
        session_id=session.session_id,
        reason_code=None,
        detail_code=None,
    )


def _blocked(session: RuntimeSessionRecord, detail_code: str) -> RuntimeAdmissionAssessment:
    return RuntimeAdmissionAssessment(
        status="upgrade_required",
        session_id=session.session_id,
        reason_code="runtime_profile_upgrade_required",
        detail_code=str(detail_code or "runtime_profile_upgrade_required"),
    )


def _provider_thread_missing(
    session: RuntimeSessionRecord,
    detail_code: str,
) -> RuntimeAdmissionAssessment:
    return RuntimeAdmissionAssessment(
        status="provider_thread_missing",
        session_id=session.session_id,
        reason_code="runtime_profile_upgrade_required",
        detail_code=detail_code,
    )
