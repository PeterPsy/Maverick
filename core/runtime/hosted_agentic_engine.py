"""Async runtime-engine adapter backed by the shared hosted agentic loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from threading import Event, RLock

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
from core.runtime.provider_private_state import ProviderPrivateStateError
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
    ) -> None:
        self.runtime_engine_id = runtime_engine_id
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.loop = loop
        self._cancellations: dict[str, tuple[str, Event]] = {}
        self._lock = RLock()

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth:
        binding = context.binding
        if (
            binding.runtime_engine_id != self.runtime_engine_id
            or binding.adapter_id != self.adapter_id
            or binding.adapter_version != self.adapter_version
        ):
            return RuntimeHealth(status="unavailable", reason_codes=("adapter_version_mismatch",))
        return RuntimeHealth(status="healthy")

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        if context.local_launch_spec is not None:
            return RuntimePrepareResult(
                ready=False,
                metadata={"reason_code": "hosted_launch_spec_forbidden"},
            )
        if context.provider_state.provider_private_envelope is not None:
            codec = self.loop.private_codec
            try:
                self.loop.private_state_service.read_state(
                    session_id=context.session.session_id,
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    codec_id=codec.codec_id,
                    codec_version=codec.codec_version,
                    schema_version=codec.schema_version,
                )
            except ProviderPrivateStateError:
                return RuntimePrepareResult(
                    ready=False,
                    metadata={"reason_code": "provider_private_state_invalid"},
                )
        return RuntimePrepareResult(ready=True, metadata={"transport": "hosted-api"})

    async def execute(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]:
        cancellation = Event()
        with self._lock:
            if context.correlation_id in self._cancellations:
                raise RuntimeError("hosted_turn_already_active")
            self._cancellations[context.correlation_id] = (
                context.session.session_id,
                cancellation,
            )
        try:
            async for event in self.loop.execute(context, cancellation=cancellation):
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
        codec = self.loop.private_codec
        if context.provider_state.provider_private_envelope is not None:
            try:
                self.loop.private_state_service.read_state(
                    session_id=context.session.session_id,
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    codec_id=codec.codec_id,
                    codec_version=codec.codec_version,
                    schema_version=codec.schema_version,
                    purpose="recovery",
                )
            except ProviderPrivateStateError:
                return RuntimeRecoveryResult(False, "provider_private_state_invalid")
        uncertain = False
        ledger = self.loop.tool_orchestrator.ledger
        for invocation in ledger.store.list_tool_invocations(
            session_id=context.session.session_id
        ):
            if invocation.state != "executing":
                continue
            recovered = ledger.recover_executing(invocation, safe_to_retry=False)
            uncertain = uncertain or recovered.state == "execution_unknown"
        if uncertain:
            return RuntimeRecoveryResult(False, "session_recovery_required")
        return RuntimeRecoveryResult(True, "recovered")

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        cancelled = 0
        with self._lock:
            for session_id, cancellation in self._cancellations.values():
                if session_id == context.session.session_id:
                    cancellation.set()
                    cancelled += 1
        return RuntimeCloseResult(closed=True, terminated_processes=cancelled)

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
