"""Loop-confined Antigravity CLI persistent ``stream-json`` lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path

from core.providers.agentic_adapter import (
    LocalLaunchContext,
    RuntimeCancelResult,
    RuntimeCloseResult,
    RuntimePrepareContext,
    RuntimePrepareResult,
    RuntimeProviderEvent,
    RuntimeRecoveryResult,
)
from core.providers.antigravity_cli_event_projection import project_antigravity_step
from core.providers.models import RuntimeSteerResult
from core.providers.native_structured_cli_transport import (
    NativeJsonlConnection,
    NativeStructuredCliError,
)


_TERMINAL_STATUSES = frozenset(
    {"SUCCESS", "ERROR", "CANCELED", "INTERRUPTED", "INVALID", "WAITING", "RUNNING"}
)
_REQUIRED_NATIVE_TOOLS = frozenset(
    {"ask_permission", "run_command", "write_to_file"}
)


class AntigravityCliSession:
    """Own one warmed Antigravity conversation and its process."""

    def __init__(self, build_launch_spec, *, provider_thread_id=None):
        self.build_launch_spec = build_launch_spec
        self.provider_thread_id = provider_thread_id
        self.client: NativeJsonlConnection | None = None
        self.connecting: NativeJsonlConnection | None = None
        self._executing = False
        self._prepare_lock = asyncio.Lock()
        self._generation = 0
        self._last_step_index = -1
        self._last_num_turns: int | None = None

    async def prepare(self, context):
        async with self._prepare_lock:
            return await self._connect(context)

    async def _connect(self, context):
        if self.client is not None:
            client = self.client
            if client.process.returncode is None and not client._reader.done():
                return self._prepared(client)
            await self.close(context)
        spec = context.local_launch_spec or await self.build_launch_spec(
            LocalLaunchContext(session=context.session, binding=context.binding)
        )
        previous = (
            getattr(context.provider_state, "provider_thread_id", None)
            or self.provider_thread_id
        )
        if previous is not None:
            previous = _conversation_id(previous)
            spec = replace(spec, command=[*spec.command, "--conversation", previous])
        generation = self._generation
        client = await NativeJsonlConnection.start(spec)
        try:
            if self._generation != generation:
                raise NativeStructuredCliError("antigravity_start_cancelled")
            self.connecting = client
            message = await client.receive(timeout=15)
            conversation_id = self._validate_init(
                message,
                context=context,
                previous=previous,
            )
            if self._generation != generation:
                raise NativeStructuredCliError("antigravity_start_cancelled")
            self.client = client
            self.provider_thread_id = conversation_id
            return self._prepared(client)
        except BaseException:
            await client.close()
            raise
        finally:
            self.connecting = None

    def _prepared(self, client: NativeJsonlConnection) -> RuntimePrepareResult:
        return RuntimePrepareResult(
            ready=True,
            prepared_handle=client,
            provider_state_updates={
                "provider_thread_id": self.provider_thread_id,
                "continuation_id": self.provider_thread_id,
            },
            metadata={"steering_mode": "safe_next_turn"},
        )

    def _validate_init(self, message, *, context, previous) -> str:
        if message.get("event") != "init" or not isinstance(message.get("init"), dict):
            raise NativeStructuredCliError("antigravity_init_invalid")
        conversation_id = _conversation_id(message.get("conversation_id"))
        if previous is not None and conversation_id != previous:
            raise NativeStructuredCliError("antigravity_resume_identity_mismatch")
        payload = message["init"]
        cwd = payload.get("cwd")
        if not isinstance(cwd, str):
            raise NativeStructuredCliError("antigravity_init_invalid")
        observed_cwd = Path(cwd)
        if observed_cwd.resolve(strict=False) != Path(
            context.session.workdir
        ).resolve(strict=False):
            raise NativeStructuredCliError("antigravity_workspace_identity_mismatch")
        tools = payload.get("tools")
        if not isinstance(tools, list) or any(
            not isinstance(tool, str) or not tool for tool in tools
        ):
            raise NativeStructuredCliError("antigravity_init_invalid")
        if not _REQUIRED_NATIVE_TOOLS.issubset(tools):
            raise NativeStructuredCliError("antigravity_toolset_incomplete")
        if payload.get("permission_mode") != "proceed-in-sandbox":
            raise NativeStructuredCliError("antigravity_permission_mode_untrusted")
        expected_model = str(context.binding.model_id or "").strip()
        if payload.get("model") != expected_model:
            raise NativeStructuredCliError("antigravity_model_identity_mismatch")
        return conversation_id

    async def execute(self, context):
        if self._executing:
            raise NativeStructuredCliError("antigravity_turn_already_active")
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
            await self.prepare(
                RuntimePrepareContext(
                    session=context.session,
                    binding=context.binding,
                    provider_state=context.provider_state,
                )
            )
        client = self.client
        if client is None:
            raise NativeStructuredCliError("antigravity_not_connected")
        if client.has_pending_messages():
            raise NativeStructuredCliError("antigravity_event_sequence_invalid")
        await client.send(
            {"event": "user", "message": {"content": context.input_text}}
        )
        ordinal = 1
        accepted = False
        answer_parts: list[str] = []
        yield RuntimeProviderEvent(
            "provider.request.sent",
            context.correlation_id,
            ordinal,
            "1",
            {"provider_thread_id": self.provider_thread_id},
        )
        ordinal += 1
        while True:
            message = await client.receive()
            event_type = message.get("event")
            if event_type not in {"step_update", "result"}:
                raise NativeStructuredCliError("antigravity_event_sequence_invalid")
            if not accepted:
                yield RuntimeProviderEvent(
                    "provider.accepted",
                    context.correlation_id,
                    ordinal,
                    "1",
                    {"provider_thread_id": self.provider_thread_id},
                )
                ordinal += 1
                accepted = True
            if event_type == "step_update":
                update = message.get("step_update")
                self._validate_step_sequence(update)
                projected_type, payload = project_antigravity_step(update)
                if projected_type == "runtime.output.delta":
                    answer_parts.append(str(payload["text"]))
                yield RuntimeProviderEvent(
                    projected_type,
                    context.correlation_id,
                    ordinal,
                    "1",
                    payload,
                )
                ordinal += 1
                continue

            result = self._validate_result(message.get("result"), answer_parts)
            usage = result["usage"]
            num_turns = result["num_turns"]
            yield RuntimeProviderEvent(
                "provider.usage",
                context.correlation_id,
                ordinal,
                "1",
                {
                    "usage_id": f"{self.provider_thread_id}:{num_turns}",
                    "semantics": "cumulative",
                    "source": "antigravity_cli",
                    "token_accuracy": "exact",
                    "context_accuracy": "unavailable",
                    "input_tokens": usage["input_tokens"],
                    "cached_input_tokens": usage["cache_read_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "reasoning_output_tokens": usage["thinking_tokens"],
                    "total_tokens": usage["total_tokens"],
                },
            )
            ordinal += 1
            response = result["response"]
            yield RuntimeProviderEvent(
                "runtime.output.final",
                context.correlation_id,
                ordinal,
                "1",
                {"text": response},
            )
            ordinal += 1
            yield RuntimeProviderEvent(
                "provider.execution.completed",
                context.correlation_id,
                ordinal,
                "1",
                {"output_text": response, "exit_code": 0},
            )
            return

    def _validate_step_sequence(self, update: object) -> None:
        if not isinstance(update, dict):
            raise NativeStructuredCliError("antigravity_step_invalid")
        if update.get("conversation_id") != self.provider_thread_id:
            raise NativeStructuredCliError("antigravity_conversation_mismatch")
        step_index = update.get("step_index")
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise NativeStructuredCliError("antigravity_step_invalid")
        if step_index < self._last_step_index:
            raise NativeStructuredCliError("antigravity_step_order_invalid")
        self._last_step_index = step_index

    def _validate_result(self, value: object, answer_parts: list[str]) -> dict[str, object]:
        if not isinstance(value, dict):
            raise NativeStructuredCliError("antigravity_result_invalid")
        if value.get("conversation_id") != self.provider_thread_id:
            raise NativeStructuredCliError("antigravity_conversation_mismatch")
        status = value.get("status")
        if status not in _TERMINAL_STATUSES:
            raise NativeStructuredCliError("antigravity_result_invalid")
        if status != "SUCCESS":
            raise NativeStructuredCliError(
                f"antigravity_result_{str(status).lower()}"
            )
        response = value.get("response")
        if not isinstance(response, str) or not response.strip():
            raise NativeStructuredCliError("agent_final_output_empty")
        if answer_parts and "".join(answer_parts) != response:
            raise NativeStructuredCliError("antigravity_output_mismatch")
        num_turns = value.get("num_turns")
        if isinstance(num_turns, bool) or not isinstance(num_turns, int) or num_turns < 1:
            raise NativeStructuredCliError("antigravity_result_invalid")
        if self._last_num_turns is not None and num_turns != self._last_num_turns + 1:
            raise NativeStructuredCliError("antigravity_turn_count_invalid")
        usage = _usage(value.get("usage"))
        self._last_num_turns = num_turns
        return {**value, "response": response, "num_turns": num_turns, "usage": usage}

    async def steer(self, context):
        if not self._executing:
            return RuntimeSteerResult(status="not_active")
        return RuntimeSteerResult(
            status="not_supported",
            reason="antigravity_safe_next_turn_only",
        )

    async def cancel(self, context):
        client = self.client or self.connecting
        active = client is not None or self._prepare_lock.locked()
        self._generation += 1
        self.client = self.connecting = None
        if client is not None:
            await client.close(interrupt=True)
        return RuntimeCancelResult(
            cancelled=active,
            reason_code="cancelled" if active else "not_active",
        )

    async def recover(self, context):
        await self.close(context)
        prepared = await self.prepare(
            RuntimePrepareContext(
                session=context.session,
                binding=context.binding,
                provider_state=context.provider_state,
                local_launch_spec=context.local_launch_spec,
            )
        )
        return RuntimeRecoveryResult(
            recovered=prepared.ready,
            reason_code="recovered",
            provider_state_updates=prepared.provider_state_updates,
        )

    async def close(self, context):
        self._generation += 1
        client = self.client or self.connecting
        self.client = self.connecting = None
        if client is not None:
            await client.close(graceful=not self._executing)
        return RuntimeCloseResult(
            closed=True,
            terminated_processes=int(client is not None),
        )


def _conversation_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in value)
    ):
        raise NativeStructuredCliError("antigravity_conversation_invalid")
    return value


def _usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise NativeStructuredCliError("antigravity_usage_invalid")
    fields = (
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "cache_read_tokens",
        "total_tokens",
    )
    usage: dict[str, int] = {}
    for field_name in fields:
        count = value.get(field_name)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise NativeStructuredCliError("antigravity_usage_invalid")
        usage[field_name] = count
    if (
        usage["thinking_tokens"] > usage["output_tokens"]
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
    ):
        raise NativeStructuredCliError("antigravity_usage_invalid")
    return usage


__all__ = ["AntigravityCliSession"]
