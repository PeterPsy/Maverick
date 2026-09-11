"""Antigravity CLI native candidate with session-owned process lifetimes."""

import asyncio
from contextlib import aclosing
from pathlib import Path
from threading import Lock

from core.providers.agentic_adapter import RuntimeCancelResult, RuntimeCloseResult, RuntimeHealth
from core.providers.antigravity_cli_sandbox import (
    antigravity_stream_launch_spec,
    resolve_antigravity_outer_sandbox,
)
from core.providers.antigravity_cli_runtime_home import (
    prepare_antigravity_runtime_skills,
)
from core.providers.antigravity_cli_session import AntigravityCliSession
from core.providers.models import RuntimeSteerResult
from core.providers.native_session_runtime import NativeSessionRuntime
from core.providers.native_structured_cli_transport import NativeStructuredCliError


class AntigravityCliNativeAdapter:
    runtime_engine_id = "antigravity-cli"
    adapter_id = "antigravity-cli-stream-json"
    adapter_version = "5"
    local_process_lifecycle = None
    requires_resolved_launch_spec = True

    @property
    def artifact_components(self):
        """Return every module able to change the native runtime wire behavior."""
        from importlib import import_module

        return tuple(
            import_module(module_name)
            for module_name in (
                "core.providers.antigravity_cli_event_projection",
                "core.providers.antigravity_cli_runtime_home",
                "core.providers.antigravity_cli_sandbox",
                "core.providers.antigravity_cli_session",
                "core.providers.native_session_runtime",
                "core.providers.native_structured_cli_transport",
                "core.providers.provider_codex_wrappers",
            )
        )

    def __init__(self, *, command="agy", dependency_roots=None, auth_home=None):
        self.command = command
        self.auth_home = auth_home
        self.dependency_roots = (
            tuple(dependency_roots)
            if dependency_roots is not None
            else tuple(
                Path(path)
                for path in (
                    "/usr/bin",
                    "/usr/lib",
                    "/usr/local/lib",
                    "/lib",
                    "/lib64",
                )
            )
        )
        self._owners = {}
        self._session_ids = {}
        self._skill_digests = {}
        self._preparation_locks = {}
        self._lock = Lock()

    async def build_launch_spec(self, context):
        return antigravity_stream_launch_spec(
            context,
            command=self.command,
            dependency_roots=self.dependency_roots,
            auth_home=self.auth_home,
        )

    async def validate(self, context):
        return await self.health(context)

    async def health(self, context):
        from core.providers.native_agent_builtins import CommandNativeRuntimeInspector

        try:
            resolve_antigravity_outer_sandbox()
        except NativeStructuredCliError as error:
            return RuntimeHealth(status="degraded", reason_codes=(str(error),))
        status = await asyncio.to_thread(
            CommandNativeRuntimeInspector(self.command).inspect
        )
        return RuntimeHealth(status=status.health, reason_codes=status.reason_codes)

    def _owner(self, session_id, *, create=True):
        with self._lock:
            owner = self._owners.get(session_id)
            if owner is None and create:
                engine = AntigravityCliSession(
                    self.build_launch_spec,
                    provider_thread_id=self._session_ids.get(session_id),
                )
                owner = self._owners[session_id] = NativeSessionRuntime(
                    session_id,
                    engine,
                )
            if owner is not None and owner.closing:
                raise NativeStructuredCliError("native_session_closing")
            return owner

    async def _retire(self, context, owner, *, interrupt=False):
        session_id = context.session.session_id
        operation = owner.engine.cancel if interrupt else owner.engine.close
        try:
            return await owner.shutdown(operation(context))
        finally:
            with self._lock:
                if self._owners.get(session_id) is owner:
                    if owner.engine.provider_thread_id is not None:
                        self._session_ids[session_id] = owner.engine.provider_thread_id
                    self._owners.pop(session_id)

    async def prepare(self, context):
        session_id = context.session.session_id
        with self._lock:
            preparation_lock = self._preparation_locks.get(session_id)
            if preparation_lock is None:
                preparation_lock = asyncio.Lock()
                self._preparation_locks[session_id] = preparation_lock
        async with preparation_lock:
            return await self._prepare(context)

    async def _prepare(self, context):
        skill_digest = await asyncio.to_thread(
            prepare_antigravity_runtime_skills,
            Path(context.session.runtime_root),
            getattr(context, "invoked_skills", ()),
        )
        session_id = context.session.session_id
        with self._lock:
            existing = self._owners.get(session_id)
            previous_digest = self._skill_digests.get(session_id)
        if existing is not None and previous_digest != skill_digest:
            await self._retire(context, existing)
        with self._lock:
            self._skill_digests[session_id] = skill_digest
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
            if (
                isinstance(error, NativeStructuredCliError)
                and str(error) == "antigravity_turn_already_active"
            ):
                raise
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
        return RuntimeCloseResult(
            closed=True,
            terminated_processes=int(result.cancelled),
        )


__all__ = ["AntigravityCliNativeAdapter"]
