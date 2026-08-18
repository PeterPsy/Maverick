"""Async bridge for existing process-oriented runtime backend adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import os
import subprocess

from core.providers.agentic_adapter import (
    AgenticRuntimeEngineAdapter,
    LocalLaunchContext,
    LocalPrewarmContext,
    LocalPrewarmResult,
    LocalProcessHandle,
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
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.provider_registry import RuntimeBackendAdapter
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.output_compaction import ToolOutputCompactionContext, compact_tool_call_event


class LegacyRuntimeBackendAgenticBridge(AgenticRuntimeEngineAdapter):
    """Preserve current adapters behind the provider-neutral async contract."""

    adapter_id = "legacy-runtime-backend-bridge"
    adapter_version = "1"

    def __init__(self, adapter: RuntimeBackendAdapter) -> None:
        self.legacy_adapter = adapter
        self.runtime_engine_id = adapter.provider_definition().provider_id
        self.adapter_id = str(getattr(adapter, "adapter_id", self.adapter_id))
        self.adapter_version = str(getattr(adapter, "adapter_version", self.adapter_version))
        self.local_process_lifecycle = self

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth:
        return await self.health(RuntimeHealthContext(binding=context.binding))

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult:
        launch_spec = context.local_launch_spec
        if launch_spec is None:
            launch_spec = await self.build_launch_spec(
                LocalLaunchContext(session=context.session, binding=context.binding)
            )
        prewarm = getattr(self.legacy_adapter, "prewarm_runtime", None)
        if not callable(prewarm):
            return RuntimePrepareResult(ready=True, prepared_handle=launch_spec)
        provider_thread_id = await asyncio.to_thread(prewarm, context.session, launch_spec)
        updates = {"provider_thread_id": provider_thread_id, "continuation_id": provider_thread_id} if provider_thread_id else {}
        return RuntimePrepareResult(
            ready=bool(provider_thread_id),
            provider_state_updates=updates,
            prepared_handle=launch_spec,
        )

    async def execute(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]:
        launch_spec = context.prepared_handle
        if not isinstance(launch_spec, RuntimeBackendLaunchSpec):
            launch_spec = await self.build_launch_spec(
                LocalLaunchContext(session=context.session, binding=context.binding)
            )
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[RuntimeProviderEvent | None] = asyncio.Queue()
        ordinal = 0
        compaction_context = ToolOutputCompactionContext(
            session_id=context.session.session_id,
            turn_id=context.correlation_id,
        )

        def publish(event_type: str, payload: dict[str, object]) -> None:
            nonlocal ordinal
            public_payload = dict(payload)
            if event_type.startswith("runtime.tool_call."):
                compacted_event = compact_tool_call_event(
                    RuntimeExecutionEvent(event_type=event_type, payload=public_payload),
                    context=compaction_context,
                )
                public_payload = compacted_event.payload
            ordinal += 1
            event = RuntimeProviderEvent(
                event_type=event_type,
                correlation_id=context.correlation_id,
                ordinal=ordinal,
                schema_version="1",
                payload=public_payload,
            )
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run() -> None:
            try:
                result = self.legacy_adapter.execute_turn(
                    session=context.session,
                    launch_spec=launch_spec,
                    input_text=context.input_text,
                    invoked_skills=list(context.invoked_skills) or None,
                    event_sink=lambda event: publish(event.event_type, event.payload),
                    timeout_seconds=context.timeout_seconds,
                    on_provider_thread_id=lambda value: publish(
                        "provider.state.update",
                        {"provider_thread_id": value, "continuation_id": value},
                    ),
                    on_provider_startup_event=lambda phase, metadata: publish(
                        "provider.lifecycle",
                        {"phase": phase, **metadata},
                    ),
                    on_provider_turn_start_sent=lambda metadata: publish("provider.request.sent", metadata),
                    on_provider_accepted=lambda metadata: publish("provider.accepted", metadata),
                )
                publish(
                    "provider.execution.completed",
                    {"output_text": result.output_text, "exit_code": result.exit_code},
                )
            except Exception as error:
                publish(
                    "runtime.error",
                    {"reason_code": "legacy_adapter_execution_failed", "error_type": type(error).__name__},
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
            await worker
        except asyncio.CancelledError:
            await self.cancel(
                RuntimeCancelContext(
                    session=context.session,
                    binding=context.binding,
                    provider_state=context.provider_state,
                    correlation_id=context.correlation_id,
                )
            )
            raise

    async def cancel(self, context: RuntimeCancelContext) -> RuntimeCancelResult:
        cancelled = await asyncio.to_thread(self.legacy_adapter.interrupt_turn, context.session.session_id)
        return RuntimeCancelResult(cancelled=bool(cancelled), reason_code="cancelled" if cancelled else "not_active")

    async def recover(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult:
        recover = getattr(self.legacy_adapter, "recover_runtime", None)
        if not callable(recover):
            return RuntimeRecoveryResult(recovered=False, reason_code="legacy_recovery_unavailable")
        recovered = await asyncio.to_thread(recover, context.session.session_id)
        return RuntimeRecoveryResult(recovered=bool(recovered), reason_code="recovered" if recovered else "not_recovered")

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult:
        terminated = await asyncio.to_thread(self.legacy_adapter.close_runtime, context.session.session_id)
        count = terminated if isinstance(terminated, int) else 0
        return RuntimeCloseResult(closed=True, terminated_processes=count)

    async def health(self, context: RuntimeHealthContext) -> RuntimeHealth:
        try:
            await asyncio.to_thread(self.legacy_adapter.validate_backend)
        except Exception as error:
            return RuntimeHealth(status="unavailable", reason_codes=(type(error).__name__,))
        return RuntimeHealth(status="healthy")

    async def build_launch_spec(self, context: LocalLaunchContext) -> RuntimeBackendLaunchSpec:
        return await asyncio.to_thread(
            self.legacy_adapter.build_launch_spec,
            context.session,
            secret_env=context.secret_env,
            credential_binding_id=context.binding.credential_binding_id,
            model_id=context.binding.model_id,
            model_reasoning_effort=context.binding.reasoning_effort,
        )

    async def start_process(self, spec: RuntimeBackendLaunchSpec) -> LocalProcessHandle:
        env = {**os.environ, **spec.env_overrides}
        process = await asyncio.to_thread(
            subprocess.Popen,
            spec.command,
            cwd=spec.working_directory,
            env=env,
        )
        return LocalProcessHandle(process_id=str(process.pid), pid=process.pid, opaque_handle=process)

    async def interrupt_process(self, handle: LocalProcessHandle) -> None:
        process = handle.opaque_handle
        if isinstance(process, subprocess.Popen):
            await asyncio.to_thread(process.terminate)

    async def close_process(self, handle: LocalProcessHandle) -> None:
        process = handle.opaque_handle
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            await asyncio.to_thread(process.kill)

    async def prewarm(self, context: LocalPrewarmContext) -> LocalPrewarmResult:
        prewarm = getattr(self.legacy_adapter, "prewarm_runtime", None)
        if not callable(prewarm):
            return LocalPrewarmResult(ready=True)
        provider_thread_id = await asyncio.to_thread(prewarm, context.session, context.launch_spec)
        updates = {"provider_thread_id": provider_thread_id, "continuation_id": provider_thread_id} if provider_thread_id else {}
        return LocalPrewarmResult(ready=bool(provider_thread_id), provider_state_updates=updates)
