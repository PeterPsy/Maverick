"""Lifecycle entry points for productive hosted provider-step recovery."""

from __future__ import annotations

from dataclasses import dataclass

from core.runtime.lifecycle_service_children import transition_runtime_session


_HOSTED_RUNTIME_ENGINE_ID = "maverick-tool-loop"
_HOSTED_ADAPTER_ID = "maverick-hosted-tool-loop"


@dataclass(frozen=True)
class HostedLifecycleRecoveryOutcome:
    applicable: bool
    recovered: bool
    reason_code: str


def recover_hosted_agentic_session(state, *, session, trigger: str):
    """Invoke recovery only for an adapter exposing the certified sync hook."""
    binding = session.execution_binding
    if binding is None or session.runtime_mode != "agentic":
        return HostedLifecycleRecoveryOutcome(False, True, "not_applicable")
    hosted_binding = (
        binding.runtime_engine_id == _HOSTED_RUNTIME_ENGINE_ID
        and binding.adapter_id == _HOSTED_ADAPTER_ID
    )
    if session.status == "recovery_required":
        return HostedLifecycleRecoveryOutcome(
            hosted_binding,
            not hosted_binding,
            session.recovery_reason_code or "provider_state_ambiguous",
        )
    try:
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            binding.runtime_engine_id
        )
    except Exception:
        return _unavailable_adapter_outcome(
            state,
            session=session,
            hosted_binding=hosted_binding,
        )
    recover_now = getattr(adapter, "recover_now", None)
    if not callable(recover_now):
        return _unavailable_adapter_outcome(
            state,
            session=session,
            hosted_binding=hosted_binding,
        )
    try:
        result = recover_now(session=session, trigger=trigger)
    except Exception:
        return _unavailable_adapter_outcome(
            state,
            session=session,
            hosted_binding=hosted_binding,
        )
    return HostedLifecycleRecoveryOutcome(
        True,
        bool(result.recovered),
        str(result.reason_code),
    )


def _unavailable_adapter_outcome(state, *, session, hosted_binding: bool):
    if not hosted_binding:
        return HostedLifecycleRecoveryOutcome(False, True, "not_applicable")
    current = state.runtime_store.get_session(session.session_id)
    if current.status != "recovery_required" and current.status in {
        "created",
        "running",
        "stopping",
        "failed",
    }:
        try:
            transition_runtime_session(
                state.runtime_store,
                session_id=current.session_id,
                target_status="recovery_required",
                expected_status=current.status,
                recovery_reason_code="provider_state_ambiguous",
            )
        except Exception:
            current = state.runtime_store.get_session(session.session_id)
            if current.status != "recovery_required":
                raise
    return HostedLifecycleRecoveryOutcome(
        True,
        False,
        "provider_state_ambiguous",
    )


def recover_all_hosted_agentic_sessions(state, *, trigger: str) -> tuple[int, int]:
    """Recover every live hosted session before generic worker-loss handling."""
    inspected = 0
    quarantined = 0
    for session in state.runtime_store.list_all_sessions():
        if session.status not in {"created", "running", "stopping", "failed"}:
            continue
        outcome = recover_hosted_agentic_session(
            state,
            session=session,
            trigger=trigger,
        )
        if not outcome.applicable:
            continue
        inspected += 1
        quarantined += int(not outcome.recovered)
    return inspected, quarantined


__all__ = [
    "HostedLifecycleRecoveryOutcome",
    "recover_all_hosted_agentic_sessions",
    "recover_hosted_agentic_session",
]
