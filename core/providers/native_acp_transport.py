"""Supervised, bounded ACP v1 NDJSON transport; never a terminal scraper."""

import asyncio
import json
import os
import signal


class NativeAcpError(RuntimeError):
    pass


class NativeAcpConnection:
    def __init__(self, process):
        self.process = process
        self.session_id = None
        self.updates = asyncio.Queue(maxsize=256)
        self._pending = {}
        self._next_id = 0
        self._writer = asyncio.Lock()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def start(cls, spec):
        process = await asyncio.create_subprocess_exec(
            *spec.command, cwd=spec.working_directory, env=spec.env_overrides,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True, limit=1_048_576,
        )
        return cls(process)

    async def send(self, payload):
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        if len(data) > 1_048_576:
            raise NativeAcpError("native_acp_request_too_large")
        async with asyncio.timeout(3):
            async with self._writer:
                self.process.stdin.write(data)
                await self.process.stdin.drain()

    async def begin(self, method, params):
        if self._reader.done() or self.process.returncode is not None:
            raise NativeAcpError("native_acp_disconnected")
        if len(self._pending) >= 64:
            raise NativeAcpError("native_acp_request_overflow")
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self._pending[request_id] = future
        try:
            await self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except BaseException:
            self._pending.pop(request_id, None)
            future.cancel()
            raise
        return future

    async def request(self, method, params, *, timeout=15):
        future = await self.begin(method, params)
        try:
            return await asyncio.wait_for(future, timeout)
        except BaseException:
            await self.close()
            raise

    async def notify(self, method, params):
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _read(self):
        failure = NativeAcpError("native_acp_disconnected")
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise NativeAcpError("native_acp_message_invalid")
                if "method" not in message:
                    future = self._pending.pop(message.get("id"), None)
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        future.set_exception(NativeAcpError("native_acp_rpc_error"))
                    elif "result" in message:
                        future.set_result(message["result"])
                    else:
                        future.set_exception(NativeAcpError("native_acp_response_invalid"))
                    continue
                params = message.get("params", {})
                if not isinstance(params, dict):
                    raise NativeAcpError("native_acp_params_invalid")
                if "id" in message:
                    # No native permission grant or client filesystem/terminal
                    # delegation exists until the candidate's certification.
                    response = {"jsonrpc": "2.0", "id": message["id"]}
                    if message["method"] == "session/request_permission":
                        response["result"] = {"outcome": {"outcome": "cancelled"}}
                    else:
                        response["error"] = {"code": -32601, "message": "Client capability unavailable"}
                    await self.send(response)
                elif message["method"] == "session/update":
                    if self.session_id is not None and params.get("sessionId") != self.session_id:
                        raise NativeAcpError("native_acp_session_mismatch")
                    update = params.get("update")
                    if not isinstance(update, dict):
                        raise NativeAcpError("native_acp_update_invalid")
                    self.updates.put_nowait(update)
        except (ValueError, OSError, asyncio.QueueFull, NativeAcpError) as error:
            failure = NativeAcpError(str(error) if isinstance(error, NativeAcpError) else "native_acp_stream_invalid")
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(failure)
            self._pending.clear()

    async def close(self):
        # Also kill remaining group children if the protocol leader has exited.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 1)
            except asyncio.TimeoutError:
                pass
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)


__all__ = ["NativeAcpConnection", "NativeAcpError"]
