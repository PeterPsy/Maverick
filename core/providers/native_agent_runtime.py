"""Structured lifecycle facade for certified native-agent runtime adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

from core.providers.agentic_adapter import (
    AgenticRuntimeEngineAdapter,
    LocalLaunchContext,
    LocalPrewarmContext,
    LocalPrewarmResult,
    LocalProcessHandle,
    LocalProcessRuntimeLifecycle,
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
from core.providers.models import RuntimeBackendLaunchSpec, RuntimeSteerResult
from core.providers.native_agent_contract import (
    NativeAgentInstallation,
    NativeRuntimeStatus,
)
from core.providers.provider_registry import RuntimeBackendAdapter
from core.providers.native_model_revision import require_native_model_revision_transport
from core.providers.errors import CapabilityCertificateError


@dataclass(frozen=True)
class NativeSteerContext:
    """Structured same-turn input request for a connected native runtime."""

    session_id: str
    input_text: str
    client_message_id: str | None = None
    expected_provider_turn_id: str | None = None
    invoked_skills: tuple[object, ...] = ()
    skill_activation_mode: str = "implicit"


class NativeAgentRuntimeController:
    """Expose one native runtime through a complete provider-neutral lifecycle."""

    def __init__(
        self,
        *,
        installation: NativeAgentInstallation,
        engine_adapter: AgenticRuntimeEngineAdapter,
        legacy_adapter: RuntimeBackendAdapter | None = None,
    ) -> None:
        self.installation = installation
        self.engine_adapter = engine_adapter
        self.legacy_adapter = legacy_adapter
        self.runtime_engine_id = installation.manifest.runtime_engine_id
        self.adapter_id = installation.manifest.adapter_id
        self.adapter_version = installation.manifest.adapter_version
        self.local_process_lifecycle = (
            self
            if engine_adapter.local_process_lifecycle is not None
            else None
        )

    def discover(self) -> tuple[str, str | None]:
        return self.installation.inspector.discover()

    def version(self) -> str | None:
        return self.installation.inspector.version()

    def installation_health(self) -> tuple[str, tuple[str, ...]]:
        return self.installation.inspector.health()

    def update_status(self) -> tuple[str, str | None]:
        return self.installation.inspector.update_status()

    def status(self) -> NativeRuntimeStatus:
        return self.installation.inspector.inspect()

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth:
        self._validate_execution_identity(context.binding)
        return await self.engine_adapter.validate(context)

    async def launch(self, context: LocalLaunchContext) -> RuntimeBackendLaunchSpec:
        return await self.build_launch_spec(context)

    async def connect(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        self._validate_execution_identity(context.binding)
        return await self.engine_adapter.prepare(context)

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        return await self.connect(context)

    async def resume(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult:
        return await self.recover(context)

    def start_turn(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]:
        self._validate_execution_identity(context.binding)
        return self.engine_adapter.execute(context)

    async def execute(
        self,
        context: RuntimeTurnContext,
    ) -> AsyncIterator[RuntimeProviderEvent]:
        final_count = 0
        async for event in self.start_turn(context):
            if event.event_type == "runtime.output.final":
                final_count += 1
                self.final_output((event,))
                if final_count > 1:
                    raise RuntimeError("native_agent_final_output_invalid")
            yield event

    async def stream_events(
        self,
        context: RuntimeTurnContext,
    ) -> AsyncIterator[RuntimeProviderEvent]:
        async for event in self.start_turn(context):
            yield event

    @staticmethod
    def final_output(events: Iterable[RuntimeProviderEvent]) -> RuntimeProviderEvent:
        """Return the single structured final output or fail closed."""
        finals = [event for event in events if event.event_type == "runtime.output.final"]
        if len(finals) != 1:
            raise RuntimeError("native_agent_final_output_invalid")
        text = finals[0].payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("agent_final_output_empty")
        return finals[0]

    async def steer(self, context: NativeSteerContext) -> RuntimeSteerResult:
        if self.legacy_adapter is None:
            steer = getattr(self.engine_adapter, "steer", None)
            if callable(steer):
                return await steer(context)
            return RuntimeSteerResult(status="not_supported", reason="native_steer_unavailable")
        return await asyncio.to_thread(
            self.legacy_adapter.steer_turn,
            context.session_id,
            input_text=context.input_text,
            client_message_id=context.client_message_id,
            expected_provider_turn_id=context.expected_provider_turn_id,
            invoked_skills=list(context.invoked_skills) or None,
            skill_activation_mode=context.skill_activation_mode,
        )

    async def interrupt(self, context: RuntimeCancelContext) -> RuntimeCancelResult:
        return await self.engine_adapter.cancel(context)

    async def cancel(self, context: RuntimeCancelContext) -> RuntimeCancelResult:
        return await self.interrupt(context)

    async def recover(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult:
        self._validate_execution_identity(context.binding)
        lifecycle = self.engine_adapter.local_process_lifecycle
        if lifecycle is None:
            return await self.engine_adapter.recover(context)
        try:
            launch_spec = await self.build_launch_spec(
                LocalLaunchContext(
                    session=context.session,
                    binding=context.binding,
                )
            )
            prewarm = await lifecycle.prewarm(
                LocalPrewarmContext(
                    session=context.session,
                    binding=context.binding,
                    launch_spec=launch_spec,
                )
            )
        except Exception:
            return RuntimeRecoveryResult(
                recovered=False,
                reason_code="native_recovery_failed",
            )
        return RuntimeRecoveryResult(
            recovered=prewarm.ready,
            reason_code="recovered" if prewarm.ready else "not_recovered",
            provider_state_updates=prewarm.provider_state_updates,
        )

    async def cleanup(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        return await self.engine_adapter.close(context)

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        return await self.cleanup(context)

    async def health(self, context: RuntimeHealthContext) -> RuntimeHealth:
        return await self.engine_adapter.health(context)

    async def build_launch_spec(
        self,
        context: LocalLaunchContext,
    ) -> RuntimeBackendLaunchSpec:
        self._validate_execution_identity(context.binding)
        if self.engine_adapter.local_process_lifecycle is None:
            return await self.engine_adapter.build_launch_spec(context)
        lifecycle = self._local_lifecycle()
        return await lifecycle.build_launch_spec(context)

    async def start_process(
        self,
        spec: RuntimeBackendLaunchSpec,
    ) -> LocalProcessHandle:
        return await self._local_lifecycle().start_process(spec)

    async def interrupt_process(self, handle: LocalProcessHandle) -> None:
        await self._local_lifecycle().interrupt_process(handle)

    async def close_process(self, handle: LocalProcessHandle) -> None:
        await self._local_lifecycle().close_process(handle)

    async def prewarm(self, context: LocalPrewarmContext) -> LocalPrewarmResult:
        self._validate_execution_identity(context.binding)
        return await self._local_lifecycle().prewarm(context)

    def _validate_execution_identity(self, binding) -> None:
        require_native_model_revision_transport(binding)
        approved = self.installation.runtime_artifact
        if approved is not None and self.installation.inspector.artifact() != approved:
            raise CapabilityCertificateError("native_runtime_artifact_mismatch")

    def _local_lifecycle(self) -> LocalProcessRuntimeLifecycle:
        lifecycle = self.engine_adapter.local_process_lifecycle
        if lifecycle is None:
            raise RuntimeError("native_agent_launch_not_supported")
        return lifecycle
