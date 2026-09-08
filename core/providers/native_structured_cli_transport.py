"""Supervised bounded NDJSON process transport for structured native CLIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import signal


MAX_NATIVE_JSONL_FRAME_BYTES = 1_048_576


class NativeStructuredCliError(RuntimeError):
    """A machine-readable native CLI violated its transport contract."""


@dataclass(frozen=True)
class _StreamFailure:
    error: NativeStructuredCliError


class NativeJsonlConnection:
    """Own one NDJSON process and expose bounded JSON objects only."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.messages: asyncio.Queue[dict[str, object] | _StreamFailure] = asyncio.Queue(
            maxsize=256
        )
        self._writer = asyncio.Lock()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def start(cls, spec):
        process = await asyncio.create_subprocess_exec(
            *spec.command,
            cwd=spec.working_directory,
            env=spec.env_overrides,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            limit=MAX_NATIVE_JSONL_FRAME_BYTES,
        )
        return cls(process)

    async def send(self, payload: dict[str, object]) -> None:
        if self._reader.done() or self.process.returncode is not None:
            raise NativeStructuredCliError("native_structured_cli_disconnected")
        try:
            data = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise NativeStructuredCliError(
                "native_structured_cli_request_invalid"
            ) from error
        if len(data) > MAX_NATIVE_JSONL_FRAME_BYTES:
            raise NativeStructuredCliError("native_structured_cli_request_too_large")
        if self.process.stdin is None:
            raise NativeStructuredCliError("native_structured_cli_disconnected")
        try:
            async with asyncio.timeout(3):
                async with self._writer:
                    self.process.stdin.write(data)
                    await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError) as error:
            raise NativeStructuredCliError(
                "native_structured_cli_disconnected"
            ) from error

    async def receive(self, *, timeout: float | None = None) -> dict[str, object]:
        try:
            if timeout is None:
                item = await self.messages.get()
            else:
                item = await asyncio.wait_for(self.messages.get(), timeout)
        except TimeoutError as error:
            raise NativeStructuredCliError(
                "native_structured_cli_response_timeout"
            ) from error
        if isinstance(item, _StreamFailure):
            raise item.error
        return item

    def has_pending_messages(self) -> bool:
        return not self.messages.empty()

    async def _read(self) -> None:
        failure = NativeStructuredCliError("native_structured_cli_disconnected")
        try:
            if self.process.stdout is None:
                raise NativeStructuredCliError("native_structured_cli_disconnected")
            while line := await self.process.stdout.readline():
                if len(line) > MAX_NATIVE_JSONL_FRAME_BYTES:
                    raise NativeStructuredCliError(
                        "native_structured_cli_response_too_large"
                    )
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise NativeStructuredCliError(
                        "native_structured_cli_message_invalid"
                    )
                await self.messages.put(message)
        except NativeStructuredCliError as error:
            failure = error
        except (ValueError, OSError, asyncio.LimitOverrunError) as error:
            failure = NativeStructuredCliError("native_structured_cli_stream_invalid")
            failure.__cause__ = error
        finally:
            await self.messages.put(_StreamFailure(failure))

    async def close(self, *, interrupt: bool = False, graceful: bool = False) -> None:
        if graceful and self.process.returncode is None and self.process.stdin is not None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 1)
            except asyncio.TimeoutError:
                pass
        if interrupt and self.process.returncode is None:
            await self._signal_group(signal.SIGINT, timeout=0.5)
        for process_signal in (signal.SIGTERM, signal.SIGKILL):
            await self._signal_group(process_signal, timeout=1)
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)

    async def _signal_group(self, process_signal: signal.Signals, *, timeout: float) -> None:
        try:
            os.killpg(self.process.pid, process_signal)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout)
        except asyncio.TimeoutError:
            pass


__all__ = [
    "MAX_NATIVE_JSONL_FRAME_BYTES",
    "NativeJsonlConnection",
    "NativeStructuredCliError",
]
