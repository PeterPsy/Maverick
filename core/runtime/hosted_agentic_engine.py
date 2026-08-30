"""Async runtime-engine adapter backed by the shared hosted agentic loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from types import SimpleNamespace
from threading import Event, RLock

import core.runtime.provider_step_admission as provider_step_admission_module
from core.providers.agentic_adapter import (
    RuntimeCancelContext,
    RuntimeCancelResult,
    RuntimeCloseContext,
    RuntimeCloseResult,
    RuntimeHealth,
    RuntimeHealthContext,
    RuntimePrepareContext,
    RuntimePrepareResult,
    RuntimeProviderEvent,
    RuntimeRecoveryContext,
    RuntimeRecoveryResult,
    RuntimeTurnContext,
    RuntimeValidationContext,
)
from core.runtime.hosted_agentic_loop import HostedAgenticLoop
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_policy import authorized_core_tool_handles
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    public_provider_private_reason,
)
from core.runtime.provider_step_admission import provider_step_admission_reason
from core.runtime.service import transition_runtime_turn


class HostedAgenticEngineAdapter:
    """Process-independent adapter sharing one policy/tool loop across providers."""

    local_process_lifecycle = None

    def __init__(
        self,
        *,
        runtime_engine_id: str,
        adapter_id: str,
        adapter_version: str,
        loop: HostedAgenticLoop,
        composition_components: tuple[object, ...] = (),
        process_registry=None,
    ) -> None:
        self.runtime_engine_id = runtime_engine_id
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.loop = loop
        self.composition_components = composition_components
        self.process_registry = process_registry
        self._cancellations: dict[str, tuple[str, Event]] = {}
        self._lock = RLock()

    @property
    def artifact_components(self) -> tuple[object, ...]:
        """Expose the shared loop and installed provider codecs to certification."""
        return (
            self.loop,
            provider_step_admission_module,
            *self.composition_components,
            *self.loop.artifact_components,
            *self.loop.provider_runtimes.artifact_components(),
        )

    def currently_authorized_tool_handles(self, binding) -> tuple[str, ...]:
        """Expose redaction-safe candidates for the pre-execution authority audit."""
        return authorized_core_tool_handles(binding)

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth:
        binding = context.binding
        if (
            binding.runtime_engine_id != self.runtime_engine_id
            or binding.adapter_id != self.adapter_id
            or binding.adapter_version != self.adapter_version
        ):
            return RuntimeHealth(status="unavailable", reason_codes=("adapter_version_mismatch",))
        try:
            self.loop.provider_runtimes.resolve(binding)
        except HostedAgenticLoopError as error:
            return RuntimeHealth(status="unavailable", reason_codes=(error.reason_code,))
        return RuntimeHealth(status="healthy")

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        persisted_session = self.loop.tool_ledger.store.get_session(
            context.session.session_id
        )
        if persisted_session.status == "recovery_required":
            return RuntimePrepareResult(
                ready=False,
                metadata={"reason_code": "runtime_session_recovery_required"},
            )
        if context.local_launch_spec is not None:
            return RuntimePrepareResult(
                ready=False,
                metadata={"reason_code": "hosted_launch_spec_forbidden"},
            )
        try:
            runtime = self.loop.provider_runtimes.resolve(context.binding)
            codec = runtime.private_codec
        except HostedAgenticLoopError as error:
            return RuntimePrepareResult(ready=False, metadata={"reason_code": error.reason_code})
        persisted_context = replace(
            context,
            session=persisted_session,
            provider_state=self.loop.tool_ledger.store.get_provider_state(
                persisted_session.session_id
            ),
        )
        recovered = self.loop.recover_session(persisted_context, trigger="pre_prepare")
        if not recovered.recovered:
            return RuntimePrepareResult(
                ready=False,
                metadata={"reason_code": recovered.reason_code},
            )
        journal_reason = provider_step_admission_reason(
            self.loop.tool_ledger.store,
            session_id=persisted_session.session_id,
        )
        if journal_reason is not None:
            return RuntimePrepareResult(
                ready=False,
                metadata={"reason_code": journal_reason},
            )
        provider_state = self.loop.tool_ledger.store.get_provider_state(
            persisted_session.session_id
        )
        if provider_state.provider_private_envelope is not None:
            try:
                self.loop.private_state_service.read_state(
                    session_id=context.session.session_id,
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    codec_id=codec.codec_id,
                    codec_version=codec.codec_version,
                    schema_version=codec.schema_version,
                )
            except ProviderPrivateStateError as error:
                return RuntimePrepareResult(
                    ready=False,
                    metadata={"reason_code": public_provider_private_reason(error)},
                )
        return RuntimePrepareResult(ready=True, metadata={"transport": "hosted-api"})

    async def execute(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]:
        store = self.loop.tool_ledger.store
        persisted_session = store.get_session(context.session.session_id)
        if persisted_session.status == "recovery_required":
            raise HostedAgenticLoopError("runtime_session_recovery_required")
        persisted_context = replace(
            context,
            session=persisted_session,
            provider_state=store.get_provider_state(persisted_session.session_id),
        )
        journal_reason = provider_step_admission_reason(
            store,
            session_id=persisted_session.session_id,
            turn_id=context.correlation_id,
            allow_same_turn_pairing=True,
        )
        if journal_reason == "provider_state_ambiguous":
            recovered = self.loop.recover_session(
                persisted_context,
                trigger="pre_execute",
            )
            if not recovered.recovered:
                raise HostedAgenticLoopError(recovered.reason_code)
            journal_reason = provider_step_admission_reason(
                store,
                session_id=persisted_session.session_id,
                turn_id=context.correlation_id,
                allow_same_turn_pairing=True,
            )
        if journal_reason is not None:
            runtime = self.loop.provider_runtimes.resolve(context.binding)
            self.loop.recovery.contain_terminal_pairing(
                session=persisted_session,
                binding=context.binding,
                provider_runtime=runtime,
                turn_id=context.correlation_id,
                trigger="pre_execute_cross_turn_pairing",
                terminal_reason_code=journal_reason,
            )
            raise HostedAgenticLoopError(journal_reason)
        cancellation = Event()
        with self._lock:
            if context.correlation_id in self._cancellations:
                raise RuntimeError("hosted_turn_already_active")
            self._cancellations[context.correlation_id] = (
                context.session.session_id,
                cancellation,
            )
        try:
            async for event in self.loop.execute(
                persisted_context,
                cancellation=cancellation,
            ):
                yield event
        finally:
            with self._lock:
                self._cancellations.pop(context.correlation_id, None)

    async def cancel(self, context: RuntimeCancelContext) -> RuntimeCancelResult:
        with self._lock:
            active = self._cancellations.get(context.correlation_id)
        if active is None or active[0] != context.session.session_id:
            return RuntimeCancelResult(cancelled=False, reason_code="runtime_turn_not_active")
        active[1].set()
        return RuntimeCancelResult(cancelled=True, reason_code="cancelled")

    async def recover(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult:
        try:
            self.loop.provider_runtimes.resolve(context.binding)
        except HostedAgenticLoopError as error:
            return RuntimeRecoveryResult(False, error.reason_code)
        result = self.loop.recover_session(context, trigger=context.trigger)
        return RuntimeRecoveryResult(result.recovered, result.reason_code)

    def recover_now(self, *, session, trigger: str):
        """Synchronous hook for startup/admission paths that do not own an event loop."""
        binding = session.execution_binding
        if binding is None:
            raise HostedAgenticLoopError("runtime_execution_binding_missing")
        return self.loop.recover_session(
            SimpleNamespace(
                session=session,
                binding=binding,
                provider_state=self.loop.tool_ledger.store.get_provider_state(
                    session.session_id
                ),
            ),
            trigger=trigger,
        )

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        cancelled = 0
        with self._lock:
            for session_id, cancellation in self._cancellations.values():
                if session_id == context.session.session_id:
                    cancellation.set()
                    cancelled += 1
        terminated = (
            self.process_registry.terminate_session(context.session.session_id)
            if self.process_registry is not None
            else 0
        )
        return RuntimeCloseResult(
            closed=True,
            terminated_processes=cancelled + terminated,
        )

    async def health(self, context: RuntimeHealthContext) -> RuntimeHealth:
        return RuntimeHealth(status="healthy")


def build_hosted_turn_status_callback(store):
    """Persist confirmation pause/resume from the authoritative invocation identity."""

    def update(status: str, invocation_id: str) -> None:
        invocation = store.get_tool_invocation(invocation_id)
        turn = store.get_turn(invocation.turn_id)
        if (
            invocation.session_id != turn.session_id
            or invocation.workspace_id != turn.workspace_id
        ):
            raise RuntimeError("hosted_tool_turn_identity_mismatch")
        if status == "waiting_for_tool_confirmation":
            if turn.status == "active":
                transition_runtime_turn(
                    store,
                    turn_id=turn.turn_id,
                    target_status="waiting_for_tool_confirmation",
                )
            elif turn.status != "waiting_for_tool_confirmation":
                raise RuntimeError("hosted_tool_turn_not_active")
            return
        if status == "active":
            if turn.status == "waiting_for_tool_confirmation":
                transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active")
            # A concurrent cancel/expiry may already have made the turn terminal.
            # Never resurrect it merely to finish confirmation cleanup.
            return
        raise ValueError("Unsupported hosted turn status callback state.")

    return update
