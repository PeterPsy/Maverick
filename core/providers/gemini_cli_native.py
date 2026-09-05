"""Gemini's disabled Native candidate, with session-owned ACP loop lifetimes."""

import asyncio
from contextlib import aclosing
from pathlib import Path
from threading import Lock

from core.providers.agentic_adapter import RuntimeCancelResult, RuntimeCloseResult, RuntimeHealth
from core.providers.gemini_cli_sandbox import gemini_acp_launch_spec
from core.providers.gemini_cli_session import GeminiAcpSession
from core.providers.models import RuntimeSteerResult
from core.providers.native_acp_runtime import NativeAcpRuntime
from core.providers.native_acp_transport import NativeAcpError


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
        self._owners = {}
        self._session_ids = {}
        self._lock = Lock()

    async def build_launch_spec(self, context):
        return gemini_acp_launch_spec(context, command=self.command, dependency_roots=self.dependency_roots)

    async def validate(self, context):
        return await self.health(context)

    async def health(self, context):
        from core.providers.native_agent_builtins import CommandNativeRuntimeInspector

        status = await asyncio.to_thread(CommandNativeRuntimeInspector(self.command).inspect)
        return RuntimeHealth(status=status.health, reason_codes=status.reason_codes)

    def _owner(self, session_id, *, create=True):
        with self._lock:
            owner = self._owners.get(session_id)
            if owner is None and create:
                engine = GeminiAcpSession(self.build_launch_spec, provider_thread_id=self._session_ids.get(session_id))
                owner = self._owners[session_id] = NativeAcpRuntime(session_id, engine)
            if owner is not None and owner.closing:
                raise NativeAcpError("native_acp_session_closing")
            return owner

    async def _retire(self, context, owner, *, interrupt=False):
        sid = context.session.session_id
        operation = owner.engine.cancel if interrupt else owner.engine.close
        try:
            return await owner.shutdown(operation(context))
        finally:
            with self._lock:
                if self._owners.get(sid) is owner:
                    if owner.engine.provider_thread_id is not None:
                        self._session_ids[sid] = owner.engine.provider_thread_id
                    self._owners.pop(sid)

    async def prepare(self, context):
        owner = self._owner(context.session.session_id)
        try:
            return await owner.call(owner.engine.prepare(context))
        except BaseException:
            await self._retire(context, owner)
            raise

    async def execute(self, context):
        owner = self._owner(context.session.session_id)
        try:
            async with aclosing(owner.stream(owner.engine.execute(context))) as events:
                async for event in events:
                    yield event
        except BaseException as error:
            if isinstance(error, NativeAcpError) and str(error) == "native_acp_turn_already_active":
                raise  # A rejected competitor must not terminate the active turn.
            await self._retire(context, owner)
            raise

    async def steer(self, context):
        owner = self._owner(context.session_id, create=False)
        if owner is None:
            return RuntimeSteerResult(status="not_active")
        return await owner.call(owner.engine.steer(context))

    async def cancel(self, context):
        with self._lock:
            owner = self._owners.get(context.session.session_id)
        if owner is None:
            return RuntimeCancelResult(cancelled=False, reason_code="not_active")
        result = await self._retire(context, owner, interrupt=True)
        if isinstance(result, RuntimeCancelResult):
            return result
        return RuntimeCancelResult(cancelled=True, reason_code="cancelled")

    async def recover(self, context):
        await self.close(context)
        owner = self._owner(context.session.session_id)
        try:
            return await owner.call(owner.engine.recover(context))
        except BaseException:
            await self._retire(context, owner)
            raise

    async def close(self, context):
        with self._lock:
            owner = self._owners.get(context.session.session_id)
        if owner is None:
            return RuntimeCloseResult(closed=True)
        result = await self._retire(context, owner)
        if isinstance(result, RuntimeCloseResult):
            return result
        return RuntimeCloseResult(closed=True, terminated_processes=int(result.cancelled))


__all__ = ["GeminiCliNativeAdapter"]
