"""Synchronous Core services over asynchronous agentic adapter operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.providers.agentic_adapter import (
    AgenticRuntimeEngineAdapter,
    RuntimeCancelContext,
    RuntimeCancelResult,
    RuntimeCloseContext,
    RuntimeCloseResult,
    RuntimePrepareContext,
    RuntimePrepareResult,
    RuntimeValidationContext,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.async_runtime import run_runtime_coroutine
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.store import RuntimeStore


PROVIDER_STATE_UPDATE_FIELDS = frozenset(
    {
        "continuation_id",
        "provider_thread_id",
        "provider_request_id",
        "turn_generation",
    }
)


def prepare_agentic_runtime(
    store: RuntimeStore,
    *,
    session_id: str,
    adapter: AgenticRuntimeEngineAdapter,
    effective_authority: EffectiveRuntimeAuthority,
    local_launch_spec: RuntimeBackendLaunchSpec | None = None,
) -> RuntimePrepareResult:
    """Prepare any engine and persist its allowlisted provider-state update."""
    session = store.get_session(session_id)
    binding = session.execution_binding
    if binding is None:
        raise RuntimeProviderStateError("Agentic runtime preparation requires a pinned binding.")
    if effective_authority.execution_binding_id != binding.execution_binding_id:
        raise RuntimeProviderStateError("Runtime authority does not match the prepared binding.")
    provider_state = store.get_provider_state(session_id)
    health = run_runtime_coroutine(adapter.validate(RuntimeValidationContext(session=session, binding=binding)))
    if health.status == "unavailable":
        raise RuntimeProviderStateError("runtime_health_unavailable")
    result = run_runtime_coroutine(
        adapter.prepare(
            RuntimePrepareContext(
                session=session,
                binding=binding,
                provider_state=provider_state,
                local_launch_spec=local_launch_spec,
            )
        )
    )
    if result.provider_state_updates:
        update_runtime_provider_state(
            store,
            session_id=session_id,
            updates=result.provider_state_updates,
        )
    return result


def close_agentic_runtime(
    store: RuntimeStore,
    *,
    session_id: str,
    adapter: AgenticRuntimeEngineAdapter,
) -> RuntimeCloseResult:
    """Close one engine through the async contract without process assumptions."""
    session = store.get_session(session_id)
    binding = session.execution_binding
    if binding is None:
        raise RuntimeProviderStateError("Agentic runtime close requires a pinned binding.")
    provider_state = store.get_provider_state(session_id)
    return run_runtime_coroutine(
        adapter.close(
            RuntimeCloseContext(
                session=session,
                binding=binding,
                provider_state=provider_state,
            )
        )
    )


def cancel_agentic_runtime(
    store: RuntimeStore,
    *,
    session_id: str,
    correlation_id: str,
    adapter: AgenticRuntimeEngineAdapter,
    wait_for_termination: bool = False,
) -> RuntimeCancelResult:
    """Cancel one active request through the provider-neutral contract."""
    session = store.get_session(session_id)
    binding = session.execution_binding
    if binding is None:
        raise RuntimeProviderStateError("Agentic runtime cancellation requires a pinned binding.")
    provider_state = store.get_provider_state(session_id)
    return run_runtime_coroutine(
        adapter.cancel(
            RuntimeCancelContext(
                session=session,
                binding=binding,
                provider_state=provider_state,
                correlation_id=correlation_id,
                wait_for_termination=wait_for_termination,
            )
        )
    )


def update_runtime_provider_state(
    store: RuntimeStore,
    *,
    session_id: str,
    updates: dict[str, object],
) -> RuntimeProviderState:
    """Apply a bounded provider-neutral state patch with revision fencing."""
    invalid = sorted(set(updates) - PROVIDER_STATE_UPDATE_FIELDS)
    if invalid:
        raise RuntimeProviderStateError(
            "Runtime provider state update contains forbidden fields: " + ", ".join(invalid)
        )
    session = store.get_session(session_id)
    if session.status not in {"created", "running"}:
        raise RuntimeProviderStateError(
            f"Runtime provider state cannot advance while session `{session_id}` is {session.status}."
        )
    for attempt in range(3):
        current = store.get_provider_state(session_id)
        effective_updates = {
            key: value
            for key, value in updates.items()
            if getattr(current, key) != value
        }
        if not effective_updates:
            return current
        updated = replace(
            current,
            **effective_updates,
            revision=current.revision + 1,
            updated_at=datetime.now(tz=UTC),
        )
        try:
            return store.update_provider_state(updated, expected_revision=current.revision)
        except RuntimeProviderStateError:
            if attempt == 2:
                raise
