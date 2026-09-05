"""Executable Gemini CLI ACP lifecycle; candidate, not release authority."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from core.providers.agentic_adapter import (
    LocalLaunchContext, RuntimeCancelResult, RuntimeCloseResult, RuntimeHealth,
    RuntimePrepareContext, RuntimePrepareResult, RuntimeProviderEvent, RuntimeRecoveryResult,
)
from core.providers.gemini_cli_sandbox import gemini_acp_launch_spec
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


class GeminiCliNativeAdapter:
    runtime_engine_id = "gemini-cli"
    adapter_id = "gemini-cli-acp"
    adapter_version = "1"
    local_process_lifecycle = None  # ACP owns its process and protocol connection.

    def __init__(self, *, command="gemini", dependency_roots=None):
        self.command = command
        self.dependency_roots = tuple(dependency_roots) if dependency_roots is not None else tuple(
            Path(path) for path in ("/usr/bin", "/usr/lib", "/lib", "/lib64", "/usr/local/lib/node_modules")
        )
        self._clients = {}
        self._session_ids = {}
        self._turns = {}
        self._executing = set()
        self._prepare_locks = {}
        self._connecting = {}
        self._generation = {}

    async def build_launch_spec(self, context):
        return gemini_acp_launch_spec(context, command=self.command, dependency_roots=self.dependency_roots)

    async def validate(self, context):
        return await self.health(context)

    async def health(self, context):
        from core.providers.native_agent_builtins import CommandNativeRuntimeInspector

        status = await asyncio.to_thread(CommandNativeRuntimeInspector(self.command).inspect)
        return RuntimeHealth(status=status.health, reason_codes=status.reason_codes)

    async def prepare(self, context):
        lock = self._prepare_locks.setdefault(context.session.session_id, asyncio.Lock())
        async with lock:
            return await self._connect(context)

    async def _connect(self, context):
        sid = context.session.session_id
        if sid in self._clients:
            client = self._clients[sid]
            if client.process.returncode is None and not client._reader.done():
                return RuntimePrepareResult(ready=True, prepared_handle=client)
            await self.close(context)
        spec = context.local_launch_spec or await self.build_launch_spec(LocalLaunchContext(
            session=context.session, binding=context.binding,
        ))
        generation = self._generation.get(sid, 0)
        client = await NativeAcpConnection.start(spec)
        try:
            if self._generation.get(sid, 0) != generation:
                raise NativeAcpError("native_acp_start_cancelled")
            self._connecting[sid] = client
            initialized = await client.request("initialize", {
                "protocolVersion": 1, "clientInfo": {"name": "maverick", "version": "1"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            })
            if not isinstance(initialized, dict) or initialized.get("protocolVersion") != 1:
                raise NativeAcpError("native_acp_protocol_mismatch")
            params = {"cwd": context.session.workdir, "mcpServers": []}
            previous = getattr(context.provider_state, "provider_thread_id", None) or self._session_ids.get(sid)
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
            if self._generation.get(sid, 0) != generation:
                raise NativeAcpError("native_acp_start_cancelled")
            self._clients[sid] = client
            self._session_ids[sid] = client.session_id
            return RuntimePrepareResult(ready=True, prepared_handle=client, provider_state_updates={
                "provider_thread_id": client.session_id, "continuation_id": client.session_id,
            })
        except BaseException:
            await client.close()
            raise
        finally:
            self._connecting.pop(sid, None)

    async def execute(self, context):
        sid = context.session.session_id
        if sid in self._executing:
            raise NativeAcpError("native_acp_turn_already_active")
        self._executing.add(sid)
        try:
            async with asyncio.timeout(context.timeout_seconds or 120):
                async for event in self._execute_turn(context):
                    yield event
        except BaseException:
            await self.close(context)
            raise
        finally:
            self._executing.discard(sid)

    async def _execute_turn(self, context):
        sid = context.session.session_id
        if sid not in self._clients:
            await self.prepare(RuntimePrepareContext(
                session=context.session, binding=context.binding, provider_state=context.provider_state,
            ))
        client = self._clients[sid]
        client.update_generation += 1
        future = await client.begin("session/prompt", {
            "sessionId": client.session_id,
            "prompt": [{"type": "text", "text": context.input_text}],
        })
        turn = _Turn(future, context.correlation_id, client.update_generation)
        self._turns[sid] = turn
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
            self._turns.pop(sid, None)

    async def steer(self, context):
        turn = self._turns.get(context.session_id)
        if turn is None:
            return RuntimeSteerResult(status="not_active")
        if context.expected_provider_turn_id not in {None, turn.correlation_id}:
            return RuntimeSteerResult(status="failed", reason="native_acp_stale_turn")
        async with turn.lock:
            if self._turns.get(context.session_id) is not turn or turn.future.done():
                return RuntimeSteerResult(status="not_active")
            client = self._clients[context.session_id]
            # ACP updates have no prompt id. Establish the cancellation response
            # boundary before replacement, and fence already-dequeued old chunks.
            try:
                await client.notify("session/cancel", {"sessionId": client.session_id})
                await asyncio.wait_for(asyncio.shield(turn.future), 3)
            except (OSError, TimeoutError, NativeAcpError):
                await client.close()
                self._clients.pop(context.session_id, None)
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
        sid = context.session.session_id
        client = self._clients.get(sid) or self._connecting.get(sid)
        preparing = self._prepare_locks.get(sid)
        active = client is not None or (preparing is not None and preparing.locked())
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
        sid = context.session.session_id
        self._generation[sid] = self._generation.get(sid, 0) + 1
        client = self._clients.pop(sid, None) or self._connecting.pop(sid, None)
        if client is not None:
            await client.close()
        return RuntimeCloseResult(closed=True, terminated_processes=int(client is not None))


__all__ = ["GeminiCliNativeAdapter"]
