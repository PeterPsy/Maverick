from __future__ import annotations

import asyncio
import unittest

from core.runtime.hosted_agentic_stream import _cancellable_events
from core.runtime.runtime_cancellation import RuntimeCancellationSignal


class _Budget:
    def check_time(self) -> None:
        return None


class _CountingStream:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)
        self.advances = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> int:
        self.advances += 1
        try:
            return next(self.values)
        except StopIteration as error:
            raise StopAsyncIteration from error

    async def aclose(self) -> None:
        self.closed = True


class HostedAgenticStreamAuthorityTest(unittest.IsolatedAsyncioTestCase):
    async def test_silent_stream_revocation_cancels_and_closes_pending_read(self):
        opened, closed = asyncio.Event(), asyncio.Event()
        revoked = False

        async def stream():
            try:
                opened.set()
                await asyncio.Event().wait()
                yield 1
            finally:
                closed.set()

        def guard():
            if revoked:
                raise RuntimeError('authority_revoked')

        events = _cancellable_events(stream(), RuntimeCancellationSignal(), _Budget(), before_transport=guard)
        pending = asyncio.create_task(anext(events))
        await asyncio.wait_for(opened.wait(), timeout=1)
        revoked = True
        with self.assertRaisesRegex(RuntimeError, 'authority_revoked'):
            await asyncio.wait_for(pending, timeout=2)
        self.assertTrue(closed.is_set())

    async def test_authority_guard_runs_for_every_stream_advancement(self) -> None:
        stream = _CountingStream([1, 2, 3])
        guard_calls = 0

        def guard() -> None:
            nonlocal guard_calls
            guard_calls += 1

        observed = [
            item
            async for item in _cancellable_events(
                stream,
                RuntimeCancellationSignal(),
                _Budget(),
                before_transport=guard,
            )
        ]

        self.assertEqual(observed, [1, 2, 3])
        self.assertEqual(guard_calls, 4)
        self.assertEqual(stream.advances, 4)
        self.assertTrue(stream.closed)

    async def test_revocation_between_events_blocks_the_next_advance(self) -> None:
        stream = _CountingStream([1, 2, 3])
        guard_calls = 0

        def guard() -> None:
            nonlocal guard_calls
            guard_calls += 1
            if guard_calls == 2:
                raise RuntimeError("authority_revoked")

        events = _cancellable_events(
            stream,
            RuntimeCancellationSignal(),
            _Budget(),
            before_transport=guard,
        )
        self.assertEqual(await anext(events), 1)
        with self.assertRaisesRegex(RuntimeError, "authority_revoked"):
            await anext(events)

        self.assertEqual(guard_calls, 2)
        self.assertEqual(stream.advances, 1)
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
