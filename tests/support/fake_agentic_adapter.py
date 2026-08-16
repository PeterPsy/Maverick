"""Deterministic non-process agentic adapter used by contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

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


class FakeLegacyLocalRuntimeCapabilities:
    """Capabilities used by legacy launch-spec tests behind the async bridge."""

    local_process_lifecycle = object()
    synchronizes_runtime_skills = True

    def prewarm_runtime(self, session, launch_spec):
        from core.providers.codex_app_server import prewarm_codex_app_server_runtime

        return prewarm_codex_app_server_runtime(session=session, launch_spec=launch_spec)


class FakeHostedAgenticAdapter:
    """Exercise the async contract without commands, pids, or launch specs."""

    runtime_engine_id = "fake-hosted-agentic"
    adapter_id = "fake-hosted-agentic-adapter"
    adapter_version = "1"
    local_process_lifecycle = None

    def __init__(self, *, output_text: str = "fake hosted answer") -> None:
        self.output_text = output_text
        self.cancelled = False
        self.closed = False
        self.recovered = False
        self.prepare_calls = 0
        self.execute_calls = 0

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth:
        return RuntimeHealth(status="healthy")

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        if context.local_launch_spec is not None:
            raise AssertionError("Fake hosted adapters must not receive a launch spec.")
        self.prepare_calls += 1
        return RuntimePrepareResult(ready=True, metadata={"transport": "fake-hosted"})

    async def execute(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]:
        self.execute_calls += 1
        events = (
            ("provider.accepted", {"request_id": f"request:{context.correlation_id}"}),
            ("provider.state.update", {"continuation_id": "fake-continuation"}),
            ("runtime.output.delta", {"text": self.output_text[:5]}),
            ("runtime.output.delta", {"text": self.output_text[5:]}),
            ("runtime.output.final", {"text": self.output_text}),
            ("provider.execution.completed", {"output_text": self.output_text, "exit_code": 0}),
        )
        for ordinal, (event_type, payload) in enumerate(events, start=1):
            yield RuntimeProviderEvent(
                event_type=event_type,
                correlation_id=context.correlation_id,
                ordinal=ordinal,
                schema_version="1",
                payload=payload,
            )

    async def cancel(self, context: RuntimeCancelContext) -> RuntimeCancelResult:
        self.cancelled = True
        return RuntimeCancelResult(cancelled=True, reason_code="cancelled")

    async def recover(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult:
        self.recovered = True
        return RuntimeRecoveryResult(recovered=True, reason_code="recovered")

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        self.closed = True
        return RuntimeCloseResult(closed=True)

    async def health(self, context: RuntimeHealthContext) -> RuntimeHealth:
        return RuntimeHealth(status="healthy")
