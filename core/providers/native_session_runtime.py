"""One supervised native session loop, independent of short-lived callers."""

import asyncio
from contextlib import aclosing
from threading import Lock, Thread

from core.providers.native_structured_cli_transport import NativeStructuredCliError


class _EventStream:
    """Pull one event at a time while retaining generator task ownership."""

    def __init__(self, iterator):
        self._requests = asyncio.Queue(maxsize=1)
        self._results = asyncio.Queue(maxsize=1)
        self._task = asyncio.create_task(self._produce(iterator))

    async def _produce(self, iterator):
        try:
            async with aclosing(iterator):
                while True:
                    await self._requests.get()
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration:
                        self._results.put_nowait((None, None))
                        return
                    self._results.put_nowait((event, None))
        except BaseException as error:
            if not self._results.full():
                self._results.put_nowait((None, error))

    async def next(self):
        if self._task.done() and self._results.empty():
            raise NativeStructuredCliError("native_session_stream_closed")
        self._requests.put_nowait(None)
        event, error = await self._results.get()
        if error is not None:
            raise error
        return event

    async def close(self):
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


class NativeSessionRuntime:
    """Own all process transports, tasks, and locks until explicit close."""

    def __init__(self, session_id, engine):
        self.engine = engine
        self._lock = Lock()
        self._shutdown = None
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self._run, name=f"maverick-native-{session_id}")
        try:
            self.thread.start()
        except BaseException:
            self.loop.close()
            raise

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self._cancel_tasks())
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()

    @staticmethod
    async def _cancel_tasks():
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    @property
    def closing(self):
        with self._lock:
            return self._shutdown is not None

    async def call(self, coroutine):
        with self._lock:
            if self._shutdown is not None:
                coroutine.close()
                raise NativeStructuredCliError("native_session_closing")
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return await asyncio.wrap_future(future)

    async def stream(self, iterator):
        async def start():
            return _EventStream(iterator)

        channel = await self.call(start())
        try:
            while (event := await self.call(channel.next())) is not None:
                yield event
        finally:
            if not self.closing:
                await self.call(channel.close())

    async def shutdown(self, coroutine):
        with self._lock:
            if self._shutdown is None:
                self._shutdown = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
                self._shutdown.add_done_callback(
                    lambda _done: self.loop.call_soon_threadsafe(self.loop.stop)
                )
            else:
                coroutine.close()
            future = self._shutdown

        async def finish():
            try:
                return await asyncio.wrap_future(future)
            finally:
                await asyncio.to_thread(self.thread.join)

        waiter = asyncio.create_task(finish())
        cancelled = False
        while not waiter.done():
            try:
                await asyncio.shield(waiter)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return waiter.result()


__all__ = ["NativeSessionRuntime"]
