"""Resolved provider-neutral runtime engine context for one session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.provider_registry import RuntimeBackendAdapter
from core.runtime.agentic_runtime_service import update_runtime_provider_state
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.authority_service import resolve_and_record_runtime_authority
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore


@dataclass(frozen=True)
class ResolvedRuntimeEngine:
    """One immutable resolution shared by preparation and turn execution."""

    provider: ProviderDefinition
    selection: ProviderSelection | None
    agentic_adapter: AgenticRuntimeEngineAdapter
    legacy_adapter: RuntimeBackendAdapter | None

    @property
    def provider_id(self) -> str:
        return self.provider.provider_id

    @property
    def requires_local_launch_spec(self) -> bool:
        return self.agentic_adapter.local_process_lifecycle is not None

    def provider_state(self, store: RuntimeStore, session: RuntimeSessionRecord) -> RuntimeProviderState | None:
        if session.execution_binding is None:
            return None
        return store.get_provider_state(session.session_id)

    def provider_state_updater(
        self,
        store: RuntimeStore,
        session: RuntimeSessionRecord,
    ) -> Callable[[dict[str, object]], RuntimeProviderState] | None:
        if session.execution_binding is None:
            return None

        def update(updates: dict[str, object]) -> RuntimeProviderState:
            return update_runtime_provider_state(store, session_id=session.session_id, updates=updates)

        return update

    def execution_kwargs(
        self,
        state,
        session: RuntimeSessionRecord,
        *,
        correlation_id: str,
    ) -> dict[str, object]:
        """Return the common adapter/state arguments for one execution call."""
        authority = (
            resolve_and_record_runtime_authority(
                state,
                session=session,
                adapter=self.agentic_adapter,
                turn_id=correlation_id,
            )
            if session.execution_binding is not None
            else None
        )
        return {
            "runtime_adapter": self.legacy_adapter,
            "agentic_adapter": self.agentic_adapter,
            "provider_state": self.provider_state(state.runtime_store, session),
            "correlation_id": correlation_id,
            "effective_authority": authority,
            "on_provider_state_update": self.provider_state_updater(state.runtime_store, session),
            "on_provider_upstream_observed": self.upstream_validator(state.provider_store, session),
        }

    def upstream_validator(self, provider_store, session: RuntimeSessionRecord) -> Callable[[str], None] | None:
        binding = session.execution_binding
        if binding is None:
            return None

        def validate(upstream_id: str) -> None:
            validate_certificate_for_binding(
                provider_store,
                binding=binding,
                adapter=self.agentic_adapter,
                observed_upstream_id=upstream_id,
            )

        return validate


def build_optional_local_launch_spec(
    engine: ResolvedRuntimeEngine,
    builder: Callable[..., Any],
    state,
    *,
    session: RuntimeSessionRecord,
    absent_result: Any = None,
) -> Any:
    """Build launch material only when the adapter declares a local lifecycle."""
    if not engine.requires_local_launch_spec:
        return absent_result
    return builder(
        state,
        session=session,
        provider_id=engine.provider_id,
        provider_definition=engine.provider,
        provider_selection=engine.selection,
        runtime_adapter=engine.legacy_adapter,
    )
