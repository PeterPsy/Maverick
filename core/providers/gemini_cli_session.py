"""Loop-confined Gemini ACP session lifecycle."""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass, field

from core.providers.agentic_adapter import (
    LocalLaunchContext, RuntimeCancelResult, RuntimeCloseResult,
    RuntimePrepareContext, RuntimePrepareResult, RuntimeProviderEvent, RuntimeRecoveryResult,
)
from core.providers.gemini_cli_event_projection import project_acp_update
from core.providers.models import RuntimeSteerResult
from core.providers.native_acp_transport import NativeAcpConnection, NativeAcpError


@dataclass
class _Turn:
    future: asyncio.Future
    correlation_id: str
    generation: int
    answer: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class GeminiAcpSession:
    def __init__(self, build_launch_spec, *, provider_thread_id=None):
        self.build_launch_spec = build_launch_spec
        self.provider_thread_id = provider_thread_id
        self.client = None
        self.connecting = None
        self._turn = None
        self._executing = False
        self._prepare_lock = asyncio.Lock()
        self._generation = 0

    async def prepare(self, context):
        async with self._prepare_lock:
            return await self._connect(context)

    async def _connect(self, context):
        if self.client is not None:
            client = self.client
            if client.process.returncode is None and not client._reader.done():
                return RuntimePrepareResult(ready=True, prepared_handle=client)
            await self.close(context)
        spec = context.local_launch_spec or await self.build_launch_spec(LocalLaunchContext(
            session=context.session, binding=context.binding,
        ))
        generation = self._generation
        client = await NativeAcpConnection.start(spec)
        try:
            if self._generation != generation:
                raise NativeAcpError("native_acp_start_cancelled")
            self.connecting = client
            initialized = await client.request("initialize", {
                "protocolVersion": 1, "clientInfo": {"name": "maverick", "version": "1"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            })
            if not isinstance(initialized, dict) or initialized.get("protocolVersion") != 1:
                raise NativeAcpError("native_acp_protocol_mismatch")
            params = {"cwd": context.session.workdir, "mcpServers": []}
            previous = getattr(context.provider_state, "provider_thread_id", None) or self.provider_thread_id
            if previous:
                if not initialized.get("agentCapabilities", {}).get("loadSession"):
                    raise NativeAcpError("native_acp_resume_unsupported")
                client.session_id = previous
                await client.request("session/load", {**params, "sessionId": previous})
            else:
                created = await client.request("session/new", params)
                client.session_id = created.get("sessionId") if isinstance(created, dict) else None
                if not isinstance(client.session_id, str) or not client.session_id:
                    raise NativeAcpError("native_acp_session_invalid")
            while not client.updates.empty():
                client.updates.get_nowait()  # Load replay is not a new turn's output.
            if self._generation != generation:
                raise NativeAcpError("native_acp_start_cancelled")
            self.client = client
            self.provider_thread_id = client.session_id
            return RuntimePrepareResult(ready=True, prepared_handle=client, provider_state_updates={
                "provider_thread_id": client.session_id, "continuation_id": client.session_id,
            })
        except BaseException:
            await client.close()
            raise
        finally:
            self.connecting = None

    async def execute(self, context):
        if self._executing:
            raise NativeAcpError("native_acp_turn_already_active")
        self._executing = True
        try:
            async with asyncio.timeout(context.timeout_seconds or 120):
                async with aclosing(self._execute_turn(context)) as events:
                    async for event in events:
                        yield event
        except BaseException:
            await self.close(context)
            raise
        finally:
            self._executing = False

    async def _execute_turn(self, context):
        if self.client is None:
            await self.prepare(RuntimePrepareContext(
                session=context.session, binding=context.binding, provider_state=context.provider_state,
            ))
        client = self.client
        client.update_generation += 1
        future = await client.begin("session/prompt", {
            "sessionId": client.session_id,
            "prompt": [{"type": "text", "text": context.input_text}],
        })
        turn = _Turn(future, context.correlation_id, client.update_generation)
        self._turn = turn
        ordinal = 1
        accepted = False
        queued = None
        try:
            yield RuntimeProviderEvent("provider.request.sent", context.correlation_id, ordinal, "1",
                                       {"provider_thread_id": client.session_id})
            ordinal += 1
            while True:
                async with turn.lock:
                    if turn.future.done() and client.updates.empty():
                        result = turn.future.result()
                        if not isinstance(result, dict) or result.get("stopReason") != "end_turn":
                            raise NativeAcpError("native_acp_turn_not_completed")
                        answer = "".join(turn.answer)
                        if not answer.strip():
                            raise NativeAcpError("agent_final_output_empty")
                        yield RuntimeProviderEvent("runtime.output.final", context.correlation_id, ordinal, "1", {"text": answer})
                        yield RuntimeProviderEvent("provider.execution.completed", context.correlation_id, ordinal + 1, "1",
                                                   {"output_text": answer, "exit_code": 0})
                        break
                queued = asyncio.create_task(client.updates.get())
                awaited = turn.future
                done, _pending = await asyncio.wait((queued, awaited), return_when=asyncio.FIRST_COMPLETED)
                if queued not in done:
                    queued.cancel()
                    await asyncio.gather(queued, return_exceptions=True)
                    continue
                generation, update = queued.result()
                if generation != turn.generation:
                    continue
                if not accepted:
                    yield RuntimeProviderEvent("provider.accepted", context.correlation_id, ordinal, "1",
                                               {"provider_thread_id": client.session_id})
                    ordinal += 1
                    accepted = True
                if generation != turn.generation:
                    continue  # Steering may occur while the accepted event is yielded.
                event_type, payload = project_acp_update(update, context.session.workspace_root)
                if event_type == "runtime.output.delta":
                    turn.answer.append(payload["text"])
                yield RuntimeProviderEvent(event_type, context.correlation_id, ordinal, "1", payload)
                ordinal += 1
        finally:
            if queued is not None and not queued.done():
                queued.cancel()
                await asyncio.gather(queued, return_exceptions=True)
            self._turn = None

    async def steer(self, context):
        turn = self._turn
        if turn is None:
            return RuntimeSteerResult(status="not_active")
        if context.expected_provider_turn_id not in {None, turn.correlation_id}:
            return RuntimeSteerResult(status="failed", reason="native_acp_stale_turn")
        async with turn.lock:
            if self._turn is not turn or turn.future.done():
                return RuntimeSteerResult(status="not_active")
            client = self.client
            # ACP updates have no prompt id. Establish the cancellation response
            # boundary before replacement, and fence already-dequeued old chunks.
            try:
                await client.notify("session/cancel", {"sessionId": client.session_id})
                await asyncio.wait_for(asyncio.shield(turn.future), 3)
            except (OSError, TimeoutError, NativeAcpError):
                await client.close()
                self.client = None
                return RuntimeSteerResult(status="failed", reason="native_acp_steer_cancel_failed")
            while not client.updates.empty():
                client.updates.get_nowait()
            client.update_generation += 1
            turn.generation = client.update_generation
            turn.future = await client.begin("session/prompt", {
                "sessionId": client.session_id, "prompt": [{"type": "text", "text": context.input_text}],
            })
            turn.answer.clear()
            return RuntimeSteerResult(status="steered", provider_turn_id=turn.correlation_id)

    async def cancel(self, context):
        client = self.client or self.connecting
        active = client is not None or self._prepare_lock.locked()
        try:
            if client is not None and client.session_id is not None:
                await client.notify("session/cancel", {"sessionId": client.session_id})
        except (OSError, TimeoutError):
            pass  # A broken or blocked protocol cannot prevent hard cleanup.
        finally:
            await self.close(context)
        return RuntimeCancelResult(cancelled=active, reason_code="cancelled" if active else "not_active")

    async def recover(self, context):
        await self.close(context)
        prepared = await self.prepare(RuntimePrepareContext(
            session=context.session, binding=context.binding, provider_state=context.provider_state,
        ))
        return RuntimeRecoveryResult(recovered=prepared.ready, reason_code="recovered",
                                     provider_state_updates=prepared.provider_state_updates)

    async def close(self, context):
        self._generation += 1
        client = self.client or self.connecting
        self.client = self.connecting = None
        if client is not None:
            await client.close()
        return RuntimeCloseResult(closed=True, terminated_processes=int(client is not None))


__all__ = ["GeminiAcpSession"]
